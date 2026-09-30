"""Functional tests of the key-value page and the API it calls."""

from __future__ import annotations

import os

import httpx

BASE = os.environ.get("KV_BASE_URL", "http://localhost:8000")


def test_page_shows_coordinator_and_l1() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        page = client.get("/")
        assert page.status_code == 200
        text = page.text
        assert 'id="put"' in text
        assert 'id="get"' in text
        assert 'id="delete"' in text
        assert 'id="log"' in text
        assert "round-robin" in text
        assert "L1" in text
        assert "tombstone" in text
        assert "2 of 3" in text
        assert 'id="bloom"' in text
        assert "bloom filter" in text


def test_page_api_put_and_get() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        assert client.post("/api/reset").status_code == 200
        put = client.put("/v1/keys/from-ui", json={"value": "hello"}, params={"at": "A"})
        assert put.status_code == 200
        body = put.json()
        assert body["coordinator"] == "A"
        assert len(body["acks"]) >= 2
        got = client.get("/v1/keys/from-ui", params={"at": "A"})
        assert got.status_code == 200
        assert got.json()["value"] == "hello"
        assert got.json()["l1"] == "hit"
