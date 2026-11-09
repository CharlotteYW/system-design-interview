from uuid import uuid4

from conftest import OWNER


def test_gateway_serves_the_browser_lab_and_assets(client):
    page = client.get("/")
    assert page.status_code == 200
    for label in ("Compare search methods", "Retry saved submission", "Refresh tables"):
        assert label in page.text
    script = client.get("/app.js")
    assert script.status_code == 200
    assert "/v1/nearby?" in script.text and "/v1/businesses" in script.text
    assert client.get("/style.css").status_code == 200


def test_advanced_page_has_the_chooser_and_reads_the_shared_cell_table(client, create):
    create("advanced-page", 40.2, -105.2)
    page = client.get("/advanced.html")
    assert page.status_code == 200
    for label in ("Compare advanced methods", "Refresh cell keys", "Which method should I choose?"):
        assert label in page.text
    inspection = client.get("/lab/cells")
    assert inspection.status_code == 200, inspection.text
    payload = inspection.json()
    assert payload["table"] == "business_cell_keys"
    counts = {row["method"]: row["total"] for row in payload["totals"]}
    assert counts["s2"] == counts["h3"] > 0


def test_register_after_lost_reply_open_profile_and_find_on_map(client, prefix):
    key = str(uuid4())
    headers = {**OWNER, "Idempotency-Key": key}
    body = {
        "name": prefix + "functional", "category": "cafe", "address": "123 Test Avenue",
        "latitude": 35.25, "longitude": -110.25,
    }
    ambiguous = client.post("/v1/businesses", headers={**headers, "X-Lab-Lose-Response": "true"}, json=body)
    assert ambiguous.status_code == 503
    store = client.get("/lab/state")
    assert store.status_code == 200, store.text
    receipt = next(row for row in store.json()["creation_requests"] if row["idempotency_key"] == key)
    retry = client.post("/v1/businesses", headers=headers, json=body)
    assert retry.status_code == 201
    assert retry.json() == receipt["response_body"]
    business_id = retry.json()["businessId"]
    assert receipt["business_id"] == business_id
    profile = client.get(f"/v1/businesses/{business_id}")
    assert profile.status_code == 200
    assert profile.json()["address"] == body["address"]
    nearby = client.get("/v1/nearby", params={"latitude": body["latitude"], "longitude": body["longitude"]})
    assert nearby.status_code == 200
    assert any(row["businessId"] == business_id for row in nearby.json()["businesses"])
