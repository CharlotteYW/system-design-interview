from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx

BASE = os.environ.get("RATE_LIMIT_BASE_URL", "http://localhost:8000")


def _client_headers(algo: str, client_id: str | None = None, now_ms: int | None = None, force_local: bool = False) -> dict[str, str]:
    headers = {
        "X-Client-Id": client_id or str(uuid.uuid4()),
        "X-Rate-Algorithm": algo,
    }
    if now_ms is not None:
        headers["X-Rate-Now-Ms"] = str(now_ms)
    if force_local:
        headers["X-Force-Local"] = "1"
    return headers


def test_under_limit_then_429() -> None:
    headers = _client_headers("fixed")
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        for _ in range(5):
            response = client.post("/api/work", headers=headers)
            assert response.status_code == 200, response.text
            assert response.headers["x-rate-path"] == "redis"
        denied = client.post("/api/work", headers=headers)
        assert denied.status_code == 429
        assert denied.headers["retry-after"]
        assert "X-RateLimit-Remaining" in denied.headers
        again = client.post("/api/work", headers=headers)
        assert again.status_code == 429
        assert again.headers["x-rate-path"] == "local-block"


def test_ping_limit_is_higher_than_work() -> None:
    headers = _client_headers("fixed")
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        for _ in range(6):
            response = client.get("/api/ping", headers=headers)
            assert response.status_code == 200, response.text


def test_fixed_window_allows_boundary_burst() -> None:
    headers_late = _client_headers("fixed", now_ms=59_900)
    client_id = headers_late["X-Client-Id"]
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        for _ in range(10):
            response = client.get("/api/edge", headers=headers_late)
            assert response.status_code == 200, response.text
        early = _client_headers("fixed", client_id=client_id, now_ms=60_000)
        allowed = 0
        for _ in range(10):
            response = client.get("/api/edge", headers=early)
            if response.status_code == 200:
                allowed += 1
        assert allowed == 10


def test_sliding_counter_rejects_boundary_burst() -> None:
    headers_late = _client_headers("sliding_counter", now_ms=59_900)
    client_id = headers_late["X-Client-Id"]
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        for _ in range(10):
            response = client.get("/api/edge", headers=headers_late)
            assert response.status_code == 200, response.text
        early = _client_headers("sliding_counter", client_id=client_id, now_ms=60_000)
        denied = 0
        for _ in range(10):
            response = client.get("/api/edge", headers=early)
            if response.status_code == 429:
                denied += 1
        assert denied == 10


def test_concurrent_work_does_not_exceed_limit() -> None:
    headers = _client_headers("fixed")

    def once() -> int:
        with httpx.Client(base_url=BASE, timeout=10.0) as client:
            return client.post("/api/work", headers=headers).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(lambda _i: once(), range(12)))
    assert codes.count(200) == 5
    assert codes.count(429) == 7


def test_local_emergency_cap_when_forced() -> None:
    headers = _client_headers("fixed", force_local=True)
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        first = client.post("/api/work", headers=headers)
        assert first.status_code == 200, first.text
        assert first.headers["x-rate-path"] == "local-emergency"
        second = client.post("/api/work", headers=headers)
        assert second.status_code == 429
        assert second.headers["x-rate-path"] == "local-emergency"
