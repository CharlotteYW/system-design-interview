from __future__ import annotations

import os

import httpx

BASE_URL = os.environ.get("CACHING_BASE_URL", "http://localhost:8000")


def test_ui_page_is_served() -> None:
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "text/html" in page.headers.get("content-type", "")
        assert "Caching lab" in page.text
        assert "/api/items/" in page.text
        assert "cache-aside" in page.text
        assert 'id="fetch"' in page.text
        assert 'id="flush-l1"' in page.text


def test_ui_fetch_twice_then_save_then_fetch() -> None:
    """Same clicks as the page: Fetch (MISS), Fetch (hit), Save new text, Fetch (MISS)."""
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
        client.put("/api/items/201", json={"body": "from-ui"})
        client.post("/api/flush-cache")
        first = client.get("/api/items/201")
        assert first.status_code == 200
        assert first.json()["cache"] == "MISS"
        assert first.headers.get("x-cache") == "MISS"
        second = client.get("/api/items/201")
        assert second.json()["cache"] == "L1"
        client.post("/api/flush-l1")
        redis_hit = client.get("/api/items/201")
        assert redis_hit.json()["cache"] == "REDIS"
        saved = client.put("/api/items/201", json={"body": "edited"})
        assert saved.status_code == 200
        third = client.get("/api/items/201")
        assert third.json()["body"] == "edited"
        assert third.json()["cache"] == "MISS"
