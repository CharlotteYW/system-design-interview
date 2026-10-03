"""CAP lab: cut the link, then sell a seat or add a like."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from src.replicas import WORLD, Refused, add_like, reset, sell_seat, set_partition

app = FastAPI(title="CAP theorem")


class PartitionIn(BaseModel):
    cut: bool


class NodeIn(BaseModel):
    node: str


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/api/state")
def state() -> dict:
    return WORLD.snapshot()


@app.post("/api/reset")
def reset_lab() -> dict:
    return reset()


@app.post("/api/partition")
def partition(body: PartitionIn) -> dict:
    state = set_partition(body.cut)
    if body.cut:
        detail = "Link cut. Seats will refuse. Likes still record on the side you click."
    else:
        detail = "Link restored. Like counts were added together. Seats were never allowed to diverge."
    return {"ok": True, "detail": detail, **state}


@app.post("/api/seat")
def seat(body: NodeIn) -> JSONResponse:
    if body.node not in {"A", "B"}:
        return JSONResponse({"ok": False, "detail": "node must be A or B"}, status_code=400)
    try:
        return JSONResponse(sell_seat(body.node))
    except Refused as exc:
        return JSONResponse(
            {"ok": False, "mode": exc.mode, "detail": exc.detail, **WORLD.snapshot()},
            status_code=exc.status,
        )


@app.post("/api/like")
def like(body: NodeIn) -> JSONResponse:
    if body.node not in {"A", "B"}:
        return JSONResponse({"ok": False, "detail": "node must be A or B"}, status_code=400)
    return JSONResponse(add_like(body.node))
