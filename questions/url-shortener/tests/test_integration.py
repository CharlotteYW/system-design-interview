from __future__ import annotations

import os

import httpx
import pytest

BASE_URL = os.environ.get("SHORTENER_BASE_URL", "http://localhost:8000")


@pytest.fixture
def client() -> httpx.Client:
    with httpx.Client(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as c:
        yield c


def test_health(client: httpx.Client) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_shorten_and_redirect(client: httpx.Client) -> None:
    long_url = "https://example.com/integration/happy-path"
    created = client.post("/api/shorten", json={"url": long_url})
    assert created.status_code == 200, created.text
    body = created.json()
    code = body["code"]
    assert len(code) == 7
    assert body["short_url"].endswith(f"/{code}")

    redirected = client.get(f"/{code}")
    assert redirected.status_code == 302
    assert redirected.headers["location"] == long_url


def test_invalid_url_rejected(client: httpx.Client) -> None:
    response = client.post("/api/shorten", json={"url": "not-a-url"})
    assert response.status_code == 422


def test_unknown_code_is_404(client: httpx.Client) -> None:
    response = client.get("/zzzzzzz")
    assert response.status_code == 404


def test_same_url_is_idempotent(client: httpx.Client) -> None:
    long_url = "https://example.com/integration/idempotent"
    first = client.post("/api/shorten", json={"url": long_url})
    second = client.post("/api/shorten", json={"url": long_url})
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["code"] == second.json()["code"]


def test_concurrent_same_url(client: httpx.Client) -> None:
    long_url = "https://example.com/integration/concurrent"
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as extra:
        responses = []
        for _ in range(8):
            responses.append(extra.post("/api/shorten", json={"url": long_url}))
        codes = {item.json()["code"] for item in responses if item.status_code == 200}
        assert all(item.status_code == 200 for item in responses)
        assert len(codes) == 1
