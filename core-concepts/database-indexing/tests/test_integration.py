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


def test_lsm_read_hits_memtable_before_sstable() -> None:
    with httpx.Client(base_url=BASE, timeout=30.0) as client:
        story = client.get("/api/lsm")
        assert story.status_code == 200
        body = story.json()
        assert body["sstables"]
        reads = {row["key"]: row for row in body["reads"]}
        assert reads["k3"]["found_in"] == "memtable"
        assert reads["k3"]["value"] == "v3-new"
        assert reads["k1"]["found_in"] == "sstable-0"
        assert reads["k1"]["value"] == "v1"
        assert reads["k9"]["found_in"] == "memtable"
        assert any("Freeze sstable-0" in line for line in body["log"])
        assert any("Read k3 → v3-new from memtable" in line for line in body["log"])


def test_near_me_btrees_keep_strips_and_rtree_keeps_the_disk() -> None:
    with httpx.Client(base_url=BASE, timeout=30.0) as client:
        body = client.get("/api/geo/compare").json()
        assert "Ferry Building" in body["lat"]
        assert "Atlantic same latitude" in body["lat"]
        assert "Same longitude far north" not in body["lat"]
        assert "Ferry Building" in body["lon"]
        assert "Same longitude far north" in body["lon"]
        assert "Atlantic same latitude" not in body["lon"]
        assert "Rectangle corner" in body["box"]
        assert "Atlantic same latitude" not in body["box"]
        assert body["rtree"] == ["Ferry Building"]
        assert "Ferry Building" in body["quadtree_kept"]
        assert "Atlantic same latitude" in body["quadtree_pruned"]
        assert body["geohash_prefix"]["Ferry Building"] > body["geohash_prefix"]["Atlantic same latitude"]
        assert "places_lat_idx" in body["plans"]["lat"]
        assert "places_lon_idx" in body["plans"]["lon"]
        assert "gist" in body["plans"]["rtree"].lower()


def test_geohash_code_then_prefix_lookup() -> None:
    with httpx.Client(base_url=BASE, timeout=30.0) as client:
        body = client.get("/api/geo/code").json()
        assert len(body["code"]) == 7
        assert len(body["steps"]) == 7
        assert "".join(step["char"] for step in body["steps"]) == body["code"]
        assert body["prefix"] == body["code"][:6]
        hits = {row["name"]: row for row in body["hits"]}
        assert hits["Ferry Building"]["hit"] is True
        assert hits["Rectangle corner"]["hit"] is True
        assert hits["Atlantic same latitude"]["hit"] is False
        assert hits["Ferry Building"]["code"] != body["code"]
        assert any(f"Index code: {body['code']}" in line for line in body["log"])


def test_radius_keeps_ferry_and_drops_same_latitude() -> None:
    with httpx.Client(base_url=BASE, timeout=30.0) as client:
        geo = client.get("/api/explain/geo").json()
        band = client.get("/api/explain/latband").json()
        assert geo["ferry"] is True
        assert geo["atlantic"] is False
        assert "gist" in geo["plan"].lower() or "places_geom" in geo["plan"]
        assert band["ferry"] is True
        assert band["atlantic"] is True
        assert "places_lat" in band["plan"]


def test_word_lookup_uses_gin_after_create() -> None:
    with httpx.Client(base_url=BASE, timeout=60.0) as client:
        dropped = client.delete("/api/gin")
        assert dropped.status_code == 200
        before = client.get("/api/explain/search").json()
        assert "Seq Scan" in before["plan"]
        assert len(before["names"]) > 0

        created = client.post("/api/gin")
        assert created.status_code == 200
        after = client.get("/api/explain/search").json()
        assert "Index" in after["plan"]
        assert "Seq Scan" not in after["plan"].split("\n")[0]
        full = client.get("/api/explain/fullscan").json()
        assert "Seq Scan" in full["plan"]
        assert full["names"] == after["names"]
        assert len(full["names"]) == 40
