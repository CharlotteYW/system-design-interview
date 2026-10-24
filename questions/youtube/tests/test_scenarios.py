"""Integration tests against the running YouTube lab."""

from __future__ import annotations

import time

import httpx

from conftest import create, put_part, sample, state, upload_all, wait_status


def test_health(client: httpx.Client) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


def test_upload_to_ready_through_s3_event(client: httpx.Client) -> None:
    data = sample(client)
    video = create(client, data)
    receipts = upload_all(client, video, data)
    done = client.post(f"/v1/videos/{video['videoId']}/complete", json={"parts": receipts})
    assert done.status_code == 202
    assert done.json()["originalEtag"].endswith(f"-{video['partCount']}\""), "a multipart ETag ends in -<parts>"
    ready = wait_status(client, video["videoId"], {"ready"})
    assert [r["name"] for r in ready["renditions"]] == ["240p", "480p", "720p"]
    job = next(j for j in state(client, video["videoId"])["postgres"]["jobs"] if j["video_id"] == video["videoId"])
    assert job["started_by"] == "s3-event"
    master = httpx.get(ready["manifestUrl"])
    assert master.status_code == 200 and master.text.count("#EXT-X-STREAM-INF") == 3
    segment = ready["manifestUrl"].replace("master.m3u8", "240p/seg_00000.ts")
    first, second = httpx.get(segment), httpx.get(segment)
    assert first.status_code == 200 and len(first.content) > 1000
    assert second.headers["x-edge-cache"] == "HIT"


def test_resume_from_listparts(client: httpx.Client) -> None:
    data = sample(client)
    video = create(client, data)
    assert video["partCount"] >= 2
    first = put_part(client, video, data, 1)
    assert first.status_code == 200
    resumed = client.get(f"/v1/videos/{video['videoId']}/upload").json()
    assert resumed["source"] == "S3 ListParts"
    assert [p["partNumber"] for p in resumed["uploadedParts"]] == [1]
    assert resumed["uploadedParts"][0]["etag"] == first.headers["etag"]
    receipts = [{"partNumber": p["partNumber"], "etag": p["etag"]} for p in resumed["uploadedParts"]]
    for n in range(2, video["partCount"] + 1):
        r = put_part(client, video, data, n)
        receipts.append({"partNumber": n, "etag": r.headers["etag"]})
    assert client.post(f"/v1/videos/{video['videoId']}/complete", json={"parts": receipts}).status_code == 202
    wait_status(client, video["videoId"], {"ready"})


def test_damaged_part_is_rejected_by_s3(client: httpx.Client) -> None:
    data = sample(client)
    video = create(client, data)
    ps = video["partSizeBytes"]
    damaged = bytearray(data[:ps])
    damaged[100] ^= 0xFF
    bad = put_part(client, video, data, 1, send=bytes(damaged))
    assert bad.status_code == 400
    assert "Checksum" in bad.text or "BadDigest" in bad.text
    stored = client.get(f"/v1/videos/{video['videoId']}/upload").json()["uploadedParts"]
    assert stored == [], "a damaged part is never stored"


def test_wrong_whole_file_sha256_fails_before_transcoding(client: httpx.Client) -> None:
    data = sample(client)
    video = create(client, data, sha256="0" * 64)
    receipts = upload_all(client, video, data)
    client.post(f"/v1/videos/{video['videoId']}/complete", json={"parts": receipts})
    failed = wait_status(client, video["videoId"], {"failed"})
    assert "checksum mismatch" in failed["error"]
    assert failed["renditions"] == []
    assert state(client, video["videoId"])["postgres"]["tasks"] == [], "no task runs on a bad original"


def test_complete_with_unknown_etag_is_rejected(client: httpx.Client) -> None:
    data = sample(client)
    video = create(client, data)
    upload_all(client, video, data)
    fake = [{"partNumber": n, "etag": '"00000000000000000000000000000000"'} for n in range(1, video["partCount"] + 1)]
    r = client.post(f"/v1/videos/{video['videoId']}/complete", json={"parts": fake})
    assert r.status_code == 400


def test_duplicate_event_starts_no_second_job(client: httpx.Client) -> None:
    data = sample(client)
    video = create(client, data)
    client.post(f"/v1/videos/{video['videoId']}/complete", json={"parts": upload_all(client, video, data)})
    wait_status(client, video["videoId"], {"ready"})
    before = len(state(client, video["videoId"])["postgres"]["tasks"])
    client.post("/v1/lab/replay-event", json={"videoId": video["videoId"]})
    time.sleep(1.5)
    st = state(client, video["videoId"])
    job = next(j for j in st["postgres"]["jobs"] if j["video_id"] == video["videoId"])
    assert job["starts_seen"] == 2
    assert len(st["postgres"]["tasks"]) == before


def test_service_trigger_crash_is_rescued_by_sweep(client: httpx.Client) -> None:
    data = sample(client)
    video = create(client, data, trigger="service")
    r = client.post(f"/v1/videos/{video['videoId']}/complete",
                    json={"parts": upload_all(client, video, data), "crashBeforeEnqueue": True})
    assert r.status_code == 500
    time.sleep(2)
    st = state(client, video["videoId"])
    assert not any(j["video_id"] == video["videoId"] for j in st["postgres"]["jobs"]), "nobody started the job"
    assert client.get(f"/v1/videos/{video['videoId']}").json()["status"] == "processing"
    swept = client.post("/v1/lab/sweep").json()
    assert video["videoId"] in swept["started"]
    wait_status(client, video["videoId"], {"ready"})


def test_worker_crash_is_retried_into_the_same_key(client: httpx.Client) -> None:
    client.post("/v1/lab/crash-next-task")
    data = sample(client)
    video = create(client, data)
    client.post(f"/v1/videos/{video['videoId']}/complete", json={"parts": upload_all(client, video, data)})
    wait_status(client, video["videoId"], {"ready"}, timeout=150)
    tasks = state(client, video["videoId"])["postgres"]["tasks"]
    assert all(t["state"] == "done" for t in tasks)
    assert any(t["attempts"] >= 2 for t in tasks), "the crashed task ran again"


def test_origin_shield_collapses_a_burst(client: httpx.Client) -> None:
    ready = next(v for v in client.get("/v1/videos").json()["videos"] if v["status"] == "ready")
    shield = client.post("/v1/lab/cdn-burst", json={"videoId": ready["video_id"], "mode": "shield", "requests": 20}).json()
    direct = client.post("/v1/lab/cdn-burst", json={"videoId": ready["video_id"], "mode": "noShield", "requests": 20}).json()
    assert shield["statusCodes"] == [200] and direct["statusCodes"] == [200]
    assert shield["originFetches"] == 1, shield
    assert direct["originFetches"] == 2, "one fetch per edge without a shield"


def test_cleanup_aborts_an_abandoned_upload(client: httpx.Client) -> None:
    data = sample(client)
    video = create(client, data)
    put_part(client, video, data, 1)
    cleaned = client.post("/v1/lab/cleanup-uploads", json={"olderThanSeconds": 0}).json()
    assert video["videoId"] in cleaned["aborted"]
    assert client.get(f"/v1/videos/{video['videoId']}").json()["status"] == "failed"
