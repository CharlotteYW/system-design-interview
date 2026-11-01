"""Leased fan-out, verification recovery, and fenced content retirement."""
import os
import time
import uuid

from . import domain as d
from .common import R, fault, http, now


def fanout(batch=50):
    worker = "worker-" + uuid.uuid4().hex[:8]
    with d.db() as c:
        job = c.execute("""SELECT o.* FROM outbox o
          WHERE (o.state='pending' OR (o.state='running' AND o.lease_until < %s))
          AND NOT EXISTS (SELECT 1 FROM outbox earlier WHERE earlier.file_id=o.file_id
             AND earlier.revision < o.revision AND earlier.state!='done')
          ORDER BY o.created_at,o.id LIMIT 1 FOR UPDATE SKIP LOCKED""", (now(),)).fetchone()
        if not job:
            return {"processed": 0, "idle": True}
        epoch = job["lease_epoch"] + 1
        c.execute("UPDATE outbox SET state='running',lease_owner=%s,lease_until=%s,lease_epoch=%s WHERE id=%s", (worker, now() + 10, epoch, job["id"]))
    if fault("crash_after_job_claim") and R.hdel("lab:faults", "crash_after_job_claim"):
        return {"eventId": job["id"], "simulatedCrash": True, "leaseUntil": now() + 10}
    recipients = []
    with d.db() as c:
        current = c.execute("SELECT * FROM outbox WHERE id=%s FOR UPDATE", (job["id"],)).fetchone()
        if current["lease_owner"] != worker or current["lease_epoch"] != epoch:
            return {"fenced": True}
        rows = c.execute("SELECT user_id FROM access WHERE file_id=%s AND user_id > %s AND user_id!=%s ORDER BY user_id LIMIT %s", (job["file_id"], current["cursor"], job["owner"], batch)).fetchall()
        for row in rows:
            user = row["user_id"]
            d.append_change(c, user, job["id"], job["file_id"], job["revision"], job["type"])
            recipients.append(user)
        cursor = rows[-1]["user_id"] if rows else current["cursor"]
        done = len(rows) < batch
        c.execute("UPDATE outbox SET cursor=%s,processed=processed+%s,state=%s,lease_until=0 WHERE id=%s AND lease_epoch=%s", (cursor, len(rows), "done" if done else "pending", job["id"], epoch))
    if not fault("drop_hints"):
        d.hints(recipients)
    return {"eventId": job["id"], "processed": len(rows), "done": done, "leaseEpoch": epoch}


def rooted(c, cid, at):
    return bool(c.execute("""SELECT 1 FROM manifest_chunks mc JOIN files f ON f.manifest_id=mc.manifest_id
       WHERE mc.chunk_id=%s AND f.deleted_at IS NULL
       UNION ALL SELECT 1 FROM upload_chunks uc JOIN uploads u ON u.id=uc.upload_id
       WHERE uc.chunk_id=%s AND u.state IN ('uploading','verifying','conflicted') AND u.expires_at>%s
       UNION ALL SELECT 1 FROM manifest_chunks mc JOIN download_sessions ds ON ds.manifest_id=mc.manifest_id
       WHERE mc.chunk_id=%s AND (ds.protect_until>%s OR (ds.state='active' AND ds.expires_at>%s)) LIMIT 1""",
       (cid, cid, at, cid, at, at)).fetchone())


def roots_for_display(c, cid):
    return {"files": [x["id"] for x in c.execute("SELECT f.id FROM files f JOIN manifest_chunks mc ON mc.manifest_id=f.manifest_id WHERE mc.chunk_id=%s AND f.deleted_at IS NULL", (cid,)).fetchall()],
            "uploads": [x["id"] for x in c.execute("SELECT u.id FROM uploads u JOIN upload_chunks uc ON uc.upload_id=u.id WHERE uc.chunk_id=%s AND u.state IN ('uploading','verifying','conflicted') AND u.expires_at>%s", (cid, now())).fetchall()],
            "downloads": [x["id"] for x in c.execute("SELECT ds.id FROM download_sessions ds JOIN manifest_chunks mc ON mc.manifest_id=ds.manifest_id WHERE mc.chunk_id=%s AND ds.protect_until>%s", (cid, now())).fetchall()]}


def gc_run(grace=5, mark_only=False):
    marked, deleted, kept = [], [], []
    with d.db() as c:
        rows = c.execute("SELECT * FROM chunk_objects WHERE state!='deleted' ORDER BY id FOR UPDATE SKIP LOCKED").fetchall()
        for row in rows:
            if row["state"] == "deleting":
                marked.append(row)
                continue
            if rooted(c, row["id"], now()) or row["protect_until"] > now():
                c.execute("UPDATE chunk_objects SET unreferenced_since=NULL WHERE id=%s", (row["id"],))
                kept.append(row["id"])
                continue
            since = row["unreferenced_since"]
            if since is None:
                since = now()
                c.execute("UPDATE chunk_objects SET unreferenced_since=%s WHERE id=%s", (since, row["id"]))
            if now() - since >= grace:
                c.execute("UPDATE chunk_objects SET state='deleting',delete_token=%s WHERE id=%s", (str(uuid.uuid4()), row["id"]))
                marked.append(row)
    if mark_only:
        return {"marked": [x["id"] for x in marked], "deleted": [], "kept": kept, "pause": "after durable mark"}
    for row in marked:
        version = row["version"]
        with http() as client:
            if not version:
                head = client.get("https://storage:8000/v1/meta/" + row["object_key"])
                if head.status_code == 200:
                    version = head.json()["version"]
            if version:
                res = client.delete("https://storage:8000/v1/objects/" + row["object_key"], params={"version": version})
                if res.status_code not in (204, 404):
                    continue
        with d.db() as c:
            c.execute("UPDATE chunk_objects SET state='deleted',version=COALESCE(version,%s),deleted_at=%s WHERE id=%s AND state='deleting'", (version, now(), row["id"]))
        deleted.append(row["id"])
    return {"marked": [x["id"] for x in marked], "deleted": deleted, "kept": kept}


def reconciliation():
    with d.db() as c:
        pending = c.execute("SELECT id,owner FROM uploads WHERE reconcile_requested=true AND state NOT IN ('completed','expired','cancelled') AND expires_at>%s LIMIT 5", (now(),)).fetchall()
    for u in pending:
        try:
            status = d.upload_status(u["owner"], u["id"])
            for ordinal in status["missingOrdinals"]:
                try:
                    d.verify(u["owner"], u["id"], ordinal)
                except Exception:
                    pass
            with d.db() as c:
                c.execute("UPDATE uploads SET reconcile_requested=false WHERE id=%s", (u["id"],))
        except Exception:
            pass


def main():
    d.POOL.open(wait=True, timeout=60)
    while True:
        try:
            if not fault("worker_paused"):
                fanout(int(R.get("lab:batch") or 50))
                reconciliation()
        except Exception as exc:
            print("Worker retains pending work:", type(exc).__name__, flush=True)
        time.sleep(0.4)


if __name__ == "__main__":
    main()
