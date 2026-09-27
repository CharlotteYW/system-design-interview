from __future__ import annotations

import os
import uuid

import httpx

BASE = os.environ.get("RATE_LIMIT_BASE_URL", "http://localhost:8000")


def test_ui_explains_every_algorithm() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "text/html" in page.headers.get("content-type", "")
        body = page.text
        for name in ("fixed", "sliding_counter", "sliding_log", "token_bucket", "leaky_bucket"):
            assert name in body
        assert 'id="algo"' in body
        assert 'id="hammer"' in body
        assert 'id="edge"' in body
        assert "What each algorithm means" in body
        assert "Example, limit 10 per 60s" in body
        meta = client.get("/api/algorithms").json()
        assert meta["rules_loaded"] == "once_at_process_start"
        assert meta["routes"]["POST /api/work"]["limit"] == 5


def test_ui_work_flow_then_429() -> None:
    client_id = str(uuid.uuid4())
    headers = {"X-Client-Id": client_id, "X-Rate-Algorithm": "token_bucket"}
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        allowed = 0
        denied = 0
        for _ in range(8):
            response = client.post("/api/work", headers=headers)
            if response.status_code == 200:
                allowed += 1
                assert "id" in response.json()
            else:
                denied += 1
                assert response.status_code == 429
        assert allowed == 5
        assert denied == 3
        me = client.get("/api/limiter/me", headers=headers)
        assert me.status_code == 200
        assert me.json()["work_rows"] == 5
