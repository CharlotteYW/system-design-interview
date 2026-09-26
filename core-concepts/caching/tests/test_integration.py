from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

BASE_URL = os.environ.get("CACHING_BASE_URL", "http://localhost:8000")


@pytest.fixture
def client() -> httpx.Client:
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


def test_health(client: httpx.Client) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200


def test_miss_then_hit(client: httpx.Client) -> None:
    item_id = 101
    client.put(f"/api/items/{item_id}", json={"body": "first"})
    client.post("/api/flush-cache")
    miss = client.get(f"/api/items/{item_id}")
    hit = client.get(f"/api/items/{item_id}")
    assert miss.status_code == 200
    assert miss.json()["cache"] == "MISS"
    assert miss.headers.get("x-cache") == "MISS"
    assert miss.json()["body"] == "first"
    assert hit.status_code == 200
    assert hit.json()["cache"] == "L1"
    assert hit.headers.get("x-cache") == "L1"
    assert hit.json()["body"] == "first"


def test_l2_hit_after_l1_dropped(client: httpx.Client) -> None:
    item_id = 104
    client.put(f"/api/items/{item_id}", json={"body": "in-redis"})
    client.post("/api/flush-cache")
    miss = client.get(f"/api/items/{item_id}")
    assert miss.json()["cache"] == "MISS"
    dropped = client.post("/api/flush-l1")
    assert dropped.status_code == 200
    l2 = client.get(f"/api/items/{item_id}")
    assert l2.status_code == 200
    assert l2.json()["cache"] == "REDIS"
    assert l2.headers.get("x-cache") == "REDIS"
    assert l2.json()["body"] == "in-redis"
    l1 = client.get(f"/api/items/{item_id}")
    assert l1.json()["cache"] == "L1"


def test_unknown_item_is_404(client: httpx.Client) -> None:
    client.post("/api/flush-cache")
    response = client.get("/api/items/999999")
    assert response.status_code == 404


def test_put_invalidates(client: httpx.Client) -> None:
    item_id = 102
    client.put(f"/api/items/{item_id}", json={"body": "before"})
    client.post("/api/flush-cache")
    client.get(f"/api/items/{item_id}")
    client.get(f"/api/items/{item_id}")
    updated = client.put(f"/api/items/{item_id}", json={"body": "after"})
    assert updated.status_code == 200
    again = client.get(f"/api/items/{item_id}")
    assert again.json()["body"] == "after"
    assert again.json()["cache"] == "MISS"


def test_concurrent_miss_is_one_db_load(client: httpx.Client) -> None:
    item_id = 103
    client.put(f"/api/items/{item_id}", json={"body": "herd"})
    client.post("/api/flush-cache")
    before = client.get("/stats").json()["db_loads"]
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as extra:

        def get() -> httpx.Response:
            return extra.get(f"/api/items/{item_id}")

        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(lambda _: get(), range(8)))
    assert all(item.status_code == 200 for item in responses)
    after = client.get("/stats").json()["db_loads"]
    assert after - before == 1
