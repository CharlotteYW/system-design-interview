"""Functional tests for the data modeling page."""

from __future__ import annotations

import os

import httpx

BASE = os.environ.get("API_BASE_URL", "http://localhost:8000")


def test_page_shows_each_variant() -> None:
    with httpx.Client(base_url=BASE, timeout=20.0) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert page.headers["cache-control"] == "no-store"
        text = page.text
        assert "Interview default." in text
        assert "Most common use." in text
        for button_id in (
            "rename-stale",
            "rename-fresh",
            "like-pg",
            "like-redis",
            "like-counter",
            "partition",
            "home",
            "graph",
        ):
            assert f'id="{button_id}"' in text
        assert "post_copies" in text
        assert "user_id" in text
        assert "salt" in text
        for button_id in (
            "engine-relational",
            "engine-key-value",
            "engine-document",
            "engine-wide-column",
            "engine-columnar",
            "engine-graph",
            "engine-time-series",
            "engine-search",
        ):
            assert f'id="{button_id}"' in text
        for name in (
            "PostgreSQL",
            "MySQL",
            "Redis",
            "DynamoDB",
            "MongoDB",
            "Cassandra",
            "ClickHouse",
            "Snowflake",
            "Neo4j",
            "TimescaleDB",
            "InfluxDB",
            "Elasticsearch",
            "OpenSearch",
        ):
            assert name in text
        assert 'id="engine-summary"' in text
        assert 'id="schema-summary"' in text
        assert "Schema design inside the store" in text
        assert "Say it in the interview when" in text
        assert "Show Postgres, document, and key-value" not in text
        assert 'role="tab"' in text
        assert "Data shape" in text
        assert "Run the write" in text
        assert "Run the read" in text
        assert 'id="panel-relational"' in text
        assert 'id="panel-search"' in text
        engine = client.get("/api/engines/key-value")
        assert engine.status_code == 200
        assert "like count" in engine.text
        rename = client.post(
            "/api/rename",
            json={"user_id": 1, "username": "ada_new", "update_copies": False},
        )
        assert rename.status_code == 200
        assert "ada_new" in rename.text
        assert "normalized_feed" in rename.text
