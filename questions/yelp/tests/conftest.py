import subprocess
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:8440"


def sql(statement):
    return subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres", "psql", "-XAt", "-v", "ON_ERROR_STOP=1",
         "-U", "app", "-d", "yelp", "-c", statement],
        cwd=ROOT, check=True, text=True, capture_output=True,
    ).stdout.strip()


@pytest.fixture
def api():
    with httpx.Client(base_url=BASE_URL, timeout=8) as client:
        client.get("/healthz").raise_for_status()
        yield client


@pytest.fixture
def catalog():
    suffix = uuid4().hex[:12]
    user, second, business = f"u-{suffix}", f"v-{suffix}", f"b-{suffix}"
    sql(f"""
        INSERT INTO users VALUES ('{user}', 'Test Author'), ('{second}', 'Second Author');
        INSERT INTO businesses SELECT '{business}', 'Test Place', 'test-only', address, location
        FROM businesses WHERE business_id = 'sunny-ramen';
    """)
    try:
        yield user, second, business
    finally:
        sql(f"""
            DELETE FROM rating_outbox WHERE business_id = '{business}';
            DELETE FROM review_submissions WHERE business_id = '{business}';
            DELETE FROM reviews WHERE business_id = '{business}';
            DELETE FROM business_rating_stats WHERE business_id = '{business}';
            DELETE FROM businesses WHERE business_id = '{business}';
            DELETE FROM users WHERE user_id IN ('{user}', '{second}');
        """)


def submit(api, user, business, key, rating=5, mode="queued", text=None):
    return api.post(f"/v1/businesses/{business}/reviews", params={"mode": mode},
                    headers={"X-Demo-User": user, "Idempotency-Key": key},
                    json={"rating": rating, "text": text})


def check_status(api, user, submission_id):
    return api.get(f"/v1/review-submissions/{submission_id}", headers={"X-Demo-User": user})


def wait_for_saved_or_failed(api, user, submission_id):
    return wait_for(lambda: status_if_done(api, user, submission_id))


def status_if_done(api, user, submission_id):
    row = check_status(api, user, submission_id).raise_for_status().json()
    return row if row["status"] != "pending" else None


def wait_for(check, timeout=8):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = check()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError("Expected state did not arrive before timeout")
