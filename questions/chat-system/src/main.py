"""Local chat lab.

Two logical chat servers (A and B) share Postgres and Redis Pub/Sub.
Connect and disconnect mock online and offline. The page shows every table
and the Redis channels.

DESIGN=postgres keeps messages and cursors in Postgres (design 1).
DESIGN=cassandra moves them to Cassandra (design 2). The roster tables stay
in Postgres in both designs.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
import psycopg
import redis
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field

from .message_store import CassandraMessageStore, PostgresMessageStore

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://app:app@localhost:5432/app"
)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
DESIGN = os.environ.get("DESIGN", "postgres")
CASSANDRA_HOSTS = os.environ.get("CASSANDRA_HOSTS", "localhost").split(",")
SERVERS = ("A", "B")
HOT_CHAT_THRESHOLD = 25

app = FastAPI(title="Chat system")
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)

# server_id -> client_id -> websocket | None (None means REST-connected)
sockets: dict[str, dict[str, WebSocket | None]] = {"A": {}, "B": {}}
# client_id -> list of delivered envelopes (for UI and REST mailbox)
mailboxes: dict[str, list[dict]] = {}
# server_id -> set of redis channels this process subscribed for that server
subscribed: dict[str, set[str]] = {"A": set(), "B": set()}
pubsub_log: list[dict] = []
_loop: asyncio.AbstractEventLoop | None = None
_listener_started = False
_lock = threading.Lock()


POOL_MAX = int(os.environ.get("PG_POOL_MAX", "30"))
_pool: ConnectionPool | None = None


def connect_db():
    if _pool is None:
        return psycopg.connect(DATABASE_URL, row_factory=dict_row)
    return _pool.connection()


def open_pool() -> None:
    global _pool
    _pool = ConnectionPool(
        DATABASE_URL,
        kwargs={"row_factory": dict_row},
        min_size=4,
        max_size=POOL_MAX,
        open=True,
    )


if DESIGN == "cassandra":
    store = CassandraMessageStore(CASSANDRA_HOSTS)
else:
    store = PostgresMessageStore(connect_db)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def ensure_database() -> None:
    params = conninfo_to_dict(DATABASE_URL)
    dbname = params.get("dbname", "app")
    admin = make_conninfo(DATABASE_URL, dbname="postgres")
    with psycopg.connect(admin, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)
        ).fetchone()
        if exists is None:
            conn.execute(f'CREATE DATABASE "{dbname}"')


def init_db() -> None:
    ensure_database()
    with connect_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chats (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL DEFAULT '',
              created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_members (
              chat_id TEXT NOT NULL,
              user_id TEXT NOT NULL,
              PRIMARY KEY (chat_id, user_id)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS chat_members_user_idx
              ON chat_members (user_id, chat_id)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS clients (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              status TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS last_seen (
              user_id TEXT PRIMARY KEY,
              disconnected_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        conn.commit()
    store.init_schema()


PEOPLE = [
    ("lee", "Lee"),
    ("kim", "Kim"),
    ("ada", "Ada"),
]
DEVICES = [
    ("lee-phone", "lee"),
    ("lee-laptop", "lee"),
    ("kim-phone", "kim"),
    ("kim-laptop", "kim"),
    ("ada-phone", "ada"),
]


def clear_runtime_state() -> None:
    """Wipe messages, cursors, last_seen, Redis seq/presence, and in-memory sockets.

    Users, chats, members, and the device catalog stay. Every try starts empty.
    """
    global pubsub_log
    store.clear()
    with connect_db() as conn:
        conn.execute("TRUNCATE TABLE last_seen")
        conn.execute("DELETE FROM clients")
        for client_id, user_id in DEVICES:
            conn.execute(
                """
                INSERT INTO clients (id, user_id, status) VALUES (%s, %s, 'active')
                """,
                (client_id, user_id),
            )
        conn.commit()

    for key in redis_client.scan_iter(match="chat:*:seq"):
        redis_client.delete(key)
    for key in redis_client.scan_iter(match="user:*:server"):
        redis_client.delete(key)

    with _lock:
        for sid in SERVERS:
            sockets[sid].clear()
            subscribed[sid].clear()
        mailboxes.clear()
        mailbox_seen.clear()
        for client_id, _ in DEVICES:
            mailboxes[client_id] = []
        pubsub_log = []


def seed() -> None:
    with connect_db() as conn:
        for user_id, name in PEOPLE:
            conn.execute(
                """
                INSERT INTO users (id, name) VALUES (%s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (user_id, name),
            )
        existing = conn.execute("SELECT id FROM chats WHERE id = 'trip'").fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO chats (id, name, created_at) VALUES ('trip', 'Trip', %s)
                """,
                (now_utc(),),
            )
            for user_id in ("lee", "kim", "ada"):
                conn.execute(
                    """
                    INSERT INTO chat_members (chat_id, user_id) VALUES ('trip', %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (user_id,),
                )
        pair = conn.execute("SELECT id FROM chats WHERE id = 'lee-kim'").fetchone()
        if pair is None:
            conn.execute(
                """
                INSERT INTO chats (id, name, created_at)
                VALUES ('lee-kim', 'Lee and Kim', %s)
                """,
                (now_utc(),),
            )
            for user_id in ("lee", "kim"):
                conn.execute(
                    """
                    INSERT INTO chat_members (chat_id, user_id) VALUES ('lee-kim', %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (user_id,),
                )
        conn.commit()
    clear_runtime_state()


def user_channel(user_id: str) -> str:
    return f"user:{user_id}"


def chat_channel(chat_id: str) -> str:
    return f"chat:{chat_id}"


def next_seq(chat_id: str) -> int:
    return int(redis_client.incr(f"chat:{chat_id}:seq"))


def log_pubsub(action: str, channel: str, server_id: str, detail: str = "") -> None:
    pubsub_log.append(
        {
            "at": now_utc().isoformat(),
            "action": action,
            "channel": channel,
            "serverId": server_id,
            "detail": detail,
        }
    )
    if len(pubsub_log) > 80:
        del pubsub_log[:-80]


def online_clients_for_user(user_id: str) -> list[tuple[str, str]]:
    """Return (server_id, client_id) for connected devices of this user."""
    found: list[tuple[str, str]] = []
    with connect_db() as conn:
        rows = conn.execute(
            "SELECT id FROM clients WHERE user_id = %s AND status = 'active'",
            (user_id,),
        ).fetchall()
    client_ids = {row["id"] for row in rows}
    with _lock:
        for server_id in SERVERS:
            for client_id in sockets[server_id]:
                if client_id in client_ids:
                    found.append((server_id, client_id))
    return found


def member_count(chat_id: str) -> int:
    with connect_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM chat_members WHERE chat_id = %s",
            (chat_id,),
        ).fetchone()
    return int(row["n"])


def publish_live(chat_id: str, message: dict) -> None:
    with connect_db() as conn:
        members = conn.execute(
            "SELECT user_id FROM chat_members WHERE chat_id = %s",
            (chat_id,),
        ).fetchall()
    user_ids = [row["user_id"] for row in members]

    use_chat_channel = len(user_ids) >= HOT_CHAT_THRESHOLD
    envelope = {
        "type": "newMessage",
        "message": message,
        "via": "chat-channel" if use_chat_channel else "user-channel",
    }

    if use_chat_channel:
        channel = chat_channel(chat_id)
        redis_client.publish(channel, json.dumps(envelope))
        log_pubsub("PUBLISH", channel, "-", message["id"])
        return

    for user_id in user_ids:
        channel = user_channel(user_id)
        redis_client.publish(channel, json.dumps(envelope))
        log_pubsub("PUBLISH", channel, "-", message["id"])


mailbox_seen: dict[str, set[str]] = {}
# client_id -> user_id for every socket this process holds. Set on connect.
socket_owner: dict[str, str] = {}


def mailbox_append_unique(client_id: str, envelope: dict) -> None:
    msg_id = envelope.get("message", {}).get("id")
    box = mailboxes.setdefault(client_id, [])
    seen = mailbox_seen.setdefault(client_id, set())
    if msg_id and msg_id in seen:
        return
    if msg_id:
        seen.add(msg_id)
    box.append(envelope)


def handle_redis_message(server_id: str, channel: str, raw: str) -> None:
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError:
        return
    log_pubsub("RECEIVE", channel, server_id, envelope.get("message", {}).get("id", ""))
    if channel.startswith("user:"):
        user_id = channel.split(":", 1)[1]
        # The server's own userToClients map answers this. No database read
        # on the receive path.
        with _lock:
            targets = [
                (client_id, sock)
                for client_id, sock in sockets[server_id].items()
                if socket_owner.get(client_id) == user_id
            ]
            for client_id, _ in targets:
                mailbox_append_unique(client_id, envelope)
        for _, sock in targets:
            push_to_socket(sock, envelope)
    elif channel.startswith("chat:"):
        chat_id = channel.split(":", 1)[1]
        with connect_db() as conn:
            members = conn.execute(
                "SELECT user_id FROM chat_members WHERE chat_id = %s",
                (chat_id,),
            ).fetchall()
            clients = conn.execute(
                "SELECT id, user_id FROM clients WHERE status = 'active'"
            ).fetchall()
        member_users = {row["user_id"] for row in members}
        with _lock:
            targets = []
            for client in clients:
                if client["user_id"] not in member_users:
                    continue
                client_id = client["id"]
                if client_id in sockets[server_id]:
                    mailbox_append_unique(client_id, envelope)
                    targets.append(sockets[server_id][client_id])
        for sock in targets:
            push_to_socket(sock, envelope)


def push_to_socket(sock: WebSocket | None, envelope: dict) -> None:
    """Write the envelope to a real WebSocket. REST-connected lab devices have None."""
    if sock is None or _loop is None:
        return
    # The Redis listener runs in its own thread. The socket belongs to the
    # event loop, so hand the write to that loop.
    asyncio.run_coroutine_threadsafe(sock.send_json(envelope), _loop)


def redis_listener() -> None:
    """One Redis Pub/Sub connection. Route receives to logical servers A and B."""
    while True:
        try:
            ps = redis_client.pubsub(ignore_subscribe_messages=True)
            ps.subscribe("__chat_lab_control__")
            active: set[str] = set()
            while True:
                with _lock:
                    wanted: set[str] = set()
                    for server_id in SERVERS:
                        wanted |= subscribed[server_id]
                for channel in wanted - active:
                    ps.subscribe(channel)
                for channel in active - wanted:
                    ps.unsubscribe(channel)
                active = set(wanted)
                item = ps.get_message(timeout=0.3)
                if item is None or item.get("type") != "message":
                    continue
                channel = item.get("channel")
                data = item.get("data")
                if isinstance(channel, bytes):
                    channel = channel.decode()
                if isinstance(data, bytes):
                    data = data.decode()
                if not channel or data is None or channel == "__chat_lab_control__":
                    continue
                with _lock:
                    targets = [sid for sid in SERVERS if channel in subscribed[sid]]
                for server_id in targets:
                    handle_redis_message(server_id, channel, data)
        except Exception:
            time.sleep(0.5)


def subscribe_user(server_id: str, user_id: str) -> None:
    channel = user_channel(user_id)
    with _lock:
        subscribed[server_id].add(channel)
    redis_client.publish("__chat_lab_control__", "refresh")
    redis_client.set(f"user:{user_id}:server", server_id)
    log_pubsub("SUBSCRIBE", channel, server_id)


def unsubscribe_user_if_idle(server_id: str, user_id: str) -> None:
    still = False
    with connect_db() as conn:
        rows = conn.execute(
            "SELECT id FROM clients WHERE user_id = %s AND status = 'active'",
            (user_id,),
        ).fetchall()
    with _lock:
        for row in rows:
            if row["id"] in sockets[server_id]:
                still = True
                break
        if not still:
            channel = user_channel(user_id)
            subscribed[server_id].discard(channel)
            log_pubsub("UNSUBSCRIBE", channel, server_id)
            # clear presence if this server owned it
            if redis_client.get(f"user:{user_id}:server") == server_id:
                redis_client.delete(f"user:{user_id}:server")
    redis_client.publish("__chat_lab_control__", "refresh")


def drain_client(client_id: str, user_id: str) -> tuple[list[dict], list[dict]]:
    """Return (envelopes, reads). Reads name each index range or partition touched."""
    drained: list[dict] = []
    reads: list[dict] = []
    with connect_db() as conn:
        chats = conn.execute(
            """
            SELECT chat_id FROM chat_members WHERE user_id = %s
            """,
            (user_id,),
        ).fetchall()
    for chat in chats:
        chat_id = chat["chat_id"]
        last_seq = store.read_cursor(client_id, chat_id)
        current_seq = int(redis_client.get(f"chat:{chat_id}:seq") or 0)
        rows, chat_reads = store.read_after(chat_id, last_seq, current_seq)
        reads.extend(chat_reads)
        for msg in rows:
            envelope = {
                "type": "newMessage",
                "message": msg,
                "via": "drain",
            }
            mailbox_append_unique(client_id, envelope)
            drained.append(envelope)
    return drained, reads


def set_last_seen(user_id: str) -> None:
    # Only when no device remains online for this user.
    if online_clients_for_user(user_id):
        return
    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO last_seen (user_id, disconnected_at)
            VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET disconnected_at = EXCLUDED.disconnected_at
            """,
            (user_id, now_utc()),
        )
        conn.commit()


def _jsonable(row: dict) -> dict:
    out = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out


class ConnectBody(BaseModel):
    serverId: str
    clientId: str


class DisconnectBody(BaseModel):
    clientId: str


class CreateChatBody(BaseModel):
    participants: list[str] = Field(min_length=1)  # the creator is added
    name: str = ""
    serverId: str = "A"
    clientId: str


class SendMessageBody(BaseModel):
    chatId: str
    message: str = ""
    mediaKey: str = ""
    serverId: str = "A"
    clientId: str


class AckBody(BaseModel):
    clientId: str
    chatId: str
    seq: int
    mode: str = ""  # cassandra: upsert | lwt. Postgres always uses GREATEST.


@app.on_event("startup")
def startup() -> None:
    global _listener_started
    init_db()
    open_pool()
    seed()
    if not _listener_started:
        threading.Thread(target=redis_listener, name="redis-listener", daemon=True).start()
        _listener_started = True


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "design": DESIGN}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/compare")
def compare() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "compare.html")


@app.post("/v1/lab/connect")
def lab_connect(body: ConnectBody) -> dict:
    if body.serverId not in SERVERS:
        raise HTTPException(status_code=422, detail="serverId must be A or B")
    with connect_db() as conn:
        client = conn.execute(
            "SELECT id, user_id, status FROM clients WHERE id = %s",
            (body.clientId,),
        ).fetchone()
    if client is None:
        raise HTTPException(status_code=404, detail="client not found")
    # Move off any other server.
    with _lock:
        for sid in SERVERS:
            sockets[sid].pop(body.clientId, None)
        sockets[body.serverId][body.clientId] = None
        socket_owner[body.clientId] = client["user_id"]
    subscribe_user(body.serverId, client["user_id"])
    drained, reads = drain_client(body.clientId, client["user_id"])
    return {
        "serverId": body.serverId,
        "clientId": body.clientId,
        "userId": client["user_id"],
        "status": "online",
        "drained": len(drained),
        "reads": reads,
    }


@app.post("/v1/lab/disconnect")
def lab_disconnect(body: DisconnectBody) -> dict:
    with connect_db() as conn:
        client = conn.execute(
            "SELECT id, user_id FROM clients WHERE id = %s",
            (body.clientId,),
        ).fetchone()
    if client is None:
        raise HTTPException(status_code=404, detail="client not found")
    server_id = None
    with _lock:
        for sid in SERVERS:
            if body.clientId in sockets[sid]:
                sockets[sid].pop(body.clientId, None)
                server_id = sid
                break
    if server_id:
        unsubscribe_user_if_idle(server_id, client["user_id"])
    set_last_seen(client["user_id"])
    return {"clientId": body.clientId, "status": "offline"}


MAX_CHAT_MEMBERS = 100


@app.post("/v1/chats", status_code=200)
def create_chat(body: CreateChatBody) -> dict:
    with connect_db() as conn:
        creator = conn.execute(
            "SELECT id, user_id FROM clients WHERE id = %s",
            (body.clientId,),
        ).fetchone()
        if creator is None:
            raise HTTPException(status_code=404, detail="client not found")
        members = list(dict.fromkeys([creator["user_id"], *body.participants]))
        known = {
            row["id"]
            for row in conn.execute(
                "SELECT id FROM users WHERE id = ANY(%s)", (members,)
            ).fetchall()
        }
        unknown = [m for m in members if m not in known]
        if unknown:
            raise HTTPException(status_code=404, detail=f"unknown users: {unknown}")
        if len(members) < 2:
            raise HTTPException(status_code=422, detail="a chat needs at least 2 people")
        if len(members) > MAX_CHAT_MEMBERS:
            raise HTTPException(status_code=422, detail="a chat has at most 100 people")

        # A two-person chat gets a fixed id, so a second "start chat" returns
        # the same chat. A group always gets a new id.
        if len(members) == 2:
            chat_id = "-".join(sorted(members))
        else:
            chat_id = "g-" + str(uuid.uuid4())[:6]
        inserted = conn.execute(
            """
            INSERT INTO chats (id, name, created_at) VALUES (%s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            RETURNING id
            """,
            (chat_id, body.name or chat_id, now_utc()),
        ).fetchone()
        for user_id in members:
            conn.execute(
                """
                INSERT INTO chat_members (chat_id, user_id) VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (chat_id, user_id),
            )
        conn.commit()
    return {
        "chatId": chat_id,
        "status": "SUCCESS",
        "created": inserted is not None,
        "members": members,
    }


@app.post("/v1/messages", status_code=202)
def send_message(body: SendMessageBody) -> dict:
    with connect_db() as conn:
        client = conn.execute(
            "SELECT id, user_id FROM clients WHERE id = %s",
            (body.clientId,),
        ).fetchone()
        if client is None:
            raise HTTPException(status_code=404, detail="client not found")
        member = conn.execute(
            """
            SELECT 1 FROM chat_members
            WHERE chat_id = %s AND user_id = %s
            """,
            (body.chatId, client["user_id"]),
        ).fetchone()
        if member is None:
            raise HTTPException(status_code=403, detail="not a chat member")
    if body.serverId not in SERVERS:
        raise HTTPException(status_code=422, detail="serverId must be A or B")

    message_id = str(uuid.uuid4())
    seq = next_seq(body.chatId)
    created = now_utc()
    stored_in = store.insert_message(
        {
            "id": message_id,
            "chat_id": body.chatId,
            "seq": seq,
            "sender_id": client["user_id"],
            "body": body.message,
            "media_key": body.mediaKey,
            "created_at": created,
        }
    )
    # Postgres design: same connection pool, two statements. Cassandra design:
    # two independent writes, no transaction. At least once covers the gap.
    store.set_sender_cursor(body.clientId, body.chatId, seq)

    message = {
        "id": message_id,
        "chat_id": body.chatId,
        "seq": seq,
        "sender_id": client["user_id"],
        "body": body.message,
        "media_key": body.mediaKey,
        "created_at": created.isoformat(),
    }
    publish_live(body.chatId, message)
    # Also put on sender mailbox so the UI can show send path.
    mailbox_append_unique(
        body.clientId,
        {"type": "sendAck", "message": message, "via": "local-store"},
    )
    return {"messageId": message_id, "status": "SUCCESS", "seq": seq, "storedIn": stored_in}


def default_ack_mode() -> str:
    return "upsert" if DESIGN == "cassandra" else "greatest"


@app.post("/v1/ack")
def ack_message(body: AckBody) -> dict:
    result = store.ack(body.clientId, body.chatId, body.seq, mode=body.mode or default_ack_mode())
    return {"clientId": body.clientId, "chatId": body.chatId, "seq": body.seq, "cursor": result}


@app.get("/v1/lab/mailbox/{client_id}")
def get_mailbox(client_id: str) -> dict:
    box = mailboxes.get(client_id, [])
    return {"clientId": client_id, "items": box[-40:], "total": len(box)}


@app.post("/v1/lab/mailbox/{client_id}/clear")
def clear_mailbox(client_id: str) -> dict:
    mailboxes[client_id] = []
    mailbox_seen[client_id] = set()
    return {"clientId": client_id, "cleared": True}


@app.post("/v1/lab/reset")
def lab_reset() -> dict:
    clear_runtime_state()
    message_tables = (
        ["messages_by_chat", "device_cursors_by_client"]
        if DESIGN == "cassandra"
        else ["messages", "device_cursors"]
    )
    return {
        "ok": True,
        "design": DESIGN,
        "cleared": message_tables + ["last_seen", "clients", "redis", "mailboxes"],
        "kept": ["users", "chats", "chat_members"],
    }


@app.get("/v1/lab/state")
def lab_state() -> dict:
    with connect_db() as conn:
        users = conn.execute("SELECT id, name FROM users ORDER BY id").fetchall()
        chats = conn.execute(
            "SELECT id, name, created_at FROM chats ORDER BY created_at"
        ).fetchall()
        members = conn.execute(
            "SELECT chat_id, user_id FROM chat_members ORDER BY chat_id, user_id"
        ).fetchall()
        clients = conn.execute(
            "SELECT id, user_id, status FROM clients ORDER BY id"
        ).fetchall()
        last_seen = conn.execute(
            "SELECT user_id, disconnected_at FROM last_seen ORDER BY user_id"
        ).fetchall()

    client_owner = {row["id"]: row["user_id"] for row in clients}

    with _lock:
        # Each chat server keeps an in-memory map: client_id -> local socket.
        # Redis presence only names which server; the socket itself never leaves
        # that process.
        connection_maps: dict[str, dict] = {}
        user_to_clients: dict[str, dict] = {}
        online: dict[str, list] = {}
        for sid in SERVERS:
            cmap: dict[str, dict] = {}
            by_user: dict[str, list] = {}
            for client_id, sock in sockets[sid].items():
                user_id = client_owner.get(client_id, "?")
                cmap[client_id] = {
                    "userId": user_id,
                    "transport": "websocket" if sock is not None else "rest-mock",
                    "socketLocal": True,
                }
                by_user.setdefault(user_id, []).append(client_id)
            connection_maps[sid] = cmap
            user_to_clients[sid] = by_user
            online[sid] = list(sockets[sid].keys())
        subs = {sid: sorted(subscribed[sid]) for sid in SERVERS}

    presence = {}
    for user in users:
        key = f"user:{user['id']}:server"
        presence[user["id"]] = redis_client.get(key)

    seq_keys = {}
    for chat in chats:
        seq_keys[chat["id"]] = int(redis_client.get(f"chat:{chat['id']}:seq") or 0)

    postgres_tables = {
        "users": [_jsonable(r) for r in users],
        "chats": [_jsonable(r) for r in chats],
        "chat_members": [_jsonable(r) for r in members],
        "clients": [_jsonable(r) for r in clients],
        "last_seen": [_jsonable(r) for r in last_seen],
    }
    message_tables = store.snapshot()
    if DESIGN == "cassandra":
        cassandra_tables = message_tables
    else:
        postgres_tables.update(message_tables)
        cassandra_tables = None

    return {
        "design": DESIGN,
        "interviewDefault": (
            "messages in Cassandra ((chat_id, bucket), seq), roster in Postgres, Redis Pub/Sub live hop"
            if DESIGN == "cassandra"
            else "store in Postgres, live push on Redis Pub/Sub, drain on connect"
        ),
        "variants": {
            "onlineSameServer": "Sender and recipient sockets on A. Local deliver plus Pub/Sub log.",
            "onlineCrossServer": "Lee on A, Kim on B. Redis RECEIVE on B fills Kim mailbox.",
            "offlineDrain": "Disconnect Kim, send, reconnect. Drain via=drain.",
        },
        "online": online,
        "connectionMaps": connection_maps,
        "userToClients": user_to_clients,
        "postgres": postgres_tables,
        "cassandra": cassandra_tables,
        "redis": {
            "subscriptions": subs,
            "presence": presence,
            "chatSeq": seq_keys,
            "pubsubLog": pubsub_log[-30:],
        },
    }


@app.websocket("/ws/{server_id}/{client_id}")
async def websocket_endpoint(websocket: WebSocket, server_id: str, client_id: str):
    if server_id not in SERVERS:
        await websocket.close(code=1008)
        return
    with connect_db() as conn:
        client = conn.execute(
            "SELECT id, user_id FROM clients WHERE id = %s",
            (client_id,),
        ).fetchone()
    if client is None:
        await websocket.close(code=1008)
        return

    global _loop
    _loop = asyncio.get_running_loop()
    await websocket.accept()
    with _lock:
        for sid in SERVERS:
            sockets[sid].pop(client_id, None)
        sockets[server_id][client_id] = websocket
        socket_owner[client_id] = client["user_id"]
    subscribe_user(server_id, client["user_id"])
    drained, _reads = drain_client(client_id, client["user_id"])
    await websocket.send_json(
        {"type": "connected", "serverId": server_id, "drained": len(drained)}
    )
    for item in drained:
        await websocket.send_json(item)

    try:
        while True:
            payload = await websocket.receive_json()
            kind = payload.get("type")
            if kind == "ack":
                store.ack(client_id, payload["chatId"], int(payload["seq"]), mode=default_ack_mode())
                await websocket.send_json({"type": "ackOk", **payload})
            elif kind == "sendMessage":
                result = send_message(
                    SendMessageBody(
                        chatId=payload["chatId"],
                        message=payload.get("message", ""),
                        mediaKey=payload.get("mediaKey", ""),
                        serverId=server_id,
                        clientId=client_id,
                    )
                )
                await websocket.send_json({"type": "sendResult", **result})
            elif kind == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        with _lock:
            if sockets[server_id].get(client_id) is websocket:
                sockets[server_id].pop(client_id, None)
        unsubscribe_user_if_idle(server_id, client["user_id"])
        set_last_seen(client["user_id"])
