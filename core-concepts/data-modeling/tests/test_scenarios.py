"""Integration tests for the data modeling lab."""

from __future__ import annotations

import json
import os

import httpx

BASE = os.environ.get("API_BASE_URL", "http://localhost:8000")


def _client() -> httpx.Client:
    return httpx.Client(base_url=BASE, timeout=60.0)


def _engine(client: httpx.Client, kind: str) -> dict:
    body = client.get(f"/api/engines/{kind}").json()
    assert body["ok"] is True
    assert body["interview"]
    assert body["requirement"]
    assert body["write_sql"]
    assert body["read_sql"]
    assert body["shape"]["kind"]
    return body


def test_relational_write_and_read() -> None:
    with _client() as client:
        body = _engine(client, "relational")
        assert body["shape"]["kind"] == "table"
        assert "555-0100" in json.dumps(body["sample"])
        wrote = client.post("/api/engines/relational/write").json()
        assert wrote["wrote"]["result"] == "bob is stored"
        assert "555-0101" in json.dumps(wrote["sample"])


def test_key_value_write_and_read() -> None:
    with _client() as client:
        before = _engine(client, "key-value")
        assert before["shape"]["kind"] == "pairs"
        start = int(before["sample"]["like_count:moment:1"])
        wrote = client.post("/api/engines/key-value/write").json()
        assert int(wrote["sample"]["like_count:moment:1"]) == start + 1


def test_document_write_and_read() -> None:
    with _client() as client:
        body = _engine(client, "document")
        assert body["shape"]["kind"] == "document"
        assert body["sample"]["city"] == "Shanghai"
        wrote = client.post("/api/engines/document/write").json()
        assert wrote["sample"]["badge"] == "vip"


def test_wide_column_write_and_read() -> None:
    with _client() as client:
        body = _engine(client, "wide-column")
        assert body["shape"]["kind"] == "partitions"
        assert "hello" in json.dumps(body["sample"])
        wrote = client.post("/api/engines/wide-column/write").json()
        assert "on my way" in json.dumps(wrote["sample"])


def test_columnar_write_and_read() -> None:
    with _client() as client:
        body = _engine(client, "columnar")
        assert body["shape"]["kind"] == "columns"
        assert "Shanghai" in json.dumps(body["sample"])
        wrote = client.post("/api/engines/columnar/write").json()
        assert "Guangzhou" in json.dumps(wrote["sample"])


def test_graph_write_and_read() -> None:
    with _client() as client:
        body = _engine(client, "graph")
        assert body["shape"]["kind"] == "graph"
        assert "nova" in json.dumps(body["sample"])
        wrote = client.post("/api/engines/graph/write").json()
        assert {"from": "ada", "to": "lee"} in wrote["shape"]["edges"]


def test_time_series_write_and_read() -> None:
    with _client() as client:
        body = _engine(client, "time-series")
        assert body["shape"]["kind"] == "series"
        assert "chat-1" in json.dumps(body["sample"])
        wrote = client.post("/api/engines/time-series/write").json()
        assert 15 in [row["messages"] for row in wrote["sample"]]


def test_search_write_and_read() -> None:
    with _client() as client:
        body = _engine(client, "search")
        assert body["shape"]["kind"] == "index"
        assert "lunch" in json.dumps(body["sample"])
        wrote = client.post("/api/engines/search/write").json()
        hit_ids = [item["id"] for item in wrote["sample"]["hits"]]
        assert "3" in hit_ids


def test_rename_leaves_copies_stale_until_they_are_updated() -> None:
    with _client() as client:
        client.post("/api/reset")
        stale = client.post(
            "/api/rename",
            json={"user_id": 1, "username": "ada_new", "update_copies": False},
        ).json()
        assert stale["normalized_feed"][0]["username"] == "ada_new"
        assert stale["denormalized_feed"][0]["username"] == "ada"
        assert stale["copy_rows_updated"] == 0

        client.post("/api/reset")
        fresh = client.post(
            "/api/rename",
            json={"user_id": 1, "username": "ada_new", "update_copies": True},
        ).json()
        assert fresh["normalized_feed"][0]["username"] == "ada_new"
        assert fresh["denormalized_feed"][0]["username"] == "ada_new"
        assert fresh["copy_rows_updated"] == 2


def test_second_like_is_one_row_and_a_bare_counter_grows() -> None:
    with _client() as client:
        client.post("/api/reset")
        postgres = client.post(
            "/api/likes",
            json={"user_id": 2, "post_id": 1, "store": "postgres"},
        ).json()
        assert postgres["replayed"] is True
        assert postgres["postgres"]["count"] == 1
        assert postgres["postgres"]["user_ids"] == [2]

        client.post("/api/reset")
        member = client.post(
            "/api/likes",
            json={"user_id": 2, "post_id": 1, "store": "redis_member"},
        ).json()
        assert member["replayed"] is True
        assert member["redis_member"]["count"] == 1

        client.post("/api/reset")
        clicks = client.post(
            "/api/likes",
            json={"user_id": 2, "post_id": 1, "store": "redis_counter"},
        ).json()
        assert clicks["replayed"] is False
        assert clicks["redis_counter"]["clicks"] == 2
        assert clicks["postgres"]["count"] == 1


def test_user_id_keeps_one_shard_and_salt_splits_the_read() -> None:
    with _client() as client:
        client.post("/api/reset")
        body = client.get("/api/partition/7").json()
        assert body["user_id_strategy"]["shards_read"] == [3]
        assert body["user_id_strategy"]["rows"] == 8
        assert len(body["salt_strategy"]["shards_read"]) > 1
        assert body["extra_app_servers"]["shard"] == 3
        assert body["read_replica"]["writes"] == "primary"
        assert "still shard 3" in body["diagram"]


def test_home_feed_scatters_by_author_and_inbox_is_one_shard() -> None:
    with _client() as client:
        client.post("/api/reset")
        body = client.get("/api/home/2").json()
        assert body["fanout_on_read"]["shards"] == [1, 3]
        assert len(body["fanout_on_read"]["rows"]) == 10
        assert body["fanout_on_write"]["shard"] == 2
        assert body["fanout_on_write"]["rows"][0]["author_name"] == "ada"
        graph = client.get("/api/graph/1").json()
        assert graph["store"] == "postgres"
        assert graph["direct"] == ["bob"]
        assert "nova" in graph["two_hop"]
