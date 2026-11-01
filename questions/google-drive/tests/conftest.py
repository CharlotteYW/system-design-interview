import base64
import gzip
import hashlib
import os
import ssl
import uuid
from contextlib import contextmanager
from pathlib import Path

import google_crc32c
import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = os.getenv("DRIVE_BASE_URL", "https://localhost:8420")
CA = ssl.create_default_context(cafile=str(ROOT / ".certs/ca.crt"))


@contextmanager
def client_for(user="lee"):
    with httpx.Client(base_url=BASE, verify=CA, timeout=30) as c:
        response = c.post("/v1/lab/login", json={"user": user})
        response.raise_for_status()
        c.headers["Authorization"] = "Bearer " + response.json()["accessToken"]
        yield c


@pytest.fixture
def client():
    with client_for() as c:
        c.post("/v1/lab/reset").raise_for_status()
        c.post("/v1/lab/faults", json={"worker_paused": True}).raise_for_status()
        yield c
        c.post("/v1/lab/faults", json={"db_down": False, "capacity_exhausted": False, "worker_paused": True})


def ok(response, status=200):
    assert response.status_code == status, (response.status_code, response.text)
    return response.json() if status != 204 else None


def checksum(data):
    return base64.b64encode(google_crc32c.value(data).to_bytes(4, "big")).decode()


def metadata(raw, ordinal, compress=False):
    stored = gzip.compress(raw, mtime=0) if compress else raw
    return {"ordinal": ordinal, "logicalSizeBytes": len(raw), "storedSizeBytes": len(stored),
            "encoding": "gzip" if compress else "identity", "storedCrc32c": checksum(stored),
            "declaredStoredSha256": hashlib.sha256(stored).hexdigest()}, stored


def begin(c, parts, name="plan.txt", key=None, target=None, base=None, **options):
    body = {"name": name, "sizeBytes": sum(map(len, parts)), "mimeType": "text/plain", "mode": "independent-chunks", **options}
    if target:
        body.update(fileId=target, baseRevision=base)
    key = key or str(uuid.uuid4())
    response = c.post("/v1/uploads", json=body, headers={"Idempotency-Key": key})
    created = ok(response, 201)
    return created, body, key


def stage(c, parts, compress=False, **options):
    created, body, key = begin(c, parts, **options)
    pairs = [metadata(raw, i, compress) for i, raw in enumerate(parts)]
    expected = {"chunking": {"algorithm": "fixed", "version": "test-1", "parameters": {}}, "chunks": [x[0] for x in pairs]}
    plan = ok(c.put("/v1/uploads/" + created["uploadId"] + "/manifest", json=expected))
    permissions = ok(c.post("/v1/uploads/" + created["uploadId"] + "/chunk-upload-urls", json={"ordinals": list(range(len(parts)))}))
    for item, (_, stored) in zip(permissions["chunks"], pairs):
        response = c.put(item["url"], content=stored, headers=item["headers"])
        assert response.status_code == 200, response.text
    return {**created, "plan": plan, "pairs": pairs, "permissions": permissions, "body": body, "key": key}


def commit(c, staged):
    return ok(c.post("/v1/uploads/" + staged["uploadId"] + "/complete", json={}))


def download(c, fid, delivery="storage"):
    ds = ok(c.post("/v1/downloads", json={"fileId": fid}), 201)
    manifest = ok(c.get("/v1/downloads/" + ds["downloadId"] + "/manifest"))
    urls = ok(c.post("/v1/downloads/" + ds["downloadId"] + "/chunk-download-urls", json={"chunkIds": [x["chunkId"] for x in manifest["chunks"]], "delivery": delivery}))
    permissions = {x["chunkId"]: x for x in urls["chunks"]}
    output = bytearray()
    for entry in manifest["chunks"]:
        response = c.get(permissions[entry["chunkId"]]["url"])
        assert response.status_code == 200, response.text
        stored = response.content
        assert len(stored) == entry["storedSizeBytes"]
        assert checksum(stored) == entry["storedCrc32c"]
        raw = gzip.decompress(stored) if entry["encoding"] == "gzip" else stored
        assert len(raw) == entry["logicalSizeBytes"]
        output.extend(raw)
    return bytes(output), ds, manifest, urls


def snapshot(c):
    return ok(c.get("/v1/lab/state"))
