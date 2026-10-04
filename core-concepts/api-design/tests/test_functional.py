"""The React page exposes each variant the user can click."""

from __future__ import annotations

import os
import re

import httpx

BASE = os.environ.get("API_BASE_URL", "http://localhost:8000")


def test_page_lists_the_variants() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        html = client.get("/").text
        assert 'id="root"' in html
        match = re.search(r'src="([^"]+\.js)"', html)
        assert match
        script = client.get(match.group(1)).text
        for marker in (
            "GET /v1/events",
            "Apollo",
            "Strawberry",
            "strawberry.type",
            "strawberry.field",
            "strawberry.mutation",
            "graphql-ruby",
            "Ariadne",
            "eventsQuery",
            "bookSeat",
            "events_query",
            "Idempotency-Key",
            "Login with Redis",
            "GET /v2/events",
            "gRPC",
        ):
            assert marker in script


def test_rest_filter_matches_the_page_request() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        response = client.get("/v1/events", params={"city": "NYC", "status": "upcoming", "sort": "date"})
        assert response.status_code == 200
        assert response.json()["events"][0]["city"] == "NYC"
