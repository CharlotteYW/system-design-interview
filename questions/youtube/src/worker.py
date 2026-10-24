"""Processing worker: plan (probe, check SHA-256, split) and transcode one chunk into one rendition.

Two workers run. They pull from Redis lists in priority order: plans first,
then 240p tasks, then the rest. A task is leased in Postgres; a worker that
dies loses its lease, and another worker redoes the task into the same key.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

from .common import (
    CHUNK_SECONDS,
    FLAG_CRASH_TASK,
    LADDER,
    LEASE_SECONDS,
    ORIGINALS,
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
    segment_key,
)

WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"
SCRATCH = Path("/tmp/yt")
LADDER_BY_NAME = {name: (name, w, h, kbps) for name, w, h, kbps in LADDER}


def run(cmd: list[str]) -> str:
    done = subprocess.run(cmd, capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {done.stderr[-400:]}")
    return done.stdout


def probe_duration(path: Path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)])
    return float(json.loads(out)["format"]["duration"])


def fail_video(video_id: str, error: str) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE videos SET status='failed', error=%s, updated_at=now() WHERE video_id=%s",
            (error, video_id),
        )
        conn.execute("UPDATE jobs SET state='failed', finished_at=now() WHERE video_id=%s", (video_id,))
        conn.commit()
    redis_client.delete(cache_key(video_id))
    lab_event("failed", error, video_id)


def plan(video_id: str) -> None:
    with db() as conn:
        video = conn.execute("SELECT * FROM videos WHERE video_id=%s", (video_id,)).fetchone()
        job = conn.execute("SELECT * FROM jobs WHERE video_id=%s", (video_id,)).fetchone()
    if video is None or job is None or job["state"] != "planning":
        return
    work = SCRATCH / video_id
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    source = work / "source.mp4"

    # Guarded read: refuse an original that changed since `complete`.
    try:
        obj = s3.get_object(Bucket=ORIGINALS, Key=video["original_key"], IfMatch=video["original_etag"])
    except Exception as exc:  # 412 when the ETag no longer matches
        fail_video(video_id, f"original changed or missing: {exc}")
        return
    digest = hashlib.sha256()
    with source.open("wb") as out:
        for block in iter(lambda: obj["Body"].read(1024 * 1024), b""):
            digest.update(block)
            out.write(block)
    actual = digest.hexdigest()
    if video["original_sha256"] and actual != video["original_sha256"]:
        fail_video(video_id, f"checksum mismatch: expected {video['original_sha256'][:12]}..., got {actual[:12]}...")
        return
    lab_event("probe", f"SHA-256 matches ({actual[:12]}...)", video_id)

    try:
        duration = probe_duration(source)
        # Split at keyframes without re-encoding. -reset_timestamps 0 keeps the
        # original timestamps, so independently encoded chunks play back in order.
        run([
            "ffmpeg", "-v", "error", "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?",
            "-c", "copy", "-f", "segment", "-segment_time", str(CHUNK_SECONDS),
            "-segment_format", "mpegts", "-reset_timestamps", "0", str(work / "chunk_%05d.ts"),
        ])
    except RuntimeError as exc:
        fail_video(video_id, f"probe or split failed: {exc}")
        return

    chunks = sorted(work.glob("chunk_*.ts"))
    durations = [round(probe_duration(c), 3) for c in chunks]
    for i, chunk in enumerate(chunks):
        s3.upload_file(str(chunk), WORK, f"tmp/{video_id}/chunk_{i:05d}.ts")

    with db() as conn:
        for name, *_ in LADDER:
            for i in range(len(chunks)):
                conn.execute(
                    """
                    INSERT INTO tasks (video_id, chunk, rendition, state, output_key, updated_at)
                    VALUES (%s, %s, %s, 'queued', %s, now()) ON CONFLICT DO NOTHING
                    """,
                    (video_id, i, name, segment_key(video_id, name, i)),
                )
        conn.execute(
            """
            UPDATE jobs SET state='transcoding', chunk_durations=%s, tasks_total=%s WHERE video_id=%s
            """,
            (json.dumps(durations), len(chunks) * len(LADDER), video_id),
        )
        conn.execute(
            "UPDATE videos SET duration_sec=%s, updated_at=now() WHERE video_id=%s",
            (duration, video_id),
        )
        conn.commit()
    # Low renditions first: 240p goes on the high-priority queue.
    for name, *_ in LADDER:
        queue = Q_TASKS_HI if name == LADDER[0][0] else Q_TASKS_LO
        for i in range(len(chunks)):
            redis_client.lpush(queue, json.dumps({"videoId": video_id, "chunk": i, "rendition": name}))
    lab_event("split", f"{len(chunks)} chunks x {len(LADDER)} renditions = {len(chunks) * len(LADDER)} tasks", video_id)
    shutil.rmtree(work, ignore_errors=True)


def lease(video_id: str, chunk: int, rendition: str) -> int | None:
    with db() as conn:
        row = conn.execute(
            """
            UPDATE tasks
            SET state='running', attempts=attempts+1, worker=%s,
                lease_until=now() + make_interval(secs => %s), updated_at=now()
            WHERE video_id=%s AND chunk=%s AND rendition=%s
              AND (state='queued' OR (state='running' AND lease_until < now()))
            RETURNING attempts
            """,
            (WORKER_ID, LEASE_SECONDS, video_id, chunk, rendition),
        ).fetchone()
        conn.commit()
    return row["attempts"] if row else None


def transcode(video_id: str, chunk: int, rendition: str) -> None:
    attempt = lease(video_id, chunk, rendition)
    if attempt is None:
        return  # done already, or another worker holds the lease
    if redis_client.getdel(FLAG_CRASH_TASK):
        lab_event("worker-crash", f"{WORKER_ID} died during {rendition} chunk {chunk} (attempt {attempt})", video_id)
        os._exit(1)  # no cleanup, no lease release: a real crash

    name, width, height, kbps = LADDER_BY_NAME[rendition]
    work = SCRATCH / f"{video_id}-{rendition}-{chunk}"
    work.mkdir(parents=True, exist_ok=True)
    src, out = work / "in.ts", work / "out.ts"
    s3.download_file(WORK, f"tmp/{video_id}/chunk_{chunk:05d}.ts", str(src))
    run([
        "ffmpeg", "-v", "error", "-y", "-copyts", "-i", str(src),
        "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", f"scale={width}:{height}", "-c:v", "libx264", "-preset", "veryfast",
        "-b:v", f"{kbps}k", "-maxrate", f"{kbps}k", "-bufsize", f"{kbps * 2}k",
        "-c:a", "aac", "-b:a", "64k", "-f", "mpegts", "-muxdelay", "0", str(out),
    ])
    # Fixed key: a retry overwrites the same object, and S3 swaps it whole.
    s3.upload_file(str(out), RENDITIONS, segment_key(video_id, rendition, chunk),
                   ExtraArgs={"ContentType": "video/mp2t"})
    shutil.rmtree(work, ignore_errors=True)
    with db() as conn:
        conn.execute(
            "UPDATE tasks SET state='done', updated_at=now() WHERE video_id=%s AND chunk=%s AND rendition=%s",
            (video_id, chunk, rendition),
        )
        conn.commit()
    fan_in(video_id, rendition)


def write_text(key: str, body: str) -> None:
    s3.put_object(Bucket=RENDITIONS, Key=key, Body=body.encode(), ContentType="application/vnd.apple.mpegurl")


def fan_in(video_id: str, rendition: str) -> None:
    """The last finished chunk of a rendition writes its manifest. Serialized by the job row lock."""
    with db() as conn:
        job = conn.execute("SELECT * FROM jobs WHERE video_id=%s FOR UPDATE", (video_id,)).fetchone()
        durations = job["chunk_durations"] or []
        done = conn.execute(
            "SELECT count(*) AS n FROM tasks WHERE video_id=%s AND rendition=%s AND state='done'",
            (video_id, rendition),
        ).fetchone()["n"]
        exists = conn.execute(
            "SELECT 1 FROM renditions WHERE video_id=%s AND name=%s", (video_id, rendition)
        ).fetchone()
        if done < len(durations) or exists:
            conn.commit()
            return

        name, width, height, kbps = LADDER_BY_NAME[rendition]
        lines = [
            "#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-PLAYLIST-TYPE:VOD",
            f"#EXT-X-TARGETDURATION:{math.ceil(max(durations))}", "#EXT-X-MEDIA-SEQUENCE:0",
        ]
        for i, d in enumerate(durations):
            lines += [f"#EXTINF:{d:.3f},", f"seg_{i:05d}.ts"]
        lines.append("#EXT-X-ENDLIST")
        index_key = f"v/{video_id}/{rendition}/index.m3u8"
        write_text(index_key, "\n".join(lines) + "\n")
        conn.execute(
            """
            INSERT INTO renditions (video_id, name, width, height, bitrate_kbps, manifest_key, segment_count, ready_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, now())
            """,
            (video_id, name, width, height, kbps, index_key, len(durations)),
        )
        finished = conn.execute(
            "SELECT * FROM renditions WHERE video_id=%s ORDER BY height", (video_id,)
        ).fetchall()
        master = ["#EXTM3U"]
        for r in finished:
            master += [
                f"#EXT-X-STREAM-INF:BANDWIDTH={(r['bitrate_kbps'] + 64) * 1000},RESOLUTION={r['width']}x{r['height']}",
                f"{r['name']}/index.m3u8",
            ]
        master_key = f"v/{video_id}/master.m3u8"
        write_text(master_key, "\n".join(master) + "\n")
        first = len(finished) == 1
        if first:
            # Playable now at the lowest rendition. Higher ones join the master as they finish.
            conn.execute(
                """
                UPDATE videos SET status='ready', manifest_key=%s, ready_at=now(), updated_at=now()
                WHERE video_id=%s
                """,
                (master_key, video_id),
            )
        all_done = len(finished) == len(LADDER)
        if all_done:
            conn.execute("UPDATE jobs SET state='done', finished_at=now() WHERE video_id=%s", (video_id,))
        conn.commit()
    # The status or the rendition list changed, so drop the cached row.
    redis_client.delete(cache_key(video_id))
    lab_event("rendition", f"{rendition} ready ({len(durations)} segments); master lists {len(finished)}", video_id)
    if all_done:
        for i in range(len(durations)):
            s3.delete_object(Bucket=WORK, Key=f"tmp/{video_id}/chunk_{i:05d}.ts")
        lab_event("done", "all renditions ready; tmp chunks deleted", video_id)


def reap() -> None:
    """Requeue tasks whose lease ran out: the worker that held them died."""
    with db() as conn:
        rows = conn.execute(
            "SELECT video_id, chunk, rendition, worker FROM tasks WHERE state='running' AND lease_until < now()"
        ).fetchall()
    for r in rows:
        queue = Q_TASKS_HI if r["rendition"] == LADDER[0][0] else Q_TASKS_LO
        redis_client.lpush(queue, json.dumps({"videoId": r["video_id"], "chunk": r["chunk"], "rendition": r["rendition"]}))
        lab_event("requeue", f"lease expired for {r['rendition']} chunk {r['chunk']} (held by {r['worker']})", r["video_id"])


def main() -> None:
    init_schema()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    last_reap = 0.0
    while True:
        if time.time() - last_reap > 2:
            # One reaper at a time, across workers.
            if redis_client.set("lab:reaper", WORKER_ID, nx=True, ex=2):
                reap()
            last_reap = time.time()
        item = redis_client.brpop([Q_PLAN, Q_TASKS_HI, Q_TASKS_LO], timeout=1)
        if item is None:
            continue
        queue, payload = item
        try:
            if queue == Q_PLAN:
                plan(payload)
            else:
                task = json.loads(payload)
                transcode(task["videoId"], task["chunk"], task["rendition"])
        except Exception as exc:  # leave the lease to expire; the reaper retries
            lab_event("task-error", f"{WORKER_ID}: {exc}"[:300])


if __name__ == "__main__":
    main()
