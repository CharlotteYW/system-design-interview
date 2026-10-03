"""Two in-memory replicas. Seats are CP. Likes are AP. The link can be cut."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Node:
    seats: int = 1
    likes: int = 0


@dataclass
class World:
    a: Node = field(default_factory=Node)
    b: Node = field(default_factory=Node)
    partitioned: bool = False
    likes_base: int = 0

    def node(self, name: str) -> Node:
        if name == "A":
            return self.a
        if name == "B":
            return self.b
        raise ValueError(name)

    def other(self, name: str) -> Node:
        return self.b if name == "A" else self.a

    def snapshot(self) -> dict:
        return {
            "partitioned": self.partitioned,
            "a": {"seats": self.a.seats, "likes": self.a.likes},
            "b": {"seats": self.b.seats, "likes": self.b.likes},
        }


WORLD = World()


def reset() -> dict:
    WORLD.a = Node()
    WORLD.b = Node()
    WORLD.partitioned = False
    WORLD.likes_base = 0
    return WORLD.snapshot()


def set_partition(cut: bool) -> dict:
    if cut and not WORLD.partitioned:
        WORLD.likes_base = WORLD.a.likes
    if not cut and WORLD.partitioned:
        merged = WORLD.a.likes + WORLD.b.likes - WORLD.likes_base
        WORLD.a.likes = merged
        WORLD.b.likes = merged
        WORLD.likes_base = merged
    WORLD.partitioned = cut
    return WORLD.snapshot()


class Refused(Exception):
    def __init__(self, status: int, detail: str, mode: str) -> None:
        self.status = status
        self.detail = detail
        self.mode = mode


def sell_seat(name: str) -> dict:
    if WORLD.partitioned:
        raise Refused(
            503,
            "The link is cut. A seat sale needs both copies, so this side refuses.",
            "CP",
        )
    if WORLD.a.seats <= 0:
        raise Refused(409, "No seats left. Both copies already show 0.", "CP")
    WORLD.a.seats -= 1
    WORLD.b.seats -= 1
    return {
        "ok": True,
        "mode": "CP",
        "detail": f"Sold on {name}. Both copies now show {WORLD.a.seats}.",
        **WORLD.snapshot(),
    }


def add_like(name: str) -> dict:
    local = WORLD.node(name)
    if WORLD.partitioned:
        local.likes += 1
        other = WORLD.other(name)
        return {
            "ok": True,
            "mode": "AP",
            "detail": (
                f"Recorded on {name} only ({local.likes}). "
                f"The other side still has {other.likes} until the link returns."
            ),
            **WORLD.snapshot(),
        }
    WORLD.a.likes += 1
    WORLD.b.likes += 1
    return {
        "ok": True,
        "mode": "synced",
        "detail": f"Like on {name} wrote both copies. Count is {WORLD.a.likes}.",
        **WORLD.snapshot(),
    }
