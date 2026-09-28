"""Indexing lab: composite B-tree, LSM write path, GiST radius, GIN words."""

from __future__ import annotations

import math
import os
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:5432/app")
INDEX_NAME = "events_user_id_created_at_idx"
GIN_NAME = "notes_body_gin"
STATIC = Path(__file__).resolve().parent / "static"

HERE = "ST_SetSRID(ST_MakePoint(-122.3930, 37.7950), 4326)::geography"
QUERIES = {
    "user": "SELECT * FROM events WHERE user_id = 42",
    "both": "SELECT * FROM events WHERE user_id = 42 AND created_at >= DATE '2024-06-01'",
    "date": "SELECT * FROM events WHERE created_at >= DATE '2024-06-01' AND created_at < DATE '2024-06-02'",
    "cover": "SELECT user_id, created_at FROM events WHERE user_id = 42",
    "body": "SELECT body FROM events WHERE user_id = 42",
    "geo": f"SELECT name FROM places WHERE ST_DWithin(geom, {HERE}, 200)",
    "latband": "SELECT name FROM places WHERE lat >= 37.79 AND lat < 37.80",
    "search": "SELECT id FROM notes WHERE to_tsvector('english', body) @@ plainto_tsquery('english', 'redis') ORDER BY id",
    "fullscan": "SELECT id FROM notes WHERE body LIKE '%redis%' ORDER BY id",
}

app = FastAPI(title="Database indexing")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def db():
    return psycopg.connect(DATABASE_URL)


def vacuum_events() -> None:
    """Index Only Scan needs a visibility map. VACUUM cannot run inside a transaction."""
    conn = psycopg.connect(DATABASE_URL, autocommit=True)
    try:
        conn.execute("VACUUM ANALYZE events")
    finally:
        conn.close()


@app.on_event("startup")
def startup() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id BIGINT PRIMARY KEY,
                user_id INT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                body TEXT NOT NULL
            )
            """
        )
        count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        if count == 0:
            conn.execute(
                """
                INSERT INTO events (id, user_id, created_at, body)
                SELECT g,
                       1 + (g % 1000),
                       TIMESTAMP '2024-01-01' + ((g % 365) || ' days')::interval,
                       'row-' || g
                FROM generate_series(1, 100000) g
                """
            )
        conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS places (
                id INT PRIMARY KEY,
                name TEXT NOT NULL,
                lat DOUBLE PRECISION NOT NULL,
                lon DOUBLE PRECISION NOT NULL,
                geom geography(Point, 4326) NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id INT PRIMARY KEY,
                body TEXT NOT NULL
            )
            """
        )
        places = conn.execute("SELECT COUNT(*) FROM places").fetchone()[0]
        if places == 0:
            conn.execute(
                """
                INSERT INTO places (id, name, lat, lon, geom)
                VALUES
                  (1, 'Ferry Building', 37.7955, -122.3933,
                   ST_SetSRID(ST_MakePoint(-122.3933, 37.7955), 4326)::geography),
                  (2, 'Atlantic same latitude', 37.7955, 10.0,
                   ST_SetSRID(ST_MakePoint(10.0, 37.7955), 4326)::geography)
                """
            )
            conn.execute(
                """
                INSERT INTO places (id, name, lat, lon, geom)
                SELECT g, 'p-' || g, lat, lon,
                       ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography
                FROM (
                    SELECT g,
                           -80 + random() * 160 AS lat,
                           -170 + random() * 340 AS lon
                    FROM generate_series(3, 5000) g
                ) points
                """
            )
        notes = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        if notes == 0:
            conn.execute(
                """
                INSERT INTO notes (id, body)
                SELECT g,
                       CASE WHEN g % 200 = 0 THEN 'how redis caching works'
                            ELSE 'note about topic ' || (g % 50)
                       END
                FROM generate_series(1, 8000) g
                """
            )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS places_geom_gist ON places USING GIST (geom)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS places_lat_idx ON places (lat)")
        conn.execute("CREATE INDEX IF NOT EXISTS places_lon_idx ON places (lon)")
        lat_d, lon_d = _box_deltas()
        conn.execute(
            """
            INSERT INTO places (id, name, lat, lon, geom)
            VALUES
              (9001, 'Same longitude far north', 47.7955, -122.3933,
               ST_SetSRID(ST_MakePoint(-122.3933, 47.7955), 4326)::geography),
              (9002, 'Rectangle corner', %s, %s,
               ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography)
            ON CONFLICT (id) DO NOTHING
            """,
            (Q_LAT + 0.85 * lat_d, Q_LON + 0.85 * lon_d, Q_LON + 0.85 * lon_d, Q_LAT + 0.85 * lat_d),
        )
        conn.execute("ANALYZE events")
        conn.execute("ANALYZE places")
        conn.execute("ANALYZE notes")
        conn.commit()
    vacuum_events()


def index_exists(conn, name: str = INDEX_NAME) -> bool:
    row = conn.execute(
        "SELECT 1 FROM pg_indexes WHERE indexname = %s",
        (name,),
    ).fetchone()
    return row is not None


def lsm_story() -> dict:
    """One memtable flush. Reads check RAM first, then immutable sorted files."""
    mem_limit = 8
    mem: dict[str, str] = {}
    wal: list[tuple[str, str]] = []
    sstables: list[dict[str, str]] = []
    log: list[str] = []

    def put(key: str, value: str) -> None:
        nonlocal mem
        wal.append((key, value))
        mem[key] = value
        log.append(f"WAL append {key}={value}. Memtable: {', '.join(sorted(mem))}.")
        if len(mem) >= mem_limit:
            frozen = dict(sorted(mem.items()))
            sstables.append(frozen)
            shown = ", ".join(f"{k}={v}" for k, v in frozen.items())
            log.append(
                f"Memtable reached {mem_limit}. Freeze sstable-{len(sstables) - 1}: {shown}. RAM is empty."
            )
            mem = {}

    for i in range(1, 9):
        put(f"k{i}", f"v{i}")
    put("k3", "v3-new")
    for i in range(9, 12):
        put(f"k{i}", f"v{i}")

    def get(key: str) -> dict:
        if key in mem:
            found = {"key": key, "found_in": "memtable", "value": mem[key]}
        else:
            found = {"key": key, "found_in": "missing", "value": None}
            for idx in range(len(sstables) - 1, -1, -1):
                if key in sstables[idx]:
                    found = {"key": key, "found_in": f"sstable-{idx}", "value": sstables[idx][key]}
                    break
        log.append(f"Read {key} → {found['value']} from {found['found_in']}.")
        return found

    return {
        "mem_limit": mem_limit,
        "wal_appends": len(wal),
        "memtable": mem,
        "sstables": sstables,
        "reads": [get("k3"), get("k1"), get("k9")],
        "log": log,
    }


Q_LAT = 37.7950
Q_LON = -122.3930
RADIUS_M = 200.0
TEACH = (
    "Ferry Building",
    "Atlantic same latitude",
    "Same longitude far north",
    "Rectangle corner",
)
_GEOHASH = "0123456789bcdefghjkmnpqrstuvwxyz"


def _box_deltas() -> tuple[float, float]:
    lat_m = 111_320.0
    lon_m = lat_m * math.cos(math.radians(Q_LAT))
    return RADIUS_M / lat_m, RADIUS_M / lon_m


def _meters(lat: float, lon: float) -> float:
    lat_m = 111_320.0
    lon_m = lat_m * math.cos(math.radians(Q_LAT))
    return math.hypot((lat - Q_LAT) * lat_m, (lon - Q_LON) * lon_m)


def _geohash_trace(lat: float, lon: float, precision: int = 7) -> tuple[str, list[dict]]:
    """Interleave lon/lat bits. Every 5 bits is one character of the index code."""
    lat_r = [-90.0, 90.0]
    lon_r = [-180.0, 180.0]
    even = True
    steps: list[dict] = []
    for _ in range(precision):
        chunk: list[int] = []
        for _bit in range(5):
            if even:
                mid = (lon_r[0] + lon_r[1]) / 2
                bit = 1 if lon >= mid else 0
                if bit:
                    lon_r[0] = mid
                else:
                    lon_r[1] = mid
            else:
                mid = (lat_r[0] + lat_r[1]) / 2
                bit = 1 if lat >= mid else 0
                if bit:
                    lat_r[0] = mid
                else:
                    lat_r[1] = mid
            chunk.append(bit)
            even = not even
        value = 0
        for bit in chunk:
            value = (value << 1) | bit
        steps.append(
            {
                "bits": "".join(str(bit) for bit in chunk),
                "char": _GEOHASH[value],
                "lat0": lat_r[0],
                "lat1": lat_r[1],
                "lon0": lon_r[0],
                "lon1": lon_r[1],
            }
        )
    return "".join(step["char"] for step in steps), steps


def _geohash(lat: float, lon: float, precision: int = 7) -> str:
    code, _steps = _geohash_trace(lat, lon, precision)
    return code


def _shared_prefix(left: str, right: str) -> int:
    count = 0
    for a, b in zip(left, right):
        if a != b:
            break
        count += 1
    return count


def _quadtree(points: list[dict]) -> tuple[list[str], list[str]]:
    """Split until a cell holds one teaching point. Search the degree square around the query."""
    lat_d, lon_d = _box_deltas()
    box = (Q_LAT - lat_d, Q_LAT + lat_d, Q_LON - lon_d, Q_LON + lon_d)

    def build(group: list[dict], lat0: float, lat1: float, lon0: float, lon1: float, depth: int) -> dict:
        if len(group) <= 1 or depth >= 16:
            return {"points": group, "children": None, "bounds": (lat0, lat1, lon0, lon1)}
        mid_lat = (lat0 + lat1) / 2
        mid_lon = (lon0 + lon1) / 2
        buckets = {key: [] for key in ("sw", "se", "nw", "ne")}
        spans = {
            "sw": (lat0, mid_lat, lon0, mid_lon),
            "se": (lat0, mid_lat, mid_lon, lon1),
            "nw": (mid_lat, lat1, lon0, mid_lon),
            "ne": (mid_lat, lat1, mid_lon, lon1),
        }
        for point in group:
            ns = "n" if point["lat"] >= mid_lat else "s"
            ew = "e" if point["lon"] >= mid_lon else "w"
            buckets[ns + ew].append(point)
        children = [
            build(buckets[key], *spans[key], depth + 1)
            for key in buckets
            if buckets[key]
        ]
        return {"points": [], "children": children, "bounds": (lat0, lat1, lon0, lon1)}

    def overlaps(bounds: tuple[float, float, float, float]) -> bool:
        lat0, lat1, lon0, lon1 = bounds
        return not (box[1] < lat0 or box[0] > lat1 or box[3] < lon0 or box[2] > lon1)

    def walk(node: dict, kept: list[str], pruned: list[str]) -> None:
        if not overlaps(node["bounds"]):
            if node["children"] is None:
                pruned.extend(point["name"] for point in node["points"])
            else:
                for child in node["children"]:
                    walk_all(child, pruned)
            return
        if node["children"] is None:
            kept.extend(point["name"] for point in node["points"])
            return
        for child in node["children"]:
            walk(child, kept, pruned)

    def walk_all(node: dict, pruned: list[str]) -> None:
        if node["children"] is None:
            pruned.extend(point["name"] for point in node["points"])
            return
        for child in node["children"]:
            walk_all(child, pruned)

    root = build(points, -90.0, 90.0, -180.0, 180.0, 0)
    kept: list[str] = []
    pruned: list[str] = []
    walk(root, kept, pruned)
    return kept, pruned


def geo_compare_story() -> dict:
    lat_d, lon_d = _box_deltas()
    lat0, lat1 = Q_LAT - lat_d, Q_LAT + lat_d
    lon0, lon1 = Q_LON - lon_d, Q_LON + lon_d
    queries = {
        "lat": (
            "SELECT name FROM places WHERE lat BETWEEN %s AND %s",
            (lat0, lat1),
            "B-tree idx_lat only. One column, so this is a band around the Earth.",
        ),
        "lon": (
            "SELECT name FROM places WHERE lon BETWEEN %s AND %s",
            (lon0, lon1),
            "B-tree idx_lng only. One column, so this is a strip from north to south.",
        ),
        "box": (
            "SELECT name FROM places WHERE lat BETWEEN %s AND %s AND lon BETWEEN %s AND %s",
            (lat0, lat1, lon0, lon1),
            "Both B-trees. The overlap is a rectangle in degrees, not a circle in meters.",
        ),
        "rtree": (
            f"SELECT name FROM places WHERE ST_DWithin(geom, {HERE}, 200)",
            (),
            "R-tree (GiST). Walk boxes that overlap the 200m disk, then check real distance.",
        ),
    }
    found: dict[str, list[str]] = {}
    plans: dict[str, str] = {}
    with db() as conn:
        rows = conn.execute(
            "SELECT name, lat, lon FROM places WHERE name = ANY(%s)",
            (list(TEACH),),
        ).fetchall()
        points = [{"name": name, "lat": lat, "lon": lon} for name, lat, lon in rows]
        for key, (sql, params, _title) in queries.items():
            names = [row[0] for row in conn.execute(sql, params).fetchall()]
            found[key] = [name for name in TEACH if name in names]
            explain_sql = "EXPLAIN " + sql
            plan_rows = conn.execute(explain_sql, params).fetchall()
            plans[key] = "\n".join(row[0] for row in plan_rows)

    by_name = {point["name"]: point for point in points}
    query_hash = _geohash(Q_LAT, Q_LON)
    prefixes = {
        name: _shared_prefix(query_hash, _geohash(point["lat"], point["lon"]))
        for name, point in by_name.items()
    }
    kept, pruned = _quadtree(points)

    def yes_no(names: list[str]) -> list[str]:
        return [f"  {name}: {'YES' if name in names else 'no'}" for name in TEACH]

    lines = [
        "Restaurants table: latitude and longitude, like",
        "  CREATE INDEX idx_lat ON restaurants(latitude);",
        "  CREATE INDEX idx_lng ON restaurants(longitude);",
        f"Question: which restaurants are within {int(RADIUS_M)}m of ({Q_LAT}, {Q_LON})?",
        "",
    ]
    for key in ("lat", "lon", "box", "rtree"):
        _sql, _params, title = queries[key]
        lines.append(title)
        lines.append(plans[key])
        lines.extend(yes_no(found[key]))
        lines.append("")
    lines.append(f"Geohash precision 7. Query cell {query_hash}. A B-tree stores that string.")
    for name in TEACH:
        point = by_name[name]
        cell = _geohash(point["lat"], point["lon"])
        lines.append(
            f"  {name}: {cell}, shared prefix {prefixes[name]}/7, {_meters(point['lat'], point['lon']):.0f}m"
        )
    lines.append("A cell edge can put a nearby restaurant in the next cell, so the query also reads neighbors.")
    lines.append("")
    lines.append("Quadtree: split the map into four until each teaching restaurant sits in its own cell.")
    lines.append("The search square keeps: " + (", ".join(kept) if kept else "(none)"))
    lines.append("The search square prunes: " + (", ".join(pruned) if pruned else "(none)"))
    outside = [name for name in kept if _meters(by_name[name]["lat"], by_name[name]["lon"]) > RADIUS_M]
    if outside:
        lines.append(
            "Still inside the square and outside 200m, so the quadtree needs a distance check: "
            + ", ".join(outside)
        )
    return {
        "log": lines,
        "lat": found["lat"],
        "lon": found["lon"],
        "box": found["box"],
        "rtree": found["rtree"],
        "quadtree_kept": kept,
        "quadtree_pruned": pruned,
        "geohash_prefix": prefixes,
        "plans": plans,
    }


def geohash_code_story() -> dict:
    """Show the bit cuts for the query point, then a prefix lookup of the four restaurants."""
    code, steps = _geohash_trace(Q_LAT, Q_LON)
    prefix = code[:6]
    with db() as conn:
        rows = conn.execute(
            "SELECT name, lat, lon FROM places WHERE name = ANY(%s)",
            (list(TEACH),),
        ).fetchall()
    coded = []
    for name, lat, lon in rows:
        cell = _geohash(lat, lon)
        coded.append({"name": name, "code": cell, "hit": cell.startswith(prefix)})
    by_name = {row["name"]: row for row in coded}
    lines = [
        f"Address as numbers: ({Q_LAT}, {Q_LON}), the point next to the Ferry Building.",
        "Start with the whole world, lat [-90, 90] and lon [-180, 180].",
        "Cut longitude, then latitude, and repeat. Five bits become one character.",
        "",
    ]
    so_far = ""
    for index, step in enumerate(steps, start=1):
        so_far += step["char"]
        lines.append(
            f"{index}. bits {step['bits']} → '{step['char']}'. Code so far {so_far}. "
            f"Cell lat [{step['lat0']:.4f}, {step['lat1']:.4f}], "
            f"lon [{step['lon0']:.4f}, {step['lon1']:.4f}]."
        )
    lines.append("")
    lines.append(f"Index code: {code}")
    ferry = by_name.get("Ferry Building")
    if ferry:
        lines.append(f"Ferry Building encodes to {ferry['code']}.")
    lines.append("")
    lines.append(f"Retrieve with the first 6 characters: WHERE geohash LIKE '{prefix}%'")
    for name in TEACH:
        row = by_name[name]
        mark = "YES" if row["hit"] else "no"
        lines.append(f"  {name}: {row['code']} {mark}")
    lines.append("")
    lines.append(
        f"The full code {code} matches no restaurant. The last character is a neighboring cell, "
        "so the lookup uses the shorter prefix and still checks distance."
    )
    return {"code": code, "prefix": prefix, "steps": steps, "hits": coded, "log": lines}


@app.get("/healthz")
def healthz() -> dict:
    with db() as conn:
        conn.execute("SELECT 1")
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/status")
def status() -> dict:
    with db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        present = index_exists(conn)
        gin = index_exists(conn, GIN_NAME)
    return {
        "rows": count,
        "composite_index": present,
        "index_name": INDEX_NAME,
        "gin_index": gin,
    }


@app.post("/api/index")
def create_index() -> dict:
    with db() as conn:
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS {INDEX_NAME} ON events (user_id, created_at)"
        )
        conn.execute("ANALYZE events")
        conn.commit()
    vacuum_events()
    return {"composite_index": True}


@app.delete("/api/index")
def drop_index() -> dict:
    with db() as conn:
        conn.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
        conn.execute("ANALYZE events")
        conn.commit()
    return {"composite_index": False}


@app.get("/api/lsm")
def lsm() -> dict:
    return lsm_story()


@app.get("/api/geo/compare")
def geo_compare() -> dict:
    return geo_compare_story()


@app.get("/api/geo/code")
def geo_code() -> dict:
    return geohash_code_story()


@app.post("/api/gin")
def create_gin() -> dict:
    with db() as conn:
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS {GIN_NAME} ON notes USING GIN (to_tsvector('english', body))"
        )
        conn.execute("ANALYZE notes")
        conn.commit()
    return {"gin_index": True}


@app.delete("/api/gin")
def drop_gin() -> dict:
    with db() as conn:
        conn.execute(f"DROP INDEX IF EXISTS {GIN_NAME}")
        conn.execute("ANALYZE notes")
        conn.commit()
    return {"gin_index": False}


@app.get("/api/explain/{kind}")
def explain(kind: str) -> dict:
    sql = QUERIES.get(kind)
    if sql is None:
        raise HTTPException(status_code=404, detail="unknown query")
    with db() as conn:
        present = index_exists(conn)
        lines = [row[0] for row in conn.execute(f"EXPLAIN {sql}").fetchall()]
        names: list[str] = []
        if kind in ("geo", "latband", "search", "fullscan"):
            names = [str(row[0]) for row in conn.execute(sql).fetchall()]
    plan = "\n".join(lines)
    uses_index = "Index" in plan and "Seq Scan" not in plan.split("\n")[0]
    return {
        "kind": kind,
        "sql": sql,
        "composite_index": present,
        "plan": plan,
        "leading_node_uses_index": uses_index,
        "names": names,
        "ferry": "Ferry Building" in names,
        "atlantic": "Atlantic same latitude" in names,
    }
