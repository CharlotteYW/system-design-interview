import os

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DATABASE_URL = os.environ["DATABASE_URL"]
pool = ConnectionPool(DATABASE_URL, kwargs={"row_factory": dict_row}, min_size=1,
                      max_size=8, timeout=3, open=False)


def add_rating(conn, business_id, stars, count=1):
    conn.execute("""
        INSERT INTO business_rating_stats VALUES (%s, %s, %s)
        ON CONFLICT (business_id) DO UPDATE SET
            rating_sum = business_rating_stats.rating_sum + EXCLUDED.rating_sum,
            review_count = business_rating_stats.review_count + EXCLUDED.review_count
    """, (business_id, stars, count))
