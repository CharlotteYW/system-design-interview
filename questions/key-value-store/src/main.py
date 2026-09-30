"""Key-value lab: round-robin coordinator, ring of three replicas, private L1 maps."""

from __future__ import annotations

import os
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.cluster import Cluster

DATA_DIR = os.environ.get("DATA_DIR", "/data")
TTL = float(os.environ.get("L1_TTL_SECONDS", "1"))
STATIC = os.path.join(os.path.dirname(__file__), "static")

app = FastAPI(title="Key-value store")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
cluster = Cluster(DATA_DIR, TTL)


class PutBody(BaseModel):
    value: str = Field(min_length=1)


def _now() -> float:
    return time.monotonic()


def _fail(exc: Exception) -> HTTPException:
    status = 400 if isinstance(exc, ValueError) else 503
    return HTTPException(status_code=status, detail=str(exc))


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/api/state")
def state() -> dict:
    return cluster.state(_now())


@app.post("/api/reset")
def reset() -> dict:
    cluster.reset(_now())
    return {"ok": True}


@app.post("/api/servers/{name}/down")
def server_down(name: str) -> dict:
    try:
        cluster.set_alive(name, False)
    except ValueError as exc:
        raise _fail(exc) from exc
    return cluster.state(_now())


@app.post("/api/servers/{name}/up")
def server_up(name: str) -> dict:
    try:
        cluster.set_alive(name, True)
    except ValueError as exc:
        raise _fail(exc) from exc
    return cluster.state(_now())


@app.put("/v1/keys/{key}")
def put_key(key: str, body: PutBody, at: str | None = None, lag_third: bool = False) -> dict:
    try:
        return cluster.put(key, body.value, False, _now(), at=at, lag_third=lag_third)
    except (RuntimeError, ValueError) as exc:
        raise _fail(exc) from exc


@app.delete("/v1/keys/{key}")
def delete_key(key: str, at: str | None = None, lag_third: bool = False) -> dict:
    try:
        return cluster.put(key, None, True, _now(), at=at, lag_third=lag_third)
    except (RuntimeError, ValueError) as exc:
        raise _fail(exc) from exc


@app.get("/v1/keys/{key}")
def get_key(key: str, at: str | None = None) -> dict:
    try:
        return cluster.get(key, _now(), at=at)
    except (RuntimeError, ValueError) as exc:
        raise _fail(exc) from exc
