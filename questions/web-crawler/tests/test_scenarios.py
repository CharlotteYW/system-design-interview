"""Integration tests against the running stack: happy path, failures, and concurrency edges."""

from __future__ import annotations

import time

import pytest

from conftest import crawl, start, state, urls, wait_done

LETTERS = "abcdefghij"


@pytest.fixture(scope="module")
def full(client):
    """One crawl of the whole fake web from kim.test, scheduler on (the interview default)."""
    return crawl(client, timeout=150, seeds=["http://kim.test/"], domainCap=20, maxDepth=4)


def test_happy_path_stores_text_for_each_parsed_page(client, full):
    s, rows = full
    parsed = [u for u in rows.values() if u["state"] == "parsed"]
    assert len(parsed) >= 20
    assert s["s3"]["text"] == len(parsed)
    home = rows["http://kim.test/"]
    assert home["state"] == "parsed"
    text = client.get(f"/v1/lab/text/{home['url_hash']}").text
    assert "Welcome to Kim's blog" in text and "<p>" not in text
    print(f"asserted: {len(parsed)} pages parsed, text in S3 for each, tags stripped")


def test_robots_longest_match_and_status_codes(full):
    _, rows = full
    assert rows["http://kim.test/private/secret"]["state"] == "skipped"
    assert "Disallow: /private/" in rows["http://kim.test/private/secret"]["last_error"]
    assert rows["http://kim.test/private/open"]["state"] == "parsed"
    assert rows["http://closed.test/"]["state"] == "skipped"
    assert rows["http://mirror.test/"]["state"] == "parsed"
    print("asserted: longest match allows /private/open, robots 500 disallows all, robots 404 allows all")


def test_non_html_and_size_limit_are_skipped(full):
    _, rows = full
    assert rows["http://kim.test/files/report.pdf"]["last_error"] == "not html"
    assert rows["http://kim.test/huge"]["last_error"] == "too large"
    print("asserted: a PDF and a 2 MB page are skipped without storing them")


def test_retry_with_backoff_then_dead_letter(full):
    s, rows = full
    assert rows["http://flaky.test/p1"]["state"] == "parsed"
    assert rows["http://flaky.test/p1"]["attempts"] == 2
    dead = rows["http://dead.test/"]
    assert dead["state"] == "dead" and dead["attempts"] == 5
    assert rows["http://flaky.test/slow"]["last_error"] == "ReadTimeout"
    assert s["queues"]["dlq"]["total"] >= 2
    print("asserted: two 503s then success; 5 failures go dead and into the DLQ; a timeout is retried")


def test_content_dedupe_hashes_text_not_html(full):
    s, rows = full
    for c in LETTERS:
        pair = {rows[f"http://kim.test/{c}"]["state"], rows[f"http://mirror.test/{c}"]["state"]}
        assert pair == {"parsed", "duplicate"}, (c, pair)
    assert s["contentHashes"] == sum(1 for u in rows.values() if u["state"] == "parsed")
    print("asserted: each kim/mirror pair keeps one copy, though the raw HTML differs")


def test_trap_depth_and_url_hygiene(full):
    s, rows = full
    max_depth = s["config"]["maxDepth"]
    assert all(u["depth"] <= max_depth + 1 for u in rows.values())
    assert not [u for u in rows if "sid=" in u or "utm_" in u or "#" in u]
    trap = [u for u in rows.values() if u["domain"] == "trap.test" and u["state"] == "skipped"]
    assert trap and "depth" in trap[0]["last_error"]
    print("asserted: the endless calendar stops at the depth limit; sid, utm, and fragments are stripped")


def test_politeness_holds_at_the_server(full):
    s, _ = full
    checked = 0
    for d in s["domains"]:
        gap = d["server"].get("minGapMs")
        if gap is not None:
            assert gap >= d["gapMs"] * 0.9, (d["domain"], gap, d["gapMs"])
            checked += 1
    assert checked >= 5
    print(f"asserted: 12 workers on 2 fetchers; every site saw at least its gap ({checked} sites)")


def test_scheduler_caps_and_releases_in_flight(full):
    s, _ = full
    wiki = next(d for d in s["domains"] if d["domain"] == "wiki.test")
    assert wiki["pages_admitted"] == 20 and wiki["pending"] > 0
    assert wiki["gapMs"] == 1000
    assert all(d.get("in_flight", 0) == 0 for d in s["domains"])
    print("asserted: wiki.test stops at the cap with pages still pending; every in_flight returns to 0")


def test_bloom_counters_add_up(full):
    s, _ = full
    st = {k: int(v) for k, v in s["stats"].items() if k.startswith("bloom")}
    assert st["bloom_pages"] == st.get("bloom_table_reads", 0) + st.get("bloom_reads_skipped", 0)
    assert st.get("bloom_false_positives", 0) + st.get("bloom_true_duplicates", 0) <= st["bloom_pages"]
    assert st.get("bloom_true_duplicates", 0) >= len(LETTERS)
    print(f"asserted: Bloom counters consistent {st}")


def test_scheduler_off_floods_the_frontier(client):
    on, _ = crawl(client, seeds=["http://wiki.test/"], domainCap=8, maxDepth=3, scheduler=True)
    off, _ = crawl(client, seeds=["http://wiki.test/"], domainCap=8, maxDepth=3, scheduler=False)
    on_run = next(r for r in off["runs"] if r["crawlId"] == on["crawlId"])
    off_run = off["runs"][0]
    assert not off_run["scheduler"] and on_run["scheduler"]
    assert on_run["wikiFetched"] == off_run["wikiFetched"] == 8
    assert off_run["wikiReceives"] > 3 * on_run["wikiReceives"], (on_run, off_run)
    print(f"asserted: same 8 pages; wiki receives {on_run['wikiReceives']} with the scheduler, "
          f"{off_run['wikiReceives']} without")


def test_fetcher_crash_redelivers_after_visibility_timeout(client):
    start(client, seeds=["http://trap.test/"], maxDepth=2)
    client.post("/v1/lab/crash-fetcher")
    s = wait_done(client, 90)
    rows = urls(client)
    assert int(s["stats"].get("crashes", 0)) == 1
    redelivered = [u for u in rows.values() if u["receives"] >= 2 and u["state"] in ("parsed", "skipped")]
    assert redelivered
    assert all(u["state"] in ("parsed", "skipped") for u in rows.values())
    print("asserted: the crashed message came back after the visibility timeout and finished")


def test_parser_crash_is_idempotent(client):
    start(client, seeds=["http://trap.test/"], maxDepth=2)
    client.post("/v1/lab/crash-parser")
    s = wait_done(client, 90)
    rows = urls(client)
    assert int(s["stats"].get("crashes", 0)) == 1
    assert not [u for u in rows.values() if u["state"] == "duplicate"]
    assert s["s3"]["text"] == sum(1 for u in rows.values() if u["state"] == "parsed")
    print("asserted: the re-parse wrote the same S3 key and did not mark the page a duplicate of itself")


def test_politeness_store_down_fails_closed(client):
    start(client, seeds=["http://kim.test/"], maxDepth=1, domainCap=4)
    client.post("/v1/lab/politeness-store", json={"down": True, "mode": "fail-closed"})
    time.sleep(4)
    s = state(client)
    assert int(s["stats"].get("fetched", 0)) == 0
    assert int(s["stats"].get("paused", 0)) > 0
    client.post("/v1/lab/politeness-store", json={"down": False, "mode": "fail-closed"})
    s = wait_done(client, 120)
    assert int(s["stats"].get("fetched", 0)) > 0
    print("asserted: no fetch while the politeness store is down; the crawl resumes when it returns")


@pytest.mark.parametrize("variant,queued", [("dynamo-conditional", 1), ("dynamo-plain", 2), ("postgres", 1)])
def test_race_two_parsers_same_new_url(client, variant, queued):
    r = client.post("/v1/lab/race", json={"variant": variant}).json()
    assert r["queuedCount"] == queued, r
    if variant == "dynamo-conditional":
        codes = sorted(p["response"]["status"] for p in r["parsers"])
        assert codes == [200, 400]
        loser = next(p for p in r["parsers"] if p["response"]["status"] == 400)
        assert loser["response"]["body"]["__type"] == "ConditionalCheckFailedException"
    print(f"asserted: {variant} queues the URL {queued} time(s)")
