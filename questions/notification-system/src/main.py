"""Local notification lab.

Kafka is two Redis lists. The scheduler, the expander, and the workers
run in this process. Vendors are a log, not Twilio.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import redis
from fastapi import FastAPI, HTTPException
from psycopg.errors import UniqueViolation
from fastapi.responses import FileResponse
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://app:app@localhost:5432/app"
)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
HIGH_RESERVE = 100
CONTRACT_RATE = 1000
VENDORS = ("twilio", "email", "apple")
TOPIC_HIGH = "notices-high"
TOPIC_LOW = "notices-low"

app = FastAPI(title="Notification system")
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
_pump_started = False


def connect():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def init_db() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notices (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              channel TEXT NOT NULL,
              title TEXT NOT NULL DEFAULT '',
              body TEXT NOT NULL DEFAULT '',
              campaign_id TEXT,
              send_at TIMESTAMPTZ NOT NULL,
              priority TEXT NOT NULL DEFAULT 'low',
              idempotency_key TEXT UNIQUE,
              topic TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS notices_campaign_user
            ON notices (campaign_id, user_id)
            WHERE campaign_id IS NOT NULL
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS campaigns (
              id TEXT PRIMARY KEY,
              channel TEXT NOT NULL,
              title TEXT NOT NULL,
              body TEXT NOT NULL,
              send_at TIMESTAMPTZ NOT NULL,
              status TEXT NOT NULL,
              idempotency_key TEXT UNIQUE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS campaign_users (
              campaign_id TEXT NOT NULL,
              user_id TEXT NOT NULL,
              PRIMARY KEY (campaign_id, user_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS send_records (
              notice_id TEXT NOT NULL,
              channel TEXT NOT NULL,
              status TEXT NOT NULL,
              attempt_count INT NOT NULL DEFAULT 0,
              next_attempt_at TIMESTAMPTZ,
              PRIMARY KEY (notice_id, channel)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schedule (
              id TEXT PRIMARY KEY,
              due_at TIMESTAMPTZ NOT NULL,
              notice_id TEXT,
              campaign_id TEXT,
              status TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS schedule_due
            ON schedule (status, due_at)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vendor_calls (
              id TEXT PRIMARY KEY,
              notice_id TEXT NOT NULL,
              vendor TEXT NOT NULL,
              result TEXT NOT NULL,
              created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        conn.commit()


def seed() -> None:
    people = {
        "lee": {
            "email": "lee@example.com",
            "phone": "+15550001111",
            "deviceToken": "token-lee",
        },
        "kim": {
            "email": "kim@example.com",
            "phone": "+15550002222",
            "deviceToken": "token-kim",
        },
    }
    preference = {
        "push": True,
        "email": True,
        "sms": True,
        "quietStart": "",
        "quietEnd": "",
    }
    for user_id, contact in people.items():
        if redis_client.get(f"contact:{user_id}") is None:
            redis_client.set(f"contact:{user_id}", json.dumps(contact))
        if redis_client.get(f"preference:{user_id}") is None:
            redis_client.set(f"preference:{user_id}", json.dumps(preference))
    refill_tokens(force=True)


def vendor_for(channel: str) -> str:
    if channel == "sms":
        return "twilio"
    if channel == "email":
        return "email"
    return "apple"


def refill_tokens(force: bool = False) -> None:
    second = int(time.time())
    if not force and redis_client.get("budget:second") == str(second):
        return
    redis_client.set("budget:second", second)
    for vendor in VENDORS:
        redis_client.set(f"budget:{vendor}:high", HIGH_RESERVE)
        redis_client.set(f"budget:{vendor}:low", CONTRACT_RATE - HIGH_RESERVE)


def take_token(vendor: str, priority: str) -> bool:
    high_key = f"budget:{vendor}:high"
    low_key = f"budget:{vendor}:low"
    if priority == "high" and int(redis_client.get(high_key) or 0) > 0:
        redis_client.decr(high_key)
        return True
    if int(redis_client.get(low_key) or 0) > 0:
        if priority == "low" or priority == "high":
            redis_client.decr(low_key)
            return True
    return False


def parse_when(value: str | None) -> datetime:
    if not value:
        return now_utc()
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def in_quiet(start: str, end: str, moment: datetime) -> bool:
    if not start or not end:
        return False
    current = moment.strftime("%H:%M")
    if start <= end:
        return start <= current < end
    return current >= start or current < end


class ContactBody(BaseModel):
    email: str
    phone: str
    deviceToken: str


class PreferenceBody(BaseModel):
    push: bool
    email: bool
    sms: bool
    quietStart: str = ""
    quietEnd: str = ""


class ContentBody(BaseModel):
    title: str = ""
    body: str


class NoticeBody(BaseModel):
    userId: str
    channel: str
    content: ContentBody
    priority: str = "low"
    scheduledAt: str | None = None
    idempotencyKey: str


class CampaignBody(BaseModel):
    userIds: list[str] = Field(min_length=1)
    channel: str
    content: ContentBody
    scheduledAt: str | None = None
    idempotencyKey: str


class VendorBody(BaseModel):
    vendor: str
    down: bool


def require_channel(channel: str) -> None:
    if channel not in ("push", "email", "sms"):
        raise HTTPException(status_code=422, detail="channel must be push, email, or sms")


def require_priority(priority: str) -> None:
    if priority not in ("high", "low"):
        raise HTTPException(status_code=422, detail="priority must be high or low")


@app.on_event("startup")
def startup() -> None:
    global _pump_started
    init_db()
    seed()
    if not _pump_started:
        threading.Thread(target=pump, name="notice-pump", daemon=True).start()
        _pump_started = True


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.put("/v1/users/{user_id}/contact")
def put_contact(user_id: str, body: ContactBody) -> dict:
    redis_client.set(
        f"contact:{user_id}",
        json.dumps(body.model_dump()),
    )
    return {"userId": user_id}


@app.put("/v1/users/{user_id}/preferences")
def put_preferences(user_id: str, body: PreferenceBody) -> dict:
    redis_client.set(f"preference:{user_id}", json.dumps(body.model_dump()))
    return {"userId": user_id}


@app.post("/v1/notices", status_code=202)
def post_notice(body: NoticeBody) -> dict:
    require_channel(body.channel)
    require_priority(body.priority)
    if not body.idempotencyKey.strip():
        raise HTTPException(status_code=422, detail="idempotencyKey is required")
    send_at = parse_when(body.scheduledAt)
    notice_id = str(uuid.uuid4())
    with connect() as conn:
        try:
            existing = conn.execute(
                "SELECT id FROM notices WHERE idempotency_key = %s",
                (body.idempotencyKey,),
            ).fetchone()
            if existing:
                return {"id": existing["id"], "status": "accepted"}
            conn.execute(
                """
                INSERT INTO notices (
                  id, user_id, channel, title, body, campaign_id, send_at, priority, idempotency_key
                ) VALUES (%s, %s, %s, %s, %s, NULL, %s, %s, %s)
                """,
                (
                    notice_id,
                    body.userId,
                    body.channel,
                    body.content.title,
                    body.content.body,
                    send_at,
                    body.priority,
                    body.idempotencyKey,
                ),
            )
            conn.execute(
                """
                INSERT INTO send_records (notice_id, channel, status, attempt_count)
                VALUES (%s, %s, 'accepted', 0)
                """,
                (notice_id, body.channel),
            )
            conn.execute(
                """
                INSERT INTO schedule (id, due_at, notice_id, campaign_id, status)
                VALUES (%s, %s, %s, NULL, 'waiting')
                """,
                (str(uuid.uuid4()), send_at, notice_id),
            )
            conn.commit()
        except UniqueViolation:
            conn.rollback()
            existing = conn.execute(
                "SELECT id FROM notices WHERE idempotency_key = %s",
                (body.idempotencyKey,),
            ).fetchone()
            if existing is None:
                raise
            return {"id": existing["id"], "status": "accepted"}
    return {"id": notice_id, "status": "accepted"}


@app.post("/v1/campaigns", status_code=202)
def post_campaign(body: CampaignBody) -> dict:
    require_channel(body.channel)
    if not body.idempotencyKey.strip():
        raise HTTPException(status_code=422, detail="idempotencyKey is required")
    send_at = parse_when(body.scheduledAt)
    campaign_id = str(uuid.uuid4())
    with connect() as conn:
        try:
            return _insert_campaign(conn, body, campaign_id, send_at)
        except UniqueViolation:
            conn.rollback()
            existing = conn.execute(
                "SELECT id FROM campaigns WHERE idempotency_key = %s",
                (body.idempotencyKey,),
            ).fetchone()
            if existing is None:
                raise
            return {"id": existing["id"], "status": "accepted"}


def _insert_campaign(conn, body: CampaignBody, campaign_id: str, send_at: datetime) -> dict:
    existing = conn.execute(
        "SELECT id, status FROM campaigns WHERE idempotency_key = %s",
        (body.idempotencyKey,),
    ).fetchone()
    if existing:
        return {"id": existing["id"], "status": "accepted"}
    conn.execute(
        """
        INSERT INTO campaigns (
          id, channel, title, body, send_at, status, idempotency_key
        ) VALUES (%s, %s, %s, %s, %s, 'accepted', %s)
        """,
        (
            campaign_id,
            body.channel,
            body.content.title,
            body.content.body,
            send_at,
            body.idempotencyKey,
        ),
    )
    for user_id in dict.fromkeys(body.userIds):
        conn.execute(
            """
            INSERT INTO campaign_users (campaign_id, user_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (campaign_id, user_id),
        )
    conn.execute(
        """
        INSERT INTO schedule (id, due_at, notice_id, campaign_id, status)
        VALUES (%s, %s, NULL, %s, 'waiting')
        """,
        (str(uuid.uuid4()), send_at, campaign_id),
    )
    conn.commit()
    return {"id": campaign_id, "status": "accepted"}


@app.post("/v1/campaigns/{campaign_id}/cancel")
def cancel_campaign(campaign_id: str) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, status FROM campaigns WHERE id = %s",
            (campaign_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="campaign not found")
        conn.execute(
            "UPDATE campaigns SET status = 'cancelled' WHERE id = %s",
            (campaign_id,),
        )
        conn.commit()
    return {"id": campaign_id, "status": "cancelled"}


@app.get("/v1/notices/{notice_id}")
def get_notice(notice_id: str) -> dict:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT n.id, n.channel, s.status
            FROM notices n
            JOIN send_records s ON s.notice_id = n.id AND s.channel = n.channel
            WHERE n.id = %s
            """,
            (notice_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="notice not found")
    return {"id": row["id"], "status": row["status"], "channel": row["channel"]}


@app.get("/v1/campaigns/{campaign_id}")
def get_campaign(campaign_id: str) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, status FROM campaigns WHERE id = %s",
            (campaign_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    return {"id": row["id"], "status": row["status"]}


@app.post("/v1/lab/vendor")
def set_vendor(body: VendorBody) -> dict:
    if body.vendor not in VENDORS:
        raise HTTPException(status_code=422, detail="unknown vendor")
    if body.down:
        redis_client.set(f"vendor:{body.vendor}:down", "1")
    else:
        redis_client.delete(f"vendor:{body.vendor}:down")
    return {"vendor": body.vendor, "down": body.down}


@app.get("/v1/lab/state")
def lab_state() -> dict:
    with connect() as conn:
        notices = conn.execute(
            """
            SELECT n.id, n.user_id, n.channel, n.priority, n.campaign_id, n.topic,
                   n.title, n.body, s.status, s.attempt_count
            FROM notices n
            JOIN send_records s ON s.notice_id = n.id AND s.channel = n.channel
            ORDER BY n.send_at DESC
            LIMIT 40
            """
        ).fetchall()
        campaigns = conn.execute(
            """
            SELECT id, channel, title, status, send_at
            FROM campaigns
            ORDER BY send_at DESC
            LIMIT 20
            """
        ).fetchall()
        schedule = conn.execute(
            """
            SELECT id, due_at, notice_id, campaign_id, status
            FROM schedule
            ORDER BY due_at DESC
            LIMIT 40
            """
        ).fetchall()
        calls = conn.execute(
            """
            SELECT notice_id, vendor, result, created_at
            FROM vendor_calls
            ORDER BY created_at DESC
            LIMIT 40
            """
        ).fetchall()
    return {
        "interviewDefault": "schedule row, then scheduler, then notices-high or notices-low",
        "topics": {
            TOPIC_HIGH: redis_client.llen(TOPIC_HIGH),
            TOPIC_LOW: redis_client.llen(TOPIC_LOW),
        },
        "budgets": {
            vendor: {
                "high": int(redis_client.get(f"budget:{vendor}:high") or 0),
                "low": int(redis_client.get(f"budget:{vendor}:low") or 0),
                "down": redis_client.get(f"vendor:{vendor}:down") == "1",
            }
            for vendor in VENDORS
        },
        "notices": [_jsonable(row) for row in notices],
        "campaigns": [_jsonable(row) for row in campaigns],
        "schedule": [_jsonable(row) for row in schedule],
        "vendorCalls": [_jsonable(row) for row in calls],
    }


def _jsonable(row: dict) -> dict:
    out = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out


def pump() -> None:
    while True:
        try:
            refill_tokens()
            tick()
        except Exception:
            time.sleep(0.5)
        time.sleep(0.2)


def tick() -> None:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, due_at, notice_id, campaign_id
            FROM schedule
            WHERE status = 'waiting' AND due_at <= %s
            ORDER BY due_at
            LIMIT 30
            FOR UPDATE SKIP LOCKED
            """,
            (now_utc(),),
        ).fetchall()
        for row in rows:
            if row["campaign_id"] and not row["notice_id"]:
                expand_campaign(conn, row)
            elif row["notice_id"]:
                publish_notice(conn, row)
        conn.commit()
    drain(TOPIC_HIGH, "high")
    drain(TOPIC_LOW, "low")


def expand_campaign(conn, row: dict) -> None:
    campaign = conn.execute(
        "SELECT id, channel, status FROM campaigns WHERE id = %s",
        (row["campaign_id"],),
    ).fetchone()
    if campaign is None or campaign["status"] == "cancelled":
        conn.execute(
            "UPDATE schedule SET status = 'queued' WHERE id = %s",
            (row["id"],),
        )
        return
    conn.execute(
        "UPDATE campaigns SET status = 'expanding' WHERE id = %s AND status = 'accepted'",
        (campaign["id"],),
    )
    pending = conn.execute(
        """
        SELECT cu.user_id
        FROM campaign_users cu
        WHERE cu.campaign_id = %s
          AND NOT EXISTS (
            SELECT 1 FROM notices n
            WHERE n.campaign_id = cu.campaign_id AND n.user_id = cu.user_id
          )
        ORDER BY cu.user_id
        LIMIT 50
        """,
        (campaign["id"],),
    ).fetchall()
    if not pending:
        conn.execute(
            "UPDATE campaigns SET status = 'done' WHERE id = %s AND status <> 'cancelled'",
            (campaign["id"],),
        )
        conn.execute(
            "UPDATE schedule SET status = 'queued' WHERE id = %s",
            (row["id"],),
        )
        return
    moment = now_utc()
    for user in pending:
        notice_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO notices (
              id, user_id, channel, title, body, campaign_id, send_at, priority, idempotency_key
            ) VALUES (%s, %s, %s, '', '', %s, %s, 'low', NULL)
            """,
            (notice_id, user["user_id"], campaign["channel"], campaign["id"], moment),
        )
        conn.execute(
            """
            INSERT INTO send_records (notice_id, channel, status, attempt_count)
            VALUES (%s, %s, 'accepted', 0)
            """,
            (notice_id, campaign["channel"]),
        )
        conn.execute(
            """
            INSERT INTO schedule (id, due_at, notice_id, campaign_id, status)
            VALUES (%s, %s, %s, NULL, 'waiting')
            """,
            (str(uuid.uuid4()), moment, notice_id),
        )


def publish_notice(conn, row: dict) -> None:
    notice = conn.execute(
        "SELECT id, priority FROM notices WHERE id = %s",
        (row["notice_id"],),
    ).fetchone()
    if notice is None:
        conn.execute(
            "UPDATE schedule SET status = 'queued' WHERE id = %s",
            (row["id"],),
        )
        return
    topic = TOPIC_HIGH if notice["priority"] == "high" else TOPIC_LOW
    redis_client.rpush(topic, notice["id"])
    conn.execute(
        "UPDATE notices SET topic = %s WHERE id = %s",
        (topic, notice["id"]),
    )
    conn.execute(
        "UPDATE schedule SET status = 'queued' WHERE id = %s",
        (row["id"],),
    )


def drain(topic: str, priority: str) -> None:
    for _ in range(20):
        notice_id = redis_client.lindex(topic, 0)
        if not notice_id:
            return
        if not handle_queued(topic, notice_id, priority):
            return


def handle_queued(topic: str, notice_id: str, priority: str) -> bool:
    with connect() as conn:
        notice = conn.execute(
            """
            SELECT n.id, n.user_id, n.channel, n.priority, n.campaign_id, n.title, n.body,
                   s.status
            FROM notices n
            JOIN send_records s ON s.notice_id = n.id AND s.channel = n.channel
            WHERE n.id = %s
            """,
            (notice_id,),
        ).fetchone()
        if notice is None or notice["status"] in ("sent", "failed", "skipped", "cancelled"):
            redis_client.lpop(topic)
            conn.rollback()
            return True
        if notice["campaign_id"]:
            campaign = conn.execute(
                "SELECT status, title, body FROM campaigns WHERE id = %s",
                (notice["campaign_id"],),
            ).fetchone()
            if campaign and campaign["status"] == "cancelled":
                redis_client.lpop(topic)
                conn.execute(
                    """
                    UPDATE send_records SET status = 'cancelled'
                    WHERE notice_id = %s AND channel = %s
                    """,
                    (notice_id, notice["channel"]),
                )
                conn.commit()
                return True
            title = campaign["title"] if campaign else ""
            body = campaign["body"] if campaign else ""
        else:
            title = notice["title"]
            body = notice["body"]
        preference = json.loads(redis_client.get(f"preference:{notice['user_id']}") or "{}")
        contact = json.loads(redis_client.get(f"contact:{notice['user_id']}") or "{}")
        channel_on = {
            "push": preference.get("push", True),
            "email": preference.get("email", True),
            "sms": preference.get("sms", True),
        }[notice["channel"]]
        if not channel_on:
            redis_client.lpop(topic)
            conn.execute(
                """
                UPDATE send_records SET status = 'skipped'
                WHERE notice_id = %s AND channel = %s
                """,
                (notice_id, notice["channel"]),
            )
            conn.commit()
            return True
        if notice["priority"] == "low" and in_quiet(
            preference.get("quietStart", ""),
            preference.get("quietEnd", ""),
            now_utc(),
        ):
            redis_client.lpop(topic)
            conn.execute(
                """
                INSERT INTO schedule (id, due_at, notice_id, campaign_id, status)
                VALUES (%s, %s, %s, NULL, 'waiting')
                """,
                (str(uuid.uuid4()), now_utc() + timedelta(minutes=1), notice_id),
            )
            conn.commit()
            return True
        vendor = vendor_for(notice["channel"])
        if redis_client.get(f"vendor:{vendor}:down") == "1":
            conn.rollback()
            return False
        if not take_token(vendor, priority):
            conn.rollback()
            return False
        claimed = conn.execute(
            """
            UPDATE send_records
            SET status = 'sending', attempt_count = attempt_count + 1
            WHERE notice_id = %s AND channel = %s AND status = 'accepted'
            RETURNING notice_id
            """,
            (notice_id, notice["channel"]),
        ).fetchone()
        redis_client.lpop(topic)
        if claimed is None:
            conn.commit()
            return True
        address = {
            "sms": contact.get("phone"),
            "email": contact.get("email"),
            "push": contact.get("deviceToken"),
        }[notice["channel"]]
        if not address:
            conn.execute(
                """
                UPDATE send_records SET status = 'failed'
                WHERE notice_id = %s AND channel = %s
                """,
                (notice_id, notice["channel"]),
            )
            conn.commit()
            return True
        conn.execute(
            """
            INSERT INTO vendor_calls (id, notice_id, vendor, result, created_at)
            VALUES (%s, %s, %s, 'sent', %s)
            """,
            (str(uuid.uuid4()), notice_id, vendor, now_utc()),
        )
        conn.execute(
            """
            UPDATE send_records SET status = 'sent'
            WHERE notice_id = %s AND channel = %s
            """,
            (notice_id, notice["channel"]),
        )
        conn.commit()
        _ = (title, body)
        return True
