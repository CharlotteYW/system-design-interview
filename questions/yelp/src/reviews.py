import os
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from psycopg import OperationalError
from psycopg_pool import PoolTimeout
from pydantic import BaseModel, Field

from .db import add_rating, pool
from .paging import PAGE_SIZE, cursor_scope, page, read_cursor

router = APIRouter()
QUEUE_LIMIT = int(os.getenv("REVIEW_QUEUE_LIMIT", "100"))
QUEUE_MAX_AGE = int(os.getenv("REVIEW_QUEUE_MAX_AGE", "300"))


class ReviewInput(BaseModel):
    rating: int = Field(ge=1, le=5, strict=True)
    text: str | None = Field(None, max_length=2000)


def author(x_demo_user: Annotated[str | None, Header(max_length=100)] = None):
    if not x_demo_user:
        raise HTTPException(401, "SIGN_IN_REQUIRED")
    with pool.connection() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE user_id = %s", (x_demo_user,)).fetchone():
            raise HTTPException(401, "UNKNOWN_DEMO_USER")
    return x_demo_user


def assert_business(conn, business_id):
    if not conn.execute("SELECT 1 FROM businesses WHERE business_id = %s", (business_id,)).fetchone():
        raise HTTPException(404, "BUSINESS_NOT_FOUND")


def list_reviews(cursor, *, business_id=None, user_id=None):
    scope = cursor_scope(business_id, user_id)
    position = read_cursor(cursor, scope)
    params = [business_id if business_id is not None else user_id]
    after = ""
    if position is not None:
        try:
            created_at, review_id = datetime.fromisoformat(position[0]), UUID(position[1])
            if created_at.tzinfo is None:
                raise ValueError
        except (AttributeError, TypeError, ValueError):
            raise HTTPException(400, "INVALID_CURSOR") from None
        after = "AND (r.created_at, r.review_id) < (%s, %s)"
        params.extend([created_at, review_id])
    params.append(PAGE_SIZE + 1)
    if business_id is not None:
        filter_column, extras, join = "r.business_id", "", ""
    else:
        filter_column = "r.user_id"
        extras = ', b.business_id AS "businessId", b.name AS "businessName"'
        join = "JOIN businesses b ON b.business_id = r.business_id"
    with pool.connection() as conn:
        if business_id is not None:
            assert_business(conn, business_id)
        rows = conn.execute(f"""
            SELECT r.review_id AS "reviewId", r.rating, r.text, r.created_at AS "createdAt" {extras}
            FROM reviews r {join} WHERE {filter_column} = %s {after}
            ORDER BY r.created_at DESC, r.review_id DESC LIMIT %s
        """, params).fetchall()
    rows, next_cursor = page(rows, scope, "createdAt", "reviewId")
    return {"reviews": rows, "nextCursor": next_cursor}


@router.get("/v1/businesses/{business_id}/reviews")
def business_reviews(business_id: str, cursor: Annotated[str | None, Query(max_length=400)] = None):
    return list_reviews(cursor, business_id=business_id)


@router.get("/v1/me/reviews")
def my_reviews(user_id: Annotated[str, Depends(author)],
               cursor: Annotated[str | None, Query(max_length=400)] = None):
    return list_reviews(cursor, user_id=user_id)


def require_same_payload(existing, business_id, body, batch_rating=None):
    if (existing["business_id"], existing["rating"], existing["text"]) != (business_id, body.rating, body.text):
        raise HTTPException(409, "IDEMPOTENCY_KEY_REUSED")
    if batch_rating is not None and existing["batch_rating"] != batch_rating:
        raise HTTPException(409, "IDEMPOTENCY_KEY_REUSED")


def queue_review(conn, user_id, business_id, key, body, batch_rating):
    # Serialize only the lab's admission check and insert. Workers do not take this lock.
    conn.execute("SELECT pg_advisory_xact_lock(8440)")
    existing = conn.execute("""
        SELECT submission_id, business_id, rating, text, batch_rating FROM review_submissions
        WHERE user_id = %s AND idempotency_key = %s
    """, (user_id, key)).fetchone()
    if existing:
        require_same_payload(existing, business_id, body, batch_rating)
        return existing["submission_id"]
    backlog = conn.execute("""
        SELECT count(*) AS jobs,
               COALESCE(extract(epoch FROM clock_timestamp() - min(created_at)), 0) AS age
        FROM review_submissions WHERE status = 'pending'
    """).fetchone()
    if backlog["jobs"] >= QUEUE_LIMIT or backlog["age"] >= QUEUE_MAX_AGE:
        raise HTTPException(503, "REVIEW_QUEUE_BUSY", headers={"Retry-After": "5"})
    return conn.execute("""
        INSERT INTO review_submissions (user_id, business_id, idempotency_key, rating, text, batch_rating)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING submission_id
    """, (user_id, business_id, key, body.rating, body.text, batch_rating)).fetchone()["submission_id"]


def save_direct(conn, user_id, business_id, key, body):
    row = conn.execute("""
        INSERT INTO reviews (user_id, business_id, rating, text, direct_retry_key)
        VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING review_id
    """, (user_id, business_id, body.rating, body.text, key)).fetchone()
    if row:
        add_rating(conn, business_id, body.rating)
        return row["review_id"]
    existing = conn.execute("""
        SELECT review_id, business_id, rating, text FROM reviews
        WHERE user_id = %s AND direct_retry_key = %s
    """, (user_id, key)).fetchone()
    if existing:
        require_same_payload(existing, business_id, body)
        return existing["review_id"]
    raise HTTPException(409, "REVIEW_ALREADY_EXISTS")


@router.post("/v1/businesses/{business_id}/reviews")
def submit(business_id: str, body: ReviewInput, user_id: Annotated[str, Depends(author)],
           key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=120)],
           mode: Literal["queued", "direct", "queued-batch"] = "queued"):
    with pool.connection() as conn:
        assert_business(conn, business_id)
        if mode == "direct":
            review_id = save_direct(conn, user_id, business_id, key, body)
            status, result = 200, {"reviewId": str(review_id), "status": "saved"}
        else:
            submission_id = queue_review(conn, user_id, business_id, key, body, mode == "queued-batch")
            status, result = 202, {"submissionId": str(submission_id), "status": "accepted"}
    return JSONResponse(result, status_code=status)


@router.get("/v1/review-submissions/{submission_id}")
def submission_status(submission_id: UUID,
                      user: Annotated[str | None, Header(alias="X-Demo-User", max_length=100)] = None):
    try:
        user_id = author(user)
        with pool.connection() as conn:
            row = conn.execute("""
                SELECT submission_id AS "submissionId", status, review_id AS "reviewId", error_code AS "errorCode"
                FROM review_submissions WHERE submission_id = %s AND user_id = %s
            """, (submission_id, user_id)).fetchone()
    except (OperationalError, PoolTimeout):
        raise HTTPException(503, "REVIEW_STATUS_UNAVAILABLE") from None
    if row is None:
        raise HTTPException(404, "SUBMISSION_NOT_FOUND")
    return {key: val for key, val in row.items() if val is not None}
