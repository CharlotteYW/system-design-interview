"""Helpers that drive the crawler through its HTTP API, the same calls the lab page makes."""

from __future__ import annotations

import os
import time

import httpx
import pytest

BASE_URL = os.environ.get("CRAWL_BASE_URL", "http://localhost:8400")


@pytest.fixture(scope="session")
def client() -> httpx.Client:
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as http:
        yield http


def start(client: httpx.Client, **body) -> str:
    r = client.post("/v1/crawls", json=body)
    assert r.status_code == 202, r.text
    return r.json()["crawlId"]


def state(client: httpx.Client) -> dict:
    r = client.get("/v1/lab/state")
    assert r.status_code == 200, r.text
    return r.json()


def urls(client: httpx.Client) -> dict[str, dict]:
    return {u["url"]: u for u in client.get("/v1/lab/urls").json()}


def wait_done(client: httpx.Client, timeout: float = 120) -> dict:
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        last = state(client)
        if last["status"] == "done":
            return last
        time.sleep(1)
    raise AssertionError(f"crawl not done: {last.get('byState')} queues={last.get('queues')}")


def crawl(client: httpx.Client, timeout: float = 120, **body) -> tuple[dict, dict[str, dict]]:
    start(client, **body)
    s = wait_done(client, timeout)
    return s, urls(client)
