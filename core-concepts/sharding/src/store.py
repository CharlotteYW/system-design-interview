"""Two schemas as shards, plus a recent table written with each order."""

from __future__ import annotations

import os

import psycopg

SHARDS = ("shard0", "shard1")
RECENT = "recent"


def connect() -> psycopg.Connection:
    return psycopg.connect(os.environ["DATABASE_URL"])


def shard_name(account_id: int) -> str:
    return "shard0" if account_id % 2 == 0 else "shard1"


def init_db() -> None:
    with connect() as conn:
        for schema in (*SHARDS, RECENT):
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {schema}.orders (
                    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    account_id bigint NOT NULL,
                    note text NOT NULL,
                    shard text NOT NULL
                )
                """
            )
        conn.commit()


def reset() -> None:
    with connect() as conn:
        for schema in (*SHARDS, RECENT):
            conn.execute(f"TRUNCATE {schema}.orders RESTART IDENTITY")
        conn.commit()


def place_order(account_id: int, note: str) -> dict:
    shard = shard_name(account_id)
    with connect() as conn:
        row = conn.execute(
            f"INSERT INTO {shard}.orders (account_id, note, shard) VALUES (%s, %s, %s) RETURNING id",
            (account_id, note, shard),
        ).fetchone()
        conn.execute(
            f"INSERT INTO {RECENT}.orders (account_id, note, shard) VALUES (%s, %s, %s)",
            (account_id, note, shard),
        )
        conn.commit()
    return {
        "id": row[0],
        "account_id": account_id,
        "note": note,
        "shard": shard,
        "wrote": [shard, RECENT],
    }


def my_orders(account_id: int) -> dict:
    shard = shard_name(account_id)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT account_id, note, shard FROM {shard}.orders WHERE account_id = %s ORDER BY id",
            (account_id,),
        ).fetchall()
    return {
        "shards_read": [shard],
        "orders": [{"account_id": r[0], "note": r[1], "shard": r[2]} for r in rows],
    }


def recent_from_table() -> dict:
    with connect() as conn:
        rows = conn.execute(
            f"SELECT account_id, note, shard FROM {RECENT}.orders ORDER BY id"
        ).fetchall()
    return {
        "source": "recent",
        "shards_read": [RECENT],
        "orders": [{"account_id": r[0], "note": r[1], "shard": r[2]} for r in rows],
    }


def recent_by_scatter() -> dict:
    orders = []
    with connect() as conn:
        for shard in SHARDS:
            rows = conn.execute(
                f"SELECT account_id, note, shard FROM {shard}.orders ORDER BY id"
            ).fetchall()
            orders.extend({"account_id": r[0], "note": r[1], "shard": r[2]} for r in rows)
    return {"source": "scatter", "shards_read": list(SHARDS), "orders": orders}
