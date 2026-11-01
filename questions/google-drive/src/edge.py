"""Private local cache: validate bearer permission BEFORE every cache lookup."""
import hashlib
import os
import threading
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import FastAPI, Header, Response
from fastapi.middleware.cors import CORSMiddleware

from .common import http, internal, metric, now, unseal

app = FastAPI(title="Private local cache edge")
app.add_middleware(CORSMiddleware, allow_origins=["https://localhost:8420", "https://127.0.0.1:8420"], allow_methods=["GET"], allow_headers=["*"], expose_headers=["X-Cache"])
CACHE = Path("/cache")
CACHE.mkdir(exist_ok=True)
LOCK = threading.Lock()
KEY = hashlib.sha256(os.environ["EDGE_MASTER_KEY"].encode()).digest()


@app.get("/healthz")
def health():
    return {"ok": True}


@app.get("/chunk")
def chunk(ticket: str):
    p = unseal(ticket, "edge-get")
    identity = p["key"] + ":" + p["version"]
    path = CACHE / hashlib.sha256(identity.encode()).hexdigest()
    hit = False
    with LOCK:
        if path.exists() and now() - path.stat().st_mtime < 3600:
            blob = path.read_bytes()
            data = AESGCM(KEY).decrypt(blob[:12], blob[12:], identity.encode())
            hit = True
        else:
            with http() as client:
                res = client.get("https://storage:8000/v1/objects/" + p["key"], params={"version": p["version"]})
            if res.status_code != 200:
                return Response(res.content, status_code=res.status_code, media_type="application/json")
            data = res.content
            nonce = os.urandom(12)
            path.write_bytes(nonce + AESGCM(KEY).encrypt(nonce, data, identity.encode()))
            os.utime(path, (now(), now()))
    metric("edge_hits" if hit else "edge_misses")
    return Response(data, media_type="application/octet-stream", headers={"X-Cache": "HIT" if hit else "MISS"})


@app.post("/clear")
def clear(x_internal_key: str | None = Header(None)):
    internal(x_internal_key)
    with LOCK:
        for path in CACHE.iterdir():
            if path.is_file():
                path.unlink()
    return {"ok": True}
