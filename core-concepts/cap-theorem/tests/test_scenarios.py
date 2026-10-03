"""Integration tests for the two-replica CAP lab."""

from __future__ import annotations

import os

import httpx

BASE = os.environ.get("CAP_BASE_URL", "http://localhost:8000")


def test_connected_seat_updates_both_copies() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        client.post("/api/reset")
        sold = client.post("/api/seat", json={"node": "A"})
        assert sold.status_code == 200
        body = sold.json()
        assert body["mode"] == "CP"
        assert body["a"]["seats"] == 0
        assert body["b"]["seats"] == 0
        again = client.post("/api/seat", json={"node": "B"})
        assert again.status_code == 409


def test_cut_link_refuses_the_seat() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        client.post("/api/reset")
        client.post("/api/partition", json={"cut": True})
        refused = client.post("/api/seat", json={"node": "B"})
        assert refused.status_code == 503
        body = refused.json()
        assert body["mode"] == "CP"
        assert body["a"]["seats"] == 1
        assert body["b"]["seats"] == 1


def test_cut_link_likes_merge_on_heal() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        client.post("/api/reset")
        client.post("/api/partition", json={"cut": True})
        left = client.post("/api/like", json={"node": "A"})
        right = client.post("/api/like", json={"node": "B"})
        assert left.status_code == 200 and right.status_code == 200
        assert left.json()["mode"] == "AP"
        assert right.json()["a"]["likes"] == 1
        assert right.json()["b"]["likes"] == 1
        healed = client.post("/api/partition", json={"cut": False})
        assert healed.status_code == 200
        assert healed.json()["a"]["likes"] == 2
        assert healed.json()["b"]["likes"] == 2
        assert healed.json()["partitioned"] is False
