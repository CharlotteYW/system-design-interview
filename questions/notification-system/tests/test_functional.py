"""Functional tests of the flows the page sends."""

from __future__ import annotations

import os
import time
import uuid

import httpx
import pytest

BASE_URL = os.environ.get("NOTIFICATION_BASE_URL", "http://localhost:8000")


@pytest.fixture
def client() -> httpx.Client:
    with httpx.Client(base_url=BASE_URL, timeout=20.0) as http:
        yield http


def test_page_shows_the_notice_shape(client: httpx.Client) -> None:
    page = client.get("/")
    assert page.status_code == 200
    text = page.text
    assert "POST /v1/notices" in text
    assert "idempotencyKey" in text
    assert "notices-high" in text
    assert "POST /v1/campaigns" in text


def test_page_flow_sends_a_low_notice(client: httpx.Client) -> None:
    created = client.post(
        "/v1/notices",
        json={
            "userId": "kim",
            "channel": "sms",
            "content": {"title": "Note", "body": "Weekly"},
            "priority": "low",
            "idempotencyKey": f"ui-{uuid.uuid4()}",
        },
    )
    assert created.status_code == 202
    assert set(created.json()) >= {"id", "status"}
    notice_id = created.json()["id"]
    last = {}
    for _ in range(40):
        last = client.get(f"/v1/notices/{notice_id}").json()
        if last["status"] == "sent":
            break
        time.sleep(0.25)
    assert last["status"] == "sent"
    assert last["channel"] == "sms"
    state = client.get("/v1/lab/state").json()
    match = next(item for item in state["notices"] if item["id"] == notice_id)
    assert match["topic"] == "notices-low"
