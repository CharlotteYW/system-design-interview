"""Functional tests of the OTP page and the API the page calls."""

from __future__ import annotations

import os
import time

import httpx

BASE = os.environ.get("OTP_BASE_URL", "http://localhost:8000")


def test_page_explains_the_contract() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        page = client.get("/")
        assert page.status_code == 200
        text = page.text
        assert 'id="generate"' in text
        assert 'id="verify"' in text
        assert 'id="verify-twice"' in text
        assert 'id="sms-down"' in text
        assert 'id="redis-down"' in text
        assert "202" in text
        assert "200" in text
        assert "hash" in text
        assert "Lua" in text
        assert "expires_in" in text
        assert "10 minutes" in text
        assert "Five wrong guesses" in text
        assert "Inbox" in text


def test_page_flow_generate_inbox_verify() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0, headers={"x-client-ip": "ui-flow"}) as client:
        client.post("/api/reset")
        destination = "user@example.com"
        created = client.post(
            "/v1/otps",
            json={"destination": destination, "channel": "email", "purpose": "payment"},
        )
        assert created.status_code == 202
        assert "code" not in created.json()
        code = ""
        for _ in range(40):
            inbox = client.get("/api/inbox", params={"destination": destination})
            assert inbox.status_code == 200
            messages = inbox.json()["messages"]
            if messages:
                code = messages[0]["code"]
                break
            time.sleep(0.1)
        assert len(code) == 6
        checked = client.post(
            "/v1/otps/verify",
            json={"destination": destination, "purpose": "payment", "code": code},
        )
        assert checked.status_code == 200
        assert checked.json() == {"ok": True}
