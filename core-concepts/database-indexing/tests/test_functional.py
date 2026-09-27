from __future__ import annotations

import os

import httpx

BASE = os.environ.get("INDEXING_BASE_URL", "http://localhost:8000")


def test_ui_explains_the_three_queries() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        page = client.get("/")
        assert page.status_code == 200
        text = page.text
        assert 'id="user"' in text
        assert 'id="both"' in text
        assert 'id="date"' in text
        assert 'id="cover"' in text
        assert 'id="body"' in text
        assert "Index Only Scan" in text
        assert "user_id, created_at" in text
        assert "June 1 only" in text


def test_ui_flow_create_index_and_explain_date() -> None:
    with httpx.Client(base_url=BASE, timeout=30.0) as client:
        client.post("/api/index")
        explained = client.get("/api/explain/date")
        assert explained.status_code == 200
        assert "created_at" in explained.json()["sql"]
        assert "Seq Scan" in explained.json()["plan"]
