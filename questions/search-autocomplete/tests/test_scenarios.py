"""Integration tests: yesterday's list, a fold, and a daily build that does not double-count."""

from __future__ import annotations


def texts(client, q: str) -> list[str]:
    r = client.get("/v1/suggestions", params={"q": q, "limit": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["layoutsAgree"] is True
    return [row["text"] for row in body["suggestions"]]


def test_prefix_returns_yesterdays_top_five(client):
    assert texts(client, "ki") == ["kitchen", "kim", "kitten", "kite", "kick"]
    assert texts(client, "k") == ["karate", "kangaroo", "kraft", "kitchen", "kim"]
    assert texts(client, "kitchenx") == []
    print("asserted: ki and k are yesterday's frequency order; kitchenx is empty")


def test_record_does_not_change_the_list_until_fold(client):
    before = texts(client, "ki")
    recorded = client.post("/v1/searches", json={"query": "kiosk", "count": 4500})
    assert recorded.status_code == 202
    assert recorded.json()["folded"] is False
    assert texts(client, "ki") == before
    folded = client.post("/v1/lab/fold")
    assert folded.status_code == 200
    after = texts(client, "ki")
    assert after[0] == "kitchen"
    assert "kiosk" in after
    assert "kick" not in after
    print(f"asserted: list unchanged until fold, then {after}")


def test_daily_build_absorbs_today_once(client):
    client.post("/v1/searches", json={"query": "kiosk", "count": 4500})
    client.post("/v1/lab/fold")
    once = texts(client, "ki")
    built = client.post("/v1/lab/daily-build")
    assert built.status_code == 200
    client.post("/v1/lab/fold")
    twice = texts(client, "ki")
    assert twice == once
    print("asserted: the daily build takes today's counts once; the next fold does not add them again")


def test_trie_and_hash_map_match_on_a_long_prefix(client):
    body = client.get("/v1/suggestions", params={"q": "kit", "limit": 5}).json()
    assert body["layoutsAgree"] is True
    assert body["trie"]["steps"][-1]["char"] == "t"
    assert body["hashMap"]["prefix"] == "kit"
    assert body["prefixCount"] > 200
    print(f"asserted: trie and hash map agree; {body['prefixCount']} prefixes in memory")
