import logging
from collections import defaultdict
from time import monotonic, sleep

import psycopg
from psycopg.rows import dict_row

from .db import DATABASE_URL, add_rating

log = logging.getLogger(__name__)


def publish_one(conn):
    with conn.transaction():
        job = conn.execute("""
            SELECT * FROM review_submissions
            WHERE status = 'pending' AND next_attempt_at <= now()
            ORDER BY created_at, submission_id LIMIT 1 FOR UPDATE SKIP LOCKED
        """).fetchone()
        if not job:
            return False
        try:
            with conn.transaction():
                conn.execute("SET LOCAL lock_timeout = '750ms'")
                review = conn.execute("""
                    INSERT INTO reviews (user_id, business_id, rating, text)
                    VALUES (%(user_id)s, %(business_id)s, %(rating)s, %(text)s)
                    ON CONFLICT (user_id, business_id) DO NOTHING RETURNING review_id
                """, job).fetchone()
                if not review:
                    conn.execute("""
                        UPDATE review_submissions SET status = 'failed', error_code = 'REVIEW_ALREADY_EXISTS'
                        WHERE submission_id = %s
                    """, (job["submission_id"],))
                    return True
                if job["batch_rating"]:
                    conn.execute("INSERT INTO rating_outbox (review_id, business_id, rating) VALUES (%s, %s, %s)",
                                 (review["review_id"], job["business_id"], job["rating"]))
                else:
                    add_rating(conn, job["business_id"], job["rating"])
                conn.execute("""
                    UPDATE review_submissions SET status = 'saved', review_id = %s WHERE submission_id = %s
                """, (review["review_id"], job["submission_id"]))
        except (psycopg.errors.LockNotAvailable, psycopg.errors.DeadlockDetected):
            conn.execute("""
                UPDATE review_submissions SET attempt_count = attempt_count + 1,
                    next_attempt_at = now() + interval '1 second'
                WHERE submission_id = %s
            """, (job["submission_id"],))
    return True


def apply_ratings(conn):
    with conn.transaction():
        rows = conn.execute("""
            SELECT review_id, business_id, rating FROM rating_outbox WHERE applied_at IS NULL
            ORDER BY created_at, review_id LIMIT 5000 FOR UPDATE SKIP LOCKED
        """).fetchall()
        if not rows:
            return
        grouped = defaultdict(list)
        for row in rows:
            grouped[row["business_id"]].append(row["rating"])
        for business_id, ratings in sorted(grouped.items()):
            add_rating(conn, business_id, sum(ratings), len(ratings))
        conn.execute("UPDATE rating_outbox SET applied_at = now() WHERE review_id = ANY(%s)",
                     ([row["review_id"] for row in rows],))


def run():
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            with psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True) as conn:
                next_batch = monotonic() + 2
                while True:
                    if monotonic() >= next_batch:
                        apply_ratings(conn)
                        next_batch = monotonic() + 2
                    if not publish_one(conn):
                        sleep(0.15)
        except psycopg.Error:
            log.exception("Review worker database operation failed. Retrying.")
            sleep(1)


if __name__ == "__main__":
    run()
