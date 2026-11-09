import base64
import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg import OperationalError, sql
from psycopg.errors import QueryCanceled
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool, PoolTimeout
from pydantic import UUID4, BaseModel, ConfigDict, Field

from .cell_indexes import H3_RESOLUTION, S2_STORAGE_LEVEL, h3_cover, prepare_cell_keys, s2_ranges, store_cell_keys
from .geohash_cover import cover
from .point_trees import Point, tree_candidates

ROLE = os.environ["SERVICE_ROLE"]
CURSOR_SECRET = os.getenv("CURSOR_SECRET", "").encode()
pool = ConnectionPool(
    os.environ["DATABASE_URL"],
    open=False,
    min_size=1,
    max_size=8,
    timeout=2,
    check=ConnectionPool.check_connection,
    kwargs={"row_factory": dict_row, "options": "-c statement_timeout=4000"},
)
search_routes = APIRouter()
business_routes = APIRouter()
SearchMode = Literal["postgis", "full-scan", "geohash", "quadtree", "kd-tree", "s2", "h3"]
COORDINATES = "ST_Y(location::geometry) AS latitude, ST_X(location::geometry) AS longitude"
LOCATION = "ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography"
MAX_TREE_POINTS = 5000


@asynccontextmanager
async def lifespan(_: FastAPI):
    pool.open()
    try:
        if ROLE == "business":
            with pool.connection() as conn:
                prepare_cell_keys(conn)
        yield
    finally:
        pool.close()


app = FastAPI(title=f"Proximity lab · {ROLE}", lifespan=lifespan)


@app.get("/healthz")
def health():
    with pool.connection() as conn:
        conn.execute("SELECT business_id FROM businesses LIMIT 1").fetchone()
    return {"service": ROLE, "status": "ok"}


@app.exception_handler(RequestValidationError)
async def invalid_input(_: Request, exc: RequestValidationError):
    fields = [
        {"field": ".".join(map(str, error["loc"])), "message": error["msg"]}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=400, content={"detail": fields})


async def unavailable(_: Request, exc: Exception):
    return JSONResponse(
        status_code=503,
        headers={"Retry-After": "2"},
        content={"detail": "Database temporarily unavailable. Retry shortly."},
    )


for error_type in (OperationalError, PoolTimeout, QueryCanceled):
    app.add_exception_handler(error_type, unavailable)


def _encode_cursor(context: list, last: dict) -> str:
    data = [context, last["distance_meters"], str(last["business_id"])]
    body = base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).decode()
    signature = hmac.digest(CURSOR_SECRET, body.encode(), "sha256").hex()
    return f"{body}.{signature}"


def _decode_cursor(token: str, context: list) -> tuple[float, UUID]:
    try:
        body, signature = token.split(".")
        expected = hmac.digest(CURSOR_SECRET, body.encode(), "sha256").hex()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        saved_context, distance, business_id = json.loads(base64.urlsafe_b64decode(body))
        if saved_context != context:
            raise ValueError
        return float(distance), UUID(business_id)
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid cursor for this search") from None


def _candidate_filter(conn, mode, latitude, longitude, radius):
    """Build a candidate predicate before the shared distance and page logic."""
    if mode == "postgis":
        return sql.SQL("ST_DWithin(location, q.center, %s)"), [radius], {}

    exact = sql.SQL("ST_Distance(location, q.center) <= %s")
    if mode == "full-scan":
        return exact, [radius], {}
    if mode == "geohash":
        keys = cover(latitude, longitude, radius)
        return sql.SQL("geohash = ANY(%s::text[]) AND ") + exact, [keys, radius], {"cellCount": len(keys)}
    if mode == "s2":
        ranges = s2_ranges(latitude, longitude, radius)
        selected = sql.SQL("""
            business_id IN (
                SELECT k.business_id
                FROM unnest(%s::text[], %s::text[]) AS bounds(low, high)
                JOIN business_cell_keys k ON k.method = 's2' AND k.cell_id BETWEEN bounds.low AND bounds.high
            ) AND
        """)
        return selected + exact, [[low for low, _ in ranges], [high for _, high in ranges], radius], {
            "cellCount": len(ranges), "storageLevel": S2_STORAGE_LEVEL, "rangeSample": ranges[:6],
        }
    if mode == "h3":
        keys = h3_cover(latitude, longitude, radius)
        if keys is None:
            return sql.SQL("ST_DWithin(location, q.center, %s)"), [radius], {
                "fallback": "PostGIS for a cover that touches a pole or crosses the date line",
            }
        selected = sql.SQL("""
            business_id IN (
                SELECT business_id FROM business_cell_keys
                WHERE method = 'h3' AND cell_id = ANY(%s::text[])
            ) AND
        """)
        return selected + exact, [keys, radius], {
            "cellCount": len(keys), "resolution": H3_RESOLUTION, "cellSample": keys[:8],
        }

    conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
    points = conn.execute(
        sql.SQL("SELECT business_id, {coordinates} FROM businesses LIMIT %s").format(
            coordinates=sql.SQL(COORDINATES)
        ),
        (MAX_TREE_POINTS + 1,),
    ).fetchall()
    if len(points) > MAX_TREE_POINTS:
        raise HTTPException(400, f"The teaching trees support up to {MAX_TREE_POINTS} businesses")
    ids, visited = tree_candidates(mode, [Point(**row) for row in points], latitude, longitude, radius)
    return sql.SQL("business_id = ANY(%s::uuid[]) AND ") + exact, [ids, radius], {
        "pointsLoaded": len(points), "nodesVisited": visited, "candidateCount": len(ids),
    }


@search_routes.get("/v1/nearby")
def nearby(
    response: Response,
    latitude: Annotated[float, Query(ge=-90, le=90)],
    longitude: Annotated[float, Query(ge=-180, le=180)],
    radius_meters: Annotated[float, Query(alias="radiusMeters", gt=0, le=50_000)] = 3000,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    mode: Annotated[SearchMode, Header(alias="X-Lab-Search-Mode")] = "postgis",
):
    context = [latitude, longitude, radius_meters, mode]
    response.headers["X-Lab-Search-Mode"] = mode
    after = sql.SQL("")
    after_params = []
    if cursor:
        after = sql.SQL("WHERE (distance_meters, business_id) > (%s, %s)")
        after_params.extend(_decode_cursor(cursor, context))

    with pool.connection() as conn:
        predicate, filter_params, diagnostics = _candidate_filter(
            conn, mode, latitude, longitude, radius_meters
        )
        query = sql.SQL("""
            WITH candidates AS (
                SELECT business_id, name, {coordinates},
                       ST_Distance(location, q.center) AS distance_meters
                FROM businesses
                CROSS JOIN (SELECT {location} AS center) q
                WHERE {predicate}
            )
            SELECT * FROM candidates
            {after}
            ORDER BY distance_meters, business_id
            LIMIT %s
        """).format(
            coordinates=sql.SQL(COORDINATES), location=sql.SQL(LOCATION),
            predicate=predicate, after=after,
        )
        params = [longitude, latitude, *filter_params, *after_params, limit + 1]
        rows = conn.execute(query, params).fetchall()
    if "cellCount" in diagnostics:
        response.headers["X-Lab-Cell-Count"] = str(diagnostics["cellCount"])
    page = rows[:limit]
    result = {
        "businesses": [
            {
                "businessId": row["business_id"], "name": row["name"],
                "latitude": row["latitude"], "longitude": row["longitude"],
                "distanceMeters": row["distance_meters"],
            }
            for row in page
        ],
        "nextCursor": _encode_cursor(context, page[-1]) if len(rows) > limit else None,
    }
    if mode in ("quadtree", "kd-tree", "s2", "h3"):
        result["diagnostics"] = diagnostics
    return result


class BusinessInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid", allow_inf_nan=False)
    name: str = Field(min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=80)
    address: str = Field(min_length=1, max_length=300)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


OWNERS = {"Bearer lab-owner-lee": "lee", "Bearer lab-owner-kim": "kim"}


@business_routes.post("/v1/businesses", status_code=201)
def create_business(
    body: BusinessInput,
    idempotency_key: Annotated[UUID4, Header(alias="Idempotency-Key")],
    authorization: Annotated[str | None, Header()] = None,
    simulate_loss: Annotated[bool, Header(alias="X-Lab-Lose-Response")] = False,
):
    owner_id = OWNERS.get(authorization)
    if owner_id is None:
        raise HTTPException(401, "Use a lab owner session", headers={"WWW-Authenticate": "Bearer"})

    fields = body.model_dump()
    for coordinate in ("latitude", "longitude"):
        fields[coordinate] = fields[coordinate] or 0.0
    fingerprint = hashlib.sha256(
        json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()
    ).digest()

    with pool.connection() as conn:
        claimed = conn.execute(
            """
            INSERT INTO creation_requests (owner_id, idempotency_key, request_fingerprint)
            VALUES (%s, %s, %s)
            ON CONFLICT (owner_id, idempotency_key) DO NOTHING
            RETURNING idempotency_key
            """,
            (owner_id, idempotency_key, fingerprint),
        ).fetchone()

        if claimed is None:
            saved = conn.execute(
                """
                SELECT request_fingerprint, response_status, response_body
                FROM creation_requests WHERE owner_id = %s AND idempotency_key = %s
                """,
                (owner_id, idempotency_key),
            ).fetchone()
            if saved["request_fingerprint"] != fingerprint:
                raise HTTPException(409, "This key already belongs to a different request")
            return JSONResponse(status_code=saved["response_status"], content=saved["response_body"])

        business_id = uuid4()
        row = conn.execute(
            sql.SQL("""
                INSERT INTO businesses (business_id, owner_id, name, category, address, location)
                VALUES (%s, %s, %s, %s, %s, {location})
                RETURNING created_at
            """).format(location=sql.SQL(LOCATION)),
            (business_id, owner_id, body.name, body.category, body.address, body.longitude, body.latitude),
        ).fetchone()
        store_cell_keys(conn, business_id, body.latitude, body.longitude)
        result = {
            "businessId": str(business_id),
            "status": "created",
            "createdAt": row["created_at"].isoformat(),
        }
        conn.execute(
            """
            UPDATE creation_requests SET business_id = %s, response_status = 201, response_body = %s
            WHERE owner_id = %s AND idempotency_key = %s
            """,
            (business_id, Jsonb(result), owner_id, idempotency_key),
        )

    if simulate_loss:
        return JSONResponse(
            status_code=503,
            headers={"Retry-After": "1"},
            content={"detail": "Lab simulated a lost reply after commit. Retry with the same key."},
        )
    return result


@business_routes.get("/v1/businesses/{business_id}")
def profile(business_id: UUID):
    with pool.connection() as conn:
        row = conn.execute(
            sql.SQL("""
                SELECT business_id AS "businessId", name, category, address,
                       {coordinates}, updated_at AS "updatedAt"
                FROM businesses WHERE business_id = %s
            """).format(coordinates=sql.SQL(COORDINATES)),
            (business_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Business not found")
    return row


FIXTURE_OWNER = "lab-fixtures"
FIXTURES = [
    ("10000000-0000-4000-8000-000000000001", "Sunny Coffee", "cafe", "100 Market Street", -122.4194, 37.7839),
    ("10000000-0000-4000-8000-000000000002", "Ada Books", "bookshop", "200 Market Street", -122.4194, 37.7659),
    ("10000000-0000-4000-8000-000000000003", "Kim Bakery", "bakery", "300 Market Street", -122.3910, 37.7974),
    ("10000000-0000-4000-8000-000000000004", "Oakland Tea", "cafe", "10 Broadway", -122.2712, 37.8044),
    ("10000000-0000-4000-8000-000000000005", "New York Deli", "deli", "10 Broadway", -74.0060, 40.7128),
]


@business_routes.post("/lab/fixtures")
def load_fixtures():
    query = sql.SQL("""
        INSERT INTO businesses (business_id, name, category, address, location, owner_id)
        VALUES (%s, %s, %s, %s, {location}, %s)
        ON CONFLICT (business_id) DO NOTHING
        RETURNING business_id
    """).format(location=sql.SQL(LOCATION))
    inserted = 0
    with pool.connection() as conn:
        for fixture in FIXTURES:
            row = conn.execute(query, (*fixture, FIXTURE_OWNER)).fetchone()
            if row:
                store_cell_keys(conn, row["business_id"], fixture[-1], fixture[-2])
                inserted += 1
    return {"inserted": inserted}


@business_routes.delete("/lab/fixtures")
def reset_fixtures():
    with pool.connection() as conn:
        result = conn.execute("DELETE FROM businesses WHERE owner_id = %s", (FIXTURE_OWNER,))
        return {"removed": result.rowcount}


@business_routes.get("/lab/state")
def inspect_store():
    with pool.connection() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        businesses = conn.execute(sql.SQL("""
            SELECT business_id, owner_id, name, category, address,
                   {coordinates}, geohash, created_at, updated_at
            FROM businesses ORDER BY created_at DESC, business_id LIMIT 20
        """).format(coordinates=sql.SQL(COORDINATES))).fetchall()
        requests = conn.execute("""
            SELECT owner_id, idempotency_key, encode(request_fingerprint, 'hex') AS request_fingerprint,
                   business_id, response_status, response_body, created_at
            FROM creation_requests ORDER BY created_at DESC, idempotency_key LIMIT 20
        """).fetchall()
    return {"businesses": businesses, "creation_requests": requests}


@business_routes.get("/lab/cells")
def inspect_cell_keys():
    with pool.connection() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        rows = []
        for method in ("s2", "h3"):
            rows.extend(conn.execute("""
                SELECT method, cell_id, b.business_id, b.name
                FROM business_cell_keys k JOIN businesses b USING (business_id)
                WHERE method = %s
                ORDER BY cell_id, b.business_id
                LIMIT 20
            """, (method,)).fetchall())
        totals = conn.execute("""
            SELECT method, count(*) AS total FROM business_cell_keys GROUP BY method ORDER BY method
        """).fetchall()
    return {"table": "business_cell_keys", "rows": rows, "totals": totals}


if ROLE == "search":
    if not CURSOR_SECRET:
        raise RuntimeError("Set CURSOR_SECRET for Search Service")
    app.include_router(search_routes)
elif ROLE == "business":
    app.include_router(business_routes)
else:
    raise RuntimeError(f"Unknown service role {ROLE}")
