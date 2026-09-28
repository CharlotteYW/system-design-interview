from __future__ import annotations

import os

import httpx

BASE = os.environ.get("HASHING_BASE_URL", "http://localhost:8000")


def test_ui_explains_ring_and_mod() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        page = client.get("/")
        assert page.status_code == 200
        text = page.text
        assert 'id="example"' in text
        assert 'id="compare"' in text
        assert "next server clockwise" in text
        assert "hash(key) % N" in text
        assert "virtual nodes" in text


def test_ui_example_flow() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        body = client.get("/api/example").json()
        assert body["moved"] == ["k2"]
