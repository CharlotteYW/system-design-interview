"""REST filters, GraphQL, gRPC, auth, idempotency, errors, and versions."""

from __future__ import annotations

import os

import httpx

BASE = os.environ.get("API_BASE_URL", "http://localhost:8000")


def test_rest_query_reaches_the_api() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        response = client.get("/v1/events", params={"city": "NYC", "status": "upcoming", "sort": "date"})
        body = response.json()
        assert body["received_query"] == {"city": "NYC", "status": "upcoming", "sort": "date"}
        assert [event["name"] for event in body["events"]] == ["Concert"]
        ordered = client.get("/v1/events", params={"sort": "-date"})
        assert [event["name"] for event in ordered.json()["events"]] == ["Fair", "Concert", "Play"]


def test_graphql_mutation_writes_a_booking() -> None:
    mutation = """
    mutation Book($eventId: Int!, $quantity: Int!, $idempotencyKey: String!) {
      bookSeat(eventId: $eventId, quantity: $quantity, idempotencyKey: $idempotencyKey) {
        code
        replayed
        bookingId
        quantity
      }
    }
    """
    variables = {"eventId": 1, "quantity": 1, "idempotencyKey": "gql-scenario"}
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        client.post("/api/reset")
        first = client.post("/graphql", json={"query": mutation, "variables": variables})
        second = client.post("/graphql", json={"query": mutation, "variables": variables})
        assert first.json()["data"]["bookSeat"]["code"] == "CREATED"
        assert first.json()["data"]["bookSeat"]["replayed"] is False
        assert second.json()["data"]["bookSeat"]["replayed"] is True
        assert second.json()["data"]["bookSeat"]["bookingId"] == first.json()["data"]["bookSeat"]["bookingId"]


def test_graphql_returns_only_the_asked_fields() -> None:
    query = '{ eventsQuery(city: "NYC", status: "upcoming") { id name } }'
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        response = client.post("/graphql", json={"query": query})
        event = response.json()["data"]["eventsQuery"][0]
        assert event == {"id": 1, "name": "Concert"}


def test_jwt_memory_and_redis_sessions() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        client.post("/api/reset")
        token = client.post("/api/login", json={"account_id": 42, "mode": "jwt", "server": "a"}).json()["token"]
        jwt_me = client.get("/api/me", params={"mode": "jwt", "server": "b"}, headers={"Authorization": f"Bearer {token}"})
        assert jwt_me.json()["store_read"] == "none"
        assert jwt_me.json()["account_id"] == 42

        memory = client.post("/api/login", json={"account_id": 42, "mode": "memory", "server": "a"}).json()
        headers = {"X-Session": memory["session_id"]}
        on_a = client.get("/api/me", params={"mode": "memory", "server": "a"}, headers=headers)
        on_b = client.get("/api/me", params={"mode": "memory", "server": "b"}, headers=headers)
        assert on_a.status_code == 200
        assert on_b.status_code == 401
        assert on_b.json()["error"]["code"] == "SESSION_NOT_ON_THIS_SERVER"

        redis_login = client.post("/api/login", json={"account_id": 42, "mode": "redis", "server": "a"}).json()
        redis_headers = {"X-Session": redis_login["session_id"]}
        for server in ("a", "b"):
            found = client.get("/api/me", params={"mode": "redis", "server": server}, headers=redis_headers)
            assert found.json()["store_read"] == "redis"
        client.post("/api/logout", params={"mode": "redis", "server": "a"}, headers=redis_headers)
        gone = client.get("/api/me", params={"mode": "redis", "server": "b"}, headers=redis_headers)
        assert gone.status_code == 401
        assert gone.json()["error"]["code"] == "SESSION_MISSING"


def test_booking_uses_grpc_and_replays_the_key() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        client.post("/api/reset")
        token = client.post("/api/login", json={"account_id": 42, "mode": "jwt", "server": "a"}).json()["token"]
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "click-1"}
        first = client.post("/v1/events/1/bookings", params={"mode": "jwt"}, headers=headers, json={"quantity": 1})
        second = client.post("/v1/events/1/bookings", params={"mode": "jwt"}, headers=headers, json={"quantity": 1})
        assert first.status_code == 201
        assert first.json()["grpc"]["transport"] == "grpc"
        assert first.json()["grpc"]["method"] == "CheckSeats"
        assert second.json()["replayed"] is True
        assert second.json()["booking"]["id"] == first.json()["booking"]["id"]
        conflict = client.post(
            "/v1/events/1/bookings",
            params={"mode": "jwt"},
            headers=headers,
            json={"quantity": 2},
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "KEY_REUSED"
        too_many = client.post(
            "/v1/events/1/bookings",
            params={"mode": "jwt"},
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "click-9"},
            json={"quantity": 9},
        )
        assert too_many.status_code == 409
        assert too_many.json()["error"]["code"] == "SEATS_UNAVAILABLE"


def test_v2_renames_the_field() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        first = client.get("/v1/events", params={"city": "NYC", "status": "upcoming"}).json()["events"][0]
        second = client.get("/v2/events", params={"city": "NYC", "status": "upcoming"}).json()["events"][0]
        assert first["name"] == "Concert"
        assert second["title"] == "Concert"
        assert "name" not in second
