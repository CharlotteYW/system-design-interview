"""Functional tests of the pages and the HTTP calls the page uses."""

from __future__ import annotations

import os

import httpx
import pytest

BASE_URL = os.environ.get("NEWS_FEED_BASE_URL", "http://localhost:8000")


@pytest.fixture
def client() -> httpx.Client:
    with httpx.Client(base_url=BASE_URL, timeout=20.0) as http:
        yield http


def test_page_shows_three_home_modes(client: httpx.Client) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    page = response.text
    assert "Fan-out on read" in page
    assert "Fan-out on write" in page
    assert "Hybrid" in page
    assert "Post service" in page
    assert "Postgres" in page
    assert "Publish" in page
    assert "Postgres posts" in page
    assert "S3 links" in page
    stores = client.get("/v1/stores")
    assert stores.status_code == 200
    body = stores.json()
    assert body["postgres"]["counts"]["users"] >= 4
    assert "posts" in body["postgres"]["tables"]
    assert "redis" in body
    assert "s3" in body


def test_publish_then_comment_through_the_page_api(client: httpx.Client) -> None:
    created = client.post(
        "/v1/posts",
        headers={"X-User-Id": "1"},
        json={"content": "Lee posts from the page.", "image_links": ["https://example.com/lee.jpg"]},
    )
    assert created.status_code == 200, created.text
    trace = " ".join(step["service"] for step in created.json()["trace"])
    assert "Post service" in trace
    post_id = created.json()["post"]["id"]
    comment = client.post(
        f"/v1/posts/{post_id}/comments",
        headers={"X-User-Id": "1"},
        json={"content": "A note under the post."},
    )
    assert comment.status_code == 200, comment.text
    assert comment.json()["trace"][0]["service"] == "Comment service"
    listed = client.get(f"/v1/posts/{post_id}/comments")
    assert listed.status_code == 200
    assert any(item["content"] == "A note under the post." for item in listed.json()["items"])
    home = client.get("/v1/home?mode=read&limit=20", headers={"X-User-Id": "1"})
    card = next(item for item in home.json()["items"] if item["id"] == post_id)
    assert "image_links" in card
    assert "A note under the post." not in card["content"]
