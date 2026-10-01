"""Integration tests against the running unique-ID stack."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

BASE = os.environ.get("ID_BASE_URL", "http://localhost:8000")


@pytest.fixture(autouse=True)
def reset() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        assert client.post("/api/reset").status_code == 200


def client() -> httpx.Client:
    return httpx.Client(base_url=BASE, timeout=10.0)


def test_counter_is_a_shared_sequence() -> None:
    with client() as http:
        body = http.post("/api/generate", params={"kind": "counter", "count": 3}).json()
        a = [item["value"] for item in body["servers"][0]["ids"]]
        b = [item["value"] for item in body["servers"][1]["ids"]]
        assert a == ["1", "2", "3"]
        assert b == ["4", "5", "6"]
        assert "id_seq" in body["servers"][0]["ids"][0]["steps"][0]


def test_tickets_refill_from_postgres() -> None:
    with client() as http:
        body = http.post("/api/generate", params={"kind": "ticket", "count": 5}).json()
        a = [item["value"] for item in body["servers"][0]["ids"]]
        b = [item["value"] for item in body["servers"][1]["ids"]]
        assert a == ["1", "2", "3", "4", "5"]
        assert b[0] == "9"
        assert "reserved 5–8" in body["servers"][0]["ids"][4]["steps"][0]
        assert "reserved 9–12" in body["servers"][1]["ids"][0]["steps"][0]


def test_uuid_v4_sets_the_version_nibble() -> None:
    with client() as http:
        body = http.post("/api/generate", params={"kind": "uuid", "count": 2}).json()
        values = [item["value"] for server in body["servers"] for item in server["ids"]]
        assert len(set(values)) == 4
        for item in body["servers"][0]["ids"]:
            assert item["value"].split("-")[2][0] == "4"
            assert item["fields"]["version"] == 4
            assert any("version is 4" in line for line in item["steps"])


def test_snowflake_workers_do_not_share_a_sequence() -> None:
    with client() as http:
        body = http.post("/api/generate", params={"kind": "snowflake", "count": 2}).json()
        a = body["servers"][0]["ids"]
        b = body["servers"][1]["ids"]
        assert int(a[1]["value"]) > int(a[0]["value"])
        assert a[0]["fields"]["worker"] == 1
        assert b[0]["fields"]["worker"] == 2
        assert a[0]["fields"]["sequence"] == 0
        if a[1]["fields"]["timestamp_ms"] == a[0]["fields"]["timestamp_ms"]:
            assert a[1]["fields"]["sequence"] == 1
        else:
            assert a[1]["fields"]["timestamp_ms"] > a[0]["fields"]["timestamp_ms"]
        assert a[0]["value"] != b[0]["value"]
        assert "worker 1" in " ".join(a[0]["steps"])


def test_unknown_generator_is_rejected() -> None:
    with client() as http:
        response = http.post("/api/generate", params={"kind": "base62", "count": 1})
        assert response.status_code == 400


def test_clock_jump_keeps_the_last_timestamp() -> None:
    with client() as http:
        body = http.post("/api/situations/clock-back").json()
        facts = body["facts"]
        assert facts["first_sequence"] == 0
        assert facts["second_sequence"] == 1
        assert facts["second_timestamp_ms"] == facts["timestamp_ms"]
        assert facts["clock_read_ms"] == facts["timestamp_ms"] - 5000
        assert int(facts["second_id"]) == int(facts["first_id"]) + 1
        assert any("clock moved backward" in line.lower() for line in body["lines"])


def test_lease_gives_each_server_its_own_slot() -> None:
    with client() as http:
        body = http.post("/api/situations/lease").json()
        facts = body["facts"]
        assert facts["slot_a"] == 0
        assert facts["slot_b"] == 1
        assert facts["refused"] is True
        assert facts["slot_a2"] == 2
        assert facts["difference"] == 4096
        assert facts["id_a"] != facts["id_b"]


def test_overflow_waits_for_the_next_millisecond() -> None:
    with client() as http:
        body = http.post("/api/situations/overflow").json()
        facts = body["facts"]
        assert facts["filled"] == 4096
        assert facts["first_sequence"] == 0
        assert facts["next_sequence"] == 0
        assert facts["next_timestamp_ms"] == facts["requested_timestamp_ms"] + 1


def test_dead_server_leaves_gaps_and_wastes_tickets() -> None:
    with client() as http:
        body = http.post("/api/situations/server-dies").json()
        facts = body["facts"]
        assert facts["sequences"] == [0, 1, 2]
        assert len(set(facts["issued"])) == 3
        assert facts["b_worker"] == 1
        assert facts["c_slot"] == 2
        assert facts["replacement_slot"] == 0
        assert facts["replacement_sequence"] == 0
        assert facts["replacement_timestamp_ms"] > 0
        assert facts["wasted_tickets"] == [3, 4]
        assert facts["next_ticket"] == 5
        assert any("Skipped" in line for line in body["lines"])


def test_postgres_outage_stops_only_the_database_paths() -> None:
    with client() as http:
        body = http.post("/api/situations/postgres-down").json()
        facts = body["facts"]
        assert facts["counter_ok"] is False
        assert facts["ticket_ok"] is False
        assert facts["snowflake_ok"] is True
        assert int(facts["snowflake_id"]) > 0


def test_parallel_counters_stay_unique() -> None:
    def once(_: int) -> str:
        with client() as http:
            body = http.post("/api/generate", params={"kind": "counter", "count": 1}).json()
            return body["servers"][0]["ids"][0]["value"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(once, range(8)))
    assert len(set(values)) == 8
