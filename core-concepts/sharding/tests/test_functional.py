"""Functional tests of the sharding page and the calls it makes."""

from __future__ import annotations

import os

import httpx

BASE = os.environ.get("SHARD_BASE_URL", "http://localhost:8000")


def test_page_explains_the_split() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        page = client.get("/")
        assert page.status_code == 200
        text = page.text
        assert "account" in text
        assert "shard0" in text
        assert "shard1" in text
        assert "recent" in text
        assert 'id="place"' in text
        assert 'id="mine"' in text
        assert 'id="scatter"' in text
        assert "one database" in text


def test_place_then_my_orders_and_recent() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        client.post("/api/reset")
        created = client.post("/api/orders", json={"account_id": 8, "note": "pen"})
        assert created.status_code == 200
        assert created.json()["shard"] == "shard0"
        mine = client.get("/api/accounts/8/orders")
        assert mine.json()["shards_read"] == ["shard0"]
        recent = client.get("/api/orders/recent")
        assert recent.json()["orders"][0]["note"] == "pen"
        assert recent.json()["shards_read"] == ["recent"]
