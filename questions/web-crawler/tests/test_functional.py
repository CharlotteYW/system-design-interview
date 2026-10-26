"""Functional tests of what the user does on the lab page, through the same HTTP calls."""

from __future__ import annotations

from conftest import crawl, state, urls


def test_page_has_every_panel(client):
    html = client.get("/").text
    for text in ("Start a crawl", "API trace", "Scheduler on vs off", "three variants", "Race: two parsers",
                 "Crash the next fetch", "Redis politeness down"):
        assert text in html, text
    print("asserted: the lab page has the control, trace, scheduler, Bloom, race, and failure panels")


def test_start_crawl_and_read_status(client):
    r = client.post("/v1/crawls", json={"seeds": ["http://trap.test/"], "maxPages": 50, "maxDepth": 2})
    assert r.status_code == 202
    body = r.json()
    assert set(body) == {"crawlId", "status"} and body["status"] == "running"
    s, rows = crawl(client, seeds=["http://trap.test/"], maxPages=50, maxDepth=2)
    status = client.get(f"/v1/crawls/{s['crawlId']}").json()
    assert set(status) == {"crawlId", "status", "pagesFetched", "frontierSize", "domains"}
    assert status["status"] == "done" and status["pagesFetched"] >= 3 and status["frontierSize"] == 0
    assert client.get("/v1/crawls/nope").status_code == 404
    print(f"asserted: POST /v1/crawls -> 202 {{crawlId, status}}; GET status -> {status}")


def test_view_text_from_the_urls_card(client):
    rows = urls(client)
    page = next(u for u in rows.values() if u["state"] == "parsed" and "/calendar/" in u["url"])
    text = client.get(f"/v1/lab/text/{page['url_hash']}")
    assert text.status_code == 200 and "No events" in text.text
    print("asserted: the text link on a parsed row returns the stored text")


def test_bad_input_is_rejected(client):
    assert client.post("/v1/crawls", json={"seeds": ["http://kim.test/"], "politeness": "bogus"}).status_code == 422
    assert client.post("/v1/lab/race", json={"variant": "mongo"}).status_code == 422
    print("asserted: unknown modes and variants get 422")


def test_reset_empties_every_store(client):
    r = client.post("/v1/lab/reset")
    assert r.status_code == 200
    s = state(client)
    assert s["urlCount"] == 0 and s["contentHashes"] == 0
    assert s["s3"] == {"html": 0, "text": 0}
    assert s["status"] == "idle" and s["bloom"]["set"] == 0
    print("asserted: reset clears DynamoDB, SQS, S3, and Redis (run history kept)")
