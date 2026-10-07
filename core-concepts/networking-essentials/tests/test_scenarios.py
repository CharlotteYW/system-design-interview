"""HTTP, a held request, a stream, a socket, and the two balancers."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time

import httpx
import websockets

BASE = os.environ.get("API_BASE_URL", "http://localhost:8000")


def test_http_returns_one_response() -> None:
    with httpx.Client(base_url=BASE, timeout=5.0) as client:
        body = client.get("/api/http", params={"region": "local"}).json()
        assert body["protocol"] == "HTTP"
        assert body["transport"] == "TCP"
        assert body["rtt_ms"] == 1


def test_long_poll_times_out_without_a_message() -> None:
    with httpx.Client(base_url=BASE, timeout=5.0) as client:
        client.post("/api/reset")
        body = client.get("/api/long-poll", params={"wait_ms": 200}).json()
        assert body["status"] == "timeout"


def test_publish_wakes_one_waiting_poll() -> None:
    with httpx.Client(base_url=BASE, timeout=5.0) as client:
        client.post("/api/reset")
        found: dict = {}

        def wait() -> None:
            found["body"] = client.get("/api/long-poll", params={"wait_ms": 3000}).json()

        thread = threading.Thread(target=wait)
        thread.start()
        time.sleep(0.2)
        client.post("/api/publish", json={"text": "seat taken"})
        thread.join()
        assert found["body"]["status"] == "message"
        assert found["body"]["text"] == "seat taken"


def test_event_stream_sends_text() -> None:
    with httpx.Client(base_url=BASE, timeout=5.0) as client:
        with client.stream("GET", "/api/events") as response:
            assert response.status_code == 200
            for line in response.iter_lines():
                if line.startswith("data:"):
                    assert "connected" in line
                    break


def test_websocket_echoes_both_ways() -> None:
    async def once() -> dict:
        async with websockets.connect("ws://localhost:8000/ws") as socket:
            await socket.send("hello")
            return json.loads(await socket.recv())

    body = asyncio.run(once())
    assert body["direction"] == "server-and-client"
    assert body["echo"] == "hello"


def test_l4_ignores_the_path_and_l7_reads_it() -> None:
    with httpx.Client(base_url=BASE, timeout=5.0) as client:
        l4 = [
            client.post("/api/balance", json={"mode": "l4", "path": path, "client": "alice"}).json()
            for path in ("/api/http", "/ws")
        ]
        assert l4[0]["server"] == l4[1]["server"]
        assert l4[0]["path_used"] is False
        l7_http = client.post("/api/balance", json={"mode": "l7", "path": "/api/http", "client": "alice"}).json()
        l7_ws = client.post("/api/balance", json={"mode": "l7", "path": "/ws", "client": "alice"}).json()
        assert l7_http["pool"] == "api"
        assert l7_ws["pool"] == "realtime"


def test_stack_walks_from_the_application_down_to_ip() -> None:
    with httpx.Client(base_url=BASE, timeout=5.0) as client:
        rest = client.get("/api/stack", params={"call": "rest"}).json()["top_to_bottom"]
        webrtc = client.get("/api/stack", params={"call": "webrtc"}).json()["top_to_bottom"]
        assert [row["layer"] for row in rest] == [
            "Application",
            "HTTP / HTTP/2",
            "TLS / DTLS",
            "TCP / UDP",
            "IP",
        ]
        assert rest[1]["uses"] == "HTTP/1.1"
        assert rest[2]["uses"] == "TLS"
        assert webrtc[2]["uses"] == "DTLS"
        assert webrtc[3]["uses"] == "UDP"


def test_graphql_returns_only_the_asked_field() -> None:
    with httpx.Client(base_url=BASE, timeout=5.0) as client:
        body = client.post("/api/graphql", json={"query": "{ video { title } }"}).json()
        assert body["data"]["video"] == {"title": "Concert"}


def test_hls_playlist_points_at_segments() -> None:
    with httpx.Client(base_url=BASE, timeout=5.0) as client:
        playlist = client.get("/video/hls/index.m3u8").text
        assert "/video/hls/seg/0" in playlist
        segment = client.get("/video/hls/seg/0").json()
        assert segment["protocol"] == "HLS"
        dash = client.get("/video/dash/manifest.mpd").text
        assert 'id="720"' in dash
        assert client.get("/video/dash/720/1").json()["quality"] == "720"


def _story(client: httpx.Client, method: str) -> list[dict]:
    frames = []
    seen = set()
    for _ in range(8):
        frame = client.post(f"/api/client-lb/{method}/next").json()
        if frame["mark"] in seen and frame["step"] == frame["of"]:
            break
        seen.add(frame["mark"])
        frames.append(frame)
        if frame["step"] == frame["of"]:
            break
    return frames


def test_dns_cache_keeps_a_dead_address_until_the_ttl() -> None:
    with httpx.Client(base_url=BASE, timeout=5.0) as client:
        client.post("/api/reset")
        frames = {frame["mark"]: frame for frame in _story(client, "dns")}
        assert "10.0.0.2" in frames["dns-lookup"]["memory"]
        assert frames["dns-lookup"]["diagram"].startswith("Client")
        assert "10.0.0.2" in frames["dns-stale"]["memory"]
        assert "10.0.0.2" not in frames["dns-stale"]["source"]
        assert "10.0.0.2" not in frames["dns-fresh"]["memory"]


def test_discovery_poll_drops_a_server_on_the_next_poll() -> None:
    with httpx.Client(base_url=BASE, timeout=5.0) as client:
        client.post("/api/reset")
        frames = {frame["mark"]: frame for frame in _story(client, "poll")}
        assert frames["poll-left"]["memory"] == ["10.0.0.1", "10.0.0.2", "10.0.0.3"]
        assert frames["poll-fresh"]["memory"] == ["10.0.0.1", "10.0.0.3"]
        push = {frame["mark"]: frame for frame in _story(client, "push")}
        assert push["push-fresh"]["memory"] == ["10.0.0.1", "10.0.0.3"]


def test_health_check_skips_a_silent_address() -> None:
    with httpx.Client(base_url=BASE, timeout=5.0) as client:
        client.post("/api/reset")
        frames = {frame["mark"]: frame for frame in _story(client, "health")}
        assert "10.0.0.2" in frames["health-removed"]["memory"]
        assert "10.0.0.2" not in frames["health-removed"]["source"]
        assert "10.0.0.2" in frames["health-back"]["source"]


def test_client_picks_a_server_from_the_registry() -> None:
    with httpx.Client(base_url=BASE, timeout=5.0) as client:
        servers = client.get("/api/registry").json()["servers"]
        assert servers == ["server-a", "server-b", "server-c"]
        work = client.get("/api/work", params={"server": servers[1]}).json()
        assert work["handled_by"] == "server-b"
        assert work["hop"] == "direct"


def test_slow_call_fails_then_succeeds() -> None:
    with httpx.Client(base_url=BASE, timeout=5.0) as client:
        client.post("/api/reset")
        first = client.get("/api/slow", params={"client": "scenario"}).json()
        second = client.get("/api/slow", params={"client": "scenario"}).json()
        third = client.get("/api/slow", params={"client": "scenario"}).json()
        assert first["ok"] is False
        assert second["ok"] is False
        assert third["ok"] is True


def test_same_charge_key_replays_the_receipt() -> None:
    with httpx.Client(base_url=BASE, timeout=5.0) as client:
        client.post("/api/reset")
        first = client.post("/api/charge", json={"key": "pay-1", "amount": 10}).json()
        second = client.post("/api/charge", json={"key": "pay-1", "amount": 10}).json()
        other = client.post("/api/charge", json={"key": "pay-2", "amount": 10}).json()
        assert first["replayed"] is False
        assert second["replayed"] is True
        assert second["id"] == first["id"]
        assert other["id"] != first["id"]


def test_breaker_opens_and_then_allows_one_trial() -> None:
    with httpx.Client(base_url=BASE, timeout=5.0) as client:
        client.post("/api/reset")
        for _ in range(3):
            failed = client.post("/api/breaker", json={"fail": True}).json()
        assert failed["state"] == "open"
        fast = client.post("/api/breaker", json={"fail": False}).json()
        assert fast["called_dependency"] is False
        time.sleep(0.5)
        trial = client.post("/api/breaker", json={"fail": False}).json()
        assert trial["state"] == "closed"
        assert trial["ok"] is True
