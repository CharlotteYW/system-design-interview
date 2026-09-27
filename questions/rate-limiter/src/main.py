"""Rate limiter lab: five algorithms, Redis counters, local fallback.

Interview ship choice is sliding_counter. The UI can switch algorithms.
Postgres stores allowed /api/work rows only. It is not the counter.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import psycopg
import redis
import yaml
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:5432/app")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
REPLICAS = max(1, int(os.environ.get("RATE_LIMIT_REPLICAS", "4")))
ALLOW_TIME_OVERRIDE = os.environ.get("ALLOW_TIME_OVERRIDE", "1") == "1"

ALGORITHMS = (
    "fixed",
    "sliding_counter",
    "sliding_log",
    "token_bucket",
    "leaky_bucket",
)
DEFAULT_ALGO = "sliding_counter"

STATIC = Path(__file__).resolve().parent / "static"
RULES_PATH = Path(__file__).resolve().parent / "rules.yaml"


@dataclass(frozen=True)
class Rule:
    limit: int
    window_seconds: int
    name: str


def load_rules(path: Path) -> dict[str, Rule]:
    raw = yaml.safe_load(path.read_text())
    routes = raw["routes"]
    return {
        key: Rule(int(item["limit"]), int(item["window_seconds"]), str(item["name"]))
        for key, item in routes.items()
    }


RULES: dict[str, Rule] = load_rules(RULES_PATH)

ALGO_HELP = {
    "fixed": "One counter per clock bucket. Cheap (one INCR). Allows about 2× at the bucket edge.",
    "sliding_counter": "Weights the previous bucket plus this one. Catches the edge burst. Small approximation error. Production default here.",
    "sliding_log": "Stores each allowed timestamp. Exact for the rolling window. Heavy at high QPS.",
    "token_bucket": "Starts full. Allows a burst of `limit`, then refills steadily.",
    "leaky_bucket": "Starts empty and leaks at a steady rate. A burst fills it; further calls wait until it leaks. Drops with 429 instead of queueing the HTTP call.",
}

app = FastAPI(title="Rate limiter")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

_redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
_local_counts: dict[tuple[str, str, int], int] = {}
_blocked_until: dict[str, float] = {}


def db():
    return psycopg.connect(DATABASE_URL)


@app.on_event("startup")
def startup() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS work_events (
                id BIGSERIAL PRIMARY KEY,
                client_id TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.commit()


def now_ms(request: Request) -> int:
    raw = request.headers.get("x-rate-now-ms")
    if raw and ALLOW_TIME_OVERRIDE:
        return int(raw)
    return int(time.time() * 1000)


def identity_of(request: Request) -> str:
    client = request.headers.get("x-client-id", "").strip()
    if client:
        return client
    if request.client:
        return request.client.host
    return "unknown"


def algorithm_of(request: Request) -> str:
    name = request.headers.get("x-rate-algorithm", DEFAULT_ALGO).strip()
    if name not in ALGORITHMS:
        return DEFAULT_ALGO
    return name


def emergency_limit(rule: Rule) -> int:
    return max(1, rule.limit // REPLICAS)


def _purge_local(now_s: int) -> None:
    dead = [key for key in _local_counts if key[2] + 120 < now_s]
    for key in dead:
        del _local_counts[key]


def local_fixed(identity: str, route: str, rule: Rule, now_ms_value: int) -> tuple[bool, int, int, int]:
    now_s = now_ms_value // 1000
    start = (now_s // rule.window_seconds) * rule.window_seconds
    _purge_local(now_s)
    key = (identity, route, start)
    count = _local_counts.get(key, 0) + 1
    _local_counts[key] = count
    cap = emergency_limit(rule)
    reset = start + rule.window_seconds
    return count <= cap, count, cap, reset


FIXED_LUA = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local n = redis.call('INCR', key)
if n == 1 then
  redis.call('EXPIRE', key, ttl)
end
if n > limit then
  return {0, n}
end
return {1, n}
"""

SLIDING_COUNTER_LUA = """
local prev_key = KEYS[1]
local cur_key = KEYS[2]
local limit = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local elapsed_ms = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])
local prev = tonumber(redis.call('GET', prev_key) or '0')
local cur = tonumber(redis.call('GET', cur_key) or '0')
local weight = (window_ms - elapsed_ms) / window_ms
local estimate = prev * weight + cur
if estimate >= limit then
  return {0, estimate, cur}
end
local n = redis.call('INCR', cur_key)
if n == 1 then
  redis.call('EXPIRE', cur_key, ttl)
end
return {1, prev * weight + n, n}
"""

SLIDING_LOG_LUA = """
local key = KEYS[1]
local window_ms = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local member = ARGV[4]
local ttl_ms = tonumber(ARGV[5])
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window_ms)
local count = redis.call('ZCARD', key)
if count >= limit then
  return {0, count}
end
redis.call('ZADD', key, now, member)
redis.call('PEXPIRE', key, ttl_ms)
return {1, count + 1}
"""

TOKEN_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_per_ms = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local ttl_ms = tonumber(ARGV[4])
local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then
  tokens = capacity
  ts = now
end
local delta = math.max(0, now - ts)
tokens = math.min(capacity, tokens + delta * refill_per_ms)
local allowed = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
end
redis.call('HSET', key, 'tokens', tokens, 'ts', now)
redis.call('PEXPIRE', key, ttl_ms)
return {allowed, tokens}
"""

LEAKY_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local leak_per_ms = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local ttl_ms = tonumber(ARGV[4])
local data = redis.call('HMGET', key, 'level', 'ts')
local level = tonumber(data[1])
local ts = tonumber(data[2])
if level == nil then
  level = 0
  ts = now
end
local leaked = math.max(0, now - ts) * leak_per_ms
level = math.max(0, level - leaked)
if level + 1 > capacity then
  redis.call('HSET', key, 'level', level, 'ts', now)
  redis.call('PEXPIRE', key, ttl_ms)
  return {0, level}
end
level = level + 1
redis.call('HSET', key, 'level', level, 'ts', now)
redis.call('PEXPIRE', key, ttl_ms)
return {1, level}
"""


def check_redis(algo: str, identity: str, route: str, rule: Rule, now: int) -> tuple[bool, float, int]:
    window_ms = rule.window_seconds * 1000
    start_ms = (now // window_ms) * window_ms
    elapsed = now - start_ms
    ttl_s = max(1, rule.window_seconds)
    base = f"rl:{algo}:{identity}:{rule.name}"
    if algo == "fixed":
        key = f"{base}:{start_ms}"
        allowed, count = _redis.eval(FIXED_LUA, 1, key, rule.limit, ttl_s)
        return bool(int(allowed)), float(count), rule.limit
    if algo == "sliding_counter":
        prev_key = f"{base}:{start_ms - window_ms}"
        cur_key = f"{base}:{start_ms}"
        allowed, estimate, _cur = _redis.eval(
            SLIDING_COUNTER_LUA,
            2,
            prev_key,
            cur_key,
            rule.limit,
            window_ms,
            elapsed,
            ttl_s * 2,
        )
        return bool(int(allowed)), float(estimate), rule.limit
    if algo == "sliding_log":
        allowed, count = _redis.eval(
            SLIDING_LOG_LUA,
            1,
            base,
            window_ms,
            rule.limit,
            now,
            str(uuid.uuid4()),
            window_ms,
        )
        return bool(int(allowed)), float(count), rule.limit
    if algo == "token_bucket":
        refill = rule.limit / window_ms
        allowed, tokens = _redis.eval(TOKEN_LUA, 1, base, rule.limit, refill, now, window_ms * 2)
        return bool(int(allowed)), float(rule.limit - float(tokens)), rule.limit
    leak = rule.limit / window_ms
    allowed, level = _redis.eval(LEAKY_LUA, 1, base, rule.limit, leak, now, window_ms * 2)
    return bool(int(allowed)), float(level), rule.limit


def rate_headers(limit: int, used: float, reset_s: int, algo: str, path: str) -> dict[str, str]:
    remaining = max(0, int(limit - used))
    return {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(reset_s),
        "X-Rate-Algorithm": algo,
        "X-Rate-Path": path,
    }


def decide(request: Request, route: str) -> tuple[bool, dict[str, str], str]:
    rule = RULES[route]
    identity = identity_of(request)
    algo = algorithm_of(request)
    now = now_ms(request)
    reset_s = ((now // 1000) // rule.window_seconds + 1) * rule.window_seconds
    block_key = f"{algo}:{identity}:{rule.name}"
    blocked = _blocked_until.get(block_key, 0)
    if blocked > now / 1000 and request.headers.get("x-force-local") != "1":
        headers = rate_headers(rule.limit, rule.limit, int(blocked), algo, "local-block")
        headers["Retry-After"] = str(max(1, int(blocked - now / 1000)))
        return False, headers, identity

    force_local = request.headers.get("x-force-local") == "1"
    if not force_local:
        try:
            allowed, used, limit = check_redis(algo, identity, route, rule, now)
            headers = rate_headers(limit, used, reset_s, algo, "redis")
            if not allowed:
                _blocked_until[block_key] = reset_s
                headers["Retry-After"] = str(max(1, reset_s - now // 1000))
                headers["X-Rate-Path"] = "redis"
            else:
                _blocked_until.pop(block_key, None)
            return allowed, headers, identity
        except redis.RedisError:
            pass

    allowed, count, cap, reset = local_fixed(identity, route, rule, now)
    headers = rate_headers(cap, count if not allowed else count, reset, "fixed", "local-emergency")
    headers["X-RateLimit-Limit"] = str(cap)
    if not allowed:
        headers["Retry-After"] = str(max(1, reset - now // 1000))
    return allowed, headers, identity


def deny(headers: dict[str, str]) -> JSONResponse:
    return JSONResponse(
        {"error": "rate_limited", "algorithm": headers.get("X-Rate-Algorithm")},
        status_code=429,
        headers=headers,
    )


@app.get("/healthz")
def healthz() -> JSONResponse:
    redis_ok = True
    try:
        _redis.ping()
    except redis.RedisError:
        redis_ok = False
    db_ok = True
    try:
        with db() as conn:
            conn.execute("SELECT 1")
    except psycopg.Error:
        db_ok = False
    return JSONResponse({"ok": True, "redis": redis_ok, "postgres": db_ok})


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/algorithms")
def algorithms() -> dict:
    return {
        "default": DEFAULT_ALGO,
        "rules_file": "src/rules.yaml",
        "rules_loaded": "once_at_process_start",
        "replicas_for_emergency_cap": REPLICAS,
        "algorithms": [{"id": name, "summary": ALGO_HELP[name]} for name in ALGORITHMS],
        "routes": {
            key: {"limit": rule.limit, "window_seconds": rule.window_seconds}
            for key, rule in RULES.items()
        },
    }


@app.get("/api/ping")
def ping(request: Request) -> JSONResponse:
    allowed, headers, identity = decide(request, "GET /api/ping")
    if not allowed:
        return deny(headers)
    return JSONResponse({"ok": True, "identity": identity, "route": "ping"}, headers=headers)


@app.get("/api/edge")
def edge(request: Request) -> JSONResponse:
    allowed, headers, identity = decide(request, "GET /api/edge")
    if not allowed:
        return deny(headers)
    return JSONResponse(
        {"ok": True, "identity": identity, "route": "edge", "note": "10 per 60s, for the clock-edge demo"},
        headers=headers,
    )


@app.post("/api/work")
def work(request: Request) -> JSONResponse:
    allowed, headers, identity = decide(request, "POST /api/work")
    if not allowed:
        return deny(headers)
    with db() as conn:
        row = conn.execute(
            "INSERT INTO work_events (client_id) VALUES (%s) RETURNING id",
            (identity,),
        ).fetchone()
        conn.commit()
    return JSONResponse({"ok": True, "id": row[0], "identity": identity}, headers=headers)


@app.get("/api/limiter/me")
def me(request: Request) -> dict:
    identity = identity_of(request)
    with db() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM work_events WHERE client_id = %s",
            (identity,),
        ).fetchone()[0]
    return {"identity": identity, "work_rows": count, "algorithm": algorithm_of(request)}
