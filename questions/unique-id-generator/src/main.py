"""Unique-ID lab: counter, tickets, UUID v4, and a 64-bit generator."""

from __future__ import annotations

import os

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from psycopg.rows import tuple_row

from src.ids import (
    BLOCK,
    WORKERS,
    GeneratorSet,
    counter_steps,
    new_uuid,
    situation_clock,
    situation_lease,
    situation_overflow,
    situation_postgres_down,
    situation_server_dies,
)

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:app@postgres:5432/app")
STATIC = os.path.join(os.path.dirname(__file__), "static")
KINDS = ("counter", "ticket", "uuid", "snowflake")

app = FastAPI(title="Unique ID generator")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
gens = GeneratorSet()


def connect() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL, row_factory=tuple_row)


def init_db() -> None:
    with connect() as conn:
        conn.execute("CREATE SEQUENCE IF NOT EXISTS id_seq")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ticket_state (
              id integer PRIMARY KEY,
              next_start bigint NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO ticket_state (id, next_start) VALUES (1, 1) ON CONFLICT (id) DO NOTHING"
        )
        conn.commit()
    gens.reset_memory()


def reset_db() -> None:
    with connect() as conn:
        conn.execute("ALTER SEQUENCE id_seq RESTART WITH 1")
        conn.execute("UPDATE ticket_state SET next_start = 1 WHERE id = 1")
        conn.commit()
    gens.reset_memory()


def next_counter() -> int:
    with connect() as conn:
        row = conn.execute("SELECT nextval('id_seq')").fetchone()
        conn.commit()
    return int(row[0])


def allocate_block() -> tuple[int, int]:
    with connect() as conn:
        with conn.transaction():
            row = conn.execute("SELECT next_start FROM ticket_state WHERE id = 1 FOR UPDATE").fetchone()
            start = int(row[0])
            end = start + BLOCK - 1
            conn.execute("UPDATE ticket_state SET next_start = %s WHERE id = 1", (end + 1,))
    return start, end


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/healthz")
def healthz() -> dict:
    with connect() as conn:
        conn.execute("SELECT 1")
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.post("/api/reset")
def reset() -> dict:
    reset_db()
    return {"ok": True}


@app.post("/api/generate")
def generate(kind: str, count: int = 3) -> dict:
    if kind not in KINDS:
        raise HTTPException(status_code=400, detail="unknown generator")
    if count < 1 or count > 20:
        raise HTTPException(status_code=400, detail="count must be 1 to 20")
    gens.ensure()
    servers = []
    for name in WORKERS:
        ids = []
        for _ in range(count):
            ids.append(one(kind, name))
        servers.append({"name": name, "ids": ids})
    return {"kind": kind, "block_size": BLOCK, "servers": servers}


SITUATIONS = {
    "clock-back": situation_clock,
    "lease": situation_lease,
    "overflow": situation_overflow,
    "server-dies": situation_server_dies,
    "postgres-down": situation_postgres_down,
}


@app.post("/api/situations/{name}")
def situation(name: str) -> dict:
    builder = SITUATIONS.get(name)
    if builder is None:
        raise HTTPException(status_code=400, detail="unknown situation")
    return builder()


def one(kind: str, server: str) -> dict:
    if kind == "counter":
        value = next_counter()
        return {"value": str(value), "steps": counter_steps(server, value)}
    if kind == "ticket":
        with gens.lock:
            value, steps = gens.tickets[server].take(server, allocate_block)
        return {"value": str(value), "steps": steps}
    if kind == "uuid":
        value, steps, fields = new_uuid(server)
        return {"value": value, "steps": steps, "fields": fields}
    with gens.lock:
        value, steps, fields = gens.snow[server].take(server)
    return {"value": str(value), "steps": steps, "fields": fields}
