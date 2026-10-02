"""Live OTP codes in Redis. The worker only delivers; it does not write the code key."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass

import redis

TTL = int(os.environ.get("OTP_TTL_SECONDS", "600"))
COOLDOWN = int(os.environ.get("COOLDOWN_SECONDS", "60"))
DAILY_CAP = int(os.environ.get("DAILY_CAP", "10"))
IP_LIMIT = int(os.environ.get("IP_LIMIT", "10"))
MAX_ATTEMPTS = int(os.environ.get("MAX_ATTEMPTS", "5"))
PEPPER = os.environ.get("OTP_PEPPER", "lab-pepper").encode()

QUEUE = "otp:queue"
CODE = "otp:{purpose}:{destination}"
COOL = "otp:cool:{purpose}:{destination}"
DAY = "otp:day:{destination}"
IP = "otp:ip:{ip}"
INBOX = "inbox:{destination}"

VERIFY_LUA = """
local raw = redis.call('GET', KEYS[1])
if not raw then
  return {'missing'}
end
local bar = string.find(raw, '|', 1, true)
local hash = string.sub(raw, 1, bar - 1)
local attempts = tonumber(string.sub(raw, bar + 1))
local max_attempts = tonumber(ARGV[2])
if attempts >= max_attempts then
  redis.call('DEL', KEYS[1])
  return {'locked'}
end
local guess = ARGV[1]
local same = 0
if #hash == #guess then
  same = 1
  for i = 1, #hash do
    if string.byte(hash, i) ~= string.byte(guess, i) then
      same = 0
    end
  end
end
if same == 1 then
  redis.call('DEL', KEYS[1])
  return {'ok'}
end
attempts = attempts + 1
local ttl = redis.call('TTL', KEYS[1])
if ttl < 1 then
  ttl = tonumber(ARGV[3])
end
if attempts >= max_attempts then
  redis.call('DEL', KEYS[1])
  return {'locked'}
end
redis.call('SET', KEYS[1], hash .. '|' .. attempts, 'EX', ttl)
return {'wrong', tostring(attempts)}
"""


def code_hash(purpose: str, destination: str, code: str) -> str:
    message = f"{purpose}|{destination}|{code}".encode()
    return hmac.new(PEPPER, message, hashlib.sha256).hexdigest()


def new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


@dataclass
class Store:
    redis_down: bool = False
    sms_down: bool = False

    def client(self) -> redis.Redis:
        return redis.Redis.from_url(
            os.environ.get("REDIS_URL", "redis://redis:6379/0"),
            decode_responses=True,
            socket_timeout=2,
        )


STORE = Store()
_worker_started = False


def _key(template: str, **parts: str) -> str:
    return template.format(**parts)


class Unavailable(Exception):
    pass


class Rejected(Exception):
    def __init__(self, error: str, retry_after: int | None = None) -> None:
        self.error = error
        self.retry_after = retry_after


def generate(destination: str, channel: str, purpose: str, ip: str) -> dict:
    if STORE.redis_down:
        raise Unavailable()
    if channel == "sms" and STORE.sms_down:
        raise Unavailable()
    if channel not in {"sms", "email"} or purpose not in {"login", "payment"}:
        raise Rejected("bad_request")

    client = STORE.client()
    try:
        client.ping()
    except redis.RedisError as exc:
        raise Unavailable() from exc

    ip_key = _key(IP, ip=ip)
    used = int(client.incr(ip_key))
    if used == 1:
        client.expire(ip_key, 60)
    if used > IP_LIMIT:
        raise Rejected("ip_limit", 60)

    cool_key = _key(COOL, purpose=purpose, destination=destination)
    if client.exists(cool_key):
        raise Rejected("cooldown", int(client.ttl(cool_key)))

    day_key = _key(DAY, destination=destination)
    current = int(client.get(day_key) or 0)
    if current >= DAILY_CAP:
        raise Rejected("daily_cap", int(client.ttl(day_key)))

    code = new_code()
    code_key = _key(CODE, purpose=purpose, destination=destination)
    digest = code_hash(purpose, destination, code)
    client.set(code_key, f"{digest}|0", ex=TTL)
    client.set(cool_key, "1", ex=COOLDOWN)
    day_count = int(client.incr(day_key))
    if day_count == 1:
        client.expire(day_key, 86_400)

    job = {
        "destination": destination,
        "channel": channel,
        "purpose": purpose,
        "code": code,
        "expires_at": time.time() + TTL,
    }
    try:
        client.lpush(QUEUE, json.dumps(job))
    except redis.RedisError:
        client.delete(code_key)
        client.delete(cool_key)
        raise Unavailable()
    return {"expires_in": TTL}


def verify(destination: str, purpose: str, code: str) -> bool:
    if STORE.redis_down:
        raise Unavailable()
    if purpose not in {"login", "payment"} or not code.isdigit() or len(code) != 6:
        return False
    client = STORE.client()
    try:
        result = client.eval(
            VERIFY_LUA,
            1,
            _key(CODE, purpose=purpose, destination=destination),
            code_hash(purpose, destination, code),
            str(MAX_ATTEMPTS),
            str(TTL),
        )
    except redis.RedisError as exc:
        raise Unavailable() from exc
    return bool(result) and result[0] == "ok"


def inbox(destination: str) -> list[dict]:
    if STORE.redis_down:
        raise Unavailable()
    client = STORE.client()
    rows = client.lrange(_key(INBOX, destination=destination), 0, 4)
    return [json.loads(row) for row in rows]


def fill_daily(destination: str) -> None:
    client = STORE.client()
    client.set(_key(DAY, destination=destination), str(DAILY_CAP), ex=86_400)


def reset() -> None:
    STORE.redis_down = False
    STORE.sms_down = False
    client = STORE.client()
    for pattern in ("otp:*", "inbox:*"):
        for key in client.scan_iter(pattern):
            client.delete(key)


def status() -> dict:
    depth = 0
    if not STORE.redis_down:
        try:
            depth = int(STORE.client().llen(QUEUE))
        except redis.RedisError:
            depth = -1
    return {
        "redis_down": STORE.redis_down,
        "sms_down": STORE.sms_down,
        "queue_depth": depth,
        "ttl_seconds": TTL,
        "cooldown_seconds": COOLDOWN,
        "daily_cap": DAILY_CAP,
        "max_attempts": MAX_ATTEMPTS,
    }


def _deliver_once(client: redis.Redis) -> None:
    if STORE.redis_down:
        time.sleep(0.3)
        return
    item = client.brpop(QUEUE, timeout=1)
    if not item:
        return
    job = json.loads(item[1])
    if job["expires_at"] < time.time():
        return
    if job["channel"] == "sms" and STORE.sms_down:
        client.lpush(QUEUE, item[1])
        time.sleep(0.4)
        return
    letter = {
        "channel": job["channel"],
        "purpose": job["purpose"],
        "code": job["code"],
        "at": int(time.time()),
    }
    box = _key(INBOX, destination=job["destination"])
    client.lpush(box, json.dumps(letter))
    client.ltrim(box, 0, 4)
    client.expire(box, TTL)


def _worker() -> None:
    client = STORE.client()
    while True:
        try:
            _deliver_once(client)
        except redis.RedisError:
            time.sleep(0.5)


def start_worker() -> None:
    global _worker_started
    if _worker_started:
        return
    _worker_started = True
    threading.Thread(target=_worker, name="otp-worker", daemon=True).start()
