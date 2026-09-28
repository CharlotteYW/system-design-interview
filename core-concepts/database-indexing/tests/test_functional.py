from __future__ import annotations

import os

import httpx

BASE = os.environ.get("INDEXING_BASE_URL", "http://localhost:8000")


def test_ui_explains_the_three_queries() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        page = client.get("/")
        assert page.status_code == 200
        text = page.text
        assert 'id="user"' in text
        assert 'id="both"' in text
        assert 'id="date"' in text
        assert 'id="cover"' in text
        assert 'id="body"' in text
        assert "Index Only Scan" in text
        assert "user_id, created_at" in text
        assert "June 1 only" in text
        assert 'id="lsm"' in text
        assert 'id="lsm-log"' in text
        assert 'id="geo-log"' in text
        assert 'id="geo"' in text
        assert 'id="geo-code"' in text
        assert "index code" in text
        assert 'id="search"' in text
        assert 'id="fullscan"' in text
        assert 'id="word-log"' in text
        assert "Full search" in text
        assert "memtable" in text
        assert "within 200 meters" in text
        assert "idx_lat" in text
        assert "idx_lng" in text
        assert "Geohash" in text
        assert "Quadtree" in text
        assert "word" in text.lower()


def test_ui_flow_create_index_and_explain_date() -> None:
    with httpx.Client(base_url=BASE, timeout=30.0) as client:
        client.post("/api/index")
        explained = client.get("/api/explain/date")
        assert explained.status_code == 200
        assert "created_at" in explained.json()["sql"]
        assert "Seq Scan" in explained.json()["plan"]
