"""Functional tests of the unique-ID page and the API it calls."""

from __future__ import annotations

import os

import httpx

BASE = os.environ.get("ID_BASE_URL", "http://localhost:8000")


def test_page_explains_each_generator() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        page = client.get("/")
        assert page.status_code == 200
        text = page.text
        assert 'id="counter"' in text
        assert 'id="ticket"' in text
        assert 'id="uuid"' in text
        assert 'id="snowflake"' in text
        assert "nextval" in text
        assert "version is 4" in text or "version is 4" in text.replace("the version is 4", "version is 4")
        assert "byte 6" in text
        assert "delta" in text
        assert "18 digits" in text
        assert "This is a sum" in text
        assert "2^22" in text
        assert "7095218864128" in text
        assert "00000" in text
        assert "04096" in text
        assert "709521886412801000" in text
        assert "blocks of 4" in text
        assert 'id="clock-back"' in text
        assert 'id="lease"' in text
        assert 'id="overflow"' in text
        assert 'id="server-dies"' in text
        assert 'id="postgres-down"' in text
        assert "1024" in text or "1023" in text
        assert "4096" in text
        assert "gaps" in text


def test_page_api_returns_steps() -> None:
    with httpx.Client(base_url=BASE, timeout=10.0) as client:
        assert client.post("/api/reset").status_code == 200
        body = client.post("/api/generate", params={"kind": "uuid", "count": 1}).json()
        steps = body["servers"][0]["ids"][0]["steps"]
        assert any("16 random bytes" in line for line in steps)
        assert body["servers"][0]["ids"][0]["value"].split("-")[2][0] == "4"
