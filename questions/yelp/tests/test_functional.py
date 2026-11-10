from conftest import submit, wait_for_saved_or_failed


def test_city_search_modes_and_profile(api):
    assert "Yelp study lab" in api.get("/").raise_for_status().text
    places = api.get("/v1/places", params={"name": "San Francisco"}).raise_for_status().json()["places"]
    place = next(place for place in places if place["name"] == "San Francisco")
    filters = {"name": "ramen", "category": "restaurant"}
    base = "/v1/businesses/search"
    boundary = api.get(base, params={**filters, "placeId": place["placeId"]}).raise_for_status().json()["businesses"]
    membership = api.get(base, params={**filters, "placeId": place["placeId"], "areaMode": "membership"}).raise_for_status().json()["businesses"]
    radius = api.get(base, params={**filters, "lat": place["centerLat"], "lon": place["centerLon"], "radiusM": 3000}).raise_for_status().json()["businesses"]
    words = api.get(base, params={**filters, "placeId": place["placeId"], "nameMode": "words"}).raise_for_status().json()["businesses"]
    assert boundary == membership
    assert "sunset-ramen" in {row["businessId"] for row in boundary}
    assert "sunset-ramen" not in {row["businessId"] for row in radius}
    assert "outside-ramen" not in {row["businessId"] for row in boundary}
    assert "ramen-books" not in {row["businessId"] for row in boundary}
    assert "ramenhouse" in {row["businessId"] for row in boundary}
    assert "ramenhouse" not in {row["businessId"] for row in words}
    assert api.get("/v1/businesses/sunny-ramen").raise_for_status().json()["name"] == "Sunny Ramen"


def test_queued_review_appears_on_profile_and_in_my_reviews(api, catalog):
    user, _, business = catalog
    receipt = submit(api, user, business, "queued", text="Excellent service")
    assert receipt.status_code == 202
    review_id = wait_for_saved_or_failed(api, user, receipt.json()["submissionId"])["reviewId"]
    public = api.get(f"/v1/businesses/{business}/reviews").raise_for_status().json()["reviews"]
    assert public[0]["reviewId"] == review_id and public[0]["text"] == "Excellent service"
    mine = api.get("/v1/me/reviews", headers={"X-Demo-User": user}).raise_for_status().json()["reviews"]
    assert mine[0]["reviewId"] == review_id and mine[0]["businessName"] == "Test Place"
    results = api.get("/v1/businesses/search", params={"lat": 37.758, "lon": -122.419, "radiusM": 50,
                                                       "category": "test-only"}).raise_for_status().json()["businesses"]
    assert next(row for row in results if row["businessId"] == business)["averageRating"] == 5


def test_direct_review_is_saved_when_response_arrives(api, catalog):
    user, _, business = catalog
    response = submit(api, user, business, "direct", rating=4, mode="direct")
    assert response.status_code == 200
    review_id = response.json()["reviewId"]
    assert response.json()["status"] == "saved"
    retry = submit(api, user, business, "direct", rating=4, mode="direct")
    assert retry.json()["reviewId"] == review_id
    rows = api.get(f"/v1/businesses/{business}/reviews").raise_for_status().json()["reviews"]
    assert [(row["reviewId"], row["rating"]) for row in rows] == [(review_id, 4)]


def test_search_cache_reports_a_miss_then_a_hit(api):
    path = "/v1/businesses/search"
    params = {"placeId": "sf-mission", "name": "Pizza", "cacheMode": "shared"}
    first = api.get(path, params=params).raise_for_status()
    second = api.get(path, params=params).raise_for_status()
    assert second.headers["X-Study-Cache"] == "hit"
    assert first.json() == second.json()
