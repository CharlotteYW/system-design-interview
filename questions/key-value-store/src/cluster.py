"""Five servers on one ring. Each has a WAL, a memtable, and a private L1 map."""

from __future__ import annotations

import json
import os
import threading
from hashlib import md5
from pathlib import Path

SERVERS = (
    ("A", 0),
    ("B", 20),
    ("C", 40),
    ("D", 60),
    ("E", 80),
)
RING = 100
FLUSH_AT = 4


def key_point(key: str) -> int:
    digest = md5(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % RING


class Node:
    def __init__(self, name: str, position: int, root: Path, ttl: float) -> None:
        self.name = name
        self.position = position
        self.ttl = ttl
        self.alive = True
        self.dir = root / name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.memtable: dict[str, dict] = {}
        self.sstables: list[dict[str, dict]] = []
        self.l1: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        for path in sorted(self.dir.glob("sst-*.json")):
            self.sstables.append(json.loads(path.read_text()))
        wal = self.dir / "wal.log"
        if not wal.exists():
            return
        for line in wal.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                self.memtable[rec["key"]] = rec

    def apply(self, key: str, value: str | None, version: int, tombstone: bool, now: float) -> None:
        rec = {"key": key, "value": value, "version": version, "tombstone": tombstone}
        wal = self.dir / "wal.log"
        with wal.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(rec) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.memtable[key] = rec
        self.set_l1(key, rec, now)
        if len(self.memtable) >= FLUSH_AT:
            self.flush()

    def flush(self) -> None:
        if not self.memtable:
            return
        n = len(list(self.dir.glob("sst-*.json")))
        (self.dir / f"sst-{n}.json").write_text(json.dumps(self.memtable))
        self.sstables.append(dict(self.memtable))
        self.memtable.clear()
        wal = self.dir / "wal.log"
        if wal.exists():
            wal.unlink()

    def read_durable(self, key: str) -> dict | None:
        if key in self.memtable:
            return self.memtable[key]
        for table in reversed(self.sstables):
            if key in table:
                return table[key]
        return None

    def set_l1(self, key: str, rec: dict, now: float) -> None:
        self.l1[key] = {
            "value": rec["value"],
            "version": rec["version"],
            "tombstone": rec["tombstone"],
            "expires_at": now + self.ttl,
        }

    def l1_get(self, key: str, now: float) -> dict | None:
        ent = self.l1.get(key)
        if ent is None:
            return None
        if ent["expires_at"] <= now:
            del self.l1[key]
            return None
        return ent

    def snapshot(self, now: float) -> dict:
        rows = []
        for key, ent in self.l1.items():
            if ent["expires_at"] <= now:
                continue
            rows.append(
                {
                    "key": key,
                    "value": ent["value"],
                    "version": ent["version"],
                    "tombstone": ent["tombstone"],
                    "ttl_left_ms": int((ent["expires_at"] - now) * 1000),
                }
            )
        return {
            "name": self.name,
            "position": self.position,
            "alive": self.alive,
            "memtable_keys": sorted(self.memtable),
            "sstable_count": len(self.sstables),
            "l1": rows,
        }


class Cluster:
    def __init__(self, data_dir: str, ttl: float) -> None:
        self.ttl = ttl
        self.root = Path(data_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.nodes = {name: Node(name, pos, self.root, ttl) for name, pos in SERVERS}
        self.order = [name for name, _ in SERVERS]
        self._rr = 0
        self._version = 0
        self._lock = threading.Lock()
        self._started = 0.0

    def reset(self, now: float) -> None:
        with self._lock:
            for node in self.nodes.values():
                for path in node.dir.glob("*"):
                    path.unlink()
            self.nodes = {name: Node(name, pos, self.root, self.ttl) for name, pos in SERVERS}
            self._rr = 0
            self._version = 0
            self._started = now

    def preference(self, key: str) -> list[str]:
        point = key_point(key)
        ranked = sorted(self.order, key=lambda name: (self.nodes[name].position - point) % RING)
        return ranked[:3]

    def _coordinator(self, at: str | None) -> Node:
        if at:
            node = self.nodes.get(at)
            if node is None:
                raise ValueError(f"unknown server {at}")
            if not node.alive:
                raise RuntimeError(f"server {at} is down")
            return node
        for _ in range(len(self.order)):
            name = self.order[self._rr % len(self.order)]
            self._rr += 1
            node = self.nodes[name]
            if node.alive:
                return node
        raise RuntimeError("no server is up")

    def put(
        self,
        key: str,
        value: str | None,
        tombstone: bool,
        now: float,
        at: str | None = None,
        lag_third: bool = False,
    ) -> dict:
        with self._lock:
            coord = self._coordinator(at)
            owners = self.preference(key)
            self._version += 1
            version = self._version
            acks: list[str] = []
            skipped: list[str] = []
            for index, name in enumerate(owners):
                node = self.nodes[name]
                if lag_third and index == 2:
                    skipped.append(name)
                    continue
                if not node.alive:
                    skipped.append(name)
                    continue
                node.apply(key, value, version, tombstone, now)
                acks.append(name)
            if len(acks) < 2:
                raise RuntimeError("quorum failed")
            rec = {"value": value, "version": version, "tombstone": tombstone}
            coord.set_l1(key, rec, now)
            updated = list(dict.fromkeys([coord.name, *acks]))
            return {
                "op": "delete" if tombstone else "put",
                "coordinator": coord.name,
                "key": key,
                "key_point": key_point(key),
                "preference": owners,
                "acks": acks,
                "skipped": skipped,
                "l1_updates": updated,
                "version": version,
                "value": value,
                "tombstone": tombstone,
            }

    def get(self, key: str, now: float, at: str | None = None) -> dict:
        with self._lock:
            coord = self._coordinator(at)
            cached = coord.l1_get(key, now)
            if cached is not None:
                return {
                    "op": "get",
                    "coordinator": coord.name,
                    "key": key,
                    "l1": "hit",
                    "preference": None,
                    "replica_reads": [],
                    "found": not cached["tombstone"],
                    "value": None if cached["tombstone"] else cached["value"],
                    "version": cached["version"],
                    "tombstone": cached["tombstone"],
                }
            owners = self.preference(key)
            reads: list[tuple[str, dict]] = []
            for name in owners:
                node = self.nodes[name]
                if not node.alive:
                    continue
                rec = node.read_durable(key) or {
                    "value": None,
                    "version": 0,
                    "tombstone": True,
                }
                reads.append((name, rec))
                if len(reads) == 2:
                    break
            if len(reads) < 2:
                raise RuntimeError("quorum failed")
            _name, best = max(reads, key=lambda item: item[1]["version"])
            if best["version"] == 0:
                best = {"value": None, "version": 0, "tombstone": True}
            coord.set_l1(key, best, now)
            return {
                "op": "get",
                "coordinator": coord.name,
                "key": key,
                "key_point": key_point(key),
                "l1": "miss",
                "preference": owners,
                "replica_reads": [name for name, _ in reads],
                "found": not best["tombstone"],
                "value": None if best["tombstone"] else best["value"],
                "version": best["version"],
                "tombstone": best["tombstone"],
            }

    def set_alive(self, name: str, alive: bool) -> None:
        with self._lock:
            if name not in self.nodes:
                raise ValueError(f"unknown server {name}")
            self.nodes[name].alive = alive

    def state(self, now: float) -> dict:
        with self._lock:
            return {
                "ttl_seconds": self.ttl,
                "servers": [self.nodes[name].snapshot(now) for name in self.order],
            }
