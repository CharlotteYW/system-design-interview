"""Where messages and device cursors live.

Design 1 keeps both in Postgres. Design 2 keeps both in Cassandra. The roster
tables (users, chats, chat_members, clients, last_seen) stay in Postgres in
both designs, so only this module changes between them.
"""

from __future__ import annotations

import os
import time
from collections import OrderedDict
from datetime import datetime, timezone

# Lab value. Production would bucket by about 10 days, or by a larger count.
BUCKET_SIZE = int(os.environ.get("CASSANDRA_BUCKET_SIZE", "5"))
MESSAGE_TTL_SECONDS = 30 * 24 * 3600


def _iso(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return value


class PostgresMessageStore:
    design = "postgres"

    def __init__(self, connect_db):
        self.connect_db = connect_db

    def init_schema(self) -> None:
        with self.connect_db() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                  id TEXT PRIMARY KEY,
                  chat_id TEXT NOT NULL,
                  seq INT NOT NULL,
                  sender_id TEXT NOT NULL,
                  body TEXT NOT NULL DEFAULT '',
                  media_key TEXT NOT NULL DEFAULT '',
                  created_at TIMESTAMPTZ NOT NULL,
                  UNIQUE (chat_id, seq)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS device_cursors (
                  client_id TEXT NOT NULL,
                  chat_id TEXT NOT NULL,
                  last_seq INT NOT NULL DEFAULT 0,
                  updated_at TIMESTAMPTZ NOT NULL,
                  PRIMARY KEY (client_id, chat_id)
                )
                """
            )
            conn.commit()

    def clear(self) -> None:
        with self.connect_db() as conn:
            conn.execute("TRUNCATE TABLE messages, device_cursors")
            conn.commit()

    def insert_message(self, msg: dict) -> dict:
        with self.connect_db() as conn:
            conn.execute(
                """
                INSERT INTO messages (
                  id, chat_id, seq, sender_id, body, media_key, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    msg["id"],
                    msg["chat_id"],
                    msg["seq"],
                    msg["sender_id"],
                    msg["body"],
                    msg["media_key"],
                    msg["created_at"],
                ),
            )
            conn.commit()
        return {"store": "postgres", "table": "messages", "key": {"id": msg["id"]}}

    def set_sender_cursor(self, client_id: str, chat_id: str, seq: int) -> None:
        self.ack(client_id, chat_id, seq, mode="greatest")

    def read_cursor(self, client_id: str, chat_id: str) -> int:
        with self.connect_db() as conn:
            row = conn.execute(
                """
                SELECT last_seq FROM device_cursors
                WHERE client_id = %s AND chat_id = %s
                """,
                (client_id, chat_id),
            ).fetchone()
        return int(row["last_seq"]) if row else 0

    def read_after(self, chat_id: str, last_seq: int, current_seq: int):
        with self.connect_db() as conn:
            rows = conn.execute(
                """
                SELECT id, chat_id, seq, sender_id, body, media_key, created_at
                FROM messages
                WHERE chat_id = %s AND seq > %s
                ORDER BY seq
                """,
                (chat_id, last_seq),
            ).fetchall()
        reads = [
            {
                "store": "postgres",
                "query": f"messages WHERE chat_id = '{chat_id}' AND seq > {last_seq}",
                "index": "UNIQUE (chat_id, seq)",
                "rows": len(rows),
            }
        ]
        return [{k: _iso(v) for k, v in row.items()} for row in rows], reads

    def ack(self, client_id: str, chat_id: str, seq: int, mode: str = "greatest") -> dict:
        before = self.read_cursor(client_id, chat_id)
        with self.connect_db() as conn:
            conn.execute(
                """
                INSERT INTO device_cursors (client_id, chat_id, last_seq, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (client_id, chat_id) DO UPDATE
                SET last_seq = GREATEST(device_cursors.last_seq, EXCLUDED.last_seq),
                    updated_at = EXCLUDED.updated_at
                """,
                (client_id, chat_id, seq, datetime.now(timezone.utc)),
            )
            conn.commit()
        after = self.read_cursor(client_id, chat_id)
        return {
            "mode": "greatest",
            "before": before,
            "after": after,
            "statement": "INSERT ... ON CONFLICT DO UPDATE SET last_seq = GREATEST(old, new)",
        }

    def snapshot(self) -> dict:
        with self.connect_db() as conn:
            messages = conn.execute(
                """
                SELECT id, chat_id, seq, sender_id, body, media_key, created_at
                FROM messages ORDER BY created_at DESC LIMIT 40
                """
            ).fetchall()
            cursors = conn.execute(
                """
                SELECT client_id, chat_id, last_seq, updated_at
                FROM device_cursors ORDER BY client_id, chat_id
                """
            ).fetchall()
        return {
            "messages": [{k: _iso(v) for k, v in r.items()} for r in messages],
            "device_cursors": [{k: _iso(v) for k, v in r.items()} for r in cursors],
        }


class CassandraMessageStore:
    design = "cassandra"

    def __init__(self, hosts: list[str], keyspace: str = "chat"):
        self.hosts = hosts
        self.keyspace = keyspace
        self.session = None

    def _connect(self):
        from cassandra.cluster import Cluster
        from cassandra.query import dict_factory

        last_error = None
        for _ in range(90):
            try:
                cluster = Cluster(self.hosts, port=9042, connect_timeout=5)
                session = cluster.connect()
                session.row_factory = dict_factory
                return session
            except Exception as exc:  # Cassandra takes about a minute to accept CQL.
                last_error = exc
                time.sleep(2)
        raise RuntimeError(f"Cassandra not reachable: {last_error}")

    def init_schema(self) -> None:
        self.session = self._connect()
        s = self.session
        s.execute(
            f"""
            CREATE KEYSPACE IF NOT EXISTS {self.keyspace}
            WITH replication = {{'class': 'SimpleStrategy', 'replication_factor': 1}}
            """
        )
        s.set_keyspace(self.keyspace)
        s.execute(
            f"""
            CREATE TABLE IF NOT EXISTS messages_by_chat (
              chat_id text,
              bucket int,
              seq int,
              id text,
              sender_id text,
              body text,
              media_key text,
              created_at timestamp,
              PRIMARY KEY ((chat_id, bucket), seq)
            ) WITH CLUSTERING ORDER BY (seq ASC)
              AND default_time_to_live = {MESSAGE_TTL_SECONDS}
            """
        )
        s.execute(
            """
            CREATE TABLE IF NOT EXISTS device_cursors_by_client (
              client_id text,
              chat_id text,
              last_seq int,
              updated_at timestamp,
              PRIMARY KEY ((client_id), chat_id)
            )
            """
        )
        self.q_insert = s.prepare(
            """
            INSERT INTO messages_by_chat
              (chat_id, bucket, seq, id, sender_id, body, media_key, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """
        )
        self.q_read_bucket = s.prepare(
            """
            SELECT chat_id, bucket, seq, id, sender_id, body, media_key, created_at
            FROM messages_by_chat
            WHERE chat_id = ? AND bucket = ? AND seq > ?
            """
        )
        self.q_cursor = s.prepare(
            """
            SELECT last_seq FROM device_cursors_by_client
            WHERE client_id = ? AND chat_id = ?
            """
        )
        self.q_upsert_cursor = s.prepare(
            """
            UPDATE device_cursors_by_client
            SET last_seq = ?, updated_at = ?
            WHERE client_id = ? AND chat_id = ?
            """
        )
        self.q_lwt_cursor = s.prepare(
            """
            UPDATE device_cursors_by_client
            SET last_seq = ?, updated_at = ?
            WHERE client_id = ? AND chat_id = ?
            IF last_seq < ?
            """
        )
        self.q_lwt_insert = s.prepare(
            """
            INSERT INTO device_cursors_by_client (client_id, chat_id, last_seq, updated_at)
            VALUES (?, ?, ?, ?)
            IF NOT EXISTS
            """
        )

    @staticmethod
    def bucket_for(seq: int) -> int:
        return seq // BUCKET_SIZE

    def clear(self) -> None:
        self.session.execute("TRUNCATE messages_by_chat")
        self.session.execute("TRUNCATE device_cursors_by_client")

    def insert_message(self, msg: dict) -> dict:
        bucket = self.bucket_for(msg["seq"])
        self.session.execute(
            self.q_insert,
            (
                msg["chat_id"],
                bucket,
                msg["seq"],
                msg["id"],
                msg["sender_id"],
                msg["body"],
                msg["media_key"],
                msg["created_at"],
            ),
        )
        return {
            "store": "cassandra",
            "table": "messages_by_chat",
            "partition": {"chat_id": msg["chat_id"], "bucket": bucket},
            "clustering": {"seq": msg["seq"]},
            "ttlSeconds": MESSAGE_TTL_SECONDS,
        }

    def set_sender_cursor(self, client_id: str, chat_id: str, seq: int) -> None:
        self.session.execute(
            self.q_upsert_cursor, (seq, datetime.now(timezone.utc), client_id, chat_id)
        )

    def read_cursor(self, client_id: str, chat_id: str) -> int:
        row = self.session.execute(self.q_cursor, (client_id, chat_id)).one()
        return int(row["last_seq"]) if row and row["last_seq"] is not None else 0

    def read_after(self, chat_id: str, last_seq: int, current_seq: int):
        rows: list[dict] = []
        reads: list[dict] = []
        first = self.bucket_for(last_seq + 1)
        last = self.bucket_for(max(current_seq, last_seq + 1))
        for bucket in range(first, last + 1):
            found = list(self.session.execute(self.q_read_bucket, (chat_id, bucket, last_seq)))
            reads.append(
                {
                    "store": "cassandra",
                    "partition": {"chat_id": chat_id, "bucket": bucket},
                    "query": f"WHERE chat_id = '{chat_id}' AND bucket = {bucket} AND seq > {last_seq}",
                    "rows": len(found),
                }
            )
            rows.extend(found)
        rows.sort(key=lambda r: r["seq"])
        return [{k: _iso(v) for k, v in r.items()} for r in rows], reads

    def ack(self, client_id: str, chat_id: str, seq: int, mode: str = "upsert") -> dict:
        before = self.read_cursor(client_id, chat_id)
        now = datetime.now(timezone.utc)
        applied = True
        if mode == "lwt":
            result = self.session.execute(
                self.q_lwt_cursor, (seq, now, client_id, chat_id, seq)
            ).one()
            applied = bool(result["[applied]"])
            if not applied and result.get("last_seq") is None:
                inserted = self.session.execute(
                    self.q_lwt_insert, (client_id, chat_id, seq, now)
                ).one()
                applied = bool(inserted["[applied]"])
            statement = "UPDATE ... SET last_seq = ? IF last_seq < ?  (Paxos round trips)"
        else:
            mode = "upsert"
            self.session.execute(self.q_upsert_cursor, (seq, now, client_id, chat_id))
            statement = "UPDATE ... SET last_seq = ?  (last write wins, no read)"
        after = self.read_cursor(client_id, chat_id)
        return {
            "mode": mode,
            "before": before,
            "after": after,
            "applied": applied,
            "statement": statement,
        }

    def snapshot(self) -> dict:
        rows = list(
            self.session.execute(
                """
                SELECT chat_id, bucket, seq, id, sender_id, body, media_key, created_at,
                       token(chat_id, bucket) AS partition_token,
                       TTL(body) AS ttl_seconds,
                       WRITETIME(body) AS writetime_us
                FROM messages_by_chat
                """
            )
        )
        rows.sort(key=lambda r: (r["chat_id"], r["bucket"], r["seq"]))
        messages = []
        partitions: "OrderedDict[tuple, dict]" = OrderedDict()
        for r in rows:
            token = str(r["partition_token"])
            messages.append(
                {
                    "chat_id": r["chat_id"],
                    "bucket": r["bucket"],
                    "seq": r["seq"],
                    "sender_id": r["sender_id"],
                    "body": r["body"],
                    "media_key": r["media_key"],
                    "ttl_seconds": r["ttl_seconds"],
                    "writetime": _iso(
                        datetime.fromtimestamp(r["writetime_us"] / 1_000_000, tz=timezone.utc)
                    )
                    if r["writetime_us"]
                    else None,
                    "token": token,
                }
            )
            key = (r["chat_id"], r["bucket"])
            part = partitions.setdefault(
                key,
                {
                    "partition_key": f"({r['chat_id']}, {r['bucket']})",
                    "token": token,
                    "rows": 0,
                    "seq_range": "",
                    "_min": r["seq"],
                    "_max": r["seq"],
                },
            )
            part["rows"] += 1
            part["_min"] = min(part["_min"], r["seq"])
            part["_max"] = max(part["_max"], r["seq"])
        part_rows = []
        for part in partitions.values():
            part["seq_range"] = f"{part.pop('_min')}..{part.pop('_max')}"
            part_rows.append(part)

        cursors = list(
            self.session.execute(
                """
                SELECT client_id, chat_id, last_seq, updated_at,
                       WRITETIME(last_seq) AS writetime_us
                FROM device_cursors_by_client
                """
            )
        )
        cursors.sort(key=lambda r: (r["client_id"], r["chat_id"]))
        cursor_rows = [
            {
                "client_id": r["client_id"],
                "chat_id": r["chat_id"],
                "last_seq": r["last_seq"],
                "updated_at": _iso(r["updated_at"]),
            }
            for r in cursors
        ]
        return {
            "messages_by_chat": messages[-60:],
            "partitions": part_rows,
            "device_cursors_by_client": cursor_rows,
            "bucketSize": BUCKET_SIZE,
        }
