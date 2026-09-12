from __future__ import annotations

import hashlib
import os
import threading
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import psycopg
import redis
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from psycopg.errors import OperationalError, UniqueViolation
from pydantic import BaseModel, Field

CODE_LENGTH = 7
MAX_SALT = 32
BASE62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
RESERVED = {"", "api", "healthz", "static", "favicon.ico"}
L1_MAX = 1024
CACHE_TTL_SECONDS = 3600
STATIC_DIR = Path(__file__).resolve().parent / "static"

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:app@postgres:5432/app")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

_l1_lock = threading.Lock()
_l1: OrderedDict[str, str] = OrderedDict()
_redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def code_for(url: str, salt: int = 0) -> str:
    digest = hashlib.sha256(f"{salt}:{url}".encode()).digest()
    n = int.from_bytes(digest[:16], "big")
    chars: list[str] = []
    for _ in range(CODE_LENGTH):
        chars.append(BASE62[n % 62])
        n //= 62
    return "".join(chars)


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
                url TEXT NOT NULL UNIQUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        conn.commit()


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
    try:
        with connect() as conn:
            existing = conn.execute(
                "SELECT code FROM links WHERE url = %s", (url,)
            ).fetchone()
            if existing:
                code = existing[0]
            else:
                code = None
                for salt in range(MAX_SALT):
                    candidate = code_for(url, salt)
                    if candidate.lower() in RESERVED:
                        continue
                    try:
                        with conn.transaction():
                            conn.execute(
                                "INSERT INTO links (code, url) VALUES (%s, %s)",
                                (candidate, url),
                            )
                        code = candidate
                        break
                    except UniqueViolation:
                        raced = conn.execute(
                            "SELECT code FROM links WHERE url = %s", (url,)
                        ).fetchone()
                        if raced:
                            code = raced[0]
                            break
                        continue
                if code is None:
                    raise HTTPException(status_code=500, detail="could not allocate a short code")
            conn.commit()
    except OperationalError as exc:
        raise HTTPException(status_code=503, detail="postgres unavailable") from exc
    cache_set(code, url)
    return ShortenOut(code=code, short_url=f"{PUBLIC_BASE_URL}/{code}")


@app.get("/{code}")
def redirect(code: str):
    if code in RESERVED or len(code) > 16:
        raise HTTPException(status_code=404, detail="unknown short code")
    url = cache_get(code)
    if url is None:
        try:
            with connect() as conn:
                row = conn.execute(
                    "SELECT url FROM links WHERE code = %s", (code,)
                ).fetchone()
        except OperationalError as exc:
            raise HTTPException(status_code=503, detail="postgres unavailable") from exc
        if row is None:
            raise HTTPException(status_code=404, detail="unknown short code")
        url = row[0]
        cache_set(code, url)
    return RedirectResponse(url=url, status_code=302)
