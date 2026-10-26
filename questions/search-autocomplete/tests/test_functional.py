"""Functional tests of the type box and the record button, through the same HTTP calls."""

from __future__ import annotations


def test_page_has_both_layouts_and_both_actions(client):
    html = client.get("/").text
    for text in ("Type a prefix", "Record a finished search", "Hash map", "Trie walk", "Fold now"):
        assert text in html, text
    print("asserted: the page has the box, the record button, and both layouts")


def test_get_and_post_shapes(client):
    got = client.get("/v1/suggestions", params={"q": "ca", "limit": 5})
    assert got.status_code == 200
    body = got.json()
    assert set(body["suggestions"][0]) == {"text", "frequency"}
    assert body["suggestions"][0]["text"] == "car"
    posted = client.post("/v1/searches", json={"query": "carpet"})
    assert posted.status_code == 202
    assert posted.json()["status"] == "recorded"
    state = client.get("/v1/lab/state", params={"q": "ca"}).json()
    assert state["pending"][0]["query"] == "carpet"
    assert state["pending"][0]["count"] == 1
    print("asserted: GET returns suggestions; POST records a row that is still pending")


def test_empty_query_is_rejected(client):
    assert client.post("/v1/searches", json={"query": "!!!"}).status_code == 422
    print("asserted: a query with no letters is rejected")
