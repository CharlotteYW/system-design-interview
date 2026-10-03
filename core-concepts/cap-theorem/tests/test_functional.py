"""Functional tests of the CAP page and the buttons it calls."""

from __future__ import annotations

import os

import httpx

BASE = os.environ.get("CAP_BASE_URL", "http://localhost:8000")


def test_page_names_the_choice() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        page = client.get("/")
        assert page.status_code == 200
        text = page.text
        assert "CP" in text
        assert "AP" in text
        assert 'id="cut"' in text
        assert 'id="seat-a"' in text
        assert 'id="like-b"' in text
        assert "2 of 3" in text or "2-of-3" in text


def test_page_flow_cut_seat_like_heal() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        client.post("/api/reset")
        cut = client.post("/api/partition", json={"cut": True})
        assert cut.json()["partitioned"] is True
        seat = client.post("/api/seat", json={"node": "A"})
        assert seat.status_code == 503
        like = client.post("/api/like", json={"node": "A"})
        assert like.status_code == 200
        assert like.json()["a"]["likes"] == 1
        assert like.json()["b"]["likes"] == 0
        healed = client.post("/api/partition", json={"cut": False})
        assert healed.json()["a"]["likes"] == 1
        assert healed.json()["b"]["likes"] == 1
