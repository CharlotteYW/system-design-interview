"""Integration tests against the running key-value stack."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

BASE = os.environ.get("KV_BASE_URL", "http://localhost:8000")


@pytest.fixture(autouse=True)
def reset() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        response = client.post("/api/reset")
        assert response.status_code == 200


def client() -> httpx.Client:
    return httpx.Client(base_url=BASE, timeout=10.0)


def outsider(body: dict, coordinator: str) -> str:
    touched = set(body["l1_updates"])
    for name in "ABCDE":
        if name not in touched and name != coordinator:
            return name
    raise AssertionError(f"no outsider in {body}")


def test_put_then_get_round_trip() -> None:
    with client() as http:
        put = http.put("/v1/keys/user:42", json={"value": "hello"}, params={"at": "A"})
        assert put.status_code == 200
        body = put.json()
        assert body["coordinator"] == "A"
        assert len(body["preference"]) == 3
        assert len(body["acks"]) >= 2
        assert "A" in body["l1_updates"]
        for name in body["acks"]:
            assert name in body["l1_updates"]

        hit = http.get("/v1/keys/user:42", params={"at": "A"})
        assert hit.status_code == 200
        got = hit.json()
        assert got["l1"] == "hit"
        assert got["replica_reads"] == []
        assert got["preference"] is None
        assert got["value"] == "hello"


def test_second_get_on_same_server_skips_replicas() -> None:
    with client() as http:
        assert http.put("/v1/keys/hot", json={"value": "v1"}, params={"at": "A"}).status_code == 200
        first = http.get("/v1/keys/hot", params={"at": "E"}).json()
        assert first["l1"] == "miss"
        assert len(first["replica_reads"]) == 2
        second = http.get("/v1/keys/hot", params={"at": "E"}).json()
        assert second["l1"] == "hit"
        assert second["replica_reads"] == []
        assert second["value"] == "v1"


def test_put_leaves_outsider_l1_stale_until_ttl() -> None:
    with client() as http:
        first = http.put("/v1/keys/profile", json={"value": "hello"}, params={"at": "A"})
        assert first.status_code == 200
        other = outsider(first.json(), "A")
        filled = http.get("/v1/keys/profile", params={"at": other}).json()
        assert filled["l1"] == "miss"
        assert filled["value"] == "hello"

        second = http.put("/v1/keys/profile", json={"value": "world"}, params={"at": "A"})
        assert second.status_code == 200
        updated = set(second.json()["l1_updates"])
        assert other not in updated

        stale = http.get("/v1/keys/profile", params={"at": other}).json()
        assert stale["l1"] == "hit"
        assert stale["value"] == "hello"
        fresh = http.get("/v1/keys/profile", params={"at": "A"}).json()
        assert fresh["l1"] == "hit"
        assert fresh["value"] == "world"


def _alive_coordinator(down: set[str]) -> str:
    for name in "ABCDE":
        if name not in down:
            return name
    raise AssertionError("no coordinator left")


def test_one_owner_down_still_puts() -> None:
    with client() as http:
        owners = http.put("/v1/keys/k-one-down", json={"value": "a"}, params={"at": "A"}).json()["preference"]
        victim = owners[0]
        coord = _alive_coordinator({victim})
        assert http.post(f"/api/servers/{victim}/down").status_code == 200
        try:
            again = http.put("/v1/keys/k-one-down", json={"value": "b"}, params={"at": coord})
            assert again.status_code == 200
            assert victim not in again.json()["acks"]
            assert len(again.json()["acks"]) >= 2
        finally:
            http.post(f"/api/servers/{victim}/up")


def test_two_owners_down_rejects_put() -> None:
    with client() as http:
        owners = http.put("/v1/keys/k-two-down", json={"value": "a"}, params={"at": "A"}).json()["preference"]
        down = {owners[0], owners[1]}
        coord = _alive_coordinator(down)
        assert http.post(f"/api/servers/{owners[0]}/down").status_code == 200
        assert http.post(f"/api/servers/{owners[1]}/down").status_code == 200
        try:
            rejected = http.put("/v1/keys/k-two-down", json={"value": "b"}, params={"at": coord})
            assert rejected.status_code == 503
        finally:
            http.post(f"/api/servers/{owners[0]}/up")
            http.post(f"/api/servers/{owners[1]}/up")


def test_delete_is_a_tombstone() -> None:
    with client() as http:
        assert http.put("/v1/keys/gone", json={"value": "hello"}, params={"at": "A"}).status_code == 200
        deleted = http.delete("/v1/keys/gone", params={"at": "A"})
        assert deleted.status_code == 200
        assert deleted.json()["tombstone"] is True
        got = http.get("/v1/keys/gone", params={"at": "A"})
        assert got.status_code == 200
        assert got.json()["found"] is False
        assert got.json()["l1"] == "hit"


def test_parallel_puts_keep_a_version() -> None:
    def write(i: int) -> int:
        with client() as http:
            response = http.put("/v1/keys/race", json={"value": f"v{i}"}, params={"at": "A"})
            assert response.status_code == 200
            return response.json()["version"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        versions = list(pool.map(write, range(8)))
    assert len(set(versions)) == 8
    with client() as http:
        got = http.get("/v1/keys/race", params={"at": "A"}).json()
    assert got["l1"] == "hit"
    assert got["version"] == max(versions)
