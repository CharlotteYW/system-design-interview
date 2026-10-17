"""Functional tests of the flows the page sends, on both designs."""

from __future__ import annotations

import uuid

import httpx

from conftest import message_rows


def test_page_shows_variants_and_stores(client: httpx.Client) -> None:
    page = client.get("/")
    assert page.status_code == 200
    text = page.text
    assert "POST /v1/lab/connect" in text
    assert "POST /v1/messages" in text
    assert "device_cursors" in text
    assert "messages_by_chat" in text
    assert "Late ack" in text
    assert "Online cross server" in text
    assert "Offline then drain" in text
    assert "Design 1 vs Design 2" in text
    assert "POST /v1/chats" in text
    assert "A view, not a second table" in text


def test_compare_page_embeds_both_designs(pg_client: httpx.Client) -> None:
    page = pg_client.get("/compare")
    assert page.status_code == 200
    assert ":8000/" in page.text and ":8001/" in page.text
    assert "((chat_id, bucket), seq)" in page.text


def test_page_flow_send_updates_message_store(client: httpx.Client, design: str) -> None:
    client.post("/v1/lab/connect", json={"serverId": "A", "clientId": "lee-phone"})
    body = f"ui-{uuid.uuid4()}"
    created = client.post(
        "/v1/messages",
        json={
            "chatId": "trip",
            "message": body,
            "mediaKey": "media/demo.jpg",
            "serverId": "A",
            "clientId": "lee-phone",
        },
    )
    assert created.status_code == 202
    payload = created.json()
    assert set(payload) >= {"messageId", "status", "seq", "storedIn"}
    assert payload["storedIn"]["store"] == design
    state = client.get("/v1/lab/state").json()
    rows = [row for row in message_rows(state) if row["body"] == body]
    assert rows and rows[0]["media_key"] == "media/demo.jpg"
    assert "trip" in state["redis"]["chatSeq"]
    if design == "cassandra":
        assert "messages" not in state["postgres"], "design 2 moves messages out of Postgres"
