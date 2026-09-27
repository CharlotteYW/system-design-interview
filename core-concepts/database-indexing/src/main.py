"""Postgres EXPLAIN lab for a composite B-tree on (user_id, created_at)."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:5432/app")
INDEX_NAME = "events_user_id_created_at_idx"
STATIC = Path(__file__).resolve().parent / "static"

QUERIES = {
    "user": "SELECT * FROM events WHERE user_id = 42",
    "both": "SELECT * FROM events WHERE user_id = 42 AND created_at >= DATE '2024-06-01'",
    "date": "SELECT * FROM events WHERE created_at >= DATE '2024-06-01' AND created_at < DATE '2024-06-02'",
    "cover": "SELECT user_id, created_at FROM events WHERE user_id = 42",
    "body": "SELECT body FROM events WHERE user_id = 42",
}

app = FastAPI(title="Database indexing")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def db():
    return psycopg.connect(DATABASE_URL)


def vacuum_events() -> None:
    """Index Only Scan needs a visibility map. VACUUM cannot run inside a transaction."""
    conn = psycopg.connect(DATABASE_URL, autocommit=True)
    try:
        conn.execute("VACUUM ANALYZE events")
    finally:
        conn.close()


@app.on_event("startup")
def startup() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id BIGINT PRIMARY KEY,
                user_id INT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                body TEXT NOT NULL
            )
            """
        )
        count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        if count == 0:
            conn.execute(
                """
                INSERT INTO events (id, user_id, created_at, body)
                SELECT g,
                       1 + (g % 1000),
                       TIMESTAMP '2024-01-01' + ((g % 365) || ' days')::interval,
                       'row-' || g
                FROM generate_series(1, 100000) g
                """
            )
        conn.execute("ANALYZE events")
        conn.commit()
    vacuum_events()


def index_exists(conn) -> bool:
    row = conn.execute(
        "SELECT 1 FROM pg_indexes WHERE indexname = %s",
        (INDEX_NAME,),
    ).fetchone()
    return row is not None


@app.get("/healthz")
def healthz() -> dict:
    with db() as conn:
        conn.execute("SELECT 1")
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/status")
def status() -> dict:
    with db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        present = index_exists(conn)
    return {"rows": count, "composite_index": present, "index_name": INDEX_NAME}


@app.post("/api/index")
def create_index() -> dict:
    with db() as conn:
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS {INDEX_NAME} ON events (user_id, created_at)"
        )
        conn.execute("ANALYZE events")
        conn.commit()
    vacuum_events()
    return {"composite_index": True}


@app.delete("/api/index")
def drop_index() -> dict:
    with db() as conn:
        conn.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
        conn.execute("ANALYZE events")
        conn.commit()
    return {"composite_index": False}


@app.get("/api/explain/{kind}")
def explain(kind: str) -> dict:
    sql = QUERIES.get(kind)
    if sql is None:
        raise HTTPException(status_code=404, detail="unknown query")
    with db() as conn:
        present = index_exists(conn)
        lines = [row[0] for row in conn.execute(f"EXPLAIN {sql}").fetchall()]
    plan = "\n".join(lines)
    uses_index = "Index" in plan and "Seq Scan" not in plan.split("\n")[0]
    return {
        "kind": kind,
        "sql": sql,
        "composite_index": present,
        "plan": plan,
        "leading_node_uses_index": uses_index,
    }
