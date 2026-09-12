from __future__ import annotations

import os

import httpx

BASE_URL = os.environ.get("SHORTENER_BASE_URL", "http://localhost:8000")


def test_ui_page_is_served() -> None:
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "text/html" in page.headers.get("content-type", "")
        assert "URL shortener" in page.text
        assert "/api/shorten" in page.text
        assert 'id="form"' in page.text


def test_ui_create_then_follow_short_link() -> None:
    """Same flow as the page: POST JSON like fetch(), then GET the short URL."""
    long_url = "https://example.com/functional/ui-flow"
    with httpx.Client(base_url=BASE_URL, follow_redirects=False, timeout=10.0) as client:
        created = client.post("/api/shorten", json={"url": long_url})
        assert created.status_code == 200, created.text
        code = created.json()["code"]
        short_url = created.json()["short_url"]
        redirected = client.get(f"/{code}")
        assert redirected.status_code == 302
        assert redirected.headers["location"] == long_url
        assert short_url.endswith(f"/{code}")
