from __future__ import annotations

import os

import httpx

BASE = os.environ.get("INDEXING_BASE_URL", "http://localhost:8000")


def test_seq_scan_without_composite_then_index_for_user_id() -> None:
    with httpx.Client(base_url=BASE, timeout=30.0) as client:
        dropped = client.delete("/api/index")
        assert dropped.status_code == 200
        before = client.get("/api/explain/user")
        assert before.status_code == 200
        assert "Seq Scan" in before.json()["plan"]

        created = client.post("/api/index")
        assert created.status_code == 200
        user = client.get("/api/explain/user").json()
        both = client.get("/api/explain/both").json()
        date = client.get("/api/explain/date").json()
        assert "Index" in user["plan"]
        assert "Index" in both["plan"]
        assert "Seq Scan" in date["plan"]
        assert date["leading_node_uses_index"] is False
        cover = client.get("/api/explain/cover").json()
        body = client.get("/api/explain/body").json()
        assert "Index Only Scan" in cover["plan"]
        assert "Index Only Scan" not in body["plan"]
        assert "Heap" in body["plan"]
