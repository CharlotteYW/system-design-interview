from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest

from conftest import BASE_URL, OWNER

MODES = ("postgis", "full-scan", "geohash", "quadtree", "kd-tree", "s2", "h3")


def search(client, mode, latitude, longitude, radius=3000, limit=100, **extra):
    response = client.get(
        "/v1/nearby",
        params={"latitude": latitude, "longitude": longitude, "radiusMeters": radius, "limit": limit, **extra},
        headers={"X-Lab-Search-Mode": mode},
    )
    assert response.status_code == 200, response.text
    assert response.headers["X-Lab-Search-Mode"] == mode
    return response.json()


def ids(page):
    return [row["businessId"] for row in page["businesses"]]


def test_all_search_modes_agree_and_cross_a_cell_boundary(client, create):
    # A four-character Geohash longitude boundary is at -122.34375.
    near = create("across-cell-boundary", 37.7, -122.3435)
    within = create("in-radius", 37.708, -122.3438)
    corner = create("rectangle-corner", 37.7225, -122.3154)
    far = create("far", 37.74, -122.3438)
    results = [ids(search(client, mode, 37.7, -122.3438)) for mode in MODES]
    assert all(result == results[0] for result in results)
    assert results[0].index(near) < results[0].index(within)
    assert corner not in results[0] and far not in results[0]


@pytest.mark.parametrize(
    "center,shop",
    [((0, 179.999), (0, -179.999)), ((89.999, 0), (89.999, 180))],
    ids=["longitude-wrap", "north-pole"],
)
def test_search_modes_include_geographic_edges(client, create, center, shop):
    business = create("edge", *shop)
    pages = [search(client, mode, *center, radius=500) for mode in MODES]
    assert all(ids(page) == ids(pages[0]) for page in pages)
    assert business in ids(pages[0])
    assert "fallback" in pages[-1]["diagnostics"]


def test_advanced_modes_report_real_candidates_and_cell_keys(client, create):
    latitude, longitude = 42.205, -83.20
    business = create("advanced-candidate", latitude, longitude)
    create("advanced-near", latitude + 0.002, longitude)
    create("advanced-far", latitude + 1, longitude)
    for mode in ("quadtree", "kd-tree"):
        page = search(client, mode, latitude, longitude, radius=1000)
        assert business in ids(page)
        metrics = page["diagnostics"]
        assert metrics["nodesVisited"] > 1
        assert 0 < metrics["candidateCount"] < metrics["pointsLoaded"]
    s2 = search(client, "s2", latitude, longitude, radius=1000)
    assert business in ids(s2)
    assert s2["diagnostics"]["rangeSample"]
    h3 = search(client, "h3", latitude, longitude, radius=1000)
    assert business in ids(h3)
    assert h3["diagnostics"]["cellSample"]


def test_validation_and_missing_business(client, prefix):
    assert client.get("/v1/nearby", params={"latitude": 91, "longitude": 0}).status_code == 400
    assert client.get(f"/v1/businesses/{uuid4()}").status_code == 404
    body = {"name": prefix + "auth", "category": "cafe", "address": "1 Test", "latitude": 0, "longitude": 0}
    key = {"Idempotency-Key": str(uuid4())}
    assert client.post("/v1/businesses", headers=key, json=body).status_code == 401
    assert client.post("/v1/businesses", headers={**key, **OWNER}, json={**body, "name": " "}).status_code == 400


def test_concurrent_retries_share_one_business_and_changed_payload_conflicts(client, prefix):
    body = {"name": prefix + "concurrent", "category": "cafe", "address": "1 Test", "latitude": 2, "longitude": 2}
    headers = {**OWNER, "Idempotency-Key": str(uuid4())}

    def submit(_):
        return httpx.post(BASE_URL + "/v1/businesses", headers=headers, json=body, timeout=10)

    with ThreadPoolExecutor(max_workers=8) as executor:
        responses = list(executor.map(submit, range(8)))
    assert all(reply.status_code == 201 for reply in responses), [reply.text for reply in responses]
    result = responses[0].json()
    assert all(reply.json() == result for reply in responses)
    assert client.post("/v1/businesses", headers=headers, json={**body, "address": "2 Test"}).status_code == 409
    hits = search(client, "postgis", 2, 2, radius=10)["businesses"]
    assert [row["businessId"] for row in hits if row["name"] == body["name"]] == [result["businessId"]]


def test_cursor_survives_a_new_closer_business_and_checks_search_context(client, create):
    center = (-30.0, 130.0)
    first = create("first", -29.995, 130.0)
    second = create("second", -29.992, 130.0)
    third = create("third", -29.988, 130.0)
    page = search(client, "postgis", *center, limit=2)
    assert ids(page) == [first, second]
    assert page["nextCursor"]
    create("inserted-before-cursor", -29.997, 130.0)
    next_page = search(client, "postgis", *center, limit=2, cursor=page["nextCursor"])
    assert ids(next_page) == [third]
    assert next_page["nextCursor"] is None
    wrong_center = client.get(
        "/v1/nearby",
        params={"latitude": -31, "longitude": 130, "cursor": page["nextCursor"]},
    )
    assert wrong_center.status_code == 400


def test_cursor_uses_business_id_to_break_equal_distance_ties(client, create):
    first = create("same-point-a", -35.0, 150.0)
    second = create("same-point-b", -35.0, 150.0)
    page = search(client, "postgis", -35.0, 150.0, radius=10, limit=1)
    next_page = search(client, "postgis", -35.0, 150.0, radius=10, limit=1, cursor=page["nextCursor"])
    assert ids(page) + ids(next_page) == sorted([first, second])
