"""News feed lab. One process hosts the five services. Postgres is the source of truth."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import psycopg
import redis
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
STATIC = os.path.join(os.path.dirname(__file__), "static")

app = FastAPI(title="News feed")
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)


class PostIn(BaseModel):
    content: str = ""
    image_links: list[str] = Field(default_factory=list)
    video_links: list[str] = Field(default_factory=list)


class CommentIn(BaseModel):
    content: str = ""
    image_links: list[str] = Field(default_factory=list)
    video_links: list[str] = Field(default_factory=list)


def connect() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
              id bigint PRIMARY KEY,
              user_name text NOT NULL,
              email text UNIQUE NOT NULL,
              famous boolean NOT NULL DEFAULT false,
              created_at timestamptz NOT NULL DEFAULT now(),
              updated_at timestamptz NOT NULL DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS follows (
              follower_id bigint NOT NULL REFERENCES users(id),
              followee_id bigint NOT NULL REFERENCES users(id),
              created_at timestamptz NOT NULL DEFAULT now(),
              PRIMARY KEY (follower_id, followee_id)
            );
            CREATE TABLE IF NOT EXISTS posts (
              id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
              user_id bigint NOT NULL REFERENCES users(id),
              content text NOT NULL,
              image_links text[] NOT NULL DEFAULT '{}',
              video_links text[] NOT NULL DEFAULT '{}',
              like_count bigint NOT NULL DEFAULT 0,
              created_at timestamptz NOT NULL DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS posts_author_time
              ON posts (user_id, created_at DESC, id DESC);
            CREATE TABLE IF NOT EXISTS likes (
              user_id bigint NOT NULL REFERENCES users(id),
              post_id bigint NOT NULL REFERENCES posts(id),
              created_at timestamptz NOT NULL DEFAULT now(),
              PRIMARY KEY (user_id, post_id)
            );
            CREATE TABLE IF NOT EXISTS comments (
              id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
              post_id bigint NOT NULL REFERENCES posts(id),
              user_id bigint NOT NULL REFERENCES users(id),
              content text NOT NULL,
              image_links text[] NOT NULL DEFAULT '{}',
              video_links text[] NOT NULL DEFAULT '{}',
              created_at timestamptz NOT NULL DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS comments_post_time
              ON comments (post_id, created_at DESC, id DESC);
            CREATE TABLE IF NOT EXISTS inbox (
              user_id bigint NOT NULL REFERENCES users(id),
              post_id bigint NOT NULL REFERENCES posts(id),
              author_id bigint NOT NULL REFERENCES users(id),
              created_at timestamptz NOT NULL,
              PRIMARY KEY (user_id, created_at, post_id)
            );
            """
        )
        conn.execute(
            """
            INSERT INTO users (id, user_name, email, famous) VALUES
              (1, 'lee', 'lee@example.com', false),
              (2, 'kim', 'kim@example.com', false),
              (3, 'ada', 'ada@example.com', false),
              (4, 'bea', 'bea@example.com', true)
            ON CONFLICT (id) DO NOTHING
            """
        )
        conn.execute(
            """
            INSERT INTO follows (follower_id, followee_id) VALUES
              (1, 2), (1, 3), (1, 4)
            ON CONFLICT DO NOTHING
            """
        )
        existing = conn.execute("SELECT count(*) AS n FROM posts").fetchone()
        if existing["n"] == 0:
            kim = conn.execute(
                """
                INSERT INTO posts (user_id, content)
                VALUES (2, 'Kim: lunch is noodles.')
                RETURNING id, user_id, created_at
                """
            ).fetchone()
            bea = conn.execute(
                """
                INSERT INTO posts (user_id, content, image_links)
                VALUES (4, 'Bea: on stage tonight.', ARRAY['https://example.com/bea.jpg'])
                RETURNING id, user_id, created_at
                """
            ).fetchone()
            for post in (kim, bea):
                conn.execute(
                    """
                    INSERT INTO inbox (user_id, post_id, author_id, created_at)
                    SELECT follower_id, %s, %s, %s FROM follows WHERE followee_id = %s
                    UNION ALL
                    SELECT %s, %s, %s, %s
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        post["id"],
                        post["user_id"],
                        post["created_at"],
                        post["user_id"],
                        post["user_id"],
                        post["id"],
                        post["user_id"],
                        post["created_at"],
                    ),
                )
        conn.commit()


@app.on_event("startup")
def startup() -> None:
    init_db()


def require_user(user_id: int | None) -> int:
    if user_id is None:
        raise HTTPException(status_code=401, detail="Send the X-User-Id header.")
    with connect() as conn:
        row = conn.execute("SELECT id FROM users WHERE id = %s", (user_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown user.")
    return user_id


def parse_cursor(cursor: str | None) -> tuple[datetime, int] | None:
    if not cursor:
        return None
    stamp, raw_id = cursor.split("|", 1)
    return datetime.fromisoformat(stamp), int(raw_id)


def make_cursor(created_at: datetime, item_id: int) -> str:
    return f"{created_at.isoformat()}|{item_id}"


def post_public(row: dict[str, Any], liked: bool) -> dict[str, Any]:
    redis_count = redis_client.get(f"like_count:{row['id']}")
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "user_name": row["user_name"],
        "famous": row["famous"],
        "content": row["content"],
        "image_links": list(row["image_links"] or []),
        "video_links": list(row["video_links"] or []),
        "like_count": row["like_count"],
        "redis_like_count": int(redis_count) if redis_count is not None else row["like_count"],
        "liked_by_me": liked,
        "created_at": row["created_at"].isoformat(),
        "source": row.get("source", "posts"),
    }


@app.get("/healthz")
def healthz() -> dict[str, str]:
    with connect() as conn:
        conn.execute("SELECT 1")
    redis_client.ping()
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(STATIC, "index.html"), headers={"Cache-Control": "no-store"})


def _iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _rows(conn: psycopg.Connection, sql: str) -> list[dict[str, Any]]:
    rows = conn.execute(sql).fetchall()
    return [{key: _iso(value) for key, value in row.items()} for row in rows]


@app.get("/v1/stores")
def stores() -> dict[str, Any]:
    with connect() as conn:
        counts = conn.execute(
            """
            SELECT
              (SELECT count(*) FROM users) AS users,
              (SELECT count(*) FROM follows) AS follows,
              (SELECT count(*) FROM posts) AS posts,
              (SELECT count(*) FROM likes) AS likes,
              (SELECT count(*) FROM comments) AS comments,
              (SELECT count(*) FROM inbox) AS inbox
            """
        ).fetchone()
        tables = {
            "users": _rows(conn, "SELECT id, user_name, email, famous FROM users ORDER BY id"),
            "follows": _rows(
                conn,
                """
                SELECT f.follower_id, fu.user_name AS follower, f.followee_id,
                       tu.user_name AS followee
                FROM follows f
                JOIN users fu ON fu.id = f.follower_id
                JOIN users tu ON tu.id = f.followee_id
                ORDER BY f.follower_id, f.followee_id
                """,
            ),
            "posts": _rows(
                conn,
                """
                SELECT p.id, u.user_name AS author, p.content, p.image_links,
                       p.video_links, p.like_count
                FROM posts p
                JOIN users u ON u.id = p.user_id
                ORDER BY p.created_at DESC, p.id DESC
                LIMIT 12
                """,
            ),
            "likes": _rows(
                conn,
                """
                SELECT u.user_name AS liker, l.post_id, l.created_at
                FROM likes l
                JOIN users u ON u.id = l.user_id
                ORDER BY l.created_at DESC
                LIMIT 12
                """,
            ),
            "comments": _rows(
                conn,
                """
                SELECT c.id, u.user_name AS author, c.post_id, c.content
                FROM comments c
                JOIN users u ON u.id = c.user_id
                ORDER BY c.created_at DESC, c.id DESC
                LIMIT 12
                """,
            ),
            "inbox": _rows(
                conn,
                """
                SELECT reader.user_name AS reader, i.post_id, author.user_name AS author
                FROM inbox i
                JOIN users reader ON reader.id = i.user_id
                JOIN users author ON author.id = i.author_id
                ORDER BY i.created_at DESC, i.post_id DESC
                LIMIT 12
                """,
            ),
        }
        links = conn.execute(
            """
            SELECT DISTINCT link FROM (
              SELECT unnest(image_links || video_links) AS link FROM posts
              UNION ALL
              SELECT unnest(image_links || video_links) AS link FROM comments
            ) files
            WHERE link IS NOT NULL AND link <> ''
            ORDER BY link
            """
        ).fetchall()
    redis_rows = []
    for key in sorted(redis_client.keys("like_count:*") + redis_client.keys("recent:*")):
        redis_rows.append({"key": key, "value": redis_client.get(key)})
    return {
        "postgres": {"counts": counts, "tables": tables},
        "redis": redis_rows,
        "s3": [row["link"] for row in links],
    }


@app.get("/v1/users")
def list_users() -> dict[str, Any]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, user_name, famous FROM users ORDER BY id"
        ).fetchall()
    return {"users": rows, "service": "Follow service", "store": "Postgres users"}


@app.post("/v1/posts")
def create_post(body: PostIn, x_user_id: int | None = Header(default=None)) -> dict[str, Any]:
    user_id = require_user(x_user_id)
    content = body.content.strip()
    if not content and not body.image_links and not body.video_links:
        raise HTTPException(status_code=422, detail="A post needs text or a media link.")
    with connect() as conn:
        author = conn.execute(
            "SELECT user_name, famous FROM users WHERE id = %s", (user_id,)
        ).fetchone()
        row = conn.execute(
            """
            INSERT INTO posts (user_id, content, image_links, video_links)
            VALUES (%s, %s, %s, %s)
            RETURNING id, user_id, content, image_links, video_links, like_count, created_at
            """,
            (user_id, content, body.image_links, body.video_links),
        ).fetchone()
        followers = conn.execute(
            "SELECT follower_id FROM follows WHERE followee_id = %s", (user_id,)
        ).fetchall()
        inbox_ids = [item["follower_id"] for item in followers]
        inbox_ids.append(user_id)
        conn.execute(
            """
            INSERT INTO inbox (user_id, post_id, author_id, created_at)
            SELECT reader, %s, %s, %s
            FROM unnest(%s::bigint[]) AS reader
            ON CONFLICT DO NOTHING
            """,
            (row["id"], user_id, row["created_at"], inbox_ids),
        )
        conn.commit()
    row["user_name"] = author["user_name"]
    row["famous"] = author["famous"]
    trace = [
        {"service": "Post service", "store": "Postgres posts", "detail": f"Inserted post {row['id']}."},
        {"service": "Post service", "store": "S3", "detail": "The row stores links. The bytes stay in object storage."},
        {
            "service": "Worker",
            "store": "Postgres inbox",
            "detail": f"Copied post {row['id']} into {len(inbox_ids)} inboxes so the write path can be compared.",
        },
    ]
    if author["famous"]:
        trace.append(
            {
                "service": "Worker",
                "store": "Postgres inbox",
                "detail": "Bea stands in for a famous account. Hybrid reads her posts from the posts table.",
            }
        )
    return {"post": post_public(row, False), "trace": trace}


@app.post("/v1/users/{followee_id}/follow")
def follow(followee_id: int, x_user_id: int | None = Header(default=None)) -> dict[str, Any]:
    user_id = require_user(x_user_id)
    require_user(followee_id)
    if user_id == followee_id:
        raise HTTPException(status_code=422, detail="You cannot follow yourself.")
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO follows (follower_id, followee_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (user_id, followee_id),
        )
        conn.commit()
    return {
        "follower_id": user_id,
        "followee_id": followee_id,
        "trace": [
            {
                "service": "Follow service",
                "store": "Postgres follows",
                "detail": f"Stored the pair ({user_id}, {followee_id}).",
            }
        ],
    }


@app.get("/v1/home")
def home(
    mode: str = "read",
    limit: int = 20,
    cursor: str | None = None,
    x_user_id: int | None = Header(default=None),
) -> dict[str, Any]:
    user_id = require_user(x_user_id)
    if mode not in {"read", "write", "hybrid"}:
        raise HTTPException(status_code=422, detail="mode must be read, write, or hybrid.")
    limit = max(1, min(limit, 50))
    parsed = parse_cursor(cursor)
    with connect() as conn:
        followees = conn.execute(
            """
            SELECT u.id, u.user_name, u.famous
            FROM follows f
            JOIN users u ON u.id = f.followee_id
            WHERE f.follower_id = %s
            ORDER BY u.id
            """,
            (user_id,),
        ).fetchall()
        me = conn.execute(
            "SELECT id, user_name, famous FROM users WHERE id = %s", (user_id,)
        ).fetchone()
        authors = followees + [me]
        author_ids = [item["id"] for item in authors]
        famous_ids = [item["id"] for item in authors if item["famous"]]
        if mode == "read":
            rows, trace = _home_from_posts(conn, user_id, author_ids, parsed, limit)
        elif mode == "write":
            rows = _home_from_inbox(conn, user_id, parsed, limit, famous_ids, skip_famous=False)
            trace = [
                {
                    "service": "Feed service",
                    "store": "Postgres inbox",
                    "detail": "Loaded one prebuilt list for this reader. The worker filled it at publish time.",
                },
                {
                    "service": "Post service",
                    "store": "Postgres posts",
                    "detail": "Loaded the post text for those inbox ids.",
                },
            ]
        else:
            rows, trace = _home_hybrid(conn, user_id, famous_ids, parsed, limit)
    liked = _liked_set(user_id, [row["id"] for row in rows])
    items = [post_public(row, row["id"] in liked) for row in rows]
    next_cursor = None
    if len(rows) == limit:
        last = rows[-1]
        next_cursor = make_cursor(last["created_at"], last["id"])
    return {"mode": mode, "items": items, "next_cursor": next_cursor, "trace": trace}


def _home_from_posts(conn, user_id: int, author_ids: list[int], parsed, limit: int):
    params: list[Any] = [author_ids]
    cursor_sql = ""
    if parsed:
        cursor_sql = "AND (p.created_at, p.id) < (%s, %s)"
        params.extend(parsed)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT p.id, p.user_id, u.user_name, u.famous, p.content, p.image_links,
               p.video_links, p.like_count, p.created_at, 'posts' AS source
        FROM posts p
        JOIN users u ON u.id = p.user_id
        WHERE p.user_id = ANY(%s)
        {cursor_sql}
        ORDER BY p.created_at DESC, p.id DESC
        LIMIT %s
        """,
        params,
    ).fetchall()
    trace = [
        {
            "service": "Feed service",
            "store": "Follow service, then Postgres follows",
            "detail": f"Loaded {len(author_ids) - 1} followee ids and added user {user_id}.",
        },
        {
            "service": "Post service",
            "store": "Postgres posts",
            "detail": "Loaded posts for those authors, newest first.",
        },
    ]
    return rows, trace


def _home_from_inbox(conn, user_id: int, parsed, limit: int, famous_ids: list[int], skip_famous: bool):
    params: list[Any] = [user_id]
    extra = ""
    if skip_famous and famous_ids:
        extra = "AND i.author_id <> ALL(%s)"
        params.append(famous_ids)
    if parsed:
        extra += " AND (i.created_at, i.post_id) < (%s, %s)"
        params.extend(parsed)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT p.id, p.user_id, u.user_name, u.famous, p.content, p.image_links,
               p.video_links, p.like_count, p.created_at, 'inbox' AS source
        FROM inbox i
        JOIN posts p ON p.id = i.post_id
        JOIN users u ON u.id = p.user_id
        WHERE i.user_id = %s
        {extra}
        ORDER BY i.created_at DESC, i.post_id DESC
        LIMIT %s
        """,
        params,
    ).fetchall()
    return rows


def _home_hybrid(conn, user_id: int, famous_ids: list[int], parsed, limit: int):
    inbox_rows = _home_from_inbox(conn, user_id, parsed, limit, famous_ids, skip_famous=True)
    famous_rows, _ = _home_from_posts(conn, user_id, famous_ids or [-1], parsed, limit)
    for row in famous_rows:
        row["source"] = "posts"
    merged = inbox_rows + famous_rows
    merged.sort(key=lambda row: (row["created_at"], row["id"]), reverse=True)
    # Drop duplicates if a famous post was also copied into the inbox and the filter missed it.
    seen: set[int] = set()
    unique = []
    for row in merged:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        unique.append(row)
    page = unique[:limit]
    trace = [
        {
            "service": "Feed service",
            "store": "Postgres inbox",
            "detail": "Loaded inbox rows for normal accounts.",
        },
        {
            "service": "Feed service",
            "store": "Redis recent, then Postgres posts",
            "detail": "Loaded famous accounts from the posts table. Bea is the famous account in this lab.",
        },
        {
            "service": "Post service",
            "store": "Postgres posts",
            "detail": "Loaded the post text for the merged ids.",
        },
    ]
    if famous_ids:
        redis_client.set(f"recent:{famous_ids[0]}", ",".join(str(row["id"]) for row in famous_rows))
    return page, trace


def _liked_set(user_id: int, post_ids: list[int]) -> set[int]:
    if not post_ids:
        return set()
    with connect() as conn:
        rows = conn.execute(
            "SELECT post_id FROM likes WHERE user_id = %s AND post_id = ANY(%s)",
            (user_id, post_ids),
        ).fetchall()
    return {row["post_id"] for row in rows}


@app.post("/v1/posts/{post_id}/likes")
def like(post_id: int, x_user_id: int | None = Header(default=None)) -> dict[str, Any]:
    user_id = require_user(x_user_id)
    with connect() as conn:
        post = conn.execute("SELECT id, like_count FROM posts WHERE id = %s", (post_id,)).fetchone()
        if post is None:
            raise HTTPException(status_code=404, detail="Unknown post.")
        inserted = conn.execute(
            """
            INSERT INTO likes (user_id, post_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            RETURNING post_id
            """,
            (user_id, post_id),
        ).fetchone()
        if inserted:
            conn.execute(
                "UPDATE posts SET like_count = like_count + 1 WHERE id = %s",
                (post_id,),
            )
            detail = "Inserted the pair and added one to the count."
        else:
            detail = "The pair already exists. The count stayed the same."
        conn.commit()
    with connect() as conn:
        count_row = conn.execute(
            "SELECT like_count FROM posts WHERE id = %s", (post_id,)
        ).fetchone()
    redis_client.set(f"like_count:{post_id}", count_row["like_count"])
    return {
        "post_id": post_id,
        "like_count": count_row["like_count"],
        "redis_like_count": int(redis_client.get(f"like_count:{post_id}") or count_row["like_count"]),
        "created": bool(inserted),
        "trace": [
            {"service": "Like service", "store": "Postgres likes", "detail": detail},
            {
                "service": "Like service",
                "store": "Postgres posts.like_count and Redis like_count",
                "detail": "The card can read either number. They match after this call.",
            },
        ],
    }


@app.post("/v1/posts/{post_id}/comments")
def create_comment(
    post_id: int, body: CommentIn, x_user_id: int | None = Header(default=None)
) -> dict[str, Any]:
    user_id = require_user(x_user_id)
    content = body.content.strip()
    if not content and not body.image_links and not body.video_links:
        raise HTTPException(status_code=422, detail="A comment needs text or a media link.")
    with connect() as conn:
        post = conn.execute("SELECT id FROM posts WHERE id = %s", (post_id,)).fetchone()
        if post is None:
            raise HTTPException(status_code=404, detail="Unknown post.")
        row = conn.execute(
            """
            INSERT INTO comments (post_id, user_id, content, image_links, video_links)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, post_id, user_id, content, image_links, video_links, created_at
            """,
            (post_id, user_id, content, body.image_links, body.video_links),
        ).fetchone()
        author = conn.execute("SELECT user_name FROM users WHERE id = %s", (user_id,)).fetchone()
        conn.commit()
    return {
        "comment": {
            "id": row["id"],
            "post_id": row["post_id"],
            "user_id": row["user_id"],
            "user_name": author["user_name"],
            "content": row["content"],
            "image_links": list(row["image_links"] or []),
            "video_links": list(row["video_links"] or []),
            "created_at": row["created_at"].isoformat(),
        },
        "trace": [
            {
                "service": "Comment service",
                "store": "Postgres comments",
                "detail": "Inserted one comment under the post. The home feed does not copy it.",
            }
        ],
    }


@app.get("/v1/posts/{post_id}/comments")
def list_comments(post_id: int, limit: int = 20, cursor: str | None = None) -> dict[str, Any]:
    limit = max(1, min(limit, 50))
    parsed = parse_cursor(cursor)
    params: list[Any] = [post_id]
    cursor_sql = ""
    if parsed:
        cursor_sql = "AND (c.created_at, c.id) < (%s, %s)"
        params.extend(parsed)
    params.append(limit)
    with connect() as conn:
        post = conn.execute("SELECT id FROM posts WHERE id = %s", (post_id,)).fetchone()
        if post is None:
            raise HTTPException(status_code=404, detail="Unknown post.")
        rows = conn.execute(
            f"""
            SELECT c.id, c.post_id, c.user_id, u.user_name, c.content, c.image_links,
                   c.video_links, c.created_at
            FROM comments c
            JOIN users u ON u.id = c.user_id
            WHERE c.post_id = %s
            {cursor_sql}
            ORDER BY c.created_at DESC, c.id DESC
            LIMIT %s
            """,
            params,
        ).fetchall()
    items = [
        {
            "id": row["id"],
            "post_id": row["post_id"],
            "user_id": row["user_id"],
            "user_name": row["user_name"],
            "content": row["content"],
            "image_links": list(row["image_links"] or []),
            "video_links": list(row["video_links"] or []),
            "created_at": row["created_at"].isoformat(),
        }
        for row in rows
    ]
    next_cursor = None
    if len(rows) == limit:
        last = rows[-1]
        next_cursor = make_cursor(last["created_at"], last["id"])
    return {
        "items": items,
        "next_cursor": next_cursor,
        "trace": [
            {
                "service": "Comment service",
                "store": "Postgres comments",
                "detail": "Returned one page older than the cursor.",
            }
        ],
    }
