"""Consistent-hashing lab: ring plus virtual nodes versus hash % N."""

from __future__ import annotations

import bisect
import hashlib
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

RING = 2**32
STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Consistent hashing")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def point(label: str) -> int:
    digest = hashlib.md5(label.encode()).hexdigest()
    return int(digest, 16) % RING


def owner_clockwise(sorted_points: list[tuple[int, str]], key_pos: int) -> str:
    positions = [pos for pos, _server in sorted_points]
    index = bisect.bisect_left(positions, key_pos)
    if index == len(sorted_points):
        index = 0
    return sorted_points[index][1]


def ring_points(servers: list[str], vnodes: int) -> list[tuple[int, str]]:
    points: list[tuple[int, str]] = []
    for server in servers:
        for vnode in range(vnodes):
            points.append((point(f"{server}#{vnode}"), server))
    points.sort()
    return points


def assignments(keys: list[str], servers: list[str], vnodes: int) -> dict[str, str]:
    points = ring_points(servers, vnodes)
    return {key: owner_clockwise(points, point(key)) for key in keys}


def mod_assignments(keys: list[str], servers: list[str]) -> dict[str, str]:
    count = len(servers)
    return {key: servers[point(key) % count] for key in keys}


def moved(before: dict[str, str], after: dict[str, str]) -> int:
    return sum(1 for key, server in before.items() if after[key] != server)


EXAMPLE_POINTS = [("A", 0), ("B", 40), ("C", 70), ("D", 55)]
EXAMPLE_KEYS = {"k1": 10, "k2": 50, "k3": 80}


def example_story() -> dict:
    before_points = sorted((pos, name) for name, pos in EXAMPLE_POINTS if name != "D")
    after_points = sorted((pos, name) for name, pos in EXAMPLE_POINTS)
    rows = []
    for key, pos in EXAMPLE_KEYS.items():
        old = owner_clockwise(before_points, pos)
        new = owner_clockwise(after_points, pos)
        rows.append({"key": key, "position": pos, "before": old, "after": new, "moved": old != new})
    return {
        "servers_before": ["A@0", "B@40", "C@70"],
        "added": "D@55",
        "keys": rows,
        "moved": [row["key"] for row in rows if row["moved"]],
    }


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/example")
def example() -> dict:
    return example_story()


@app.get("/api/compare")
def compare(servers: int = 4, keys: int = 1000, vnodes: int = 100) -> dict:
    servers = min(max(servers, 2), 20)
    keys = min(max(keys, 10), 20000)
    vnodes = min(max(vnodes, 1), 500)
    names = [f"s{i}" for i in range(servers)]
    key_names = [f"key-{i}" for i in range(keys)]
    extra = f"s{servers}"
    mod_before = mod_assignments(key_names, names)
    mod_after = mod_assignments(key_names, names + [extra])
    ring_before = assignments(key_names, names, vnodes)
    ring_after = assignments(key_names, names + [extra], vnodes)
    mod_move = moved(mod_before, mod_after)
    ring_move = moved(ring_before, ring_after)
    return {
        "servers_before": servers,
        "keys": keys,
        "vnodes": vnodes,
        "mod_moved": mod_move,
        "ring_moved": ring_move,
        "mod_fraction": round(mod_move / keys, 3),
        "ring_fraction": round(ring_move / keys, 3),
    }
