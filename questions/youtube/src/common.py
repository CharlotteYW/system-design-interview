"""Shared config, stores, and schema for the app and the workers."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

import boto3
import psycopg
import redis
from botocore.config import Config
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:5432/app")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
S3_INTERNAL_URL = os.environ.get("S3_INTERNAL_URL", "http://localhost:9000")
S3_PUBLIC_URL = os.environ.get("S3_PUBLIC_URL", "http://localhost:9000")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "minio")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "minio12345")
LEASE_SECONDS = int(os.environ.get("LEASE_SECONDS", "8"))

ORIGINALS = "originals"
RENDITIONS = "renditions"
WORK = "work"
# S3 needs at least 5 MiB per part, except the last one.
PART_SIZE = 5 * 1024 * 1024
CHUNK_SECONDS = 4

# name, width, height, video kbps. Low renditions first: 240p is the high-priority queue.
LADDER = [
    ("240p", 426, 240, 300),
    ("480p", 854, 480, 900),
    ("720p", 1280, 720, 2500),
]

# Public URLs the browser uses. The edges live in the cdn container.
DELIVERIES = {
    "cdn": "http://localhost:8301",
    "slow": "http://localhost:8305",
    "noShield": "http://localhost:8303",
    "origin": "http://localhost:9000",
}

Q_EVENTS = "s3events"          # MinIO writes bucket events here
Q_PLAN = "q:plan"              # one item per video to probe and split
Q_TASKS_HI = "q:tasks:hi"      # 240p transcode tasks
Q_TASKS_LO = "q:tasks:lo"      # 480p and 720p transcode tasks
LAB_EVENTS = "lab:events"      # what happened, newest first, for the page
FLAG_CRASH_TASK = "lab:crash_next_task"

redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
_pool: ConnectionPool | None = None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def db():
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            DATABASE_URL, kwargs={"row_factory": dict_row}, min_size=1, max_size=10, open=True
        )
    return _pool.connection()


def _s3(endpoint: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


# Server-side calls go to minio:9000 inside Docker.
s3 = _s3(S3_INTERNAL_URL)
# Presigned URLs are signed for the host the browser uses. Signing is local math,
# so this client never connects to anything.
s3_public = _s3(S3_PUBLIC_URL)


def lab_event(kind: str, detail: str, video_id: str = "") -> None:
    item = {"at": now_utc().isoformat(timespec="seconds"), "kind": kind, "videoId": video_id, "detail": detail}
    redis_client.lpush(LAB_EVENTS, json.dumps(item))
    redis_client.ltrim(LAB_EVENTS, 0, 99)


SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
  video_id TEXT PRIMARY KEY,
  uploader_id TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,             -- uploading, processing, ready, failed
  visibility TEXT NOT NULL DEFAULT 'public',
  trigger TEXT NOT NULL DEFAULT 'event',   -- event or service: who starts processing
  original_key TEXT NOT NULL,
  original_etag TEXT,
  original_sha256 TEXT,
  manifest_key TEXT,
  duration_sec REAL,
  size_bytes BIGINT,
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL,
  ready_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS videos_uploader_idx ON videos (uploader_id, created_at);

CREATE TABLE IF NOT EXISTS uploads (
  video_id TEXT PRIMARY KEY,
  s3_upload_id TEXT NOT NULL,
  part_size_bytes INT NOT NULL,
  part_count INT NOT NULL,
  file_size_bytes BIGINT NOT NULL,
  state TEXT NOT NULL,              -- open, completed, aborted
  created_at TIMESTAMPTZ NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS renditions (
  video_id TEXT NOT NULL,
  name TEXT NOT NULL,
  width INT NOT NULL,
  height INT NOT NULL,
  bitrate_kbps INT NOT NULL,
  manifest_key TEXT NOT NULL,
  segment_count INT NOT NULL,
  ready_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (video_id, name)
);

CREATE TABLE IF NOT EXISTS jobs (
  video_id TEXT PRIMARY KEY,
  state TEXT NOT NULL,              -- planning, transcoding, done, failed
  started_by TEXT NOT NULL,         -- s3-event, service, sweep
  starts_seen INT NOT NULL DEFAULT 1,
  chunk_durations JSONB,
  tasks_total INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS tasks (
  video_id TEXT NOT NULL,
  chunk INT NOT NULL,
  rendition TEXT NOT NULL,
  state TEXT NOT NULL,              -- queued, running, done
  attempts INT NOT NULL DEFAULT 0,
  worker TEXT,
  lease_until TIMESTAMPTZ,
  output_key TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (video_id, chunk, rendition)
);
"""


def init_schema() -> None:
    for _ in range(60):
        try:
            with db() as conn:
                conn.execute(SCHEMA)
                conn.commit()
            return
        except psycopg.OperationalError:
            time.sleep(1)
    raise RuntimeError("Postgres not reachable")


def segment_key(video_id: str, rendition: str, chunk: int) -> str:
    return f"v/{video_id}/{rendition}/seg_{chunk:05d}.ts"


def cache_key(video_id: str) -> str:
    return f"video:{video_id}"
