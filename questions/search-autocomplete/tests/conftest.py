from __future__ import annotations

import os

import httpx
import pytest

BASE_URL = os.environ.get("AC_BASE_URL", "http://localhost:8410")


@pytest.fixture
def client() -> httpx.Client:
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as http:
        http.post("/v1/lab/reset")
        yield http
