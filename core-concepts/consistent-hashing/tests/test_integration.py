from __future__ import annotations

import os

import httpx

BASE = os.environ.get("HASHING_BASE_URL", "http://localhost:8000")


def test_example_only_k2_moves() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        body = client.get("/api/example").json()
        assert body["moved"] == ["k2"]
        by_key = {row["key"]: row for row in body["keys"]}
        assert by_key["k1"]["before"] == "B" and by_key["k1"]["after"] == "B"
        assert by_key["k2"]["before"] == "C" and by_key["k2"]["after"] == "D"
        assert by_key["k3"]["before"] == "A" and by_key["k3"]["after"] == "A"


def test_ring_moves_fewer_keys_than_mod_n() -> None:
    with httpx.Client(base_url=BASE, timeout=20.0) as client:
        body = client.get("/api/compare", params={"servers": 4, "keys": 2000, "vnodes": 100}).json()
        assert body["mod_moved"] > body["keys"] * 0.5
        assert body["ring_moved"] < body["mod_moved"]
        assert body["ring_moved"] < body["keys"] * 0.4
