"""Trusted LOCAL storage adapter: CRC32C validation and envelope encryption.

Clients transfer directly here. Drive reads its metadata API in the default path.
MinIO stores AES-GCM ciphertext. This adapter does not claim native GCS semantics.
"""
import base64
import hashlib
import os
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from .common import CA, crc, internal, metric, unseal

app = FastAPI(title="Local protected storage adapter")
app.add_middleware(CORSMiddleware, allow_origins=["https://localhost:8420", "https://127.0.0.1:8420"],
                   allow_methods=["GET", "PUT", "OPTIONS"], allow_headers=["*"],
                   expose_headers=["ETag", "X-Object-Version", "X-CRC32C"])
BUCKET = "drive-chunks"
KEK = hashlib.sha256(os.environ["STORAGE_MASTER_KEY"].encode()).digest()
S3 = boto3.client("s3", endpoint_url="https://minio:9000", verify=CA,
                  aws_access_key_id="lab-storage", aws_secret_access_key="local-study-minio-password",
                  config=Config(signature_version="s3v4", s3={"addressing_style": "path"}, retries={"max_attempts": 3}))


@app.on_event("startup")
def startup():
    for attempt in range(40):
        try:
            try:
                S3.head_bucket(Bucket=BUCKET)
            except ClientError:
                S3.create_bucket(Bucket=BUCKET)
            S3.put_bucket_versioning(Bucket=BUCKET, VersioningConfiguration={"Status": "Enabled"})
            return
        except Exception:
            if attempt == 39:
                raise
            time.sleep(1)


def args(key, version=None):
    return {"Bucket": BUCKET, "Key": key, **({"VersionId": version} if version else {})}


def head(key, version=None):
    try:
        obj = S3.head_object(**args(key, version))
    except ClientError as exc:
        if str(exc.response["Error"]["Code"]) in ("404", "NoSuchKey", "NoSuchVersion", "NotFound"):
            raise HTTPException(404, detail={"code": "object_missing"})
        raise
    meta = obj["Metadata"]
    return {"key": key, "version": obj["VersionId"], "size": int(meta["plain-size"]),
            "crc32c": meta["crc32c"], "etag": obj["ETag"], "encoding": meta["encoding"],
            "verificationMethod": "local_provider_crc32c", "sha256Verified": False}


def read(key, version):
    try:
        obj = S3.get_object(**args(key, version))
    except ClientError:
        raise HTTPException(404, detail={"code": "object_missing"})
    m = obj["Metadata"]
    aad = key.encode()
    dek = AESGCM(KEK).decrypt(base64.b64decode(m["wrap-nonce"]), base64.b64decode(m["wrapped-key"]), aad)
    raw = AESGCM(dek).decrypt(base64.b64decode(m["nonce"]), obj["Body"].read(), aad)
    if len(raw) != int(m["plain-size"]) or crc(raw) != m["crc32c"]:
        raise HTTPException(503, detail={"code": "stored_integrity_error"})
    return raw, m


@app.get("/healthz")
def health():
    S3.head_bucket(Bucket=BUCKET)
    return {"ok": True, "adapter": "local CRC32C + AES-GCM over versioned MinIO"}


@app.put("/v1/objects/{key:path}")
async def put(key: str, request: Request, ticket: str):
    policy = unseal(ticket, "storage-put")
    if policy["key"] != key:
        raise HTTPException(403, detail={"code": "wrong_object"})
    raw = await request.body()
    if len(raw) > 32 * 1024 * 1024 or len(raw) != policy["size"] or crc(raw) != policy["crc"]:
        raise HTTPException(400, detail={"code": "checksum_or_size_mismatch"})
    dek, nonce, wn = os.urandom(32), os.urandom(12), os.urandom(12)
    aad = key.encode()
    cipher = AESGCM(dek).encrypt(nonce, raw, aad)
    metadata = {"plain-size": str(len(raw)), "crc32c": crc(raw), "encoding": policy.get("encoding", "identity"),
                "nonce": base64.b64encode(nonce).decode(), "wrap-nonce": base64.b64encode(wn).decode(),
                "wrapped-key": base64.b64encode(AESGCM(KEK).encrypt(wn, dek, aad)).decode()}
    try:
        S3.put_object(Bucket=BUCKET, Key=key, Body=cipher, ContentType="application/octet-stream",
                      Metadata=metadata, IfNoneMatch="*")
    except ClientError as exc:
        if str(exc.response["Error"]["Code"]) in ("PreconditionFailed", "412", "ConditionalRequestConflict"):
            raise HTTPException(412, detail={"code": "already_exists"})
        raise
    metric("storage_puts")
    metric("storage_upload_bytes", len(raw))
    receipt = head(key)
    return Response(status_code=200, headers={"ETag": receipt["etag"], "X-Object-Version": receipt["version"], "X-CRC32C": receipt["crc32c"]})


@app.get("/v1/meta/{key:path}")
def metadata(key: str, version: str | None = None, x_internal_key: str | None = Header(None)):
    internal(x_internal_key)
    metric("provider_metadata_reads")
    return head(key, version)


@app.get("/v1/objects/{key:path}")
def get(key: str, ticket: str | None = None, version: str | None = None,
        x_internal_key: str | None = Header(None), range: str | None = Header(None)):
    if x_internal_key:
        internal(x_internal_key)
    else:
        policy = unseal(ticket or "", "storage-get")
        if policy["key"] != key:
            raise HTTPException(403, detail={"code": "wrong_object"})
        version = policy["version"]
    if not version:
        raise HTTPException(400, detail={"code": "version_required"})
    raw, meta = read(key, version)
    headers = {"X-Object-Version": version, "X-CRC32C": meta["crc32c"], "Accept-Ranges": "bytes"}
    status = 200
    if range:
        # The local encrypted adapter decrypts the full object before slicing.
        # This teaches HTTP resume semantics, not efficient random access encryption.
        import re
        match = re.fullmatch(r"bytes=(\d+)-(\d*)", range)
        if not match or int(match[1]) >= len(raw):
            return Response(status_code=416, headers={"Content-Range": f"bytes */{len(raw)}"})
        start, end = int(match[1]), min(int(match[2]) if match[2] else len(raw)-1, len(raw)-1)
        if end < start:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{len(raw)}"})
        headers["Content-Range"] = f"bytes {start}-{end}/{len(raw)}"
        raw, status = raw[start:end+1], 206
    metric("origin_gets")
    metric("origin_bytes", len(raw))
    return Response(raw, status_code=status, media_type="application/gzip" if meta["encoding"] == "gzip" else "application/octet-stream", headers=headers)


@app.delete("/v1/objects/{key:path}")
def delete(key: str, version: str, x_internal_key: str | None = Header(None)):
    internal(x_internal_key)
    S3.delete_object(**args(key, version))
    metric("storage_deletes")
    return Response(status_code=204)


@app.get("/v1/proof/{key:path}")
def proof(key: str, version: str, x_internal_key: str | None = Header(None)):
    internal(x_internal_key)
    obj = S3.get_object(**args(key, version))
    encrypted = obj["Body"].read()
    return {"ciphertextPrefixHex": encrypted[:48].hex(), "ciphertextSize": len(encrypted),
            "plaintextSize": int(obj["Metadata"]["plain-size"]), "algorithm": "AES-256-GCM envelope encryption",
            "keyLocation": "storage adapter configuration; not the MinIO volume",
            "limitation": "local demonstration keys; not Google KMS"}
