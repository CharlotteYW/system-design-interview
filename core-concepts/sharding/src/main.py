"""Sharding lab: one account's orders hit one shard. The hourly screen reads a recent table."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from src import store

app = FastAPI(title="Sharding")


class OrderIn(BaseModel):
    account_id: int = Field(ge=0)
    note: str = Field(min_length=1, max_length=80)


@app.on_event("startup")
def startup() -> None:
    store.init_db()


@app.get("/healthz")
def healthz() -> dict:
    with store.connect() as conn:
        conn.execute("SELECT 1")
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.post("/api/reset")
def reset() -> dict:
    store.reset()
    return {"ok": True}


@app.post("/api/orders")
def create_order(body: OrderIn) -> dict:
    return store.place_order(body.account_id, body.note.strip())


@app.get("/api/accounts/{account_id}/orders")
def account_orders(account_id: int) -> dict:
    return store.my_orders(account_id)


@app.get("/api/orders/recent")
def recent() -> dict:
    return store.recent_from_table()


@app.get("/api/orders/scatter")
def scatter() -> dict:
    return store.recent_by_scatter()
