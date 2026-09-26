from __future__ import annotations

import os
import threading
from collections import OrderedDict
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TypeVar

import psycopg
import redis
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from psycopg.errors import OperationalError
from pydantic import BaseModel, Field

L1_MAX = 256
CACHE_TTL_SECONDS = 60
STATIC_DIR = Path(__file__).resolve().parent / "static"
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:app@postgres:5432/app")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

_l1_lock = threading.Lock()
_l1: OrderedDict[str, str] = OrderedDict()
_redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
_stats_lock = threading.Lock()
_db_loads = 0
T = TypeVar("T")


class Singleflight:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._inflight: dict[str, tuple[threading.Event, dict[str, object]]] = {}

    def do(self, key: str, fn: Callable[[], T]) -> T:
        with self._lock:
            existing = self._inflight.get(key)
            if existing is None:
                event = threading.Event()
                box: dict[str, object] = {}
                self._inflight[key] = (event, box)
                leader = True
            else:
                event, box = existing
                leader = False
        if not leader:
            event.wait(timeout=10)
            exc = box.get("exc")
            if isinstance(exc, BaseException):
                raise exc
            return box["value"]  # type: ignore[return-value]
        try:
            value = fn()
            box["value"] = value
            return value
        except Exception as exc:
            box["exc"] = exc
            raise
        finally:
            event.set()
            with self._lock:
                self._inflight.pop(key, None)


_loads = Singleflight()


def connect():
    return psycopg.connect(DATABASE_URL)


def init_db() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY,
                body TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO items (id, body) VALUES (1, 'hello from postgres')
            ON CONFLICT (id) DO NOTHING
            """
        )
        conn.commit()


def bump_db_loads() -> None:
    global _db_loads
    with _stats_lock:
        _db_loads += 1


def load_from_db(item_id: int) -> str | None:
    try:
        with connect() as conn:
            row = conn.execute("SELECT body FROM items WHERE id = %s", (item_id,)).fetchone()
    except OperationalError as exc:
        raise HTTPException(status_code=503, detail="postgres unavailable") from exc
    bump_db_loads()
    if row is None:
        return None
    return row[0]


def cache_key(item_id: int) -> str:
    return f"item:{item_id}"


def l1_get(key: str) -> str | None:
    with _l1_lock:
        val = _l1.get(key)
        if val is not None:
            _l1.move_to_end(key)
        return val


def l1_set(key: str, val: str) -> None:
    with _l1_lock:
        if key in _l1:
            _l1.move_to_end(key)
        _l1[key] = val
        while len(_l1) > L1_MAX:
            _l1.popitem(last=False)


def l1_del(key: str) -> None:
    with _l1_lock:
        _l1.pop(key, None)


def cache_fill(key: str, val: str) -> None:
    l1_set(key, val)
    try:
        _redis.set(key, val, ex=CACHE_TTL_SECONDS)
    except redis.RedisError:
        pass


def cache_delete(key: str) -> None:
    l1_del(key)
    try:
        _redis.delete(key)
    except redis.RedisError:
        pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Caching lab", lifespan=lifespan)


class ItemOut(BaseModel):
    id: int
    body: str
    cache: str


class ItemIn(BaseModel):
    body: str = Field(min_length=1, max_length=2048)


def item_response(item: ItemOut, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=item.model_dump(),
        headers={"X-Cache": item.cache},
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    try:
        with connect() as conn:
            conn.execute("SELECT 1")
    except OperationalError as exc:
        raise HTTPException(status_code=503, detail="postgres unavailable") from exc
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/stats")
def stats() -> dict[str, int]:
    with _stats_lock:
        return {"db_loads": _db_loads}


@app.post("/api/flush-l1")
def flush_l1() -> dict[str, str]:
    with _l1_lock:
        _l1.clear()
    return {"status": "l1-flushed"}


@app.post("/api/flush-cache")
def flush_cache() -> dict[str, str]:
    with _l1_lock:
        _l1.clear()
    try:
        _redis.flushdb()
    except redis.RedisError:
        pass
    return {"status": "flushed"}


@app.get("/api/items/{item_id}")
def get_item(item_id: int) -> JSONResponse:
    """Cache-aside: L1 → Redis L2 → Postgres. CDN is not on this path."""
    if item_id < 1:
        raise HTTPException(status_code=422, detail="id must be positive")
    key = cache_key(item_id)
    hit = l1_get(key)
    if hit is not None:
        return item_response(ItemOut(id=item_id, body=hit, cache="L1"))
    try:
        cached = _redis.get(key)
    except redis.RedisError:
        cached = None
    if cached:
        l1_set(key, cached)
        return item_response(ItemOut(id=item_id, body=cached, cache="REDIS"))

    def load() -> str | None:
        found = load_from_db(item_id)
        if found is not None:
            cache_fill(key, found)
        return found

    body = _loads.do(key, load)
    if body is None:
        raise HTTPException(status_code=404, detail="unknown item")
    return item_response(ItemOut(id=item_id, body=body, cache="MISS"))


@app.put("/api/items/{item_id}")
def put_item(item_id: int, payload: ItemIn) -> JSONResponse:
    if item_id < 1:
        raise HTTPException(status_code=422, detail="id must be positive")
    try:
        with connect() as conn:
            row = conn.execute(
                """
                INSERT INTO items (id, body) VALUES (%s, %s)
                ON CONFLICT (id) DO UPDATE SET body = EXCLUDED.body
                RETURNING body
                """,
                (item_id, payload.body),
            ).fetchone()
            conn.commit()
    except OperationalError as exc:
        raise HTTPException(status_code=503, detail="postgres unavailable") from exc
    assert row is not None
    cache_delete(cache_key(item_id))
    return item_response(ItemOut(id=item_id, body=row[0], cache="WRITE"))
