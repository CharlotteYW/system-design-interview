"""Integration tests against the running news feed."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

BASE_URL = os.environ.get("NEWS_FEED_BASE_URL", "http://localhost:8000")


@pytest.fixture
def client() -> httpx.Client:
    with httpx.Client(base_url=BASE_URL, timeout=20.0) as http:
        yield http


def test_health(client: httpx.Client) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_lee_sees_kim_on_read_path(client: httpx.Client) -> None:
    created = client.post(
        "/v1/posts",
        headers={"X-User-Id": "2"},
        json={"content": "Kim writes for the happy path."},
    )
    assert created.status_code == 200, created.text
    post_id = created.json()["post"]["id"]
    home = client.get("/v1/home?mode=read&limit=20", headers={"X-User-Id": "1"})
    assert home.status_code == 200, home.text
    body = home.json()
    assert body["mode"] == "read"
    assert any(item["id"] == post_id for item in body["items"])
    assert body["items"][0]["created_at"] >= body["items"][-1]["created_at"]
    stores = " ".join(step["store"] for step in body["trace"])
    assert "Postgres" in stores


def test_empty_post_is_rejected(client: httpx.Client) -> None:
    response = client.post(
        "/v1/posts",
        headers={"X-User-Id": "2"},
        json={"content": "   "},
    )
    assert response.status_code == 422


def test_second_like_does_not_increment(client: httpx.Client) -> None:
    created = client.post(
        "/v1/posts",
        headers={"X-User-Id": "3"},
        json={"content": "Ada asks for one like."},
    )
    post_id = created.json()["post"]["id"]
    first = client.post(f"/v1/posts/{post_id}/likes", headers={"X-User-Id": "1"})
    second = client.post(f"/v1/posts/{post_id}/likes", headers={"X-User-Id": "1"})
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["like_count"] == 1
    assert second.json()["like_count"] == 1
    assert second.json()["created"] is False


def test_page_cursor_does_not_repeat(client: httpx.Client) -> None:
    for index in range(3):
        response = client.post(
            "/v1/posts",
            headers={"X-User-Id": "2"},
            json={"content": f"Page post {index}"},
        )
        assert response.status_code == 200
    first = client.get("/v1/home?mode=read&limit=2", headers={"X-User-Id": "1"})
    assert first.status_code == 200
    page = first.json()
    assert len(page["items"]) == 2
    assert page["next_cursor"]
    second = client.get(
        "/v1/home?mode=read&limit=2",
        params={"cursor": page["next_cursor"]},
        headers={"X-User-Id": "1"},
    )
    assert second.status_code == 200
    first_ids = {item["id"] for item in page["items"]}
    second_ids = {item["id"] for item in second.json()["items"]}
    assert first_ids.isdisjoint(second_ids)


def test_hybrid_marks_famous_post_from_posts_table(client: httpx.Client) -> None:
    created = client.post(
        "/v1/posts",
        headers={"X-User-Id": "4"},
        json={"content": "Bea posts to a huge audience.", "image_links": ["https://example.com/show.jpg"]},
    )
    post_id = created.json()["post"]["id"]
    home = client.get("/v1/home?mode=hybrid&limit=20", headers={"X-User-Id": "1"})
    assert home.status_code == 200, home.text
    match = next(item for item in home.json()["items"] if item["id"] == post_id)
    assert match["famous"] is True
    assert match["source"] == "posts"


def test_concurrent_likes_count_once(client: httpx.Client) -> None:
    created = client.post(
        "/v1/posts",
        headers={"X-User-Id": "2"},
        json={"content": "Two taps at once."},
    )
    post_id = created.json()["post"]["id"]

    def tap() -> httpx.Response:
        with httpx.Client(base_url=BASE_URL, timeout=20.0) as http:
            return http.post(f"/v1/posts/{post_id}/likes", headers={"X-User-Id": "1"})

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: tap(), range(2)))
    assert all(item.status_code == 200 for item in responses)
    counts = {item.json()["like_count"] for item in responses}
    assert counts == {1}
