from concurrent.futures import Future
from math import isfinite
from threading import Lock
from time import monotonic
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

from .db import pool
from .paging import PAGE_SIZE, cursor_scope, like_literal, page, read_cursor

router = APIRouter()
cache = {}
inflight = {}
cache_lock = Lock()


class Search(BaseModel):
    placeId: str | None = Field(None, max_length=100)
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    radiusM: int | None = Field(None, gt=0, le=50_000)
    name: str | None = Field(None, max_length=100)
    category: str | None = Field(None, max_length=50)
    cursor: str | None = Field(None, max_length=400)
    areaMode: Literal["boundary", "membership"] = "boundary"
    nameMode: Literal["contains", "words"] = "contains"
    cacheMode: Literal["off", "shared"] = "off"


@router.get("/v1/places")
def places(name: Annotated[str, Query(min_length=1, max_length=100)]):
    with pool.connection() as conn:
        rows = conn.execute("""
            SELECT place_id AS "placeId", name, region, kind,
                   ST_Y(center) AS "centerLat", ST_X(center) AS "centerLon"
            FROM places WHERE lower(name) LIKE lower(%s)
            ORDER BY name, region, place_id LIMIT 20
        """, (like_literal(name.strip()) + "%",)).fetchall()
    return {"places": rows}


def query_search(q, scope, cursor):
    with pool.connection() as conn:
        if q.placeId:
            if not conn.execute("SELECT 1 FROM places WHERE place_id = %s", (q.placeId,)).fetchone():
                raise HTTPException(404, "PLACE_NOT_FOUND")
            source = "businesses b CROSS JOIN places p"
            origin = "p.center::geography"
            if q.areaMode == "membership":
                source = ("businesses b JOIN business_places m ON m.business_id = b.business_id "
                          "JOIN places p ON p.place_id = m.place_id")
                conditions = ["p.place_id = %(place)s"]
            else:
                conditions = ["p.place_id = %(place)s", "ST_Covers(p.boundary, b.location)"]
        else:
            source = "businesses b"
            origin = "ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography"
            conditions = [f"ST_DWithin(b.location::geography, {origin}, %(radius)s)"]

        if q.name:
            conditions.append(
                "b.name ILIKE %(pattern)s" if q.nameMode == "contains"
                else "to_tsvector('simple', b.name) @@ plainto_tsquery('simple', %(name)s)"
            )
        if q.category:
            conditions.append("b.category = %(category)s")
        params = {"place": q.placeId, "lon": q.lon, "lat": q.lat, "radius": q.radiusM,
                  "name": q.name, "pattern": "%" + like_literal(q.name or "") + "%",
                  "category": q.category, "limit": PAGE_SIZE + 1}
        after = ""
        if cursor is not None:
            distance, business_id = cursor
            if type(distance) not in (int, float) or not isfinite(distance) or not isinstance(business_id, str):
                raise HTTPException(400, "INVALID_CURSOR")
            params.update(distance=distance, last_id=business_id)
            after = 'WHERE ("distanceM", "businessId") > (%(distance)s, %(last_id)s)'
        filters = " AND ".join(conditions)
        rows = conn.execute(f"""
            WITH candidates AS (
                SELECT b.business_id AS "businessId", b.name, b.category,
                       ST_Distance(b.location::geography, {origin}) AS "distanceM"
                FROM {source} WHERE {filters}
            ), page AS (
                SELECT * FROM candidates {after}
                ORDER BY "distanceM", "businessId" LIMIT %(limit)s
            )
            SELECT page.*, COALESCE(s.review_count, 0) AS "reviewCount",
                   s.rating_sum::float8 / s.review_count AS "averageRating"
            FROM page LEFT JOIN business_rating_stats s ON s.business_id = page."businessId"
            ORDER BY "distanceM", "businessId"
        """, params).fetchall()
    rows, next_cursor = page(rows, scope, "distanceM", "businessId")
    return {"businesses": rows, "nextCursor": next_cursor}


def cached_search(q, scope, cursor):
    key = (scope, q.cursor)
    with cache_lock:
        entry = cache.get(key)
        if entry and entry[0] > monotonic():
            return entry[1], "hit"
        refresh = inflight.get(key)
        if refresh is None:
            refresh = inflight[key] = Future()
            leader = True
        else:
            leader = False
    if not leader:
        return refresh.result(timeout=8), "shared refresh"
    try:
        result = query_search(q, scope, cursor)
        with cache_lock:
            if len(cache) >= 128:
                cache.pop(next(iter(cache)))
            cache[key] = (monotonic() + 3, result)
        refresh.set_result(result)
        return result, "miss"
    except Exception as exc:
        refresh.set_exception(exc)
        raise
    finally:
        with cache_lock:
            inflight.pop(key, None)


@router.get("/v1/businesses/search")
def search(q: Annotated[Search, Query()], response: Response):
    radius_fields = (q.lat, q.lon, q.radiusM)
    if (q.placeId and any(v is not None for v in radius_fields)
            or not q.placeId and any(v is None for v in radius_fields)):
        raise HTTPException(422, "SELECT_PLACE_OR_RADIUS")
    scope = cursor_scope(q.placeId, *radius_fields, q.name, q.category, q.areaMode, q.nameMode)
    cursor = read_cursor(q.cursor, scope)
    if q.cacheMode == "shared":
        try:
            result, status = cached_search(q, scope, cursor)
        except TimeoutError:
            raise HTTPException(503, "SEARCH_REFRESH_TIMEOUT") from None
    else:
        result, status = query_search(q, scope, cursor), "off"
    response.headers["X-Study-Cache"] = status
    return result


@router.get("/v1/businesses/{business_id}")
def business(business_id: str):
    with pool.connection() as conn:
        row = conn.execute("""
            SELECT business_id AS "businessId", name, category, address
            FROM businesses WHERE business_id = %s
        """, (business_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "BUSINESS_NOT_FOUND")
    return row
