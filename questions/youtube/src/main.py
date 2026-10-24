"""YouTube lab API: upload service, video service, S3 event consumer, and lab switches."""

from __future__ import annotations

import asyncio
import json
import math
import subprocess
import threading
import time
import uuid
from datetime import timedelta
from pathlib import Path
from urllib.parse import unquote

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .common import (
    DELIVERIES,
    FLAG_CRASH_TASK,
    LAB_EVENTS,
    LADDER,
    ORIGINALS,
    PART_SIZE,
    Q_EVENTS,
    Q_PLAN,
    Q_TASKS_HI,
    Q_TASKS_LO,
    RENDITIONS,
    WORK,
    cache_key,
    db,
    init_schema,
    lab_event,
    now_utc,
    redis_client,
    s3,
    s3_public,
)

app = FastAPI(title="YouTube lab")
STATIC = Path(__file__).parent / "static"
app.mount("/vendor", StaticFiles(directory="/app/vendor"), name="vendor")
CDN_HOST = "cdn"
L1_TTL = 5.0
_l1: dict[str, tuple[float, dict]] = {}


# ---------- setup ----------

def ensure_buckets() -> None:
    for _ in range(60):
        try:
            existing = {b["Name"] for b in s3.list_buckets().get("Buckets", [])}
            break
        except Exception:
            time.sleep(1)
    else:
        raise RuntimeError("MinIO not reachable")
    for bucket in (ORIGINALS, RENDITIONS, WORK):
        if bucket not in existing:
            s3.create_bucket(Bucket=bucket)
    # Renditions are public: players and CDN edges read them without a signature.
    s3.put_bucket_policy(Bucket=RENDITIONS, Policy=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Principal": {"AWS": ["*"]},
                       "Action": ["s3:GetObject"], "Resource": [f"arn:aws:s3:::{RENDITIONS}/*"]}],
    }))
    # Every completed original sends an event to the Redis list "s3events".
    s3.put_bucket_notification_configuration(Bucket=ORIGINALS, NotificationConfiguration={
        "QueueConfigurations": [{
            "QueueArn": "arn:minio:sqs::YT:redis",
            "Events": ["s3:ObjectCreated:*"],
            "Filter": {"Key": {"FilterRules": [{"Name": "suffix", "Value": "source.mp4"}]}},
        }]
    })


@app.on_event("startup")
def startup() -> None:
    init_schema()
    ensure_buckets()
    threading.Thread(target=event_consumer, name="s3-events", daemon=True).start()


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


# ---------- processing start (idempotent) ----------

def start_job(video_id: str, started_by: str) -> bool:
    """Create the job once. A second start (duplicate event, retry, sweep) only counts."""
    with db() as conn:
        row = conn.execute(
            """
            INSERT INTO jobs (video_id, state, started_by, created_at) VALUES (%s, 'planning', %s, now())
            ON CONFLICT (video_id) DO UPDATE SET starts_seen = jobs.starts_seen + 1
            RETURNING (xmax = 0) AS inserted, starts_seen
            """,
            (video_id, started_by),
        ).fetchone()
        conn.commit()
    if row["inserted"]:
        redis_client.lpush(Q_PLAN, video_id)
        lab_event("job-start", f"started by {started_by}", video_id)
        return True
    lab_event("job-duplicate", f"{started_by} start ignored (start #{row['starts_seen']}); job already exists", video_id)
    return False


def video_id_from_event(raw: str) -> list[str]:
    """MinIO's Redis access format is [{"Event": [S3 records], "EventTime": ...}]. Keys look like {id}/source.mp4."""
    data = json.loads(raw)
    envelopes = data if isinstance(data, list) else [data]
    records = []
    for env in envelopes:
        records += env.get("Event") or env.get("Records") or []
    ids = []
    for record in records:
        key = unquote(record.get("s3", {}).get("object", {}).get("key", ""))  # keys arrive URL-encoded
        if key.endswith("/source.mp4"):
            ids.append(key.split("/")[0])
    return ids


def event_consumer() -> None:
    while True:
        try:
            item = redis_client.blpop([Q_EVENTS], timeout=1)
            if item is None:
                continue
            for video_id in video_id_from_event(item[1]):
                with db() as conn:
                    v = conn.execute("SELECT trigger FROM videos WHERE video_id=%s", (video_id,)).fetchone()
                if v is None:
                    continue
                if v["trigger"] == "event":
                    lab_event("s3-event", "ObjectCreated for the original", video_id)
                    start_job(video_id, "s3-event")
                else:
                    lab_event("s3-event", "ObjectCreated ignored: this upload uses the service trigger", video_id)
        except Exception as exc:
            lab_event("event-error", str(exc)[:200])
            time.sleep(0.5)


# ---------- upload service ----------

class CreateVideo(BaseModel):
    title: str
    description: str = ""
    fileSizeBytes: int
    contentType: str = "video/mp4"
    sha256: str = ""
    trigger: str = "event"   # event | service


class PartRequest(BaseModel):
    partNumber: int
    sha256: str = ""         # base64 SHA-256 of this part. S3 rejects a mismatch


class PartsBody(BaseModel):
    parts: list[PartRequest]


class CompletedPart(BaseModel):
    partNumber: int
    etag: str


class CompleteBody(BaseModel):
    parts: list[CompletedPart]
    crashBeforeEnqueue: bool = False   # lab: the service dies after S3 completes


def load_upload(video_id: str) -> tuple[dict, dict]:
    with db() as conn:
        v = conn.execute("SELECT * FROM videos WHERE video_id=%s", (video_id,)).fetchone()
        u = conn.execute("SELECT * FROM uploads WHERE video_id=%s", (video_id,)).fetchone()
    if v is None or u is None:
        raise HTTPException(status_code=404, detail="video not found")
    return v, u


@app.post("/v1/videos")
def create_video(body: CreateVideo) -> dict:
    if body.fileSizeBytes <= 0:
        raise HTTPException(status_code=422, detail="fileSizeBytes must be positive")
    if body.trigger not in ("event", "service"):
        raise HTTPException(status_code=422, detail="trigger must be event or service")
    video_id = uuid.uuid4().hex[:10]
    key = f"{video_id}/source.mp4"
    part_count = max(1, math.ceil(body.fileSizeBytes / PART_SIZE))
    upload_id = s3.create_multipart_upload(Bucket=ORIGINALS, Key=key, ContentType=body.contentType)["UploadId"]
    with db() as conn:
        conn.execute(
            """
            INSERT INTO videos (video_id, uploader_id, title, description, status, trigger, original_key,
                                original_sha256, size_bytes, created_at, updated_at)
            VALUES (%s, 'lee', %s, %s, 'uploading', %s, %s, %s, %s, now(), now())
            """,
            (video_id, body.title, body.description, body.trigger, key, body.sha256 or None, body.fileSizeBytes),
        )
        conn.execute(
            """
            INSERT INTO uploads (video_id, s3_upload_id, part_size_bytes, part_count, file_size_bytes, state,
                                 created_at, expires_at)
            VALUES (%s, %s, %s, %s, %s, 'open', now(), now() + interval '7 days')
            """,
            (video_id, upload_id, PART_SIZE, part_count, body.fileSizeBytes),
        )
        conn.commit()
    lab_event("create", f"multipart upload started, {part_count} parts of {PART_SIZE // (1024 * 1024)} MiB", video_id)
    return {"videoId": video_id, "uploadId": upload_id, "partSizeBytes": PART_SIZE, "partCount": part_count}


@app.post("/v1/videos/{video_id}/parts")
def part_urls(video_id: str, body: PartsBody) -> dict:
    v, u = load_upload(video_id)
    if u["state"] != "open":
        raise HTTPException(status_code=409, detail=f"upload is {u['state']}")
    expires = 900
    out = []
    for p in body.parts:
        if not 1 <= p.partNumber <= u["part_count"]:
            raise HTTPException(status_code=422, detail=f"part {p.partNumber} out of range")
        params = {"Bucket": ORIGINALS, "Key": v["original_key"], "UploadId": u["s3_upload_id"], "PartNumber": p.partNumber}
        headers = {}
        if p.sha256:
            params["ChecksumSHA256"] = p.sha256
            headers["x-amz-checksum-sha256"] = p.sha256
        url = s3_public.generate_presigned_url("upload_part", Params=params, ExpiresIn=expires)
        out.append({
            "partNumber": p.partNumber,
            "url": url,
            "headers": headers,
            "expiresAt": (now_utc() + timedelta(seconds=expires)).isoformat(timespec="seconds"),
        })
    return {"parts": out}


def list_all_parts(bucket: str, key: str, upload_id: str) -> list[dict]:
    parts, marker = [], 0
    while True:
        page = s3.list_parts(Bucket=bucket, Key=key, UploadId=upload_id, PartNumberMarker=marker)
        parts += page.get("Parts", [])
        if not page.get("IsTruncated"):
            return parts
        marker = page["NextPartNumberMarker"]


@app.get("/v1/videos/{video_id}/upload")
def upload_state(video_id: str) -> dict:
    v, u = load_upload(video_id)
    parts = []
    if u["state"] == "open":
        parts = [
            {"partNumber": p["PartNumber"], "etag": p["ETag"], "size": p["Size"]}
            for p in list_all_parts(ORIGINALS, v["original_key"], u["s3_upload_id"])
        ]
    return {
        "videoId": video_id,
        "status": v["status"],
        "uploadState": u["state"],
        "partCount": u["part_count"],
        "uploadedParts": parts,
        "uploadedBytes": sum(p["size"] for p in parts),
        "fileSizeBytes": u["file_size_bytes"],
        "source": "S3 ListParts" if u["state"] == "open" else "upload already completed",
    }


@app.post("/v1/videos/{video_id}/complete", status_code=202)
def complete(video_id: str, body: CompleteBody) -> dict:
    v, u = load_upload(video_id)
    if u["state"] == "completed":
        return {"videoId": video_id, "status": v["status"], "note": "already completed; nothing done"}
    if u["state"] != "open":
        raise HTTPException(status_code=409, detail=f"upload is {u['state']}")
    try:
        res = s3.complete_multipart_upload(
            Bucket=ORIGINALS, Key=v["original_key"], UploadId=u["s3_upload_id"],
            MultipartUpload={"Parts": [{"PartNumber": p.partNumber, "ETag": p.etag}
                                       for p in sorted(body.parts, key=lambda p: p.partNumber)]},
        )
    except Exception as exc:  # InvalidPart: a pair that matches no stored part
        raise HTTPException(status_code=400, detail=f"S3 rejected the part list: {exc}") from exc
    with db() as conn:
        conn.execute(
            "UPDATE videos SET status='processing', original_etag=%s, updated_at=now() WHERE video_id=%s",
            (res["ETag"], video_id),
        )
        conn.execute("UPDATE uploads SET state='completed' WHERE video_id=%s", (video_id,))
        conn.commit()
    lab_event("complete", f"S3 joined {len(body.parts)} parts; ETag {res['ETag']}", video_id)
    if v["trigger"] == "service":
        if body.crashBeforeEnqueue:
            lab_event("service-crash", "service died after S3 completed, before it queued the job", video_id)
            raise HTTPException(status_code=500, detail="lab: the upload service crashed before queueing the job")
        start_job(video_id, "service")
    return {"videoId": video_id, "status": "processing", "originalEtag": res["ETag"], "trigger": v["trigger"]}


# ---------- video service ----------

def video_view(video_id: str) -> dict | None:
    with db() as conn:
        v = conn.execute("SELECT * FROM videos WHERE video_id=%s", (video_id,)).fetchone()
        if v is None:
            return None
        rs = conn.execute(
            "SELECT name, width, height, bitrate_kbps, segment_count FROM renditions WHERE video_id=%s ORDER BY height",
            (video_id,),
        ).fetchall()
    manifest = v["manifest_key"]
    deliveries = {}
    if manifest:
        deliveries = {name: f"{base}/{RENDITIONS}/{manifest}" for name, base in DELIVERIES.items()}
    return {
        "videoId": video_id,
        "title": v["title"],
        "status": v["status"],
        "error": v["error"],
        "durationSec": v["duration_sec"],
        "manifestUrl": deliveries.get("cdn"),
        "deliveries": deliveries,
        "renditions": [dict(r) for r in rs],
        "trigger": v["trigger"],
    }


@app.get("/v1/videos/{video_id}")
def get_video(video_id: str) -> dict:
    # In-process cache (5 s), then Redis, then Postgres. Only ready videos are cached.
    hit = _l1.get(video_id)
    if hit and time.time() - hit[0] < L1_TTL:
        return {**hit[1], "servedFrom": "in-process cache"}
    cached = redis_client.get(cache_key(video_id))
    if cached:
        view = json.loads(cached)
        _l1[video_id] = (time.time(), view)
        return {**view, "servedFrom": "redis"}
    view = video_view(video_id)
    if view is None:
        raise HTTPException(status_code=404, detail="video not found")
    if view["status"] == "ready" and len(view["renditions"]) == len(LADDER):
        redis_client.set(cache_key(video_id), json.dumps(view), ex=600)
        _l1[video_id] = (time.time(), view)
    return {**view, "servedFrom": "postgres"}


@app.get("/v1/videos")
def list_videos() -> dict:
    with db() as conn:
        rows = conn.execute(
            "SELECT video_id, title, status, trigger, created_at FROM videos ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
    return {"videos": [{**r, "created_at": r["created_at"].isoformat(timespec="seconds")} for r in rows]}


# ---------- lab ----------

SAMPLES = Path("/tmp/samples")


@app.get("/v1/lab/sample.mp4")
def sample(seconds: int = 24) -> FileResponse:
    """A generated test clip: 720p, a keyframe every 2 s, a tone, about 8 Mbps so it spans several parts."""
    seconds = max(4, min(seconds, 60))
    SAMPLES.mkdir(exist_ok=True)
    path = SAMPLES / f"sample_{seconds}s.mp4"
    if not path.exists():
        subprocess.run([
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate=24:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:v", "libx264", "-preset", "veryfast", "-b:v", "8M", "-g", "48", "-keyint_min", "48",
            "-sc_threshold", "0", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
        ], check=True, capture_output=True)
    return FileResponse(path, media_type="video/mp4", filename=path.name)


class ReplayBody(BaseModel):
    videoId: str


@app.post("/v1/lab/replay-event")
def replay_event(body: ReplayBody) -> dict:
    """Send the same ObjectCreated event again, as S3 may do."""
    event = {"Event": [{"eventName": "s3:ObjectCreated:CompleteMultipartUpload",
                        "s3": {"object": {"key": f"{body.videoId}/source.mp4"}}}]}
    redis_client.rpush(Q_EVENTS, json.dumps(event))
    lab_event("replay", "duplicate ObjectCreated event sent", body.videoId)
    return {"replayed": True}


@app.post("/v1/lab/crash-next-task")
def crash_next_task() -> dict:
    redis_client.set(FLAG_CRASH_TASK, "1")
    lab_event("lab", "the next worker to lease a task will die mid-task")
    return {"crashNextTask": True}


@app.post("/v1/lab/sweep")
def sweep() -> dict:
    """Find originals that S3 completed but nobody started processing."""
    with db() as conn:
        stuck = conn.execute(
            """
            SELECT v.video_id, v.original_key FROM videos v
            JOIN uploads u ON u.video_id = v.video_id
            LEFT JOIN jobs j ON j.video_id = v.video_id
            WHERE v.status = 'processing' AND u.state = 'completed' AND j.video_id IS NULL
            """
        ).fetchall()
    started = []
    for row in stuck:
        try:
            s3.head_object(Bucket=ORIGINALS, Key=row["original_key"])
        except Exception:
            continue
        if start_job(row["video_id"], "sweep"):
            started.append(row["video_id"])
    lab_event("sweep", f"found {len(stuck)} stuck, started {len(started)}")
    return {"stuck": len(stuck), "started": started}


class CleanupBody(BaseModel):
    olderThanSeconds: int = 0


@app.post("/v1/lab/cleanup-uploads")
def cleanup_uploads(body: CleanupBody) -> dict:
    """The sweep half of abandoned-upload cleanup. S3's lifecycle rule would delete the parts after 7 days."""
    with db() as conn:
        rows = conn.execute(
            """
            SELECT video_id, s3_upload_id FROM uploads
            WHERE state='open' AND created_at < now() - make_interval(secs => %s)
            """,
            (body.olderThanSeconds,),
        ).fetchall()
    aborted = []
    for r in rows:
        with db() as conn:
            v = conn.execute("SELECT original_key FROM videos WHERE video_id=%s", (r["video_id"],)).fetchone()
        try:
            s3.abort_multipart_upload(Bucket=ORIGINALS, Key=v["original_key"], UploadId=r["s3_upload_id"])
        except Exception:
            pass
        with db() as conn:
            conn.execute("UPDATE uploads SET state='aborted' WHERE video_id=%s", (r["video_id"],))
            conn.execute(
                "UPDATE videos SET status='failed', error='upload abandoned', updated_at=now() WHERE video_id=%s",
                (r["video_id"],),
            )
            conn.commit()
        aborted.append(r["video_id"])
    open_in_s3 = len(s3.list_multipart_uploads(Bucket=ORIGINALS).get("Uploads", []))
    lab_event("cleanup", f"aborted {len(aborted)} open uploads; {open_in_s3} still open in S3")
    return {"aborted": aborted, "openMultipartUploadsInS3": open_in_s3}


class BurstBody(BaseModel):
    videoId: str
    mode: str = "shield"   # shield: edges A and B ask the shield. noShield: edges C and D ask the origin
    requests: int = 20


def origin_hits(tag: str) -> dict:
    """Count, from the CDN log, how often the tagged URL reached each layer."""
    stats = {"edgeMiss": 0, "edgeHit": 0, "shieldMiss": 0, "shieldHit": 0, "originFetches": 0}
    try:
        lines = Path("/cdn-logs/cdn.log").read_text().splitlines()[-4000:]
    except FileNotFoundError:
        return stats
    for line in lines:
        if tag not in line:
            continue
        entry = json.loads(line)
        port, cache = entry["port"], entry["cache"]
        if port == "8390":
            stats["shieldMiss" if cache == "MISS" else "shieldHit"] += 1
            if cache == "MISS":
                stats["originFetches"] += 1
        else:
            stats["edgeMiss" if cache == "MISS" else "edgeHit"] += 1
            if cache == "MISS" and port in ("8303", "8304"):
                stats["originFetches"] += 1
    return stats


@app.post("/v1/lab/cdn-burst")
async def cdn_burst(body: BurstBody) -> dict:
    """Many viewers ask for the same new segment at once, through two edges."""
    view = video_view(body.videoId)
    if not view or not view["renditions"]:
        raise HTTPException(status_code=409, detail="video has no rendition yet")
    tag = uuid.uuid4().hex[:8]
    rendition = view["renditions"][0]["name"]
    path = f"/{RENDITIONS}/v/{body.videoId}/{rendition}/seg_00000.ts?burst={tag}"
    ports = (8301, 8302) if body.mode == "shield" else (8303, 8304)
    async with httpx.AsyncClient(timeout=20) as client:
        results = await asyncio.gather(*[
            client.get(f"http://{CDN_HOST}:{ports[i % 2]}{path}") for i in range(body.requests)
        ])
    await asyncio.sleep(0.3)
    stats = origin_hits(tag)
    lab_event("cdn-burst", f"{body.requests} requests via {body.mode}: origin fetched {stats['originFetches']}x", body.videoId)
    return {
        "mode": body.mode,
        "requests": body.requests,
        "edges": list(ports),
        "statusCodes": sorted({r.status_code for r in results}),
        "url": path,
        **stats,
    }


@app.post("/v1/lab/reset")
def reset() -> dict:
    with db() as conn:
        conn.execute("TRUNCATE videos, uploads, renditions, jobs, tasks")
        conn.commit()
    for bucket in (ORIGINALS, RENDITIONS, WORK):
        for up in s3.list_multipart_uploads(Bucket=bucket).get("Uploads", []):
            s3.abort_multipart_upload(Bucket=bucket, Key=up["Key"], UploadId=up["UploadId"])
        while True:
            objs = s3.list_objects_v2(Bucket=bucket).get("Contents", [])
            if not objs:
                break
            s3.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": o["Key"]} for o in objs]})
    for key in [Q_PLAN, Q_TASKS_HI, Q_TASKS_LO, LAB_EVENTS, FLAG_CRASH_TASK]:
        redis_client.delete(key)
    for key in redis_client.scan_iter("video:*"):
        redis_client.delete(key)
    _l1.clear()
    return {"ok": True}


def bucket_summary(bucket: str, prefix: str = "") -> dict:
    objs = s3.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1000).get("Contents", [])
    return {
        "objects": len(objs),
        "bytes": sum(o["Size"] for o in objs),
        "sample": [{"key": o["Key"], "size": o["Size"], "etag": o["ETag"]} for o in objs[:12]],
    }


@app.get("/v1/lab/state")
def state(videoId: str = "") -> dict:
    with db() as conn:
        videos = conn.execute(
            """SELECT video_id, title, status, trigger, original_etag, left(original_sha256, 16) AS sha256_prefix,
                      manifest_key, round(duration_sec::numeric, 1) AS duration_sec, error FROM videos
               ORDER BY created_at DESC LIMIT 8"""
        ).fetchall()
        uploads = conn.execute(
            "SELECT video_id, state, part_count, part_size_bytes, left(s3_upload_id, 16) AS s3_upload_id FROM uploads "
            "ORDER BY created_at DESC LIMIT 8"
        ).fetchall()
        jobs = conn.execute(
            "SELECT video_id, state, started_by, starts_seen, tasks_total FROM jobs ORDER BY created_at DESC LIMIT 8"
        ).fetchall()
        renditions = conn.execute(
            "SELECT video_id, name, segment_count, manifest_key FROM renditions ORDER BY ready_at DESC LIMIT 12"
        ).fetchall()
        tasks = []
        if videoId:
            tasks = conn.execute(
                "SELECT chunk, rendition, state, attempts, worker FROM tasks WHERE video_id=%s ORDER BY rendition, chunk",
                (videoId,),
            ).fetchall()
    open_uploads = s3.list_multipart_uploads(Bucket=ORIGINALS).get("Uploads", [])
    return {
        "postgres": {
            "videos": [dict(r) for r in videos],
            "uploads": [dict(r) for r in uploads],
            "jobs": [dict(r) for r in jobs],
            "renditions": [dict(r) for r in renditions],
            "tasks": [dict(r) for r in tasks],
        },
        "s3": {
            "originals": bucket_summary(ORIGINALS),
            "renditions": bucket_summary(RENDITIONS, f"v/{videoId}/" if videoId else ""),
            "work": bucket_summary(WORK),
            "openMultipartUploads": [{"key": u["Key"], "uploadId": u["UploadId"][:16]} for u in open_uploads],
        },
        "redis": {
            "queues": {q: redis_client.llen(q) for q in (Q_EVENTS, Q_PLAN, Q_TASKS_HI, Q_TASKS_LO)},
            "cachedVideos": sorted(k for k in redis_client.scan_iter("video:*")),
            "crashNextTask": bool(redis_client.get(FLAG_CRASH_TASK)),
        },
        "events": [json.loads(e) for e in redis_client.lrange(LAB_EVENTS, 0, 40)],
    }
