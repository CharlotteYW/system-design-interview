"""Integration tests against the running notification lab."""

from __future__ import annotations

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

BASE_URL = os.environ.get("NOTIFICATION_BASE_URL", "http://localhost:8000")


@pytest.fixture
def client() -> httpx.Client:
    with httpx.Client(base_url=BASE_URL, timeout=20.0) as http:
        yield http


def wait_notice(client: httpx.Client, notice_id: str, wanted: set[str]) -> dict:
    last = {}
    for _ in range(40):
        response = client.get(f"/v1/notices/{notice_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last["status"] in wanted:
            return last
        time.sleep(0.25)
    raise AssertionError(last)


def test_health(client: httpx.Client) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_high_notice_is_sent(client: httpx.Client) -> None:
    key = f"otp-{uuid.uuid4()}"
    created = client.post(
        "/v1/notices",
        json={
            "userId": "lee",
            "channel": "sms",
            "content": {"title": "Code", "body": "482913"},
            "priority": "high",
            "idempotencyKey": key,
        },
    )
    assert created.status_code == 202, created.text
    body = created.json()
    assert body["status"] == "accepted"
    sent = wait_notice(client, body["id"], {"sent"})
    assert sent["channel"] == "sms"
    state = client.get("/v1/lab/state").json()
    match = next(item for item in state["notices"] if item["id"] == body["id"])
    assert match["topic"] == "notices-high"
    assert match["priority"] == "high"


def test_sms_off_skips_the_vendor(client: httpx.Client) -> None:
    user_id = f"quiet-{uuid.uuid4()}"
    contact = client.put(
        f"/v1/users/{user_id}/contact",
        json={"email": "a@example.com", "phone": "+15551110000", "deviceToken": "tok"},
    )
    assert contact.status_code == 200
    pref = client.put(
        f"/v1/users/{user_id}/preferences",
        json={"push": True, "email": True, "sms": False, "quietStart": "", "quietEnd": ""},
    )
    assert pref.status_code == 200
    created = client.post(
        "/v1/notices",
        json={
            "userId": user_id,
            "channel": "sms",
            "content": {"title": "Hi", "body": "Hello"},
            "priority": "low",
            "idempotencyKey": f"off-{uuid.uuid4()}",
        },
    )
    assert created.status_code == 202
    skipped = wait_notice(client, created.json()["id"], {"skipped"})
    assert skipped["status"] == "skipped"


def test_same_idempotency_key_returns_one_notice(client: httpx.Client) -> None:
    key = f"same-{uuid.uuid4()}"
    payload = {
        "userId": "kim",
        "channel": "email",
        "content": {"title": "Hi", "body": "Once"},
        "priority": "low",
        "idempotencyKey": key,
    }

    def post_once() -> httpx.Response:
        with httpx.Client(base_url=BASE_URL, timeout=20.0) as http:
            return http.post("/v1/notices", json=payload)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(lambda _fn: post_once(), (0, 1))
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    wait_notice(client, first.json()["id"], {"sent"})
    state = client.get("/v1/lab/state").json()
    calls = [item for item in state["vendorCalls"] if item["notice_id"] == first.json()["id"]]
    assert len(calls) == 1


def test_cancel_stops_a_campaign_in_the_middle(client: httpx.Client) -> None:
    down = client.post("/v1/lab/vendor", json={"vendor": "twilio", "down": True})
    assert down.status_code == 200
    try:
        created = client.post(
            "/v1/campaigns",
            json={
                "userIds": ["lee", "kim"],
                "channel": "sms",
                "content": {"title": "Promo", "body": "Stop me"},
                "idempotencyKey": f"camp-{uuid.uuid4()}",
            },
        )
        assert created.status_code == 202, created.text
        campaign_id = created.json()["id"]
        notices = []
        for _ in range(40):
            state = client.get("/v1/lab/state").json()
            notices = [item for item in state["notices"] if item["campaign_id"] == campaign_id]
            if len(notices) == 2:
                break
            time.sleep(0.25)
        assert len(notices) == 2
        cancelled = client.post(f"/v1/campaigns/{campaign_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
    finally:
        client.post("/v1/lab/vendor", json={"vendor": "twilio", "down": False})
    for notice in notices:
        finished = wait_notice(client, notice["id"], {"cancelled", "sent"})
        assert finished["status"] == "cancelled"
