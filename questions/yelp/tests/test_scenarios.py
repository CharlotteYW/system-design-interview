from concurrent.futures import ThreadPoolExecutor

from conftest import check_status, sql, submit, wait_for, wait_for_saved_or_failed


def test_invalid_input_and_author_only_status(api, catalog):
    user, other, business = catalog
    assert submit(api, user, business, "invalid", rating=0).status_code == 422
    receipt = submit(api, user, business, "valid")
    assert receipt.status_code == 202
    sid = receipt.json()["submissionId"]
    assert check_status(api, other, sid).status_code == 404
    assert wait_for_saved_or_failed(api, user, sid)["status"] == "saved"


def test_concurrent_retries_create_one_job_and_count_once(api, catalog):
    user, _, business = catalog
    with ThreadPoolExecutor(max_workers=8) as executor:
        receipts = list(executor.map(lambda _: submit(api, user, business, "same-request"), range(8)))
    assert {response.status_code for response in receipts} == {202}
    ids = {response.json()["submissionId"] for response in receipts}
    assert len(ids) == 1
    assert wait_for_saved_or_failed(api, user, ids.pop())["status"] == "saved"
    assert sql(f"SELECT rating_sum, review_count FROM business_rating_stats WHERE business_id = '{business}'") == "5|1"
    assert submit(api, user, business, "same-request", rating=4).status_code == 409


def test_different_keys_cannot_publish_two_reviews(api, catalog):
    user, _, business = catalog
    ids = [submit(api, user, business, key, rating=rating).raise_for_status().json()["submissionId"]
           for key, rating in [("phone", 5), ("laptop", 4)]]
    rows = [wait_for_saved_or_failed(api, user, sid) for sid in ids]
    assert {row["status"] for row in rows} == {"saved", "failed"}
    assert next(row for row in rows if row["status"] == "failed")["errorCode"] == "REVIEW_ALREADY_EXISTS"
    assert sql(f"SELECT review_count FROM business_rating_stats WHERE business_id = '{business}'") == "1"


def test_batch_applies_two_authors_once(api, catalog):
    first, second, business = catalog
    for user, rating in [(first, 3), (second, 5)]:
        response = submit(api, user, business, "batch", rating=rating, mode="queued-batch")
        assert response.status_code == 202
        assert wait_for_saved_or_failed(api, user, response.json()["submissionId"])["status"] == "saved"
    def both_applied():
        return sql(f"SELECT count(*) FROM rating_outbox WHERE business_id = '{business}' AND applied_at IS NOT NULL") == "2"
    wait_for(both_applied)
    assert sql(f"SELECT rating_sum, review_count FROM business_rating_stats WHERE business_id = '{business}'") == "8|2"


def test_direct_concurrent_increments_keep_both_ratings(api, catalog):
    first, second, business = catalog
    with ThreadPoolExecutor(max_workers=2) as executor:
        writes = [executor.submit(submit, api, user, business, "direct", rating, "direct")
                  for user, rating in [(first, 5), (second, 4)]]
    assert all(write.result().status_code == 200 for write in writes)
    assert sql(f"SELECT rating_sum, review_count FROM business_rating_stats WHERE business_id = '{business}'") == "9|2"
