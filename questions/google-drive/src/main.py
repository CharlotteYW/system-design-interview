import asyncio
import json
import os
import time
from pathlib import Path

import httpx
from fastapi import Body, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from psycopg.types.json import Jsonb

from . import domain as d
from . import jobs
from .common import R, fault, http, metric, now, seal, unseal

app = FastAPI(title="Drive system-design lab")
STATIC = Path(__file__).with_name("static")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
ADMISSION = asyncio.Semaphore(32)


@app.exception_handler(HTTPException)
async def handled(request, exc):
    return JSONResponse(exc.detail if isinstance(exc.detail, dict) else {"code": str(exc.detail)}, status_code=exc.status_code,
                        headers={"Retry-After": "1"} if exc.status_code == 503 else None)


@app.middleware("http")
async def admission(request, call_next):
    if not request.url.path.startswith("/v1/") or request.url.path.startswith("/v1/lab/") or request.url.path == "/v1/events":
        return await call_next(request)
    if fault("capacity_exhausted"):
        return JSONResponse({"code": "capacity_exhausted", "retryable": True}, status_code=503, headers={"Retry-After": "1"})
    try:
        await asyncio.wait_for(ADMISSION.acquire(), timeout=0.2)
    except asyncio.TimeoutError:
        return JSONResponse({"code": "capacity_exhausted", "retryable": True}, status_code=503, headers={"Retry-After": "1"})
    try:
        metric("drive_control_requests")
        return await call_next(request)
    finally:
        ADMISSION.release()


def user(request):
    ticket = request.headers.get("Authorization", "").removeprefix("Bearer ") or request.cookies.get("lab_session", "")
    return unseal(ticket, "session")["user"]


def admin(request):
    u = user(request)
    if u != "lee":
        d.fail(403, "lab_admin_only")
    return u


@app.on_event("startup")
def startup():
    d.initialize()


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/healthz")
def health():
    with d.POOL.connection() as c:
        c.execute("SELECT 1")
    R.ping()
    with http() as client:
        client.get("https://storage:8000/healthz").raise_for_status()
    return {"ok": True, "tls": True, "lab": "Small-file local model; not a production capacity or region test"}


@app.post("/v1/lab/login")
def login(response: Response, body=Body(...)):
    # Explicit classroom identity provider; this endpoint is never production authentication.
    if body.get("user") not in ("lee", "kim", "ada"):
        d.fail(400, "unknown_demo_identity")
    token = seal({"aud": "session", "user": body["user"], "exp": time.time() + 86400 * 365})
    response.set_cookie("lab_session", token, httponly=True, secure=True, samesite="strict")
    return {"user": body["user"], "accessToken": token, "identityProvider": "mock, local lab only"}


@app.post("/v1/uploads", status_code=201)
def upload(request: Request, body=Body(...), idempotency_key: str | None = Header(None)):
    return d.create_upload(user(request), idempotency_key, body)


@app.put("/v1/uploads/{uid}/manifest")
def plan(uid: str, request: Request, body=Body(...)):
    return d.plan(user(request), uid, body)


@app.post("/v1/uploads/{uid}/chunk-upload-urls")
def put_urls(uid: str, request: Request, body=Body(...)):
    return d.upload_urls(user(request), uid, body.get("ordinals", []))


@app.post("/v1/uploads/{uid}/chunks/{ordinal}/complete")
def receipt(uid: str, ordinal: int, request: Request, body=Body(default={})):
    return d.verify(user(request), uid, ordinal)


@app.get("/v1/uploads/{uid}")
def upload_status(uid: str, request: Request):
    return d.upload_status(user(request), uid)


@app.post("/v1/uploads/{uid}/reconcile", status_code=202)
def reconcile(uid: str, request: Request, body=Body(default={})):
    with d.db() as c:
        d.owned_upload(c, uid, user(request))
        c.execute("UPDATE uploads SET reconcile_requested=true WHERE id=%s", (uid,))
    return {"uploadId": uid, "reconciliation": "pending"}


@app.post("/v1/uploads/{uid}/complete")
def complete(uid: str, request: Request, body=Body(default={})):
    return d.publish(user(request), uid)


@app.post("/v1/uploads/{uid}/conflict-copy", status_code=201)
def conflict_copy(uid: str, request: Request, body=Body(default={}), idempotency_key: str | None = Header(None)):
    return d.publish(user(request), uid, body.get("name", "conflict copy"), idempotency_key)


@app.get("/v1/files")
def files(request: Request, scope: str = "owned", cursor: str = ""):
    u = user(request)
    with d.db() as c:
        if scope == "shared":
            rows = c.execute("SELECT f.* FROM files f JOIN access a ON a.file_id=f.id WHERE a.user_id=%s AND f.deleted_at IS NULL AND f.manifest_id IS NOT NULL AND f.id>%s ORDER BY f.id LIMIT 100", (u, cursor)).fetchall()
        else:
            rows = c.execute("SELECT * FROM files WHERE owner=%s AND deleted_at IS NULL AND manifest_id IS NOT NULL AND id>%s ORDER BY id LIMIT 100", (u, cursor)).fetchall()
    return {"files": [{"fileId": x["id"], "name": x["name"], "sizeBytes": x["size"], "revision": x["revision"], "manifestId": x["manifest_id"]} for x in rows], "nextCursor": rows[-1]["id"] if len(rows) == 100 else None}


@app.post("/v1/files/{fid}/shares")
def share(fid: str, request: Request, body=Body(...)):
    u, recipient = user(request), body.get("recipientId")
    if recipient not in ("lee", "kim", "ada") or body.get("role", "reader") != "reader":
        d.fail(400, "invalid_recipient_or_role")
    with d.db() as c:
        f = d.file_access(c, fid, u, owner_only=True)
        new = c.execute("INSERT INTO access VALUES (%s,%s,'reader') ON CONFLICT DO NOTHING RETURNING user_id", (recipient, fid)).fetchone()
        if new:
            d.append_change(c, recipient, d.ident("share"), fid, f["revision"], "shared")
    if new:
        d.hints([recipient])
    return {"fileId": fid, "recipientId": recipient, "role": "reader"}


@app.delete("/v1/files/{fid}/shares/{recipient}", status_code=204)
def revoke(fid: str, recipient: str, request: Request):
    u = user(request)
    with d.db() as c:
        f = d.file_access(c, fid, u, owner_only=True)
        deleted = c.execute("DELETE FROM access WHERE user_id=%s AND file_id=%s RETURNING user_id", (recipient, fid)).fetchone()
        if deleted:
            d.append_change(c, recipient, d.ident("revoke"), fid, f["revision"], "access_removed")
    if deleted:
        d.hints([recipient])
    return Response(status_code=204)


@app.delete("/v1/files/{fid}", status_code=204)
def delete_file(fid: str, request: Request):
    u = user(request)
    with d.db() as c:
        f = d.file_access(c, fid, u, owner_only=True, allow_deleted=True)
        locked = c.execute("SELECT * FROM files WHERE id=%s FOR UPDATE", (fid,)).fetchone()
        if locked["deleted_at"] is None:
            rev, eid = locked["revision"] + 1, d.ident("deleted")
            c.execute("UPDATE files SET deleted_at=%s,revision=%s WHERE id=%s", (now(), rev, fid))
            d.append_change(c, u, eid, fid, rev, "deleted")
            c.execute("INSERT INTO outbox(id,owner,file_id,revision,type,created_at) VALUES (%s,%s,%s,%s,'deleted',%s)", (eid, u, fid, rev, now()))
    d.hints([u])
    return Response(status_code=204)


@app.post("/v1/downloads", status_code=201)
def create_download(request: Request, body=Body(...)):
    return d.new_download(user(request), body["fileId"])


@app.get("/v1/downloads/{did}/manifest")
def get_manifest(did: str, request: Request, cache: bool = True):
    return d.download_manifest(user(request), did, cache)


@app.post("/v1/downloads/{did}/chunk-download-urls")
def get_urls(did: str, request: Request, body=Body(...)):
    return d.download_urls(user(request), did, body.get("chunkIds", []), body.get("delivery", "storage"))


@app.post("/v1/downloads/{did}/download-url")
def whole_url(did: str, request: Request, body=Body(default={})):
    m = d.download_manifest(user(request), did)
    if len(m["chunks"]) != 1:
        d.fail(409, "whole_object_mode_required")
    entry = m["chunks"][0]
    signed = d.download_urls(user(request), did, [entry["chunkId"]])["chunks"][0]
    return {**signed, "downloadId": did, "fileId": m["fileId"], "revision": m["revision"], "totalSizeBytes": m["totalSizeBytes"], "crc32c": entry["storedCrc32c"]}


@app.post("/v1/downloads/{did}/complete")
def finish_download(did: str, request: Request, body=Body(default={})):
    with d.db() as c:
        caller = user(request)
        ds = c.execute("SELECT * FROM download_sessions WHERE id=%s AND user_id=%s FOR UPDATE", (did, caller)).fetchone()
        if not ds:
            d.fail(403, "access_denied")
        if ds["state"] != "completed":
            ds = d.session(c, did, caller)
        # Retain the original bounded protection conservatively; no trust in client erasure.
        c.execute("UPDATE download_sessions SET state='completed' WHERE id=%s", (did,))
    return {"downloadId": did, "revision": ds["revision"], "status": "completed"}


@app.get("/v1/changes")
def changes(request: Request, cursor: int = 0, limit: int = 100):
    u = user(request)
    with d.db() as c:
        stream = c.execute("SELECT * FROM user_streams WHERE user_id=%s", (u,)).fetchone()
        if cursor < 0 or (stream and cursor < stream["floor_seq"]):
            d.fail(410, "cursor_expired", resyncRequired=True)
        rows = c.execute("SELECT * FROM changes WHERE user_id=%s AND seq>%s ORDER BY seq LIMIT %s", (u, cursor, min(100, max(1, limit)) + 1)).fetchall()
        more = len(rows) > min(100, max(1, limit))
        rows = rows[:min(100, max(1, limit))]
        visible = []
        for row in rows:
            # Revoke/deletion tombstones convey removal without leaking current private metadata.
            allowed = row["type"] in ("access_removed", "deleted") or c.execute("SELECT 1 FROM files f WHERE f.id=%s AND f.deleted_at IS NULL AND (f.owner=%s OR EXISTS (SELECT 1 FROM access a WHERE a.file_id=f.id AND a.user_id=%s))", (row["file_id"], u, u)).fetchone()
            if allowed:
                visible.append({"cursor": row["seq"], "fileId": row["file_id"], "revision": row["revision"], "type": row["type"]})
    return {"changes": visible, "nextCursor": rows[-1]["seq"] if rows else cursor, "hasMore": more}


@app.get("/v1/events")
async def events(request: Request):
    u = user(request)
    async def stream():
        previous = await asyncio.to_thread(R.get, "lab:hint:" + u)
        last = time.time()
        yield ": connected\n\n"
        while not await request.is_disconnected():
            current = await asyncio.to_thread(R.get, "lab:hint:" + u)
            if current != previous:
                previous = current
                yield 'data: {"type":"changes_available"}\n\n'
            if time.time() - last > 5:
                yield ": heartbeat\n\n"
                last = time.time()
            await asyncio.sleep(0.4)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.post("/v1/lab/reset")
def reset(request: Request):
    admin(request)
    R.delete("lab:faults")
    R.set("lab:offset", 0)
    R.set("lab:batch", 50)
    R.hset("lab:region", mapping={"mode": "sync", "secondary": "up"})
    # Storage objects are kept as unreachable encrypted demo data, never a cross-store truncate.
    with d.db() as c:
        c.execute("TRUNCATE replica_model,download_sessions,outbox,changes,user_streams,access,manifest_chunks,manifests,upload_chunks,uploads,chunk_objects,files CASCADE")
    for key in R.scan_iter("manifest:*"):
        R.delete(key)
    for key in R.scan_iter("lab:hint:*"):
        R.delete(key)
    R.delete("lab:metrics")
    with http() as client:
        client.post("https://edge:8000/clear").raise_for_status()
    return {"ok": True, "state": "empty", "note": "old encrypted demo objects are not silently deleted"}


@app.get("/v1/lab/state")
def state(request: Request):
    admin(request)
    tables = ["files", "uploads", "upload_chunks", "chunk_objects", "manifests", "manifest_chunks", "access", "user_streams", "changes", "outbox", "download_sessions", "replica_model"]
    # The inspector remains usable while the db_down fault simulates application failure.
    with d.POOL.connection() as c:
        data = {name: c.execute("SELECT * FROM " + name + " LIMIT 200").fetchall() for name in tables}
        for chunk in data["chunk_objects"]:
            chunk["roots"] = jobs.roots_for_display(c, chunk["id"])
        counts = {name: c.execute("SELECT count(*) AS n FROM " + name).fetchone()["n"] for name in tables}
    return {"postgres": data, "counts": counts, "redis": {"manifestKeys": list(R.scan_iter("manifest:*")), "metrics": R.hgetall("lab:metrics")},
            "faults": R.hgetall("lab:faults"), "regionModel": R.hgetall("lab:region"), "clock": now(),
            "limits": {"maxFileBytes": d.MAX_FILE, "urlSeconds": d.URL_TTL, "leaseSeconds": d.LEASE_TTL, "poolMax": 8},
            "evidence": {"tls": "real local TLS on API, storage, edge, PostgreSQL, Redis, MinIO", "atRest": "AES-GCM ciphertext in MinIO and edge cache",
                         "region": "simulation in one PostgreSQL database; NOT cross-region durability",
                         "identity": "mock accounts, not production authentication", "capacity": "bounded lab, not 40000 starts/s"}}


@app.post("/v1/lab/faults")
def faults(request: Request, body=Body(...)):
    admin(request)
    valid = {"db_down", "capacity_exhausted", "worker_paused", "drop_completion_reply", "drop_hints", "crash_after_job_claim"}
    if not set(body).issubset(valid):
        d.fail(400, "unknown_fault")
    R.hset("lab:faults", mapping={k: "1" if v else "0" for k, v in body.items()})
    return R.hgetall("lab:faults")


@app.post("/v1/lab/advance")
def advance(request: Request, body=Body(...)):
    admin(request)
    seconds = max(0, min(100000, float(body.get("seconds", 0))))
    R.incrbyfloat("lab:offset", seconds)
    return {"clock": now(), "advanced": seconds}


@app.post("/v1/lab/fanout/run")
def fanout(request: Request, body=Body(default={})):
    admin(request)
    return jobs.fanout(max(1, min(1000, int(body.get("batch", 50)))))


@app.post("/v1/lab/recipients")
def recipients(request: Request, body=Body(...)):
    u = admin(request)
    count = max(1, min(100000, int(body.get("count", 100))))
    with d.db() as c:
        d.file_access(c, body["fileId"], u, owner_only=True)
        c.execute("INSERT INTO access(user_id,file_id) SELECT 'reader-' || lpad(i::text,6,'0'),%s FROM generate_series(1,%s) AS i ON CONFLICT DO NOTHING", (body["fileId"], count))
    return {"fileId": body["fileId"], "addedUpTo": count, "note": "synthetic reader grants; update the file to create fan-out work"}


@app.post("/v1/lab/gc/run")
def gc(request: Request, body=Body(default={})):
    admin(request)
    return jobs.gc_run(max(0, float(body.get("grace", 5))), bool(body.get("markOnly", False)))


@app.get("/v1/lab/storage-proof/{cid}")
def proof(cid: str, request: Request):
    admin(request)
    with d.db() as c:
        co = c.execute("SELECT * FROM chunk_objects WHERE id=%s", (cid,)).fetchone()
    if not co or not co["version"]:
        d.fail(404, "object_missing")
    with http() as client:
        res = client.get("https://storage:8000/v1/proof/" + co["object_key"], params={"version": co["version"]})
    return JSONResponse(res.json(), status_code=res.status_code)


@app.post("/v1/lab/region")
def region(request: Request, body=Body(...)):
    admin(request)
    action = body.get("action", "configure")
    if action == "configure":
        mode = body.get("mode", "sync")
        if mode not in ("sync", "async"):
            d.fail(400, "invalid_mode")
        R.hset("lab:region", mapping={"mode": mode, "secondary": body.get("secondary", "up")})
    elif action == "replay":
        with d.db() as c:
            c.execute("INSERT INTO replica_model SELECT id,result FROM uploads WHERE result IS NOT NULL ON CONFLICT DO NOTHING")
    elif action == "failover":
        with d.db() as c:
            lost = c.execute("SELECT id FROM uploads WHERE result IS NOT NULL AND id NOT IN (SELECT upload_id FROM replica_model)").fetchall()
        return {"simulationOnly": True, "safe": not lost, "wouldLoseAcknowledgedUploads": [x["id"] for x in lost], "action": "refuse stale promotion" if lost else "model permits promotion after replay and fencing"}
    return {"simulationOnly": True, **R.hgetall("lab:region")}
