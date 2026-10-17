"""Run every test against both designs unless CHAT_BASE_URLS narrows it."""

from __future__ import annotations

import os

import httpx
import pytest

PG_URL = os.environ.get("CHAT_PG_URL", "http://localhost:8000")
CS_URL = os.environ.get("CHAT_CS_URL", "http://localhost:8001")
DESIGN_URLS = {"postgres": PG_URL, "cassandra": CS_URL}


@pytest.fixture(params=["postgres", "cassandra"])
def design(request) -> str:
    return request.param


@pytest.fixture
def client(design: str) -> httpx.Client:
    with httpx.Client(base_url=DESIGN_URLS[design], timeout=20.0) as http:
        yield http


@pytest.fixture
def pg_client() -> httpx.Client:
    with httpx.Client(base_url=PG_URL, timeout=20.0) as http:
        yield http


@pytest.fixture
def cs_client() -> httpx.Client:
    with httpx.Client(base_url=CS_URL, timeout=20.0) as http:
        yield http


def message_rows(state: dict) -> list[dict]:
    if state["design"] == "cassandra":
        return state["cassandra"]["messages_by_chat"]
    return state["postgres"]["messages"]


def cursor_rows(state: dict) -> list[dict]:
    if state["design"] == "cassandra":
        return state["cassandra"]["device_cursors_by_client"]
    return state["postgres"]["device_cursors"]
