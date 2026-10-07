"""The page lists each connection the user can click."""

from __future__ import annotations

import os
import re

import httpx

BASE = os.environ.get("API_BASE_URL", "http://localhost:8000")


def test_page_lists_the_connections() -> None:
    with httpx.Client(base_url=BASE, timeout=5.0) as client:
        html = client.get("/").text
        headings = [
            re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", heading)).strip()
            for heading in re.findall(r"<h2>(.*?)</h2>", html, flags=re.S)
        ]
        order = (
            "The stack",
            "Application layer",
            "REST",
            "GraphQL",
            "gRPC",
            "Server-Sent Events",
            "WebSocket",
            "WebRTC",
            "HLS and DASH",
            "Long polling",
            "HTTP / HTTP/2",
            "TLS / DTLS",
            "TCP and UDP",
            "IP",
            "Client-side balancer",
            "L4 and L7",
            "Timeout and backoff",
            "Idempotency",
            "Circuit breaker",
        )
        cursor = 0
        for heading in headings:
            if cursor < len(order) and heading.startswith(order[cursor]):
                cursor += 1
        assert cursor == len(order)
        assert "Round trip" in html
        assert "Usual job" in html
        assert "Use it when" in html
        assert html.count("Most common use.") >= 16
        for marker in ("DNS cache", "Service discovery", "Registry push", "Health check", "MOVED"):
            assert marker in html
        body = client.get("/api/http", params={"region": "local"}).json()
        assert body["protocol"] == "HTTP"
