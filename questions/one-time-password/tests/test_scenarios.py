"""Integration tests against the running OTP stack."""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

BASE = os.environ.get("OTP_BASE_URL", "http://localhost:8000")


def _client(ip: str) -> httpx.Client:
    return httpx.Client(base_url=BASE, timeout=10.0, headers={"x-client-ip": ip})


def _wait_code(client: httpx.Client, destination: str) -> str:
    for _ in range(40):
        inbox = client.get("/api/inbox", params={"destination": destination})
        assert inbox.status_code == 200
        messages = inbox.json()["messages"]
        if messages:
            return messages[0]["code"]
        time.sleep(0.1)
    raise AssertionError("worker did not deliver a code")


def test_generate_returns_202_without_the_code() -> None:
    with _client("203-a") as client:
        client.post("/api/reset")
        response = client.post(
            "/v1/otps",
            json={"destination": "+15550000001", "channel": "email", "purpose": "login"},
        )
        assert response.status_code == 202
        assert response.json() == {"expires_in": 600}
        assert "code" not in response.json()


def test_inbox_then_verify_once() -> None:
    with _client("203-b") as client:
        destination = "+15550000002"
        created = client.post(
            "/v1/otps",
            json={"destination": destination, "channel": "sms", "purpose": "login"},
        )
        assert created.status_code == 202
        code = _wait_code(client, destination)
        ok = client.post(
            "/v1/otps/verify",
            json={"destination": destination, "purpose": "login", "code": code},
        )
        assert ok.status_code == 200
        assert ok.json() == {"ok": True}
        again = client.post(
            "/v1/otps/verify",
            json={"destination": destination, "purpose": "login", "code": code},
        )
        assert again.status_code == 400
        assert again.json() == {"ok": False}


def test_wrong_code_is_the_same_shape_as_unknown() -> None:
    with _client("203-c") as client:
        destination = "+15550000003"
        client.post(
            "/v1/otps",
            json={"destination": destination, "channel": "email", "purpose": "payment"},
        )
        _wait_code(client, destination)
        wrong = client.post(
            "/v1/otps/verify",
            json={"destination": destination, "purpose": "payment", "code": "000000"},
        )
        missing = client.post(
            "/v1/otps/verify",
            json={"destination": "+15550999999", "purpose": "payment", "code": "000000"},
        )
        assert wrong.status_code == 400
        assert missing.status_code == 400
        assert wrong.json() == missing.json() == {"ok": False}


def test_fifth_wrong_guess_kills_the_real_code() -> None:
    with _client("203-d") as client:
        destination = "+15550000004"
        client.post(
            "/v1/otps",
            json={"destination": destination, "channel": "email", "purpose": "login"},
        )
        code = _wait_code(client, destination)
        for _ in range(5):
            bad = client.post(
                "/v1/otps/verify",
                json={"destination": destination, "purpose": "login", "code": "111111"},
            )
            assert bad.status_code == 400
        late = client.post(
            "/v1/otps/verify",
            json={"destination": destination, "purpose": "login", "code": code},
        )
        assert late.status_code == 400
        assert late.json() == {"ok": False}


def test_cooldown_blocks_a_second_generate() -> None:
    with _client("203-e") as client:
        destination = "+15550000005"
        body = {"destination": destination, "channel": "email", "purpose": "login"}
        first = client.post("/v1/otps", json=body)
        assert first.status_code == 202
        second = client.post("/v1/otps", json=body)
        assert second.status_code == 429
        assert second.json()["error"] == "cooldown"


def test_only_one_of_two_overlapping_verifies_succeeds() -> None:
    with _client("203-f") as client:
        destination = "+15550000006"
        client.post(
            "/v1/otps",
            json={"destination": destination, "channel": "email", "purpose": "login"},
        )
        code = _wait_code(client, destination)

    def once() -> int:
        with _client("203-f") as client:
            response = client.post(
                "/v1/otps/verify",
                json={"destination": destination, "purpose": "login", "code": code},
            )
            return response.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(lambda _: once(), range(2)))
    assert sorted(codes) == [200, 400]


def test_sms_down_rejects_sms_and_still_sends_email() -> None:
    with _client("203-g") as client:
        client.post("/api/reset")
        flagged = client.post("/api/situations/sms", json={"down": True})
        assert flagged.json()["sms_down"] is True
        sms = client.post(
            "/v1/otps",
            json={"destination": "+15550000007", "channel": "sms", "purpose": "login"},
        )
        assert sms.status_code == 503
        email = client.post(
            "/v1/otps",
            json={"destination": "+15550000008", "channel": "email", "purpose": "login"},
        )
        assert email.status_code == 202
        assert _wait_code(client, "+15550000008")
        client.post("/api/situations/sms", json={"down": False})


def test_redis_down_is_503_on_generate_and_verify() -> None:
    with _client("203-h") as client:
        client.post("/api/situations/redis", json={"down": True})
        generated = client.post(
            "/v1/otps",
            json={"destination": "+15550000009", "channel": "email", "purpose": "login"},
        )
        checked = client.post(
            "/v1/otps/verify",
            json={"destination": "+15550000009", "purpose": "login", "code": "123456"},
        )
        assert generated.status_code == 503
        assert checked.status_code == 503
        assert generated.json()["error"] == "unavailable"
        client.post("/api/situations/redis", json={"down": False})


def test_daily_cap_rejects_generate() -> None:
    with _client("203-i") as client:
        destination = "+15550000010"
        client.post("/api/situations/daily-full", json={"destination": destination})
        response = client.post(
            "/v1/otps",
            json={"destination": destination, "channel": "email", "purpose": "login"},
        )
        assert response.status_code == 429
        assert response.json()["error"] == "daily_cap"
