"""JWT, a process session, and a Redis session."""

from __future__ import annotations

import os
import secrets
import time

import jwt
import redis

from src.errors import ApiError

SECRET = os.environ.get("JWT_SECRET", "lab-secret")
MEMORY: dict[str, dict[str, int]] = {"a": {}, "b": {}}
_redis: redis.Redis | None = None


def client() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    return _redis


def reset() -> None:
    MEMORY["a"].clear()
    MEMORY["b"].clear()
    stored = client()
    for key in stored.scan_iter("session:*"):
        stored.delete(key)


def login(account_id: int, mode: str, server: str) -> dict:
    if server not in MEMORY:
        raise ApiError(400, "BAD_SERVER", "Server must be a or b")
    if mode == "jwt":
        token = jwt.encode(
            {"account_id": account_id, "exp": int(time.time()) + 3600},
            SECRET,
            algorithm="HS256",
        )
        return {"mode": "jwt", "token": token, "store": "none"}
    session_id = secrets.token_hex(8)
    if mode == "memory":
        MEMORY[server][session_id] = account_id
        return {"mode": "memory", "session_id": session_id, "server": server, "store": "process"}
    if mode == "redis":
        client().set(f"session:{session_id}", str(account_id), ex=3600)
        return {"mode": "redis", "session_id": session_id, "store": "redis"}
    raise ApiError(400, "BAD_MODE", "Mode must be jwt, memory, or redis")


def who(mode: str, server: str, authorization: str | None, session_id: str | None) -> dict:
    if server not in MEMORY:
        raise ApiError(400, "BAD_SERVER", "Server must be a or b")
    if mode == "jwt":
        if not authorization or not authorization.startswith("Bearer "):
            raise ApiError(401, "UNAUTHORIZED", "Send the JWT in Authorization")
        try:
            payload = jwt.decode(authorization.removeprefix("Bearer ").strip(), SECRET, algorithms=["HS256"])
        except jwt.PyJWTError as exc:
            raise ApiError(401, "BAD_TOKEN", "The token is not valid") from exc
        return {"account_id": int(payload["account_id"]), "mode": "jwt", "store_read": "none", "server": server}
    if not session_id:
        raise ApiError(401, "UNAUTHORIZED", "Send the session id")
    if mode == "memory":
        account_id = MEMORY[server].get(session_id)
        if account_id is None:
            raise ApiError(401, "SESSION_NOT_ON_THIS_SERVER", f"Server {server} does not have this session")
        return {"account_id": account_id, "mode": "memory", "store_read": f"process:{server}", "server": server}
    if mode == "redis":
        raw = client().get(f"session:{session_id}")
        if raw is None:
            raise ApiError(401, "SESSION_MISSING", "Redis does not have this session")
        return {"account_id": int(raw), "mode": "redis", "store_read": "redis", "server": server}
    raise ApiError(400, "BAD_MODE", "Mode must be jwt, memory, or redis")


def logout(mode: str, server: str, session_id: str | None) -> dict:
    if mode == "jwt":
        return {"cleared": False, "store": "none"}
    if not session_id:
        raise ApiError(400, "MISSING_SESSION", "Send the session id")
    if mode == "memory":
        MEMORY.get(server, {}).pop(session_id, None)
        return {"cleared": True, "store": f"process:{server}"}
    if mode == "redis":
        client().delete(f"session:{session_id}")
        return {"cleared": True, "store": "redis"}
    raise ApiError(400, "BAD_MODE", "Mode must be jwt, memory, or redis")
