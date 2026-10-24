"""Helpers that do what the browser does: hash, ask for part URLs, PUT parts to S3, complete."""

from __future__ import annotations

import base64
import hashlib
import os
import time

import httpx
import pytest

BASE_URL = os.environ.get("YT_BASE_URL", "http://localhost:8300")
_samples: dict[int, bytes] = {}


@pytest.fixture
def client() -> httpx.Client:
    with httpx.Client(base_url=BASE_URL, timeout=60.0) as http:
        yield http


def sample(client: httpx.Client, seconds: int = 8) -> bytes:
    if seconds not in _samples:
        r = client.get("/v1/lab/sample.mp4", params={"seconds": seconds})
        assert r.status_code == 200
        _samples[seconds] = r.content
    return _samples[seconds]


def part_sha(data: bytes) -> str:
    return base64.b64encode(hashlib.sha256(data).digest()).decode()


def create(client: httpx.Client, data: bytes, trigger: str = "event", sha256: str | None = None) -> dict:
    r = client.post("/v1/videos", json={
        "title": "test", "fileSizeBytes": len(data), "contentType": "video/mp4",
        "sha256": hashlib.sha256(data).hexdigest() if sha256 is None else sha256, "trigger": trigger,
    })
    assert r.status_code == 200, r.text
    return r.json()


def put_part(client: httpx.Client, video: dict, data: bytes, n: int, send: bytes | None = None) -> httpx.Response:
    ps = video["partSizeBytes"]
    chunk = data[(n - 1) * ps: n * ps]
    urls = client.post(f"/v1/videos/{video['videoId']}/parts",
                       json={"parts": [{"partNumber": n, "sha256": part_sha(chunk)}]}).json()["parts"]
    return httpx.put(urls[0]["url"], content=chunk if send is None else send, headers=urls[0]["headers"], timeout=60)


def upload_all(client: httpx.Client, video: dict, data: bytes) -> list[dict]:
    receipts = []
    for n in range(1, video["partCount"] + 1):
        r = put_part(client, video, data, n)
        assert r.status_code == 200, r.text
        receipts.append({"partNumber": n, "etag": r.headers["etag"]})
    return receipts


def wait_status(client: httpx.Client, video_id: str, want: set[str], all_renditions: bool = True,
                timeout: float = 120) -> dict:
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        last = client.get(f"/v1/videos/{video_id}").json()
        if last["status"] in want and (not all_renditions or last["status"] != "ready" or len(last["renditions"]) == 3):
            return last
        time.sleep(0.5)
    raise AssertionError(f"video {video_id} stuck: {last}")


def state(client: httpx.Client, video_id: str) -> dict:
    return client.get("/v1/lab/state", params={"videoId": video_id}).json()
