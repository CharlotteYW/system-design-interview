"""Integration tests against the running chat lab.

Shared tests run on both designs. The last tests show where the two
message stores behave differently.
"""

from __future__ import annotations

import json
import time
import uuid

import httpx

from conftest import cursor_rows


def wait_mailbox(client: httpx.Client, client_id: str, min_items: int = 1, body: str | None = None) -> list:
    last: list = []
    for _ in range(40):
        last = client.get(f"/v1/lab/mailbox/{client_id}").json()["items"]
        news = [item for item in last if item.get("type") == "newMessage"]
        if body is not None:
            if any(item["message"]["body"] == body for item in news):
                return news
        elif len(news) >= min_items:
            return news
        time.sleep(0.15)
    raise AssertionError(last)


def send(client: httpx.Client, chat_id: str, body: str, sender: str = "lee-phone") -> dict:
    created = client.post(
        "/v1/messages",
        json={"chatId": chat_id, "message": body, "serverId": "A", "clientId": sender},
    )
    assert created.status_code == 202, created.text
    return created.json()


def cursor_of(client: httpx.Client, client_id: str, chat_id: str) -> int:
    state = client.get("/v1/lab/state").json()
    row = next(
        (r for r in cursor_rows(state) if r["client_id"] == client_id and r["chat_id"] == chat_id),
        None,
    )
    return row["last_seq"] if row else 0


def test_health(client: httpx.Client, design: str) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "design": design}


def test_cross_server_live_push(client: httpx.Client) -> None:
    client.post("/v1/lab/mailbox/kim-phone/clear")
    assert client.post("/v1/lab/connect", json={"serverId": "A", "clientId": "lee-phone"}).status_code == 200
    assert client.post("/v1/lab/connect", json={"serverId": "B", "clientId": "kim-phone"}).status_code == 200
    time.sleep(0.5)
    body = f"cross-{uuid.uuid4()}"
    send(client, "lee-kim", body)
    news = wait_mailbox(client, "kim-phone", body=body)
    match = next(item for item in news if item["message"]["body"] == body)
    assert match["via"] == "user-channel"
    state = client.get("/v1/lab/state").json()
    actions = [row["action"] for row in state["redis"]["pubsubLog"]]
    assert "PUBLISH" in actions
    assert "RECEIVE" in actions


def test_offline_drain(client: httpx.Client) -> None:
    client.post("/v1/lab/disconnect", json={"clientId": "kim-phone"})
    client.post("/v1/lab/mailbox/kim-phone/clear")
    assert client.post("/v1/lab/connect", json={"serverId": "A", "clientId": "lee-phone"}).status_code == 200
    body = f"offline-{uuid.uuid4()}"
    send(client, "lee-kim", body)
    time.sleep(0.4)
    before = client.get("/v1/lab/mailbox/kim-phone").json()["items"]
    assert not any(item.get("message", {}).get("body") == body for item in before)
    connected = client.post("/v1/lab/connect", json={"serverId": "B", "clientId": "kim-phone"})
    assert connected.status_code == 200
    assert connected.json()["drained"] >= 1
    assert connected.json()["reads"], "connect must list what the drain read"
    news = wait_mailbox(client, "kim-phone", body=body)
    match = next(item for item in news if item["message"]["body"] == body)
    assert match["via"] == "drain"


def test_ack_moves_cursor(client: httpx.Client) -> None:
    client.post("/v1/lab/connect", json={"serverId": "A", "clientId": "lee-phone"})
    client.post("/v1/lab/connect", json={"serverId": "B", "clientId": "kim-laptop"})
    body = f"ack-{uuid.uuid4()}"
    seq = send(client, "lee-kim", body)["seq"]
    wait_mailbox(client, "kim-laptop", body=body)
    acked = client.post("/v1/ack", json={"clientId": "kim-laptop", "chatId": "lee-kim", "seq": seq})
    assert acked.status_code == 200
    assert acked.json()["cursor"]["after"] == seq
    assert cursor_of(client, "kim-laptop", "lee-kim") >= seq


def test_rejects_non_member(client: httpx.Client) -> None:
    response = client.post(
        "/v1/messages",
        json={"chatId": "lee-kim", "message": "intruder", "serverId": "A", "clientId": "ada-phone"},
    )
    assert response.status_code == 403


def test_anyone_can_start_a_chat_and_send(client: httpx.Client) -> None:
    first = client.post("/v1/chats", json={"participants": ["kim"], "clientId": "ada-phone"})
    assert first.status_code == 200, first.text
    assert first.json()["chatId"] == "ada-kim"
    assert sorted(first.json()["members"]) == ["ada", "kim"]
    again = client.post("/v1/chats", json={"participants": ["kim"], "clientId": "ada-phone"})
    assert again.json()["chatId"] == "ada-kim" and again.json()["created"] is False

    client.post("/v1/lab/mailbox/kim-phone/clear")
    client.post("/v1/lab/connect", json={"serverId": "A", "clientId": "ada-phone"})
    client.post("/v1/lab/connect", json={"serverId": "B", "clientId": "kim-phone"})
    time.sleep(0.3)
    body = f"ada-{uuid.uuid4()}"
    send(client, "ada-kim", body, sender="ada-phone")
    news = wait_mailbox(client, "kim-phone", body=body)
    match = next(item for item in news if item["message"]["body"] == body)
    assert match["via"] == "user-channel"


def test_cross_server_push_reaches_a_real_websocket(client: httpx.Client, design: str) -> None:
    from websockets.sync.client import connect

    ws_url = str(client.base_url).replace("http://", "ws://").rstrip("/") + "/ws/B/kim-laptop"
    client.post("/v1/lab/connect", json={"serverId": "A", "clientId": "lee-phone"})
    with connect(ws_url, open_timeout=5) as ws:
        hello = json.loads(ws.recv(timeout=5))
        assert hello["type"] == "connected" and hello["serverId"] == "B"
        body = f"ws-{uuid.uuid4()}"
        send(client, "lee-kim", body)
        deadline = time.time() + 5
        while time.time() < deadline:
            frame = json.loads(ws.recv(timeout=5))
            if frame.get("type") == "newMessage" and frame["message"]["body"] == body:
                assert frame["via"] == "user-channel"
                break
        else:
            raise AssertionError(f"{design}: no live push on the WebSocket")


def test_concurrent_sends_get_unique_contiguous_seq(client: httpx.Client) -> None:
    from concurrent.futures import ThreadPoolExecutor

    def one(i: int) -> int:
        sender, server = ("lee-phone", "A") if i % 2 else ("kim-phone", "B")
        with httpx.Client(base_url=client.base_url, timeout=20.0) as http:
            created = http.post(
                "/v1/messages",
                json={"chatId": "lee-kim", "message": f"race-{i}", "serverId": server, "clientId": sender},
            )
            assert created.status_code == 202, created.text
            return created.json()["seq"]

    with ThreadPoolExecutor(max_workers=20) as pool:
        seqs = sorted(pool.map(one, range(20)))
    assert len(set(seqs)) == 20, seqs
    assert seqs == list(range(seqs[0], seqs[0] + 20)), "INCR hands out one block with no holes"


def test_retry_with_same_client_msg_id_stores_once(client: httpx.Client) -> None:
    cmid = f"retry-{uuid.uuid4()}"
    payload = {"chatId": "lee-kim", "message": cmid, "serverId": "A", "clientId": "lee-phone", "clientMsgId": cmid}
    first = client.post("/v1/messages", json=payload).json()
    again = client.post("/v1/messages", json=payload).json()
    assert first["duplicate"] is False and again["duplicate"] is True
    assert again["seq"] == first["seq"] and again["messageId"] == first["messageId"]
    rows = client.get("/v1/chats/lee-kim/messages", params={"clientId": "lee-phone", "afterSeq": first["seq"] - 1}).json()
    assert [m["body"] for m in rows["messages"]].count(cmid) == 1


def test_client_seq_flags_a_swapped_pair(client: httpx.Client) -> None:
    chat = client.post("/v1/chats", json={"participants": ["lee"], "clientId": "kim-laptop"}).json()["chatId"]
    base = {"chatId": chat, "serverId": "B", "clientId": "kim-laptop"}
    top = client.get(f"/v1/chats/{chat}/messages", params={"clientId": "kim-laptop"}).json()["messages"]
    n = max([m["client_seq"] or 0 for m in top], default=0)
    second = client.post("/v1/messages", json={**base, "message": "second", "clientSeq": n + 2}).json()
    first = client.post("/v1/messages", json={**base, "message": "first", "clientSeq": n + 1}).json()
    assert second["outOfOrder"] is False and first["outOfOrder"] is True
    assert first["seq"] > second["seq"], "server order wins: the late one gets the higher seq"


def test_lost_counter_is_rebuilt_from_the_store(client: httpx.Client) -> None:
    before = send(client, "lee-kim", f"before-{uuid.uuid4()}")["seq"]
    lost = client.post("/v1/lab/lose-seq-counter", json={"chatId": "lee-kim", "guard": True}).json()
    assert lost["counterDeleted"] is True and lost["maxStoredSeq"] >= before
    after = send(client, "lee-kim", f"after-{uuid.uuid4()}")
    assert after["seq"] == lost["maxStoredSeq"] + 1
    assert after["seqSeeded"]["from"] == "store"


def test_lost_counter_without_guard_reuses_a_seq(client: httpx.Client, design: str) -> None:
    send(client, "lee-kim", f"keep-{uuid.uuid4()}")
    client.post("/v1/lab/lose-seq-counter", json={"chatId": "lee-kim", "guard": False})
    response = client.post(
        "/v1/messages",
        json={"chatId": "lee-kim", "message": "reused", "serverId": "A", "clientId": "lee-phone"},
    )
    if design == "postgres":
        assert response.status_code == 409, "UNIQUE (chat_id, seq) rejects the reused seq"
    else:
        assert response.status_code == 202
        assert response.json()["seq"] == 1
        assert "overwrote" in response.json()["storedIn"], "Cassandra upserts over the old row"
    follow = send(client, "lee-kim", f"follow-{uuid.uuid4()}")
    assert "overwrote" not in follow["storedIn"], "the lab repairs the counter after the demo send"


def test_dropped_push_leaves_a_gap_that_gap_fill_closes(client: httpx.Client) -> None:
    client.post("/v1/lab/connect", json={"serverId": "A", "clientId": "lee-phone"})
    client.post("/v1/lab/connect", json={"serverId": "B", "clientId": "kim-phone"})
    client.post("/v1/lab/drop-next-push", json={"clientId": "kim-phone"})
    lost_body, kept_body = f"lost-{uuid.uuid4()}", f"kept-{uuid.uuid4()}"
    lost = send(client, "lee-kim", lost_body)
    send(client, "lee-kim", kept_body)
    news = wait_mailbox(client, "kim-phone", body=kept_body)
    assert not any(item["message"]["body"] == lost_body for item in news), "the push was dropped"
    fill = client.get(
        "/v1/chats/lee-kim/messages", params={"clientId": "kim-phone", "afterSeq": lost["seq"] - 1}
    ).json()
    assert [m["body"] for m in fill["messages"]][:2] == [lost_body, kept_body]
    state = client.get("/v1/lab/state").json()
    assert "DROP" in [row["action"] for row in state["redis"]["pubsubLog"]]


def test_crash_mid_send_leaves_a_hole_and_the_retry_stores_later(client: httpx.Client) -> None:
    cmid = f"crash-{uuid.uuid4()}"
    crash = client.post(
        "/v1/lab/crash-mid-send", json={"chatId": "lee-kim", "clientId": "lee-phone", "clientMsgId": cmid}
    ).json()
    hole = crash["seqTaken"]
    payload = {"chatId": "lee-kim", "message": cmid, "serverId": "A", "clientId": "lee-phone", "clientMsgId": cmid}

    early = client.post("/v1/messages", json=payload)
    assert early.status_code == 409, "the dead server's claim is still pending"

    time.sleep(crash["pendingExpiresInSeconds"] + 0.5)
    retry = client.post("/v1/messages", json=payload)
    assert retry.status_code == 202, retry.text
    assert retry.json()["duplicate"] is False and retry.json()["seq"] > hole

    rows = client.get(
        "/v1/chats/lee-kim/messages", params={"clientId": "kim-phone", "afterSeq": hole - 1}
    ).json()["messages"]
    assert rows[0]["seq"] > hole, f"seq {hole} stays a hole"
    assert [m["body"] for m in rows].count(cmid) == 1


def test_ack_past_the_newest_seq_is_rejected(client: httpx.Client) -> None:
    newest = send(client, "lee-kim", f"top-{uuid.uuid4()}")["seq"]
    bad = client.post("/v1/ack", json={"clientId": "kim-laptop", "chatId": "lee-kim", "seq": newest + 1000})
    assert bad.status_code == 422
    assert cursor_of(client, "kim-laptop", "lee-kim") <= newest


def test_pubsub_down_still_stores_and_sync_catches_up(client: httpx.Client) -> None:
    client.post("/v1/lab/connect", json={"serverId": "A", "clientId": "lee-phone"})
    client.post("/v1/lab/connect", json={"serverId": "B", "clientId": "kim-phone"})
    client.post("/v1/lab/pubsub-down", json={"down": True})
    try:
        body = f"no-bus-{uuid.uuid4()}"
        sent = client.post(
            "/v1/messages",
            json={"chatId": "lee-kim", "message": body, "serverId": "A", "clientId": "lee-phone"},
        )
        assert sent.status_code == 202, "the store worked, so the send succeeds"
        assert sent.json()["livePush"].startswith("failed")
        time.sleep(0.5)
        box = client.get("/v1/lab/mailbox/kim-phone").json()["items"]
        assert not any(i.get("message", {}).get("body") == body for i in box), "no live push"
        fill = client.get(
            "/v1/chats/lee-kim/messages", params={"clientId": "kim-phone", "afterSeq": sent.json()["seq"] - 1}
        ).json()
        assert fill["messages"][0]["body"] == body, "the sync read still finds it"
    finally:
        client.post("/v1/lab/pubsub-down", json={"down": False})


def test_gap_fill_rejects_non_member(client: httpx.Client) -> None:
    response = client.get("/v1/chats/lee-kim/messages", params={"clientId": "ada-phone"})
    assert response.status_code == 403


def test_create_chat_rejects_unknown_user(client: httpx.Client) -> None:
    response = client.post("/v1/chats", json={"participants": ["nobody"], "clientId": "ada-phone"})
    assert response.status_code == 404


def test_postgres_ignores_late_ack(pg_client: httpx.Client) -> None:
    seqs = [send(pg_client, "lee-kim", f"pg-late-{i}")["seq"] for i in range(3)]
    top = seqs[-1]
    pg_client.post("/v1/ack", json={"clientId": "lee-laptop", "chatId": "lee-kim", "seq": top})
    late = pg_client.post("/v1/ack", json={"clientId": "lee-laptop", "chatId": "lee-kim", "seq": top - 2})
    cursor = late.json()["cursor"]
    assert cursor["mode"] == "greatest"
    assert cursor["before"] == top and cursor["after"] == top


def test_cassandra_upsert_moves_cursor_back_and_lwt_does_not(cs_client: httpx.Client) -> None:
    seqs = [send(cs_client, "lee-kim", f"cs-late-{i}")["seq"] for i in range(3)]
    top = seqs[-1]
    ack = lambda seq, mode: cs_client.post(  # noqa: E731
        "/v1/ack",
        json={"clientId": "lee-laptop", "chatId": "lee-kim", "seq": seq, "mode": mode},
    ).json()["cursor"]

    ack(top, "upsert")
    regressed = ack(top - 2, "upsert")
    assert regressed["before"] == top and regressed["after"] == top - 2

    ack(top, "lwt")
    guarded = ack(top - 2, "lwt")
    assert guarded["applied"] is False
    assert guarded["after"] == top


def test_cassandra_buckets_split_partitions(cs_client: httpx.Client) -> None:
    results = [send(cs_client, "trip", f"bucket-{i}") for i in range(6)]
    buckets = {r["storedIn"]["partition"]["bucket"] for r in results}
    assert len(buckets) >= 2, results
    assert all(r["storedIn"]["ttlSeconds"] == 30 * 24 * 3600 for r in results)
    state = cs_client.get("/v1/lab/state").json()
    trip_parts = [p for p in state["cassandra"]["partitions"] if p["partition_key"].startswith("(trip,")]
    assert len(trip_parts) >= 2
    assert len({p["token"] for p in trip_parts}) == len(trip_parts), "each bucket hashes to its own token"
