"""Data modeling lab: store choice, a copied name, and the key for the hot read."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path

import psycopg
import redis
from fastapi import FastAPI

from src.engines import catalog, read_engine, seed_all, seed_key_value, write_engine
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:5432/app")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
STATIC = Path(__file__).resolve().parent / "static"
SHARDS = 4

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS posts (
    id INT PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users (id),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS posts_user_id_created_at_idx
    ON posts (user_id, created_at DESC);
CREATE TABLE IF NOT EXISTS post_copies (
    id INT PRIMARY KEY,
    user_id INT NOT NULL,
    username TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS likes (
    user_id INT NOT NULL REFERENCES users (id),
    post_id INT NOT NULL REFERENCES posts (id),
    PRIMARY KEY (user_id, post_id)
);
CREATE TABLE IF NOT EXISTS user_documents (
    user_id INT PRIMARY KEY,
    body JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS follows (
    follower_id INT NOT NULL REFERENCES users (id),
    followee_id INT NOT NULL REFERENCES users (id),
    PRIMARY KEY (follower_id, followee_id)
);
CREATE TABLE IF NOT EXISTS feed_items (
    reader_id INT NOT NULL,
    post_id INT NOT NULL,
    author_id INT NOT NULL,
    author_name TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (reader_id, post_id)
);
"""

app = FastAPI(title="Data modeling")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def db():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def cache():
    return redis.Redis.from_url(REDIS_URL, decode_responses=True)


def shard_of(value: int) -> int:
    return value % SHARDS


def salted_shard(user_id: int, salt: int) -> int:
    return (user_id * 10 + salt) % SHARDS


def seed(conn) -> None:
    conn.execute(
        """
        INSERT INTO users (id, username, email) VALUES
            (1, 'ada', 'ada@example.com'),
            (2, 'bob', 'bob@example.com'),
            (7, 'nova', 'nova@example.com')
        """
    )
    conn.execute(
        """
        INSERT INTO posts (id, user_id, content, created_at) VALUES
            (1, 1, 'hello', '2024-01-01 10:00:00+00'),
            (2, 1, 'second', '2024-01-01 10:05:00+00')
        """
    )
    for offset in range(8):
        post_id = 3 + offset
        conn.execute(
            """
            INSERT INTO posts (id, user_id, content, created_at)
            VALUES (%s, 7, %s, '2024-01-02 10:00:00+00'::timestamptz + (%s || ' minutes')::interval)
            """,
            (post_id, f"nova-{offset}", offset),
        )
    conn.execute(
        """
        INSERT INTO post_copies (id, user_id, username, content, created_at)
        SELECT p.id, p.user_id, u.username, p.content, p.created_at
        FROM posts p
        JOIN users u ON u.id = p.user_id
        """
    )
    conn.execute("INSERT INTO likes (user_id, post_id) VALUES (2, 1)")
    conn.execute(
        """
        INSERT INTO follows (follower_id, followee_id) VALUES
            (1, 2),
            (2, 1),
            (2, 7)
        """
    )
    document = {
        "id": 1,
        "username": "ada",
        "email": "ada@example.com",
        "posts": [
            {"id": 1, "content": "hello"},
            {"id": 2, "content": "second"},
        ],
    }
    conn.execute(
        "INSERT INTO user_documents (user_id, body) VALUES (1, %s::jsonb)",
        (json.dumps(document),),
    )
    conn.execute(
        """
        INSERT INTO feed_items (reader_id, post_id, author_id, author_name, content, created_at)
        SELECT 2, p.id, p.user_id, u.username, p.content, p.created_at
        FROM posts p
        JOIN users u ON u.id = p.user_id
        WHERE p.user_id IN (1, 7)
        """
    )


def seed_redis() -> None:
    client = cache()
    client.flushdb()
    with db() as conn:
        users = conn.execute("SELECT id, username FROM users ORDER BY id").fetchall()
        posts = conn.execute(
            "SELECT id, user_id, content FROM posts ORDER BY id"
        ).fetchall()
        likes = conn.execute(
            "SELECT user_id, post_id FROM likes ORDER BY post_id, user_id"
        ).fetchall()
    by_user: dict[int, list[str]] = defaultdict(list)
    for user in users:
        client.set(f"user:{user['id']}", user["username"])
    for post in posts:
        client.set(f"post:{post['id']}", post["content"])
        by_user[post["user_id"]].append(str(post["id"]))
    for user_id, post_ids in by_user.items():
        client.set(f"posts_of:{user_id}", ",".join(post_ids))
    counts: dict[int, int] = defaultdict(int)
    for like in likes:
        client.set(f"liked:{like['post_id']}:{like['user_id']}", "1")
        counts[like["post_id"]] += 1
    for post_id, count in counts.items():
        client.set(f"like_count:{post_id}", count)
        client.set(f"like_clicks:{post_id}", count)
    client.close()
    seed_key_value()


def reset_state() -> None:
    with db() as conn:
        conn.execute(
            """
            TRUNCATE feed_items, post_copies, user_documents, users
            RESTART IDENTITY CASCADE
            """
        )
        seed(conn)
    seed_redis()


def ensure_ready() -> None:
    with db() as conn:
        conn.execute(SCHEMA)
        count = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        if count == 0:
            seed(conn)
    seed_redis()


@app.on_event("startup")
def startup() -> None:
    ensure_ready()
    seed_all()


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/api/engines")
def list_engines() -> dict:
    return {"ok": True, "code": "read_engine", "engines": catalog()}


@app.get("/api/engines/{kind}")
def show_engine(kind: str) -> dict:
    return read_engine(kind)


@app.post("/api/engines/{kind}/write")
def run_engine_write(kind: str) -> dict:
    return write_engine(kind)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


@app.post("/api/reset")
def reset() -> dict:
    reset_state()
    return {"ok": True, "code": "reset_state"}


def feeds_for(conn, user_id: int) -> dict:
    normalized = conn.execute(
        """
        SELECT p.id, u.username, p.content
        FROM posts p
        JOIN users u ON u.id = p.user_id
        WHERE p.user_id = %s
        ORDER BY p.created_at
        """,
        (user_id,),
    ).fetchall()
    copied = conn.execute(
        """
        SELECT id, username, content
        FROM post_copies
        WHERE user_id = %s
        ORDER BY created_at
        """,
        (user_id,),
    ).fetchall()
    return {
        "normalized_feed": [dict(row) for row in normalized],
        "denormalized_feed": [dict(row) for row in copied],
    }


@app.post("/api/rename")
def rename_user(body: dict) -> dict:
    user_id = int(body["user_id"])
    username = str(body["username"]).strip()
    update_copies = bool(body.get("update_copies"))
    if username == "":
        return {"ok": False, "code": "rename_user"}
    with db() as conn:
        updated = conn.execute(
            "UPDATE users SET username = %s WHERE id = %s RETURNING id",
            (username, user_id),
        ).fetchone()
        if updated is None:
            return {"ok": False, "code": "rename_user"}
        copy_rows = 0
        if update_copies:
            copy_rows = conn.execute(
                """
                UPDATE post_copies
                SET username = %s
                WHERE user_id = %s
                """,
                (username, user_id),
            ).rowcount
            conn.execute(
                """
                UPDATE feed_items
                SET author_name = %s
                WHERE author_id = %s
                """,
                (username, user_id),
            )
            conn.execute(
                """
                UPDATE user_documents
                SET body = jsonb_set(body, '{username}', to_jsonb(%s::text), false)
                WHERE user_id = %s
                """,
                (username, user_id),
            )
        result = feeds_for(conn, user_id)
    if update_copies:
        client = cache()
        client.set(f"user:{user_id}", username)
        client.close()
    stale = [row["username"] for row in result["denormalized_feed"]]
    if update_copies:
        diagram = (
            f"Rename user {user_id} to {username}\n"
            "\n"
            "users.username\n"
            f"  {username}\n"
            "\n"
            f"post_copies updated: {copy_rows}\n"
            "\n"
            "The user row is the source of truth.\n"
            "Each copied name is updated in the same step."
        )
    else:
        diagram = (
            f"Rename user {user_id} to {username}\n"
            "\n"
            "users.username\n"
            f"  {username}\n"
            "\n"
            "post_copies.username\n"
            f"  {', '.join(stale)}\n"
            "\n"
            "A join reads the user row.\n"
            "A copied name stays old until each copy is updated."
        )
    result.update(
        {
            "ok": True,
            "code": "rename_user",
            "update_copies": update_copies,
            "copy_rows_updated": copy_rows,
            "diagram": diagram,
        }
    )
    return result


def like_view(post_id: int) -> dict:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT user_id FROM likes
            WHERE post_id = %s
            ORDER BY user_id
            """,
            (post_id,),
        ).fetchall()
    client = cache()
    members = {}
    for key in client.scan_iter(match=f"liked:{post_id}:*"):
        members[key] = client.get(key)
    view = {
        "postgres": {
            "store": "postgres",
            "count": len(rows),
            "user_ids": [row["user_id"] for row in rows],
            "answers": ["count", "who liked", "did this user like"],
        },
        "redis_member": {
            "store": "redis",
            "count": int(client.get(f"like_count:{post_id}") or 0),
            "members": members,
        },
        "redis_counter": {
            "store": "redis",
            "clicks": int(client.get(f"like_clicks:{post_id}") or 0),
            "answers": ["click count"],
        },
    }
    client.close()
    return view


@app.get("/api/likes/{post_id}")
def show_likes(post_id: int) -> dict:
    view = like_view(post_id)
    view["code"] = "record_like"
    view["diagram"] = (
        f"Post {post_id}\n"
        "\n"
        "Postgres likes\n"
        f"  count {view['postgres']['count']}\n"
        f"  user_ids {view['postgres']['user_ids']}\n"
        "\n"
        "Redis member plus count\n"
        f"  like_count {view['redis_member']['count']}\n"
        f"  members {view['redis_member']['members']}\n"
        "\n"
        "Redis click counter\n"
        f"  like_clicks {view['redis_counter']['clicks']}"
    )
    return view


@app.post("/api/likes")
def record_like(body: dict) -> dict:
    user_id = int(body["user_id"])
    post_id = int(body["post_id"])
    store = str(body.get("store", "postgres"))
    replayed = False
    if store == "postgres":
        with db() as conn:
            row = conn.execute(
                """
                INSERT INTO likes (user_id, post_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                RETURNING user_id
                """,
                (user_id, post_id),
            ).fetchone()
            replayed = row is None
    elif store == "redis_member":
        client = cache()
        added = client.set(f"liked:{post_id}:{user_id}", "1", nx=True)
        if added:
            client.incr(f"like_count:{post_id}")
        else:
            replayed = True
        client.close()
    elif store == "redis_counter":
        client = cache()
        client.incr(f"like_clicks:{post_id}")
        client.close()
    else:
        return {"ok": False, "code": "record_like"}
    view = like_view(post_id)
    view.update(
        {
            "ok": True,
            "code": "record_like",
            "store": store,
            "replayed": replayed,
            "diagram": (
                f"Like from user {user_id} on post {post_id}\n"
                f"  store {store}\n"
                f"  replayed {str(replayed).lower()}\n"
                "\n"
                "Postgres keeps one row per pair.\n"
                "A second insert returns the first row.\n"
                "\n"
                "A member key increments the count once.\n"
                "A bare counter increments on every click."
            ),
        }
    )
    return view


@app.get("/api/partition/{user_id}")
def partition_map(user_id: int) -> dict:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, content, created_at
            FROM posts
            WHERE user_id = %s
            ORDER BY created_at, id
            """,
            (user_id,),
        ).fetchall()
    home = shard_of(user_id)
    placed = []
    for row in rows:
        salt = row["id"] % SHARDS
        placed.append(
            {
                "id": row["id"],
                "content": row["content"],
                "user_shard": home,
                "salt": salt,
                "salt_shard": salted_shard(user_id, salt),
            }
        )
    salt_shards = sorted({item["salt_shard"] for item in placed})
    return {
        "code": "partition_map",
        "index": "(user_id, created_at)",
        "user_id_strategy": {
            "shard": home,
            "shards_read": [home],
            "rows": len(placed),
        },
        "salt_strategy": {
            "shards_read": salt_shards,
            "rows": len(placed),
        },
        "extra_app_servers": {"count": 4, "shard": home},
        "read_replica": {
            "shard": home,
            "reads": "primary or replica",
            "writes": "primary",
        },
        "posts": placed,
        "diagram": (
            f"user {user_id}\n"
            "  |\n"
            f"  | user_id % {SHARDS}\n"
            "  v\n"
            f"shard {home}\n"
            f"  {len(placed)} posts\n"
            "\n"
            f"user {user_id} with salt\n"
            "  |\n"
            "  v\n"
            f"shards {salt_shards}\n"
            "  the read merges those shards\n"
            "\n"
            "4 app servers\n"
            "  |\n"
            "  v\n"
            f"still shard {home}\n"
            "\n"
            f"A read replica of shard {home} can serve the read.\n"
            "The write stays on the primary."
        ),
    }


@app.get("/api/home/{reader_id}")
def home_feed(reader_id: int) -> dict:
    with db() as conn:
        scatter = conn.execute(
            """
            SELECT p.id, p.user_id, u.username, p.content
            FROM follows f
            JOIN posts p ON p.user_id = f.followee_id
            JOIN users u ON u.id = p.user_id
            WHERE f.follower_id = %s
            ORDER BY p.created_at, p.id
            """,
            (reader_id,),
        ).fetchall()
        inbox = conn.execute(
            """
            SELECT post_id, author_id, author_name, content
            FROM feed_items
            WHERE reader_id = %s
            ORDER BY created_at, post_id
            """,
            (reader_id,),
        ).fetchall()
        followees = conn.execute(
            """
            SELECT followee_id FROM follows
            WHERE follower_id = %s
            ORDER BY followee_id
            """,
            (reader_id,),
        ).fetchall()
    author_shards = sorted({shard_of(row["followee_id"]) for row in followees})
    inbox_shard = shard_of(reader_id)
    return {
        "code": "home_feed",
        "diagram": (
            f"reader {reader_id}\n"
            "\n"
            "Fan-out on read\n"
            f"  authors live on shards {author_shards}\n"
            "  read each shard\n"
            "  merge the posts\n"
            "\n"
            "Fan-out on write\n"
            f"  inbox for reader {reader_id}\n"
            f"  shard {inbox_shard}\n"
            "  one query\n"
            "  author_name is a copy"
        ),
        "fanout_on_read": {
            "shards": author_shards,
            "rows": [dict(row) for row in scatter],
        },
        "fanout_on_write": {
            "shard": inbox_shard,
            "rows": [dict(row) for row in inbox],
        },
    }


@app.get("/api/graph/{user_id}")
def graph_hops(user_id: int) -> dict:
    with db() as conn:
        direct = conn.execute(
            """
            SELECT u.id, u.username
            FROM follows f
            JOIN users u ON u.id = f.followee_id
            WHERE f.follower_id = %s
            ORDER BY u.id
            """,
            (user_id,),
        ).fetchall()
        two_hop = conn.execute(
            """
            SELECT DISTINCT u.id, u.username
            FROM follows f1
            JOIN follows f2 ON f2.follower_id = f1.followee_id
            JOIN users u ON u.id = f2.followee_id
            WHERE f1.follower_id = %s
              AND u.id <> %s
            ORDER BY u.id
            """,
            (user_id, user_id),
        ).fetchall()
    direct_names = [row["username"] for row in direct]
    hop_names = [row["username"] for row in two_hop]
    return {
        "code": "graph_hops",
        "store": "postgres",
        "direct": direct_names,
        "two_hop": hop_names,
        "diagram": (
            f"user {user_id}\n"
            "  |\n"
            "  | one join on follows\n"
            "  v\n"
            f"{', '.join(direct_names)}\n"
            "  |\n"
            "  | second join on follows\n"
            "  v\n"
            f"{', '.join(hop_names)}\n"
            "\n"
            "The edges live in Postgres.\n"
            "A graph database is a later choice."
        ),
    }
