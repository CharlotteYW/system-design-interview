"""Durable application state. All object operations are outside publication SQL."""
import hashlib
import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool, PoolTimeout

from .common import R, fault, http, metric, now, seal

POOL = ConnectionPool(os.environ["DATABASE_URL"], min_size=1, max_size=8, timeout=3,
                      kwargs={"row_factory": dict_row}, open=False)
URL_TTL = int(os.getenv("URL_TTL", "30"))
LEASE_TTL = int(os.getenv("LEASE_TTL", "180"))
UPLOAD_TTL = 900
MAX_FILE = 64 * 1024 * 1024


def fail(status, code, **fields):
    raise HTTPException(status, detail={"code": code, **fields})


def ident(prefix):
    return prefix + "-" + uuid.uuid4().hex[:20]


@contextmanager
def db():
    if fault("db_down"):
        fail(503, "metadata_unavailable", retryable=True)
    try:
        with POOL.connection() as conn:
            with conn.transaction():
                yield conn
    except PoolTimeout:
        fail(503, "capacity_exhausted", retryable=True)


def initialize():
    POOL.open(wait=True, timeout=60)
    with POOL.connection() as c:
        c.execute(Path(__file__).with_name("schema.sql").read_text())


def owned_upload(c, uid, owner, lock=False):
    u = c.execute("SELECT * FROM uploads WHERE id=%s" + (" FOR UPDATE" if lock else ""), (uid,)).fetchone()
    if not u or u["owner"] != owner:
        fail(403, "access_denied")
    return u


def active(u):
    if u["state"] in ("expired", "cancelled") or u["expires_at"] <= now():
        fail(410, "upload_expired")


def file_access(c, fid, user, owner_only=False, allow_deleted=False):
    f = c.execute("SELECT * FROM files WHERE id=%s", (fid,)).fetchone()
    if not f:
        fail(404, "file_not_found")
    allowed = f["owner"] == user or (not owner_only and c.execute("SELECT 1 FROM access WHERE user_id=%s AND file_id=%s", (user, fid)).fetchone())
    if not allowed:
        fail(403, "access_denied")
    if f["deleted_at"] is not None and not allow_deleted:
        fail(404, "file_deleted")
    return f


def append_change(c, user, eid, fid, rev, kind):
    c.execute("INSERT INTO user_streams(user_id) VALUES (%s) ON CONFLICT DO NOTHING", (user,))
    stream = c.execute("SELECT * FROM user_streams WHERE user_id=%s FOR UPDATE", (user,)).fetchone()
    previous = c.execute("SELECT seq FROM changes WHERE user_id=%s AND source_event_id=%s", (user, eid)).fetchone()
    if previous:
        return previous["seq"]
    seq = stream["last_seq"] + 1
    c.execute("UPDATE user_streams SET last_seq=%s WHERE user_id=%s", (seq, user))
    c.execute("INSERT INTO changes VALUES (%s,%s,%s,%s,%s,%s,%s)", (user, seq, eid, fid, rev, kind, now()))
    return seq


def hints(users):
    for user in set(users):
        R.incr("lab:hint:" + user)
        R.publish("drive:hints:" + user, "changes_available")


def create_upload(user, key, body):
    if not key or len(key) > 200:
        fail(400, "idempotency_key_required")
    body = {**body, "mode": body.get("mode", "independent-chunks"), "mimeType": body.get("mimeType", "application/octet-stream")}
    if not body.get("name") or not 0 <= body.get("sizeBytes", -1) <= MAX_FILE:
        fail(400, "invalid_file", labMaxBytes=MAX_FILE)
    if body["mode"] not in ("independent-chunks", "whole"):
        fail(400, "invalid_mode")
    if body.get("verificationMode", "provider") not in ("provider", "sha256"):
        fail(400, "invalid_verification_mode")
    with db() as c:
        # A transaction-scoped lock avoids orphan pending files on duplicate create races.
        c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("create:" + user + ":" + key,))
        old = c.execute("SELECT * FROM uploads WHERE owner=%s AND idem_key=%s", (user, key)).fetchone()
        if old:
            if old["request"] != body:
                fail(409, "idempotency_key_reused")
            return {"uploadId": old["id"], "fileId": old["file_id"], "mode": body["mode"], "status": "uploading", "replayed": True}
        fid = body.get("fileId")
        if fid:
            file_access(c, fid, user, owner_only=True)
            if not isinstance(body.get("baseRevision"), int):
                fail(400, "base_revision_required")
        else:
            fid = ident("f")
            c.execute("INSERT INTO files(id,owner,name,mime,size,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                      (fid, user, body["name"], body["mimeType"], body["sizeBytes"], now(), now()))
        uid = ident("u")
        c.execute("INSERT INTO uploads(id,owner,file_id,idem_key,request,created_at,expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                  (uid, user, fid, key, Jsonb(body), now(), now() + UPLOAD_TTL))
    return {"uploadId": uid, "fileId": fid, "mode": body["mode"], "status": "uploading", "replayed": False}


def plan(user, uid, body):
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    entries = body.get("chunks", [])
    if len(entries) > 1000 or [x.get("ordinal") for x in entries] != list(range(len(entries))):
        fail(400, "invalid_chunk_order")
    with db() as c:
        u = owned_upload(c, uid, user, True)
        active(u)
        if u["plan_hash"]:
            if u["plan_hash"] != digest:
                fail(409, "plan_changed")
            rows = c.execute("SELECT ordinal,chunk_id,expected FROM upload_chunks WHERE upload_id=%s ORDER BY ordinal", (uid,)).fetchall()
            return {"uploadId": uid, "manifestHash": digest, "chunks": [{"ordinal": x["ordinal"], "chunkId": x["chunk_id"], "uploadRequired": not x["expected"].get("reuseFrom")} for x in rows], "status": u["state"]}
        prepared = []
        for entry in entries:
            if "reuseFrom" in entry:
                source = entry["reuseFrom"]
                sf = file_access(c, source["fileId"], user, owner_only=True)
                if sf["manifest_id"] != source["manifestId"]:
                    fail(409, "source_unavailable")
                row = c.execute("SELECT co.* FROM manifest_chunks mc JOIN chunk_objects co ON co.id=mc.chunk_id WHERE mc.manifest_id=%s AND mc.ordinal=%s", (source["manifestId"], source["ordinal"])).fetchone()
                if not row:
                    fail(409, "source_unavailable")
                prepared.append((row["id"], {**row["meta"], "ordinal": entry["ordinal"], "reuseFrom": source}, True))
            else:
                m = {k: entry[k] for k in ("logicalSizeBytes", "storedSizeBytes", "storedCrc32c")}
                m.update(encoding=entry.get("encoding", "identity"), declaredStoredSha256=entry.get("declaredStoredSha256"), ordinal=entry["ordinal"])
                if m["encoding"] not in ("identity", "gzip") or not 0 <= m["storedSizeBytes"] <= 16 * 1024 * 1024 or not 0 <= m["logicalSizeBytes"] <= 16 * 1024 * 1024:
                    fail(400, "invalid_chunk")
                prepared.append((ident("c"), m, False))
        if sum(x[1]["logicalSizeBytes"] for x in prepared) != u["request"]["sizeBytes"]:
            fail(409, "size_mismatch")
        # All acquisitions and cleanup serialize on registry rows in stable order.
        for cid, m, reuse in sorted(prepared):
            if reuse:
                co = c.execute("SELECT * FROM chunk_objects WHERE id=%s FOR UPDATE", (cid,)).fetchone()
                if co["state"] != "live":
                    fail(409, "source_unavailable")
                c.execute("UPDATE chunk_objects SET unreferenced_since=NULL WHERE id=%s", (cid,))
            else:
                c.execute("INSERT INTO chunk_objects(id,owner,object_key,meta,created_at) VALUES (%s,%s,%s,%s,%s)",
                          (cid, user, "uploads/" + uid + "/" + str(m["ordinal"]), Jsonb(m), now()))
        result = []
        for cid, m, reuse in prepared:
            co = c.execute("SELECT version FROM chunk_objects WHERE id=%s", (cid,)).fetchone()
            receipt = {"version": co["version"], "verificationMethod": "authorized_reference", "sha256Verified": False} if reuse else None
            c.execute("INSERT INTO upload_chunks VALUES (%s,%s,%s,%s,%s,%s,NULL)",
                      (uid, m["ordinal"], cid, Jsonb(m), "verified" if reuse else "planned", Jsonb(receipt) if receipt else None))
            result.append({"ordinal": m["ordinal"], "chunkId": cid, "uploadRequired": not reuse})
        c.execute("UPDATE uploads SET plan_hash=%s,policy=%s WHERE id=%s", (digest, Jsonb(body.get("chunking", {})), uid))
    return {"uploadId": uid, "manifestHash": digest, "chunks": result, "status": "uploading"}


def upload_urls(user, uid, ordinals):
    if len(ordinals) > 100:
        fail(400, "batch_too_large")
    result = []
    with db() as c:
        u = owned_upload(c, uid, user)
        active(u)
        for ordinal in ordinals:
            row = c.execute("SELECT uc.*,co.object_key FROM upload_chunks uc JOIN chunk_objects co ON co.id=uc.chunk_id WHERE uc.upload_id=%s AND uc.ordinal=%s FOR UPDATE OF co", (uid, ordinal)).fetchone()
            if not row or row["expected"].get("reuseFrom"):
                fail(409, "not_a_planned_new_chunk")
            expiry = min(now() + URL_TTL, u["expires_at"])
            p = {"aud": "storage-put", "key": row["object_key"], "exp": expiry, "size": row["expected"]["storedSizeBytes"], "crc": row["expected"]["storedCrc32c"], "encoding": row["expected"]["encoding"]}
            result.append({"ordinal": ordinal, "url": "https://localhost:8421/v1/objects/" + row["object_key"] + "?ticket=" + seal(p), "headers": {"Content-Type": "application/octet-stream"}, "expiresAt": expiry})
            c.execute("UPDATE chunk_objects SET protect_until=GREATEST(protect_until,%s) WHERE id=%s", (expiry, row["chunk_id"]))
    return {"uploadId": uid, "chunks": result}


def verify(user, uid, ordinal):
    with db() as c:
        u = owned_upload(c, uid, user)
        active(u)
        row = c.execute("SELECT uc.*,co.object_key,co.version FROM upload_chunks uc JOIN chunk_objects co ON co.id=uc.chunk_id WHERE uc.upload_id=%s AND uc.ordinal=%s", (uid, ordinal)).fetchone()
        if not row:
            fail(404, "chunk_not_planned")
        if row["state"] == "verified":
            return {"uploadId": uid, "ordinal": ordinal, "chunkId": row["chunk_id"], "state": "verified", **row["receipt"]}
    with http() as client:
        res = client.get("https://storage:8000/v1/meta/" + row["object_key"], params={"version": row["version"]} if row["version"] else {})
        if res.status_code != 200:
            fail(409, "chunk_missing")
        observed = res.json()
        m = row["expected"]
        if observed["size"] != m["storedSizeBytes"] or observed["crc32c"] != m["storedCrc32c"]:
            fail(409, "chunk_mismatch")
        observed["sha256Verified"] = False
        if u["request"].get("verificationMode") == "sha256":
            payload = client.get("https://storage:8000/v1/objects/" + row["object_key"], params={"version": observed["version"]})
            payload.raise_for_status()
            metric("drive_hash_bytes", len(payload.content))
            if hashlib.sha256(payload.content).hexdigest() != m.get("declaredStoredSha256"):
                fail(409, "sha256_mismatch")
            observed.update(sha256Verified=True, sha256=m["declaredStoredSha256"], verificationMethod="application_sha256")
    with db() as c:
        u = owned_upload(c, uid, user, True)
        active(u)
        co = c.execute("SELECT * FROM chunk_objects WHERE id=%s FOR UPDATE", (row["chunk_id"],)).fetchone()
        if co["state"] in ("deleting", "deleted") or co["version"] not in (None, observed["version"]):
            fail(409, "chunk_version_changed")
        trusted = {"storedSha256Verified": observed["sha256Verified"]}
        if observed["sha256Verified"]:
            trusted["storedSha256"] = observed["sha256"]
        c.execute("UPDATE chunk_objects SET version=%s,state='live',meta=meta || %s WHERE id=%s", (observed["version"], Jsonb(trusted), row["chunk_id"]))
        c.execute("UPDATE upload_chunks SET state='verified',receipt=%s,last_error=NULL WHERE upload_id=%s AND ordinal=%s", (Jsonb(observed), uid, ordinal))
    return {"uploadId": uid, "ordinal": ordinal, "chunkId": row["chunk_id"], "state": "verified", **observed}


def upload_status(user, uid):
    with db() as c:
        u = owned_upload(c, uid, user)
        rows = c.execute("SELECT * FROM upload_chunks WHERE upload_id=%s ORDER BY ordinal", (uid,)).fetchall()
    return {"uploadId": uid, "fileId": u["file_id"], "status": u["state"], "reconciliation": "pending" if u["reconcile_requested"] else "idle",
            "totalSizeBytes": u["request"]["sizeBytes"], "totalStoredSizeBytes": sum(x["expected"]["storedSizeBytes"] for x in rows),
            "verifiedStoredBytes": sum(x["expected"]["storedSizeBytes"] for x in rows if x["state"] == "verified"),
            "verifiedLogicalBytes": sum(x["expected"]["logicalSizeBytes"] for x in rows if x["state"] == "verified"),
            "missingOrdinals": [x["ordinal"] for x in rows if x["state"] != "verified"], "pendingOrdinals": [], "result": u["result"]}


def publish(user, uid, copy_name=None, resolution_key=None):
    with db() as c:
        u = owned_upload(c, uid, user)
        if u["result"]:
            if copy_name is not None and (u["resolution_key"] != resolution_key or u["resolution_request"] != {"name": copy_name}):
                fail(409, "resolution_conflict")
            return u["result"]
        active(u)
        if not u["plan_hash"]:
            fail(409, "upload_incomplete")
        ordinals = [x["ordinal"] for x in c.execute("SELECT ordinal FROM upload_chunks WHERE upload_id=%s ORDER BY ordinal", (uid,)).fetchall()]
    for ordinal in ordinals:
        verify(user, uid, ordinal)
    if (R.hget("lab:region", "mode") or "sync") == "sync" and R.hget("lab:region", "secondary") == "down":
        fail(503, "remote_ack_pending", retryable=True, labSimulation=True)
    conflict = None
    notified = []
    with db() as c:
        u = owned_upload(c, uid, user, True)
        if u["result"]:
            if copy_name is not None and (u["resolution_key"] != resolution_key or u["resolution_request"] != {"name": copy_name}):
                fail(409, "resolution_conflict")
            return u["result"]
        active(u)
        f = file_access(c, u["file_id"], user, owner_only=True)
        f = c.execute("SELECT * FROM files WHERE id=%s FOR UPDATE", (f["id"],)).fetchone()
        rows = c.execute("SELECT uc.*,co.state AS object_state FROM upload_chunks uc JOIN chunk_objects co ON co.id=uc.chunk_id WHERE uc.upload_id=%s ORDER BY co.id FOR UPDATE OF co", (uid,)).fetchall()
        if any(x["state"] != "verified" or x["object_state"] != "live" for x in rows):
            fail(409, "upload_incomplete")
        base = u["request"].get("baseRevision")
        if copy_name is not None:
            if u["state"] != "conflicted" or not resolution_key:
                fail(409, "resolution_conflict")
            fid = ident("f")
            c.execute("INSERT INTO files(id,owner,name,mime,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s)", (fid, user, copy_name, f["mime"], now(), now()))
            rev = 1
        elif base is not None and f["revision"] != base and u["request"].get("conflictPolicy", "conflict_copy") != "last_write_wins":
            c.execute("UPDATE uploads SET state='conflicted',conflict_revision=%s WHERE id=%s", (f["revision"], uid))
            conflict = {"fileId": f["id"], "uploadId": uid, "baseRevision": base, "currentRevision": f["revision"], "candidateState": "conflicted", "candidateExpiresAt": u["expires_at"], "allowedResolution": "save_conflict_copy"}
            fid, rev = None, None
        else:
            fid, rev = f["id"], f["revision"] + 1
        if conflict is None:
            mid, eid = ident("m"), ident("e")
            c.execute("INSERT INTO manifests VALUES (%s,%s,%s,%s,%s,%s)", (mid, fid, user, Jsonb(u["policy"] or {}), u["request"]["sizeBytes"], now()))
            for row in rows:
                c.execute("INSERT INTO manifest_chunks VALUES (%s,%s,%s)", (mid, row["ordinal"], row["chunk_id"]))
            c.execute("UPDATE files SET revision=%s,manifest_id=%s,size=%s,updated_at=%s WHERE id=%s", (rev, mid, u["request"]["sizeBytes"], now(), fid))
            kind = "created" if rev == 1 else "updated"
            append_change(c, user, eid, fid, rev, kind)
            notified.append(user)
            fanmode = u["request"].get("fanoutMode", "outbox")
            if fanmode == "synchronous":
                for recipient in c.execute("SELECT user_id FROM access WHERE file_id=%s ORDER BY user_id", (fid,)).fetchall():
                    append_change(c, recipient["user_id"], eid, fid, rev, kind)
                    notified.append(recipient["user_id"])
            else:
                c.execute("INSERT INTO outbox(id,source_upload_id,owner,file_id,revision,type,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)", (eid, uid, user, fid, rev, kind, now()))
            result = {"fileId": fid, "revision": rev, "manifestId": mid, "status": "ready", "updatedAt": now(),
                      "completionKind": "conflict_copy" if copy_name is not None else "normal",
                      "discovery": {"eventId": eid, "state": "pending" if fanmode == "outbox" else "done", "mode": fanmode}}
            c.execute("UPDATE uploads SET state='completed',result=%s,resolution_key=%s,resolution_request=%s WHERE id=%s",
                      (Jsonb(result), resolution_key, Jsonb({"name": copy_name}) if copy_name is not None else None, uid))
            if (R.hget("lab:region", "mode") or "sync") == "sync":
                c.execute("INSERT INTO replica_model VALUES (%s,%s) ON CONFLICT DO NOTHING", (uid, Jsonb(result)))
    if conflict:
        fail(409, "revision_conflict", **conflict)
    hints(notified)
    if fault("drop_completion_reply") and R.hdel("lab:faults", "drop_completion_reply"):
        fail(503, "simulated_reply_lost_after_commit", uploadId=uid, retryable=True)
    return result


def session(c, did, user):
    d = c.execute("SELECT * FROM download_sessions WHERE id=%s", (did,)).fetchone()
    if not d or d["user_id"] != user:
        fail(403, "access_denied")
    if d["state"] != "active" or d["expires_at"] <= now():
        fail(410, "revision_expired")
    file_access(c, d["file_id"], user)
    return d


def entries(c, mid):
    rows = c.execute("SELECT mc.ordinal,co.* FROM manifest_chunks mc JOIN chunk_objects co ON co.id=mc.chunk_id WHERE mc.manifest_id=%s ORDER BY mc.ordinal", (mid,)).fetchall()
    return [{"ordinal": x["ordinal"], "chunkId": x["id"], "generation": x["version"], **{k: v for k, v in x["meta"].items() if k not in ("ordinal", "reuseFrom", "declaredStoredSha256")}} for x in rows]


def new_download(user, fid):
    with db() as c:
        f = file_access(c, fid, user)
        if not f["manifest_id"]:
            fail(409, "file_not_ready")
        chunks = c.execute("SELECT co.* FROM manifest_chunks mc JOIN chunk_objects co ON co.id=mc.chunk_id WHERE mc.manifest_id=%s ORDER BY co.id FOR UPDATE OF co", (f["manifest_id"],)).fetchall()
        if any(x["state"] != "live" for x in chunks):
            fail(503, "content_unavailable")
        did, expiry = ident("d"), now() + LEASE_TTL
        c.execute("INSERT INTO download_sessions(id,user_id,file_id,manifest_id,revision,expires_at,protect_until,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (did, user, fid, f["manifest_id"], f["revision"], expiry, expiry, now()))
        for x in chunks:
            c.execute("UPDATE chunk_objects SET unreferenced_since=NULL WHERE id=%s", (x["id"],))
    return {"downloadId": did, "fileId": fid, "revision": f["revision"], "manifestId": f["manifest_id"], "mode": "independent-chunks", "totalSizeBytes": f["size"], "leaseExpiresAt": expiry}


def download_manifest(user, did, use_cache=True):
    with db() as c:
        d = session(c, did, user)
        key = "manifest:" + d["manifest_id"] + ":format:1:page:0"
        cached = R.get(key) if use_cache else None
        if cached:
            chunks = json.loads(cached)
            metric("manifest_cache_hits")
        else:
            chunks = entries(c, d["manifest_id"])
            metric("manifest_sql_reads")
            if use_cache:
                R.setex(key, 600, json.dumps(chunks))
        m = c.execute("SELECT size FROM manifests WHERE id=%s", (d["manifest_id"],)).fetchone()
    return {"downloadId": did, "fileId": d["file_id"], "revision": d["revision"], "manifestId": d["manifest_id"], "totalSizeBytes": m["size"], "chunks": chunks, "cache": "HIT" if cached else "MISS"}


def download_urls(user, did, ids, delivery="storage"):
    if len(ids) > 100 or delivery not in ("storage", "cdn"):
        fail(400, "invalid_batch")
    result = []
    with db() as c:
        d = session(c, did, user)
        allowed = {x["chunk_id"] for x in c.execute("SELECT chunk_id FROM manifest_chunks WHERE manifest_id=%s", (d["manifest_id"],)).fetchall()}
        if not set(ids).issubset(allowed):
            fail(403, "chunk_not_in_selected_file")
        for cid in sorted(set(ids)):
            co = c.execute("SELECT * FROM chunk_objects WHERE id=%s FOR UPDATE", (cid,)).fetchone()
            if co["state"] != "live":
                fail(503, "content_unavailable")
            expiry = min(now() + URL_TTL, d["expires_at"])
            audience = "edge-get" if delivery == "cdn" else "storage-get"
            ticket = seal({"aud": audience, "key": co["object_key"], "version": co["version"], "exp": expiry})
            url = ("https://localhost:8422/chunk" if delivery == "cdn" else "https://localhost:8421/v1/objects/" + co["object_key"]) + "?ticket=" + ticket
            result.append({"chunkId": cid, "generation": co["version"], "url": url, "expiresAt": expiry, "delivery": delivery})
            c.execute("UPDATE chunk_objects SET protect_until=GREATEST(protect_until,%s),unreferenced_since=NULL WHERE id=%s", (expiry, cid))
    return {"downloadId": did, "revision": d["revision"], "chunks": result}
