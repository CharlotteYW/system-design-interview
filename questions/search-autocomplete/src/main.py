"""Autocomplete lab. Yesterday's frequency is the batch layer. A fold adds today's counts."""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .index import SuggestionIndex

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:app@postgres:5432/app")
FOLD_SECONDS = int(os.environ.get("FOLD_SECONDS", "20"))
DESIGN_FOLD_SECONDS = 120
STATIC = Path(__file__).parent / "static"

# Yesterday's counts. Shared prefixes (ki, ca, do) make the trie and the map visible.
SEED: list[tuple[str, int]] = [
    ("karate", 9000), ("kangaroo", 8000), ("kraft", 7000),
    ("kitchen", 5000), ("kim", 4000), ("kitten", 3000), ("kite", 2500), ("kick", 2000),
    ("king", 1500), ("kiosk", 100), ("kimchi", 800), ("kimberly", 600),
    ("kitchenaid", 400), ("kitkat", 350),
    ("cat", 4200), ("catch", 3100), ("category", 2800), ("catalog", 1900), ("cattle", 900),
    ("car", 6100), ("card", 4400), ("career", 3300), ("carpet", 1700), ("cartoon", 1200),
    ("dog", 5500), ("door", 3600), ("double", 2100), ("doctor", 4800), ("document", 2600),
    ("apple", 5300), ("application", 3900), ("apartment", 2200), ("apricot", 700),
    ("banana", 3400), ("bank", 4600), ("band", 1800), ("banner", 900),
    ("sun", 3800), ("sunday", 2400), ("sushi", 1600), ("super", 2900), ("supermarket", 1100),
    ("red", 2700), ("read", 2300), ("recipe", 3200), ("record", 1400), ("redwood", 500),
    ("map", 2000), ("maple", 1300), ("market", 3600), ("mars", 800), ("marshmallow", 400),
    ("new", 4700), ("news", 4100), ("newspaper", 900), ("newt", 200),
    ("pizza", 3700), ("piano", 1500), ("picnic", 600), ("picture", 2800), ("pilot", 1100),
    ("train", 2600), ("travel", 3400), ("tree", 2200), ("treasure", 700), ("truck", 1800),
    ("water", 4300), ("watch", 2500), ("waterfall", 600), ("wave", 900),
    ("book", 3900), ("boot", 1200), ("booth", 400), ("border", 800), ("bottle", 1600),
    ("phone", 4500), ("photo", 3200), ("phrase", 500), ("physics", 700),
    ("green", 2100), ("grey", 600), ("great", 2800), ("grape", 900), ("graph", 1100),
    ("home", 5200), ("horse", 1400), ("hotel", 2600), ("hour", 800), ("house", 3100),
    ("ice", 1800), ("ice cream", 2400), ("icon", 700), ("idea", 1600),
    ("job", 2200), ("join", 900), ("joke", 1300), ("journal", 600),
    ("light", 2700), ("lion", 800), ("list", 1900), ("listen", 1100), ("little", 700),
    ("music", 3600), ("museum", 900), ("mushroom", 500), ("must", 400),
    ("orange", 1700), ("orbit", 300), ("order", 2100), ("organ", 400),
    ("park", 2900), ("party", 1800), ("pasta", 1200), ("path", 600), ("patient", 500),
    ("queen", 400), ("question", 1500), ("quick", 800), ("quiet", 300),
    ("rain", 1600), ("rainbow", 700), ("raise", 400), ("random", 500),
    ("school", 3300), ("science", 1400), ("score", 800), ("screen", 2100),
    ("table", 1900), ("tablet", 600), ("taco", 1100), ("tail", 300), ("talent", 400),
    ("video", 2800), ("village", 500), ("vine", 300), ("violet", 400), ("visit", 900),
    ("window", 1300), ("wind", 1600), ("winter", 1100), ("wire", 300), ("wish", 700),
    ("yellow", 900), ("yoga", 1200), ("yogurt", 800), ("young", 500),
    ("zoo", 600), ("zone", 400), ("zoom", 1500),
]

app = FastAPI(title="Search autocomplete lab")
index_lock = threading.Lock()
serving = SuggestionIndex({})
snapshot = 1
last_fold = 0.0
next_fold = 0.0


def normalize(text: str) -> str:
    cleaned = "".join(ch.lower() if ch.isascii() and ch.isalpha() else " " if ch == " " else "" for ch in text)
    return " ".join(cleaned.split())


@contextmanager
def db():
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        yield conn


def rebuild() -> None:
    global serving
    with db() as conn:
        rows = conn.execute(
            "SELECT query, yesterday + folded_today FROM query_freq WHERE yesterday + folded_today > 0"
        ).fetchall()
    built = SuggestionIndex({query: count for query, count in rows})
    with index_lock:
        serving = built


def fold() -> dict:
    global last_fold, next_fold, snapshot
    with db() as conn:
        grouped = conn.execute(
            "SELECT query, count(*) FROM searches WHERE NOT folded GROUP BY query"
        ).fetchall()
        for query, count in grouped:
            conn.execute(
                """
                INSERT INTO query_freq (query, yesterday, folded_today)
                VALUES (%s, 0, %s)
                ON CONFLICT (query) DO UPDATE SET folded_today = query_freq.folded_today + EXCLUDED.folded_today
                """,
                (query, count),
            )
        conn.execute("UPDATE searches SET folded = true WHERE NOT folded")
    rebuild()
    last_fold = time.time()
    next_fold = last_fold + FOLD_SECONDS
    if grouped:
        snapshot += 1
    return {"foldedQueries": len(grouped), "snapshot": snapshot}


def daily_build() -> dict:
    """Move every search, folded or not, into yesterday. Clear the speed layer."""
    global snapshot
    with db() as conn:
        grouped = conn.execute("SELECT query, count(*) FROM searches GROUP BY query").fetchall()
        for query, count in grouped:
            conn.execute(
                """
                INSERT INTO query_freq (query, yesterday, folded_today)
                VALUES (%s, %s, 0)
                ON CONFLICT (query) DO UPDATE
                  SET yesterday = query_freq.yesterday + %s, folded_today = 0
                """,
                (query, count, count),
            )
        conn.execute("UPDATE query_freq SET folded_today = 0")
        conn.execute("DELETE FROM searches")
    rebuild()
    snapshot += 1
    return {"moved": len(grouped), "snapshot": snapshot}


def folder_loop() -> None:
    while True:
        time.sleep(FOLD_SECONDS)
        try:
            fold()
        except Exception:
            time.sleep(1)


def seed() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS query_freq (
              query text PRIMARY KEY,
              yesterday integer NOT NULL,
              folded_today integer NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS searches (
              id bigserial PRIMARY KEY,
              query text NOT NULL,
              searched_at timestamptz NOT NULL DEFAULT now(),
              folded boolean NOT NULL DEFAULT false
            )
            """
        )
        count = conn.execute("SELECT count(*) FROM query_freq").fetchone()[0]
        if count == 0:
            conn.cursor().executemany(
                "INSERT INTO query_freq (query, yesterday) VALUES (%s, %s)",
                SEED,
            )
    rebuild()


@app.on_event("startup")
def startup() -> None:
    global last_fold, next_fold
    for _ in range(60):
        try:
            seed()
            last_fold = time.time()
            next_fold = last_fold + FOLD_SECONDS
            threading.Thread(target=folder_loop, daemon=True).start()
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError("postgres never became ready")


async def folder() -> None:
    while True:
        await asyncio.sleep(FOLD_SECONDS)
        try:
            await asyncio.to_thread(fold)
        except Exception:
            await asyncio.sleep(1)


@app.get("/healthz")
def healthz() -> dict:
    with index_lock:
        prefixes = serving.prefix_count
    return {"ok": True, "prefixes": prefixes}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/v1/suggestions")
def suggestions(q: str = Query(""), limit: int = Query(5, ge=1, le=10)) -> dict:
    prefix = normalize(q)
    with index_lock:
        found = serving.lookup(prefix, limit)
        prefixes = serving.prefix_count
    return {
        "suggestions": found["suggestions"],
        "snapshot": snapshot,
        "prefix": prefix,
        "hashMap": found["hashMap"],
        "trie": found["trie"],
        "layoutsAgree": found["same"],
        "prefixCount": prefixes,
    }


class SearchIn(BaseModel):
    query: str
    count: int = Field(default=1, ge=1, le=20000)


@app.post("/v1/searches", status_code=202)
def record(body: SearchIn) -> dict:
    query = normalize(body.query)
    if not query:
        raise HTTPException(422, "query has no letters")
    with db() as conn:
        conn.execute(
            "INSERT INTO searches (query) SELECT %s FROM generate_series(1, %s)",
            (query, body.count),
        )
    return {"status": "recorded", "query": query, "count": body.count, "folded": False}


@app.post("/v1/lab/fold")
def fold_now() -> dict:
    return fold()


@app.post("/v1/lab/daily-build")
def build_now() -> dict:
    return daily_build()


@app.post("/v1/lab/reset")
def reset() -> dict:
    global snapshot
    with db() as conn:
        conn.execute("DELETE FROM searches")
        conn.execute("DELETE FROM query_freq")
        conn.cursor().executemany(
            "INSERT INTO query_freq (query, yesterday) VALUES (%s, %s)",
            SEED,
        )
    rebuild()
    snapshot += 1
    return {"ok": True, "snapshot": snapshot}


@app.get("/v1/lab/state")
def state(q: str = Query("")) -> dict:
    prefix = normalize(q)
    with db() as conn:
        pending = conn.execute(
            "SELECT query, count(*) FROM searches WHERE NOT folded GROUP BY query ORDER BY count(*) DESC LIMIT 12"
        ).fetchall()
        recent = conn.execute(
            "SELECT query, folded, searched_at FROM searches ORDER BY id DESC LIMIT 8"
        ).fetchall()
        totals = conn.execute(
            """
            SELECT
              (SELECT count(*) FROM query_freq),
              (SELECT count(*) FROM searches WHERE NOT folded),
              (SELECT coalesce(sum(folded_today), 0) FROM query_freq)
            """
        ).fetchone()
        rows = conn.execute(
            """
            SELECT query, yesterday, folded_today
            FROM query_freq
            WHERE query LIKE %s
            ORDER BY yesterday + folded_today DESC, query
            LIMIT 15
            """,
            (prefix + "%",),
        ).fetchall()
    with index_lock:
        found = serving.lookup(prefix, 10) if prefix or True else None
        prefix_count = serving.prefix_count
        sample = []
        for key in sorted(serving.hash_map, key=lambda item: (len(item), item)):
            if prefix and not key.startswith(prefix):
                continue
            if not key:
                continue
            top = serving.hash_map[key]
            sample.append({"prefix": key, "top": top[0]["text"] if top else "", "n": len(top)})
            if len(sample) >= 80:
                break
    return {
        "snapshot": snapshot,
        "foldSeconds": FOLD_SECONDS,
        "designFoldSeconds": DESIGN_FOLD_SECONDS,
        "lastFold": last_fold,
        "nextFold": next_fold,
        "prefixCount": prefix_count,
        "queryCount": totals[0],
        "pendingRows": totals[1],
        "foldedToday": totals[2],
        "pending": [{"query": query, "count": count} for query, count in pending],
        "recent": [
            {"query": query, "folded": folded, "at": at.isoformat()}
            for query, folded, at in recent
        ],
        "matching": [
            {"query": query, "yesterday": yesterday, "foldedToday": folded, "merged": yesterday + folded}
            for query, yesterday, folded in rows
        ],
        "prefixes": sample,
        "hashMap": found["hashMap"],
        "trie": found["trie"],
        "layoutsAgree": found["same"],
    }
