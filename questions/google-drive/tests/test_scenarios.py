import concurrent.futures
import time
import uuid

from conftest import begin, checksum, client_for, commit, download, metadata, ok, snapshot, stage


def test_lost_creation_and_completion_reply_are_one_operation(client):
    c = client
    data = stage(c, [b"A" * 100, b"B" * 100])
    replay = ok(c.post("/v1/uploads", json=data["body"], headers={"Idempotency-Key": data["key"]}), 201)
    assert replay["uploadId"] == data["uploadId"]
    mismatch = c.post("/v1/uploads", json={**data["body"], "name": "another.txt"}, headers={"Idempotency-Key": data["key"]})
    assert mismatch.status_code == 409
    ok(c.post("/v1/lab/faults", json={"drop_completion_reply": True}))
    lost = c.post("/v1/uploads/" + data["uploadId"] + "/complete", json={})
    assert lost.status_code == 503
    assert lost.json()["code"] == "simulated_reply_lost_after_commit"
    first = commit(c, data)
    again = commit(c, data)
    assert first == again
    state = snapshot(c)
    assert state["counts"]["uploads"] == state["counts"]["files"] == state["counts"]["manifests"] == state["counts"]["outbox"] == 1
    assert state["postgres"]["files"][0]["revision"] == 1
    assert state["counts"]["changes"] == 1


def test_concurrent_duplicate_creation_and_completion(client):
    key = str(uuid.uuid4())
    body = {"name": "one.txt", "sizeBytes": 0, "mimeType": "text/plain", "mode": "independent-chunks"}
    def create(_):
        with client_for() as c:
            return ok(c.post("/v1/uploads", json=body, headers={"Idempotency-Key": key}), 201)["uploadId"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        ids = list(pool.map(create, range(6)))
    assert len(set(ids)) == 1
    uid = ids[0]
    ok(client.put("/v1/uploads/" + uid + "/manifest", json={"chunking": {"algorithm": "whole"}, "chunks": []}))
    def finish(_):
        with client_for() as c:
            return ok(c.post("/v1/uploads/" + uid + "/complete", json={}))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(finish, range(4)))
    assert all(x == results[0] for x in results)
    assert snapshot(client)["counts"]["outbox"] == 1


def test_provider_rejects_damage_and_create_only_retry_is_reconciled(client):
    created, _, _ = begin(client, [b"expected bytes"])
    entry, stored = metadata(b"expected bytes", 0)
    ok(client.put("/v1/uploads/" + created["uploadId"] + "/manifest", json={"chunks": [entry]}))
    permission = ok(client.post("/v1/uploads/" + created["uploadId"] + "/chunk-upload-urls", json={"ordinals": [0]}))["chunks"][0]
    bad = client.put(permission["url"], content=b"damaged bytes!", headers=permission["headers"])
    assert bad.status_code == 400
    assert client.put(permission["url"], content=stored).status_code == 200
    assert client.put(permission["url"], content=stored).status_code == 412
    result = ok(client.post("/v1/uploads/" + created["uploadId"] + "/chunks/0/complete", json={}))
    assert result["state"] == "verified" and not result["sha256Verified"]
    assert snapshot(client)["redis"]["metrics"].get("drive_hash_bytes", "0") == "0"


def test_database_outage_does_not_repeat_uploaded_bytes(client):
    item = stage(client, [b"stored before the outage"])
    before = snapshot(client)["redis"]["metrics"]["storage_puts"]
    ok(client.post("/v1/lab/faults", json={"db_down": True}))
    response = client.post("/v1/uploads/" + item["uploadId"] + "/complete", json={})
    assert response.status_code == 503 and response.json()["code"] == "metadata_unavailable"
    ok(client.post("/v1/lab/faults", json={"db_down": False}))
    result = commit(client, item)
    assert result["status"] == "ready"
    assert snapshot(client)["redis"]["metrics"]["storage_puts"] == before


def test_same_base_conflict_and_repeat_safe_private_copy(client):
    original = commit(client, stage(client, [b"revision one"]))
    left = stage(client, [b"laptop edit"], target=original["fileId"], base=1)
    right = stage(client, [b"phone edit"], target=original["fileId"], base=1)
    assert commit(client, left)["revision"] == 2
    stale = client.post("/v1/uploads/" + right["uploadId"] + "/complete", json={})
    assert stale.status_code == 409 and stale.json()["code"] == "revision_conflict"
    key = str(uuid.uuid4())
    copy = ok(client.post("/v1/uploads/" + right["uploadId"] + "/conflict-copy", json={"name": "phone conflict.txt"}, headers={"Idempotency-Key": key}), 201)
    replay = ok(client.post("/v1/uploads/" + right["uploadId"] + "/conflict-copy", json={"name": "phone conflict.txt"}, headers={"Idempotency-Key": key}), 201)
    assert copy == replay and copy["fileId"] != original["fileId"]
    assert download(client, original["fileId"])[0] == b"laptop edit"
    assert download(client, copy["fileId"])[0] == b"phone edit"
    assert snapshot(client)["counts"]["files"] == 2


def test_last_write_wins_comparison_accepts_second_stale_replacement(client):
    original = commit(client, stage(client, [b"base"]))
    a = stage(client, [b"one"], target=original["fileId"], base=1, conflictPolicy="last_write_wins")
    b = stage(client, [b"two"], target=original["fileId"], base=1, conflictPolicy="last_write_wins")
    assert commit(client, a)["revision"] == 2
    assert commit(client, b)["revision"] == 3
    assert download(client, original["fileId"])[0] == b"two"


def test_fanout_crash_checkpoint_and_offline_recipient_replay(client):
    original = commit(client, stage(client, [b"old"]))
    ok(client.post("/v1/lab/fanout/run", json={"batch": 100}))
    ok(client.post("/v1/files/" + original["fileId"] + "/shares", json={"recipientId": "kim", "role": "reader"}))
    ok(client.post("/v1/lab/recipients", json={"fileId": original["fileId"], "count": 40}))
    update = commit(client, stage(client, [b"new"], target=original["fileId"], base=1))
    ok(client.post("/v1/lab/faults", json={"crash_after_job_claim": True, "drop_hints": True}))
    claim = ok(client.post("/v1/lab/fanout/run", json={"batch": 7}))
    assert claim["simulatedCrash"]
    assert ok(client.post("/v1/lab/fanout/run", json={"batch": 7}))["idle"]
    ok(client.post("/v1/lab/advance", json={"seconds": 11}))
    for _ in range(9):
        ok(client.post("/v1/lab/fanout/run", json={"batch": 7}))
    with client_for("kim") as kim:
        changes = ok(kim.get("/v1/changes?cursor=0"))["changes"]
        assert any(x["revision"] == 2 and x["type"] == "updated" for x in changes)
    before = snapshot(client)["counts"]["changes"]
    ok(client.post("/v1/lab/fanout/run", json={"batch": 7}))
    assert snapshot(client)["counts"]["changes"] == before
    job = next(x for x in snapshot(client)["postgres"]["outbox"] if x["id"] == update["discovery"]["eventId"])
    assert job["state"] == "done" and job["processed"] == 41


def test_real_worker_consumes_durable_job(client):
    file = commit(client, stage(client, [b"base"]))
    ok(client.post("/v1/lab/fanout/run", json={"batch": 100}))
    ok(client.post("/v1/files/" + file["fileId"] + "/shares", json={"recipientId": "kim"}))
    result = commit(client, stage(client, [b"changed"], target=file["fileId"], base=1))
    ok(client.post("/v1/lab/faults", json={"worker_paused": False}))
    deadline = time.time() + 12
    while time.time() < deadline:
        events = snapshot(client)["postgres"]["outbox"]
        if any(x["id"] == result["discovery"]["eventId"] and x["state"] == "done" for x in events):
            break
        time.sleep(0.2)
    else:
        raise AssertionError("real worker did not finish the durable event")


def test_private_cache_checks_expiry_and_live_authorization(client):
    original = commit(client, stage(client, [b"private repeated content"]))
    fid = original["fileId"]
    ok(client.post("/v1/files/" + fid + "/shares", json={"recipientId": "kim"}))
    with client_for("ada") as ada:
        assert ada.post("/v1/downloads", json={"fileId": fid}).status_code == 403
    with client_for("kim") as kim:
        ds = ok(kim.post("/v1/downloads", json={"fileId": fid}), 201)
        manifest = ok(kim.get("/v1/downloads/" + ds["downloadId"] + "/manifest"))
        cid = manifest["chunks"][0]["chunkId"]
        url = ok(kim.post("/v1/downloads/" + ds["downloadId"] + "/chunk-download-urls", json={"chunkIds": [cid], "delivery": "cdn"}))["chunks"][0]["url"]
        a, b = kim.get(url), kim.get(url)
        assert a.status_code == b.status_code == 200
        assert a.headers["x-cache"] == "MISS" and b.headers["x-cache"] == "HIT"
        ok(client.delete("/v1/files/" + fid + "/shares/kim"), 204)
        assert kim.post("/v1/downloads/" + ds["downloadId"] + "/chunk-download-urls", json={"chunkIds": [cid]}).status_code == 403
        assert kim.get("/v1/downloads/" + ds["downloadId"] + "/manifest").status_code == 403
        assert kim.get(url).status_code == 200
        ok(client.post("/v1/lab/advance", json={"seconds": 40}))
        assert kim.get(url).status_code == 403
        assert kim.get(url.replace("ticket=", "ticket=modified")).status_code == 403


def test_download_is_pinned_then_lease_expiry_stops_resume(client):
    original = commit(client, stage(client, [b"old-A", b"old-B"]))
    ds = ok(client.post("/v1/downloads", json={"fileId": original["fileId"]}), 201)
    commit(client, stage(client, [b"new-A", b"new-B"], target=original["fileId"], base=1))
    manifest = ok(client.get("/v1/downloads/" + ds["downloadId"] + "/manifest"))
    assert manifest["revision"] == 1
    urls = ok(client.post("/v1/downloads/" + ds["downloadId"] + "/chunk-download-urls", json={"chunkIds": [x["chunkId"] for x in manifest["chunks"]]}))
    data = b"".join(client.get(next(x["url"] for x in urls["chunks"] if x["chunkId"] == e["chunkId"])).content for e in manifest["chunks"])
    assert data == b"old-Aold-B"
    ok(client.post("/v1/lab/advance", json={"seconds": 200}))
    assert client.get("/v1/downloads/" + ds["downloadId"] + "/manifest").status_code == 410


def test_reuse_and_gc_preserve_other_file_and_active_lease(client):
    original = commit(client, stage(client, [b"A" * 30, b"B" * 30, b"C" * 30]))
    ds = ok(client.post("/v1/downloads", json={"fileId": original["fileId"]}), 201)
    source = ok(client.get("/v1/downloads/" + ds["downloadId"] + "/manifest"))
    copy, _, _ = begin(client, [b"A" * 30, b"X" * 30, b"C" * 30], name="copy.txt")
    new, raw = metadata(b"X" * 30, 1)
    chunks = [{"ordinal": 0, "reuseFrom": {"fileId": original["fileId"], "manifestId": original["manifestId"], "ordinal": 0}}, new,
              {"ordinal": 2, "reuseFrom": {"fileId": original["fileId"], "manifestId": original["manifestId"], "ordinal": 2}}]
    plan = ok(client.put("/v1/uploads/" + copy["uploadId"] + "/manifest", json={"chunks": chunks}))
    assert [x["uploadRequired"] for x in plan["chunks"]] == [False, True, False]
    url = ok(client.post("/v1/uploads/" + copy["uploadId"] + "/chunk-upload-urls", json={"ordinals": [1]}))["chunks"][0]["url"]
    assert client.put(url, content=raw).status_code == 200
    result = ok(client.post("/v1/uploads/" + copy["uploadId"] + "/complete", json={}))
    abandoned = stage(client, [b"Y" * 30, b"Z" * 30])
    ok(client.delete("/v1/files/" + original["fileId"]), 204)
    ok(client.post("/v1/lab/advance", json={"seconds": 40}))
    first = ok(client.post("/v1/lab/gc/run", json={"grace": 0}))
    bid = source["chunks"][1]["chunkId"]
    assert bid in first["kept"]
    ok(client.post("/v1/lab/advance", json={"seconds": 1000}))
    marked = ok(client.post("/v1/lab/gc/run", json={"grace": 0, "markOnly": True}))
    assert bid in marked["marked"]
    second = ok(client.post("/v1/lab/gc/run", json={"grace": 0}))
    assert bid in second["deleted"]
    for cid in [x["chunkId"] for x in plan["chunks"]]:
        assert next(x for x in snapshot(client)["postgres"]["chunk_objects"] if x["id"] == cid)["state"] == "live"
    assert download(client, result["fileId"])[0] == b"A" * 30 + b"X" * 30 + b"C" * 30


def test_region_model_and_capacity_are_explicit(client):
    ok(client.post("/v1/lab/region", json={"mode": "async", "secondary": "up"}))
    item = stage(client, [b"acknowledged before replica-model receipt"])
    commit(client, item)
    unsafe = ok(client.post("/v1/lab/region", json={"action": "failover"}))
    assert unsafe["simulationOnly"] and not unsafe["safe"]
    assert item["uploadId"] in unsafe["wouldLoseAcknowledgedUploads"]
    ok(client.post("/v1/lab/region", json={"action": "replay"}))
    assert ok(client.post("/v1/lab/region", json={"action": "failover"}))["safe"]
    ok(client.post("/v1/lab/region", json={"mode": "sync", "secondary": "down"}))
    pending = stage(client, [b"wait for replica-model receipt"])
    assert client.post("/v1/uploads/" + pending["uploadId"] + "/complete", json={}).status_code == 503
    assert ok(client.get("/v1/uploads/" + pending["uploadId"]))["result"] is None
    ok(client.post("/v1/lab/region", json={"mode": "sync", "secondary": "up"}))
    assert commit(client, pending)["status"] == "ready"
    ok(client.post("/v1/lab/faults", json={"capacity_exhausted": True}))
    response = client.post("/v1/uploads", json={"name": "busy", "sizeBytes": 0}, headers={"Idempotency-Key": str(uuid.uuid4())})
    assert response.status_code == 503 and response.json()["code"] == "capacity_exhausted"
