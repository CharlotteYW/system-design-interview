from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TypeVar
from urllib.parse import urlparse

import psycopg
import redis
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from psycopg.errors import OperationalError, UniqueViolation
from pydantic import BaseModel, Field

CODE_LENGTH = 11
MAX_INSERT_ATTEMPTS = 8
BASE62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
RESERVED = {"", "api", "healthz", "static", "favicon.ico"}
L1_MAX = 1024
CACHE_TTL_SECONDS = 3600
STATIC_DIR = Path(__file__).resolve().parent / "static"

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:app@postgres:5432/app")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
WORKER_ID = int(os.environ.get("WORKER_ID", "1"))

_l1_lock = threading.Lock()
_l1: OrderedDict[str, str] = OrderedDict()
_redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
T = TypeVar("T")


class Snowflake:
    """64-bit ids: timestamp | worker | sequence. Uniqueness still relies on UNIQUE(code)."""

    EPOCH_MS = 1_704_067_200_000  # 2024-01-01 UTC
    WORKER_BITS = 10
    SEQ_BITS = 12

    def __init__(self, worker_id: int) -> None:
        self.worker_id = worker_id & ((1 << self.WORKER_BITS) - 1)
        self._lock = threading.Lock()
        self._seq = 0
        self._last_ms = -1

    def next_id(self) -> int:
        with self._lock:
            now = _now_ms()
            if now < self._last_ms:
                time.sleep(min((self._last_ms - now) / 1000.0, 0.01))
                now = _now_ms()
                if now < self._last_ms:
                    now = self._last_ms
            if now == self._last_ms:
                self._seq = (self._seq + 1) & ((1 << self.SEQ_BITS) - 1)
                if self._seq == 0:
                    now = _wait_until_ms(self._last_ms + 1)
            else:
                self._seq = 0
            self._last_ms = now
            ts = max(0, now - self.EPOCH_MS)
            return (ts << (self.WORKER_BITS + self.SEQ_BITS)) | (self.worker_id << self.SEQ_BITS) | self._seq


class Singleflight:
    """One loader per key; concurrent callers wait for that result (thundering-herd guard)."""

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


_snowflake = Snowflake(WORKER_ID)
_redirect_loads = Singleflight()


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _wait_until_ms(target: int) -> int:
    now = _now_ms()
    while now < target:
        time.sleep(0.001)
        now = _now_ms()
    return now


def to_base62(n: int, width: int = CODE_LENGTH) -> str:
    chars: list[str] = []
    while n:
        chars.append(BASE62[n % 62])
        n //= 62
    while len(chars) < width:
        chars.append(BASE62[0])
    return "".join(reversed(chars))


def mint_code() -> str:
    return to_base62(_snowflake.next_id())


def validate_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=422, detail="url must be an absolute http(s) URL")
    if len(url) > 2048:
        raise HTTPException(status_code=422, detail="url is too long")
    return url.strip()


def l1_get(code: str) -> str | None:
    with _l1_lock:
        url = _l1.get(code)
        if url is not None:
            _l1.move_to_end(code)
        return url


def l1_set(code: str, url: str) -> None:
    with _l1_lock:
        if code in _l1:
            _l1.move_to_end(code)
        _l1[code] = url
        while len(_l1) > L1_MAX:
            _l1.popitem(last=False)


def cache_get(code: str) -> str | None:
    hit = l1_get(code)
    if hit is not None:
        return hit
    try:
        cached = _redis.get(code)
    except redis.RedisError:
        cached = None
    if cached:
        l1_set(code, cached)
        return cached
    return None


def cache_set(code: str, url: str) -> None:
    l1_set(code, url)
    try:
        _redis.set(code, url, ex=CACHE_TTL_SECONDS)
    except redis.RedisError:
        pass


def connect():
    return psycopg.connect(DATABASE_URL)


def init_db() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS links (
                code VARCHAR(16) PRIMARY KEY,
                url TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                expires_at TIMESTAMPTZ NULL
            )
            """
        )
        conn.execute("ALTER TABLE links DROP CONSTRAINT IF EXISTS links_url_key")
        conn.execute(
            "ALTER TABLE links ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
        )
        conn.execute("ALTER TABLE links ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ NULL")
        conn.commit()


def load_url_from_db(code: str) -> str | None:
    try:
        with connect() as conn:
            row = conn.execute("SELECT url FROM links WHERE code = %s", (code,)).fetchone()
    except OperationalError as exc:
        raise HTTPException(status_code=503, detail="postgres unavailable") from exc
    if row is None:
        return None
    return row[0]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="URL shortener", lifespan=lifespan)


class ShortenIn(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


class ShortenOut(BaseModel):
    code: str
    short_url: str


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


@app.post("/api/shorten", response_model=ShortenOut)
def shorten(body: ShortenIn) -> ShortenOut:
    url = validate_url(body.url)
    code: str | None = None
    try:
        with connect() as conn:
            for _ in range(MAX_INSERT_ATTEMPTS):
                candidate = mint_code()
                if candidate.lower() in RESERVED:
                    continue
                try:
                    with conn.transaction():
                        conn.execute(
                            """
                            INSERT INTO links (code, url, created_at, updated_at)
                            VALUES (%s, %s, NOW(), NOW())
                            """,
                            (candidate, url),
                        )
                    code = candidate
                    break
                except UniqueViolation:
                    continue
            conn.commit()
    except OperationalError as exc:
        raise HTTPException(status_code=503, detail="postgres unavailable") from exc
    if code is None:
        raise HTTPException(status_code=500, detail="could not allocate a short code")
    cache_set(code, url)
    return ShortenOut(code=code, short_url=f"{PUBLIC_BASE_URL}/{code}")


@app.get("/{code}")
def redirect(code: str):
    if code in RESERVED or len(code) > 16:
        raise HTTPException(status_code=404, detail="unknown short code")
    url = cache_get(code)
    if url is None:

        def load() -> str | None:
            found = load_url_from_db(code)
            if found is not None:
                cache_set(code, found)
            return found

        url = _redirect_loads.do(code, load)
        if url is None:
            raise HTTPException(status_code=404, detail="unknown short code")
    return RedirectResponse(url=url, status_code=302)
