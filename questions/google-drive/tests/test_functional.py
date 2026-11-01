import hashlib
import subprocess
import time

from conftest import ROOT, client_for, commit, download, ok, snapshot, stage


def test_page_and_actual_share_list_download_flow(client):
    page = client.get("/")
    assert page.status_code == 200
    for label in ("Upload a file", "Share by account", "Request → response", "IndexedDB", "SIMULATION"):
        assert label in page.text
    assert client.get("/static/app.js").status_code == 200
    content = b"Lee's private plan.\n" * 2000
    result = commit(client, stage(client, [content[:12000], content[12000:]], compress=True))
    own = ok(client.get("/v1/files?scope=owned"))["files"]
    assert any(x["fileId"] == result["fileId"] for x in own)
    ok(client.post("/v1/files/" + result["fileId"] + "/shares", json={"recipientId": "kim", "role": "reader"}))
    with client_for("kim") as kim:
        shared = ok(kim.get("/v1/files?scope=shared"))["files"]
        assert shared[0]["fileId"] == result["fileId"]
        actual, ds, manifest, _ = download(kim, result["fileId"], "cdn")
        assert hashlib.sha256(actual).digest() == hashlib.sha256(content).digest()
        assert any(x["storedSizeBytes"] < x["logicalSizeBytes"] for x in manifest["chunks"])
        ok(kim.post("/v1/downloads/" + ds["downloadId"] + "/complete", json={}))
        ok(kim.post("/v1/downloads/" + ds["downloadId"] + "/complete", json={}))
    with client_for("ada") as ada:
        assert ada.post("/v1/downloads", json={"fileId": result["fileId"]}).status_code == 403


def test_optional_strong_verification_and_actual_ciphertext(client):
    original = b"content that must not appear in the raw MinIO object" * 50
    item = stage(client, [original], verificationMode="sha256")
    result = commit(client, item)
    state = snapshot(client)
    assert int(state["redis"]["metrics"]["drive_hash_bytes"]) == len(original)
    assert state["postgres"]["upload_chunks"][0]["receipt"]["sha256Verified"]
    cid = item["plan"]["chunks"][0]["chunkId"]
    proof = ok(client.get("/v1/lab/storage-proof/" + cid))
    assert proof["algorithm"].startswith("AES-256-GCM")
    assert proof["ciphertextSize"] == len(original) + 16
    assert bytes.fromhex(proof["ciphertextPrefixHex"]) != original[:48]
    actual, _, manifest, _ = download(client, result["fileId"])
    assert actual == original
    assert manifest["chunks"][0]["storedSha256Verified"]
    assert manifest["chunks"][0]["storedSha256"] == hashlib.sha256(original).hexdigest()


def test_version_bound_range_and_upload_ownership(client):
    item = stage(client, [b"0123456789"])
    result = commit(client, item)
    _, _, _, urls = download(client, result["fileId"])
    url = urls["chunks"][0]["url"]
    part = client.get(url, headers={"Range": "bytes=4-7"})
    assert part.status_code == 206
    assert part.headers["Content-Range"] == "bytes 4-7/10"
    assert part.content == b"4567"
    assert client.get(url, headers={"Range": "bytes=10-"}).status_code == 416
    with client_for("kim") as kim:
        assert kim.get("/v1/uploads/" + item["uploadId"]).status_code == 403


def test_real_api_restart_keeps_attempt_result_and_content(client):
    item = stage(client, [b"persist through a real container restart"])
    before = commit(client, item)
    subprocess.run(["docker", "compose", "restart", "app"], cwd=ROOT, check=True, capture_output=True, text=True, timeout=60)
    # Nginx retains the same app address when restarting an existing container.
    deadline = time.time() + 45
    while time.time() < deadline:
        try:
            if client.get("/healthz").status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.3)
    else:
        raise AssertionError("API did not recover after restart")
    replay = commit(client, item)
    assert replay == before
    assert download(client, before["fileId"])[0] == b"persist through a real container restart"
    assert snapshot(client)["counts"]["files"] == 1
