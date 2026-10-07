"""One process. Each route is one networking choice the page can click."""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

app = FastAPI()
STATIC = Path(__file__).resolve().parent / "static"

DELAY_MS = {"local": 1, "country": 40, "ocean": 150}
VIDEO = {"id": 1, "title": "Concert", "city": "NYC"}
SERVERS = ["server-a", "server-b", "server-c"]

_messages: list[str] = []
_waiters: list[asyncio.Event] = []
_sse: list[str] = []
_charges: dict[str, dict] = {}
_slow_tries: dict[str, int] = {}
_breaker = {"state": "closed", "failures": 0, "opened_at": 0.0}
BREAKER_LIMIT = 3
BREAKER_COOL_S = 0.4


class PublishBody(BaseModel):
    text: str


class BalanceBody(BaseModel):
    mode: str
    path: str
    client: str


class QueryBody(BaseModel):
    query: str


class RpcBody(BaseModel):
    video_id: int


class ChargeBody(BaseModel):
    key: str
    amount: int


class BreakerBody(BaseModel):
    fail: bool = False


def _server_for(client: str) -> str:
    total = sum(ord(char) for char in client)
    return "server-a" if total % 2 == 0 else "server-b"


def reset_state() -> None:
    _messages.clear()
    _sse.clear()
    _charges.clear()
    _slow_tries.clear()
    _breaker["state"] = "closed"
    _breaker["failures"] = 0
    _breaker["opened_at"] = 0.0
    for event in list(_waiters):
        event.set()
    _waiters.clear()
    for key in _lb_step:
        _lb_step[key] = -1


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.post("/api/reset")
def reset() -> dict:
    reset_state()
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/http")
async def http_call(region: str = "local") -> dict:
    delay = DELAY_MS.get(region, 1)
    await asyncio.sleep(delay / 1000)
    return {
        "protocol": "HTTP",
        "transport": "TCP",
        "region": region,
        "rtt_ms": delay,
        "tls_extra_rtt_ms": delay,
        "code": "http_call",
    }


@app.get("/api/videos/{video_id}")
def rest_video(video_id: int) -> dict:
    return {"protocol": "REST", "resource": "video", "id": video_id, "title": VIDEO["title"], "code": "rest_video"}


@app.post("/api/graphql")
def graphql_video(body: QueryBody) -> dict:
    picked = {name: VIDEO[name] for name in ("id", "title", "city") if re.search(rf"\b{name}\b", body.query)}
    return {"protocol": "GraphQL", "data": {"video": picked}, "code": "graphql_video"}


def get_video_rpc(video_id: int) -> dict:
    return {
        "protocol": "gRPC",
        "rpc": "Video.Get",
        "transport": "HTTP/2",
        "body": "protobuf",
        "video_id": video_id,
        "title": VIDEO["title"],
        "code": "get_video_rpc",
    }


@app.post("/api/grpc")
def grpc_call(body: RpcBody) -> dict:
    return get_video_rpc(body.video_id)


@app.get("/api/long-poll")
async def long_poll(wait_ms: int = 8000) -> dict:
    if _messages:
        return {"protocol": "long-poll", "status": "message", "text": _messages.pop(0), "code": "long_poll"}
    event = asyncio.Event()
    _waiters.append(event)
    try:
        await asyncio.wait_for(event.wait(), timeout=max(wait_ms, 1) / 1000)
    except TimeoutError:
        return {"protocol": "long-poll", "status": "timeout", "text": "", "code": "long_poll"}
    finally:
        if event in _waiters:
            _waiters.remove(event)
    if _messages:
        return {"protocol": "long-poll", "status": "message", "text": _messages.pop(0), "code": "long_poll"}
    return {"protocol": "long-poll", "status": "timeout", "text": "", "code": "long_poll"}


@app.post("/api/publish")
async def publish(body: PublishBody) -> dict:
    _messages.append(body.text)
    _sse.append(body.text)
    for event in list(_waiters):
        event.set()
    return {"ok": True, "text": body.text, "code": "publish"}


@app.get("/api/events")
async def events() -> StreamingResponse:
    async def stream():
        yield "data: connected\n\n"
        seen = 0
        while True:
            while seen < len(_sse):
                yield f"data: {_sse[seen]}\n\n"
                seen += 1
            await asyncio.sleep(0.2)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.websocket("/ws")
async def ws(socket: WebSocket) -> None:
    await socket.accept()
    try:
        while True:
            text = await socket.receive_text()
            await socket.send_json({"direction": "server-and-client", "echo": text, "code": "ws"})
    except WebSocketDisconnect:
        return


@app.post("/api/webrtc")
def webrtc(step: str) -> dict:
    notes = {
        "signal": "Both peers ask the signaling server who is in the room.",
        "stun": "Each peer learns a public address.",
        "share": "The peers exchange those addresses through the signaling server.",
        "direct": "Media uses UDP from peer to peer.",
        "turn": "The direct path failed. A TURN server relays the media.",
    }
    return {"protocol": "WebRTC", "step": step, "note": notes.get(step, "Unknown step."), "code": "webrtc"}


@app.get("/video/hls/index.m3u8")
def hls_playlist() -> PlainTextResponse:
    lines = ["#EXTM3U", "#EXT-X-TARGETDURATION:2"]
    for index in range(3):
        lines.append("#EXTINF:2")
        lines.append(f"/video/hls/seg/{index}")
    lines.append("#EXT-X-ENDLIST")
    return PlainTextResponse("\n".join(lines) + "\n", media_type="application/vnd.apple.mpegurl")


@app.get("/video/hls/seg/{index}")
def hls_segment(index: int) -> dict:
    return {"protocol": "HLS", "index": index, "seconds": 2, "code": "hls_segment"}


@app.get("/video/dash/manifest.mpd")
def dash_manifest() -> PlainTextResponse:
    xml = """<?xml version="1.0"?>
<MPD>
  <Representation id="360" bandwidth="800000"/>
  <Representation id="720" bandwidth="2500000"/>
</MPD>
"""
    return PlainTextResponse(xml, media_type="application/dash+xml")


@app.get("/video/dash/{quality}/{index}")
def dash_segment(quality: str, index: int) -> dict:
    return {"protocol": "DASH", "quality": quality, "index": index, "seconds": 2, "code": "dash_segment"}


@app.get("/api/stack")
def stack(call: str = "rest") -> dict:
    paths = {
        "rest": [
            {"layer": "Application", "uses": "REST GET /api/videos/1"},
            {"layer": "HTTP / HTTP/2", "uses": "HTTP/1.1"},
            {"layer": "TLS / DTLS", "uses": "TLS"},
            {"layer": "TCP / UDP", "uses": "TCP"},
            {"layer": "IP", "uses": "10.0.0.8 -> 10.0.0.1"},
        ],
        "grpc": [
            {"layer": "Application", "uses": "gRPC Video.Get"},
            {"layer": "HTTP / HTTP/2", "uses": "HTTP/2"},
            {"layer": "TLS / DTLS", "uses": "TLS"},
            {"layer": "TCP / UDP", "uses": "TCP"},
            {"layer": "IP", "uses": "10.0.0.8 -> 10.0.0.2"},
        ],
        "webrtc": [
            {"layer": "Application", "uses": "WebRTC media"},
            {"layer": "HTTP / HTTP/2", "uses": "Signaling uses HTTP. Media uses DTLS on UDP."},
            {"layer": "TLS / DTLS", "uses": "DTLS"},
            {"layer": "TCP / UDP", "uses": "UDP"},
            {"layer": "IP", "uses": "10.0.0.8 -> 10.0.0.9"},
        ],
    }
    layers = paths.get(call, paths["rest"])
    return {"call": call, "top_to_bottom": layers, "code": "stack"}


@app.get("/api/packets")
def packets(transport: str = "tcp") -> dict:
    if transport == "udp":
        return {
            "transport": "UDP",
            "arrived": [3, 1],
            "dropped": [2],
            "order": "Packet 3 arrived before packet 1. Packet 2 was lost.",
            "code": "packets",
        }
    return {
        "transport": "TCP",
        "arrived": [1, 2, 3],
        "resent": [2],
        "order": "The bytes arrived in order. Packet 2 was sent again.",
        "code": "packets",
    }


_lb_step = {"static": -1, "dns": -1, "poll": -1, "push": -1, "health": -1, "moved": -1}

LB_FRAMES = {
    "static": [
        {
            "mark": "static-copied",
            "title": "The client copies the file into memory.",
            "memory": ["10.0.0.1", "10.0.0.2", "10.0.0.3"],
            "source": ["10.0.0.1", "10.0.0.2", "10.0.0.3"],
            "diagram": "config file\n  10.0.0.1\n  10.0.0.2\n  10.0.0.3\n       |\n       | read at start\n       v\nClient memory\n  10.0.0.1\n  10.0.0.2\n  10.0.0.3",
            "note": "The seed is the whole list. The client does not ask anyone.",
        },
        {
            "mark": "static-stale",
            "title": "A new server starts. The file is old.",
            "memory": ["10.0.0.1", "10.0.0.2", "10.0.0.3"],
            "source": ["10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4"],
            "diagram": "New server\n  10.0.0.4\n\nClient memory\n  10.0.0.1\n  10.0.0.2\n  10.0.0.3",
            "note": "10.0.0.4 stays unused until you ship a new file.",
        },
    ],
    "dns": [
        {
            "mark": "dns-empty",
            "title": "The client has a name. The memory is empty.",
            "memory": [],
            "source": ["10.0.0.1", "10.0.0.2", "10.0.0.3"],
            "diagram": "Client\n  |\n  | seed is a name\n  v\nuser-service.example.com\n  |\n  | memory\n  v\n(empty)",
            "note": "The config holds the name. It does not hold the three addresses.",
        },
        {
            "mark": "dns-lookup",
            "title": "The client asks DNS and stores the answer.",
            "memory": ["10.0.0.1", "10.0.0.2", "10.0.0.3"],
            "source": ["10.0.0.1", "10.0.0.2", "10.0.0.3"],
            "diagram": "Client\n  |\n  | DNS lookup\n  v\nuser-service.example.com\n  |\n  v\n10.0.0.1\n10.0.0.2\n10.0.0.3\nTTL 30s",
            "note": "The phone or the laptop caches this answer for the TTL. TTL is 30 seconds here.",
        },
        {
            "mark": "dns-stale",
            "title": "DNS dropped 10.0.0.2. The cache still has it.",
            "memory": ["10.0.0.1", "10.0.0.2", "10.0.0.3"],
            "source": ["10.0.0.1", "10.0.0.3"],
            "diagram": "DNS now\n  10.0.0.1\n  10.0.0.3\n\nClient cache, TTL still open\n  10.0.0.1\n  10.0.0.2\n  10.0.0.3",
            "note": "The client can still send to 10.0.0.2. The update waits for the TTL.",
        },
        {
            "mark": "dns-miss",
            "title": "The client uses the cache and picks the dead address.",
            "memory": ["10.0.0.1", "10.0.0.2", "10.0.0.3"],
            "source": ["10.0.0.1", "10.0.0.3"],
            "diagram": "Client\n  |\n  | uses cache\n  v\n10.0.0.2\n  |\n  v\nno answer",
            "note": "The call fails. A new lookup is not allowed yet.",
        },
        {
            "mark": "dns-fresh",
            "title": "The TTL ends. The client looks up again.",
            "memory": ["10.0.0.1", "10.0.0.3"],
            "source": ["10.0.0.1", "10.0.0.3"],
            "diagram": "Client\n  |\n  | DNS lookup after TTL\n  v\nuser-service.example.com\n  |\n  v\n10.0.0.1\n10.0.0.3",
            "note": "The dead address leaves memory only after the TTL. That delay is the DNS cache issue.",
        },
    ],
    "poll": [
        {
            "mark": "poll-empty",
            "title": "The seed is the registry address.",
            "memory": [],
            "source": [],
            "diagram": "Client\n  |\n  | seed\n  v\nregistry.internal\n  |\n  | memory\n  v\n(empty)",
            "note": "The client knows where to ask. It does not know the servers yet.",
        },
        {
            "mark": "poll-registered",
            "title": "Three servers register.",
            "memory": [],
            "source": ["10.0.0.1", "10.0.0.2", "10.0.0.3"],
            "diagram": "10.0.0.1  register\n10.0.0.2  register\n10.0.0.3  register\n        |\n        v\n   registry\n\nClient memory\n  (empty)",
            "note": "The registry has the list. The client has not asked.",
        },
        {
            "mark": "poll-filled",
            "title": "The client polls and stores the list.",
            "memory": ["10.0.0.1", "10.0.0.2", "10.0.0.3"],
            "source": ["10.0.0.1", "10.0.0.2", "10.0.0.3"],
            "diagram": "Client\n  |\n  | poll\n  v\nregistry.internal\n  |\n  v\n10.0.0.1\n10.0.0.2\n10.0.0.3",
            "note": "This is service discovery. The client copies the registry into memory.",
        },
        {
            "mark": "poll-left",
            "title": "10.0.0.2 leaves the registry.",
            "memory": ["10.0.0.1", "10.0.0.2", "10.0.0.3"],
            "source": ["10.0.0.1", "10.0.0.3"],
            "diagram": "registry now\n  10.0.0.1\n  10.0.0.3\n\nClient memory, waiting for the next poll\n  10.0.0.1\n  10.0.0.2\n  10.0.0.3",
            "note": "The client still has the old list until it polls again.",
        },
        {
            "mark": "poll-fresh",
            "title": "The next poll drops 10.0.0.2.",
            "memory": ["10.0.0.1", "10.0.0.3"],
            "source": ["10.0.0.1", "10.0.0.3"],
            "diagram": "Client\n  |\n  | poll again\n  v\nregistry.internal\n  |\n  v\n10.0.0.1\n10.0.0.3",
            "note": "There is no TTL. The wait is only the time until the next poll.",
        },
    ],
    "push": [
        {
            "mark": "push-watch",
            "title": "The client opens a watch.",
            "memory": [],
            "source": ["10.0.0.1", "10.0.0.2", "10.0.0.3"],
            "diagram": "Client\n  |\n  | watch\n  v\nregistry.internal",
            "note": "A watch stays open. The registry can send a new list.",
        },
        {
            "mark": "push-filled",
            "title": "The registry pushes the three addresses.",
            "memory": ["10.0.0.1", "10.0.0.2", "10.0.0.3"],
            "source": ["10.0.0.1", "10.0.0.2", "10.0.0.3"],
            "diagram": "registry.internal\n  |\n  | push\n  v\nClient memory\n  10.0.0.1\n  10.0.0.2\n  10.0.0.3",
            "note": "The client stores the push. It did not poll.",
        },
        {
            "mark": "push-fresh",
            "title": "10.0.0.2 leaves. The registry pushes the new list.",
            "memory": ["10.0.0.1", "10.0.0.3"],
            "source": ["10.0.0.1", "10.0.0.3"],
            "diagram": "registry.internal\n  |\n  | push\n  v\nClient memory\n  10.0.0.1\n  10.0.0.3",
            "note": "The memory changes in this step. A poll would have waited.",
        },
    ],
    "health": [
        {
            "mark": "health-known",
            "title": "The client already has three addresses.",
            "memory": ["10.0.0.1", "10.0.0.2", "10.0.0.3"],
            "source": ["10.0.0.1", "10.0.0.2", "10.0.0.3"],
            "diagram": "Client memory\n  10.0.0.1\n  10.0.0.2\n  10.0.0.3\n\nRouting set\n  (not probed yet)",
            "note": "A health check starts from a known list. The list came from a file, DNS, or discovery.",
        },
        {
            "mark": "health-ok",
            "title": "The client probes each address.",
            "memory": ["10.0.0.1", "10.0.0.2", "10.0.0.3"],
            "source": ["10.0.0.1", "10.0.0.2", "10.0.0.3"],
            "diagram": "Client\n  | probe\n  v\n10.0.0.1  ok\n10.0.0.2  ok\n10.0.0.3  ok",
            "note": "Every probe succeeds. The routing set matches the memory.",
        },
        {
            "mark": "health-down",
            "title": "10.0.0.2 stops answering.",
            "memory": ["10.0.0.1", "10.0.0.2", "10.0.0.3"],
            "source": ["10.0.0.1", "10.0.0.3"],
            "diagram": "10.0.0.2\n  |\n  v\nsilent\n\nRouting set still\n  10.0.0.1\n  10.0.0.2\n  10.0.0.3",
            "note": "The server is down. The client has not probed again.",
        },
        {
            "mark": "health-removed",
            "title": "The next probe removes 10.0.0.2 from the routing set.",
            "memory": ["10.0.0.1", "10.0.0.2", "10.0.0.3"],
            "source": ["10.0.0.1", "10.0.0.3"],
            "diagram": "Client\n  | probe\n  v\n10.0.0.1  ok\n10.0.0.2  fail\n10.0.0.3  ok\n\nRouting set\n  10.0.0.1\n  10.0.0.3",
            "note": "The known list still has 10.0.0.2. The routing set skips it. A probe cannot find a new server.",
        },
        {
            "mark": "health-back",
            "title": "10.0.0.2 answers. The probe puts it back.",
            "memory": ["10.0.0.1", "10.0.0.2", "10.0.0.3"],
            "source": ["10.0.0.1", "10.0.0.2", "10.0.0.3"],
            "diagram": "Client\n  | probe\n  v\n10.0.0.1  ok\n10.0.0.2  ok\n10.0.0.3  ok",
            "note": "The routing set has three addresses again.",
        },
    ],
    "moved": [
        {
            "mark": "moved-guess",
            "title": "The client sends every key to 10.0.0.1.",
            "memory": ["10.0.0.1"],
            "source": ["10.0.0.2"],
            "diagram": "Client memory\n  user-7 -> 10.0.0.1",
            "note": "That guess is stale. user-7 lives on 10.0.0.2.",
        },
        {
            "mark": "moved-send",
            "title": "The client sends user-7 to 10.0.0.1.",
            "memory": ["10.0.0.1"],
            "source": ["10.0.0.2"],
            "diagram": "Client\n  |\n  | user-7\n  v\n10.0.0.1",
            "note": "10.0.0.1 does not own this key.",
        },
        {
            "mark": "moved-answer",
            "title": "10.0.0.1 answers MOVED.",
            "memory": ["10.0.0.2"],
            "source": ["10.0.0.2"],
            "diagram": "10.0.0.1\n  |\n  | MOVED 10.0.0.2\n  v\nClient memory\n  user-7 -> 10.0.0.2",
            "note": "The client stores the new address for this key.",
        },
        {
            "mark": "moved-retry",
            "title": "The client sends user-7 to 10.0.0.2.",
            "memory": ["10.0.0.2"],
            "source": ["10.0.0.2"],
            "diagram": "Client\n  |\n  | user-7\n  v\n10.0.0.2\n  |\n  v\nok",
            "note": "The retry hits the owner. Redis Cluster uses this MOVED answer.",
        },
    ],
}


@app.post("/api/client-lb/{method}/next")
def client_lb_next(method: str) -> dict:
    frames = LB_FRAMES.get(method)
    if frames is None:
        return {"ok": False, "code": "client_lb_story"}
    _lb_step[method] = min(_lb_step[method] + 1, len(frames) - 1)
    frame = dict(frames[_lb_step[method]])
    frame["method"] = method
    frame["step"] = _lb_step[method] + 1
    frame["of"] = len(frames)
    frame["code"] = "client_lb_story"
    return frame


@app.get("/api/registry")
def registry() -> dict:
    return {"servers": SERVERS, "code": "registry"}


@app.get("/api/work")
def work(server: str) -> dict:
    return {"handled_by": server, "hop": "direct", "code": "work"}


@app.post("/api/balance")
def balance(body: BalanceBody) -> dict:
    if body.mode == "l4":
        return {
            "mode": "l4",
            "side": "server",
            "saw": "ip and port",
            "path_used": False,
            "pool": "tcp",
            "server": _server_for(body.client),
            "code": "balance",
        }
    pool = "realtime" if body.path.startswith("/ws") else "api"
    return {
        "mode": "l7",
        "side": "server",
        "saw": "method and path",
        "path_used": True,
        "pool": pool,
        "server": pool,
        "code": "balance",
    }


@app.get("/api/slow")
async def slow(client: str) -> dict:
    count = _slow_tries.get(client, 0) + 1
    _slow_tries[client] = count
    if count < 3:
        await asyncio.sleep(0.35)
        return {"ok": False, "attempt_on_server": count, "code": "slow"}
    return {"ok": True, "attempt_on_server": count, "code": "slow"}


@app.post("/api/charge")
def charge(body: ChargeBody) -> dict:
    previous = _charges.get(body.key)
    if previous is not None:
        replay = dict(previous)
        replay["replayed"] = True
        replay["code"] = "charge"
        return replay
    receipt = {"id": len(_charges) + 1, "amount": body.amount, "key": body.key, "replayed": False, "code": "charge"}
    _charges[body.key] = receipt
    return receipt


@app.post("/api/breaker")
def breaker_call(body: BreakerBody) -> dict:
    now = time.monotonic()
    state = _breaker["state"]
    if state == "open" and now - _breaker["opened_at"] >= BREAKER_COOL_S:
        _breaker["state"] = "half-open"
        state = "half-open"
    if state == "open":
        return {"state": "open", "called_dependency": False, "ok": False, "code": "breaker_call"}
    if body.fail or (state == "half-open" and body.fail):
        _breaker["failures"] += 1
        if _breaker["failures"] >= BREAKER_LIMIT or state == "half-open":
            _breaker["state"] = "open"
            _breaker["opened_at"] = now
        return {
            "state": _breaker["state"],
            "called_dependency": True,
            "ok": False,
            "failures": _breaker["failures"],
            "code": "breaker_call",
        }
    _breaker["state"] = "closed"
    _breaker["failures"] = 0
    return {"state": "closed", "called_dependency": True, "ok": True, "code": "breaker_call"}
