import subprocess
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

BASE_URL = "http://127.0.0.1:8430"
OWNER = {"Authorization": "Bearer lab-owner-lee"}
QUESTION_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10) as session:
        yield session


@pytest.fixture(scope="session")
def prefix():
    marker = f"test-{uuid4().hex}-"
    yield marker
    subprocess.run(
        [
            "docker", "compose", "exec", "-T", "postgres",
            "psql", "-U", "app", "-d", "proximity",
            "-v", "ON_ERROR_STOP=1", "-v", f"test_prefix={marker}",
        ],
        cwd=QUESTION_DIR,
        input="""
            BEGIN;
            DELETE FROM creation_requests
            USING businesses
            WHERE creation_requests.business_id = businesses.business_id
              AND starts_with(businesses.name, :'test_prefix');
            DELETE FROM businesses WHERE starts_with(name, :'test_prefix');
            COMMIT;
        """,
        text=True,
        check=True,
        timeout=15,
    )


@pytest.fixture
def create(client, prefix):
    def register(name, latitude, longitude):
        response = client.post(
            "/v1/businesses",
            headers={**OWNER, "Idempotency-Key": str(uuid4())},
            json={
                "name": prefix + name, "category": "cafe", "address": "100 Test Street",
                "latitude": latitude, "longitude": longitude,
            },
        )
        assert response.status_code == 201, response.text
        return response.json()["businessId"]
    return register
