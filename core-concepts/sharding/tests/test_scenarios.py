"""Integration tests for account sharding and the recent table."""

from __future__ import annotations

import os

import httpx

BASE = os.environ.get("SHARD_BASE_URL", "http://localhost:8000")


def test_even_account_stays_on_shard0() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        client.post("/api/reset")
        created = client.post("/api/orders", json={"account_id": 42, "note": "book"})
        assert created.status_code == 200
        body = created.json()
        assert body["shard"] == "shard0"
        assert body["wrote"] == ["shard0", "recent"]
        mine = client.get("/api/accounts/42/orders")
        assert mine.json()["shards_read"] == ["shard0"]
        assert mine.json()["orders"] == [{"account_id": 42, "note": "book", "shard": "shard0"}]
        other = client.get("/api/accounts/43/orders")
        assert other.json()["shards_read"] == ["shard1"]
        assert other.json()["orders"] == []


def test_odd_account_and_recent_versus_scatter() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        client.post("/api/reset")
        client.post("/api/orders", json={"account_id": 42, "note": "book"})
        client.post("/api/orders", json={"account_id": 7, "note": "lamp"})
        recent = client.get("/api/orders/recent")
        scatter = client.get("/api/orders/scatter")
        assert recent.json()["shards_read"] == ["recent"]
        assert scatter.json()["shards_read"] == ["shard0", "shard1"]
        notes = {row["note"] for row in recent.json()["orders"]}
        assert notes == {"book", "lamp"}
        assert {row["note"] for row in scatter.json()["orders"]} == notes
