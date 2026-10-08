"""One live engine for each database type. The other product names stay on the list."""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

import psycopg
import redis
from cassandra.cluster import Cluster
from psycopg.rows import dict_row
from pymongo import MongoClient

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:5432/app")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://mongo:27017")
CASSANDRA_HOST = os.environ.get("CASSANDRA_HOST", "cassandra")
CLICKHOUSE_URL = os.environ.get("CLICKHOUSE_URL", "http://clickhouse:8123")
CLICKHOUSE_USER = os.environ.get("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "app")
NEO4J_URL = os.environ.get("NEO4J_URL", "http://neo4j:7474")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "datamodel")
TIMESCALE_URL = os.environ.get(
    "TIMESCALE_URL", "postgresql://app:app@timescale:5432/app"
)
ELASTIC_URL = os.environ.get("ELASTIC_URL", "http://elasticsearch:9200")

CATALOG = [
    {
        "id": "relational",
        "title": "Relational / row-oriented",
        "engine": "PostgreSQL",
        "products": ["PostgreSQL", "MySQL", "Oracle", "SQL Server"],
        "use": "Store a WeChat account. The phone is unique. A payment stays here when the write must happen once.",
        "structure": "A table has columns. One account is one row. The primary key is the id. The phone has a unique constraint.",
        "storage": "The engine stores the whole row together. An index on phone finds that row.",
    },
    {
        "id": "key-value",
        "title": "Key-value",
        "engine": "Redis",
        "products": ["Redis", "DynamoDB", "RocksDB"],
        "use": "Store a like count and an unread badge. The read asks for one key.",
        "structure": "A key maps to one value. like_count:moment:1 maps to 42. unread:ada maps to 3.",
        "storage": "Redis keeps the value in memory. The key is the lookup.",
    },
    {
        "id": "document",
        "title": "Document",
        "engine": "MongoDB",
        "products": ["MongoDB", "Couchbase", "Firestore"],
        "use": "Store a profile whose fields differ per user. The moments sit inside that profile.",
        "structure": "One JSON document. The profile has a city, a signature, and a list of moments.",
        "storage": "MongoDB stores the document as BSON. The moments array lives inside the profile.",
    },
    {
        "id": "wide-column",
        "title": "Wide-column",
        "engine": "Cassandra",
        "products": ["Cassandra", "ScyllaDB", "HBase"],
        "use": "Store WeChat messages for one chat. The chat id picks the partition. Time sorts the messages.",
        "structure": "The partition key is chat_id. The clustering column is sent_at. Each message has a sender and a body.",
        "storage": "Messages for one chat sit together. A read of that chat touches one partition.",
    },
    {
        "id": "columnar",
        "title": "Columnar analytics",
        "engine": "ClickHouse",
        "products": ["Snowflake", "BigQuery", "ClickHouse", "Redshift", "DuckDB"],
        "use": "Count messages per city per day. This scan is for analytics. The chat send path stays on the message store.",
        "structure": "A table of day, city, and messages. The query sums the messages column.",
        "storage": "ClickHouse stores each column together. A sum reads the messages column.",
    },
    {
        "id": "graph",
        "title": "Graph",
        "engine": "Neo4j",
        "products": ["Neo4j", "Amazon Neptune", "JanusGraph"],
        "use": "Store a friend edge. A friend of a friend is a hop along those edges.",
        "structure": "A person is a node. FRIEND is an edge from Ada to Bob, and from Bob to Nova.",
        "storage": "Neo4j stores the edge with the nodes. The hop follows FRIEND.",
    },
    {
        "id": "time-series",
        "title": "Time-series",
        "engine": "TimescaleDB",
        "products": ["InfluxDB", "TimescaleDB", "Prometheus"],
        "use": "Store how many messages a room sends each minute. Time is the main column.",
        "structure": "Each row is a time, a room, and a count. The read asks for one room in time order.",
        "storage": "TimescaleDB keeps the rows in time chunks. A chunk is a time range of the same table.",
    },
    {
        "id": "search",
        "title": "Search / inverted index",
        "engine": "Elasticsearch",
        "products": ["Elasticsearch", "OpenSearch", "Solr"],
        "use": "Find chat messages that contain one word. The word lunch points at the matching message.",
        "structure": "A message has a sender and a body. The body is text. The index maps a word to the message id.",
        "storage": "Elasticsearch builds an inverted index. The word is the key. The message id is the value.",
    },
]


def catalog() -> list[dict]:
    return [
        {
            "id": item["id"],
            "title": item["title"],
            "engine": item["engine"],
            "products": item["products"],
        }
        for item in CATALOG
    ]


DETAILS = {
    "relational": {
        "interview": "Say PostgreSQL when rows point at each other and a write must stay correct.",
        "requirement": "You need a unique phone, a foreign key, or a payment that happens once.",
        "write_sql": "INSERT INTO accounts (id, username, phone) VALUES (2, 'bob', '555-0101');",
        "read_sql": "SELECT id, username, phone FROM accounts;",
    },
    "key-value": {
        "interview": "Say Redis when the read names one key and the value can live in memory.",
        "requirement": "You need a like count, a session, or an unread badge.",
        "write_sql": "INCR like_count:moment:1",
        "read_sql": "GET like_count:moment:1",
    },
    "document": {
        "interview": "Say a document store when one screen loads one object and fields differ per user.",
        "requirement": "A profile has optional fields and a nested list of moments.",
        "write_sql": "db.profiles.updateOne({_id: 'ada'}, {$set: {badge: 'vip'}})",
        "read_sql": "db.profiles.findOne({_id: 'ada'})",
    },
    "wide-column": {
        "interview": "Say Cassandra when one chat id owns a time-ordered list of messages.",
        "requirement": "The hot read is the messages in one conversation, in time order.",
        "write_sql": "INSERT INTO messages (chat_id, sent_at, sender, body) VALUES ('chat-1', '2024-01-01 10:05:00', 'ada', 'on my way');",
        "read_sql": "SELECT sender, body FROM messages WHERE chat_id = 'chat-1';",
    },
    "columnar": {
        "interview": "Say a columnar store when a report sums one column across many rows.",
        "requirement": "The screen is messages per city per day. The send path stays on the message store.",
        "write_sql": "INSERT INTO message_stats VALUES ('2024-01-01', 'Guangzhou', 400);",
        "read_sql": "SELECT city, sum(messages) FROM message_stats WHERE day = '2024-01-01' GROUP BY city;",
    },
    "graph": {
        "interview": "Say a graph store when the product is a hop from friend to friend.",
        "requirement": "The main screen walks friend edges. A short hop can stay in PostgreSQL.",
        "write_sql": "MERGE (ada:Person {name:'ada'}) MERGE (lee:Person {name:'lee'}) MERGE (ada)-[:FRIEND]->(lee);",
        "read_sql": "MATCH (ada:Person {name:'ada'})-[:FRIEND]->(friend)-[:FRIEND]->(next) RETURN next;",
    },
    "time-series": {
        "interview": "Say a time-series store when every row is a time and a measurement.",
        "requirement": "The question is how many messages a room sends each minute.",
        "write_sql": "INSERT INTO msg_rate (time, room, messages) VALUES ('2024-01-01 10:03:00+00', 'chat-1', 15);",
        "read_sql": "SELECT time, messages FROM msg_rate WHERE room = 'chat-1' ORDER BY time;",
    },
    "search": {
        "interview": "Say a search index when the user types a word and you find the messages.",
        "requirement": "The query is text inside the message. A lookup by id stays a primary key.",
        "write_sql": "PUT /messages/_doc/3 {sender: 'ada', body: 'lunch menu'}",
        "read_sql": "POST /messages/_search {query: {match: {body: 'lunch'}}}",
    },
}


def _meta(kind: str) -> dict:
    for item in CATALOG:
        if item["id"] == kind:
            data = dict(item)
            data.update(DETAILS.get(kind, {}))
            return data
    return {}


def _pg(url: str):
    return psycopg.connect(url, row_factory=dict_row)


def _http_json(url: str, method: str, body: dict | None, headers: dict | None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode()
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        if exc.code >= 400 and exc.code != 400:
            raise RuntimeError(raw) from exc
    if raw.strip() == "":
        return {}
    return json.loads(raw)


def _clickhouse(sql: str) -> str:
    token = base64.b64encode(f"{CLICKHOUSE_USER}:{CLICKHOUSE_PASSWORD}".encode()).decode()
    request = urllib.request.Request(CLICKHOUSE_URL + "/", data=sql.encode(), method="POST")
    request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.read().decode()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(exc.read().decode()) from exc


def _neo4j(statement: str) -> list:
    token = base64.b64encode(f"{NEO4J_USER}:{NEO4J_PASSWORD}".encode()).decode()
    payload = _http_json(
        f"{NEO4J_URL}/db/neo4j/tx/commit",
        "POST",
        {"statements": [{"statement": statement}]},
        {"Authorization": f"Basic {token}"},
    )
    if payload.get("errors"):
        raise RuntimeError(str(payload["errors"]))
    data = payload["results"][0]["data"]
    return [item["row"] for item in data]


def seed_relational() -> None:
    with _pg(DATABASE_URL) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id INT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                phone TEXT NOT NULL UNIQUE
            )
            """
        )
        conn.execute(
            """
            INSERT INTO accounts (id, username, phone)
            VALUES (1, 'ada', '555-0100')
            ON CONFLICT (id) DO NOTHING
            """
        )


def read_relational() -> dict:
    with _pg(DATABASE_URL) as conn:
        rows = conn.execute(
            "SELECT id, username, phone FROM accounts ORDER BY id"
        ).fetchall()
    sample = [dict(row) for row in rows]
    return {
        "query": "SELECT id, username, phone FROM accounts",
        "sample": sample,
        "shape": {
            "kind": "table",
            "columns": ["id", "username", "phone"],
            "rows": [[row["id"], row["username"], row["phone"]] for row in sample],
        },
        "diagram": (
            "accounts\n"
            "  id | username | phone\n"
            "  1  | ada      | 555-0100\n"
            "\n"
            "phone is unique\n"
            "one row holds the whole account"
        ),
    }


def seed_key_value() -> None:
    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    client.set("like_count:moment:1", 42)
    client.set("unread:ada", 3)
    client.close()


def read_key_value() -> dict:
    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    sample = {
        "like_count:moment:1": client.get("like_count:moment:1"),
        "unread:ada": client.get("unread:ada"),
    }
    client.close()
    return {
        "query": "GET like_count:moment:1; GET unread:ada",
        "sample": sample,
        "shape": {
            "kind": "pairs",
            "pairs": [{"key": key, "value": value} for key, value in sample.items()],
        },
        "diagram": (
            "like_count:moment:1\n"
            "  |\n"
            "  v\n"
            "42\n"
            "\n"
            "unread:ada\n"
            "  |\n"
            "  v\n"
            "3"
        ),
    }


def seed_document() -> None:
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=8000)
    client.chat.profiles.replace_one(
        {"_id": "ada"},
        {
            "_id": "ada",
            "city": "Shanghai",
            "signature": "hi",
            "moments": [{"text": "lunch", "photos": 2}],
        },
        upsert=True,
    )
    client.close()


def read_document() -> dict:
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=8000)
    document = client.chat.profiles.find_one({"_id": "ada"})
    client.close()
    return {
        "query": "db.profiles.find_one({_id: 'ada'})",
        "sample": document,
        "shape": {"kind": "document", "document": document},
        "diagram": (
            "profile ada\n"
            "  city: Shanghai\n"
            "  signature: hi\n"
            "  moments\n"
            "    text: lunch\n"
            "    photos: 2"
        ),
    }


def _cassandra():
    cluster = Cluster(
        [CASSANDRA_HOST],
        port=9042,
        protocol_version=4,
        connect_timeout=15,
    )
    session = cluster.connect()
    return cluster, session


def seed_wide_column() -> None:
    cluster, session = _cassandra()
    try:
        session.execute(
            """
            CREATE KEYSPACE IF NOT EXISTS chat
            WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1}
            """
        )
        session.execute(
            """
            CREATE TABLE IF NOT EXISTS chat.messages (
                chat_id text,
                sent_at timestamp,
                sender text,
                body text,
                PRIMARY KEY (chat_id, sent_at)
            ) WITH CLUSTERING ORDER BY (sent_at ASC)
            """
        )
        rows = [
            ("chat-1", datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc), "ada", "hello"),
            ("chat-1", datetime(2024, 1, 1, 10, 1, tzinfo=timezone.utc), "bob", "hi ada"),
            ("chat-2", datetime(2024, 1, 1, 10, 2, tzinfo=timezone.utc), "nova", "other room"),
        ]
        for row in rows:
            session.execute(
                """
                INSERT INTO chat.messages (chat_id, sent_at, sender, body)
                VALUES (%s, %s, %s, %s)
                """,
                row,
            )
    finally:
        cluster.shutdown()


def read_wide_column() -> dict:
    cluster, session = _cassandra()
    try:
        rows = session.execute(
            """
            SELECT chat_id, sent_at, sender, body
            FROM chat.messages
            WHERE chat_id IN ('chat-1', 'chat-2')
            """
        )
        stored = [
            {
                "chat_id": row.chat_id,
                "sent_at": row.sent_at.strftime("%H:%M"),
                "sender": row.sender,
                "body": row.body,
            }
            for row in rows
        ]
    finally:
        cluster.shutdown()
    partitions: dict[str, list] = {}
    for row in stored:
        partitions.setdefault(row["chat_id"], []).append(row)
    sample = partitions.get("chat-1", [])
    return {
        "query": "SELECT * FROM messages WHERE chat_id = 'chat-1'",
        "sample": sample,
        "shape": {
            "kind": "partitions",
            "partitions": [
                {"key": key, "rows": partitions[key]} for key in sorted(partitions)
            ],
        },
        "diagram": (
            "chat-1\n"
            "  |\n"
            "  | partition key\n"
            "  v\n"
            "10:00 ada hello\n"
            "10:01 bob hi ada\n"
            "\n"
            "chat-2 is a different partition"
        ),
    }


def seed_columnar() -> None:
    _clickhouse(
        """
        CREATE TABLE IF NOT EXISTS message_stats (
            day Date,
            city String,
            messages UInt64
        ) ENGINE = MergeTree
        ORDER BY (day, city)
        """
    )
    count = _clickhouse("SELECT count() FROM message_stats").strip()
    if count == "0":
        _clickhouse(
            """
            INSERT INTO message_stats VALUES
            ('2024-01-01', 'Shanghai', 1200),
            ('2024-01-01', 'Beijing', 900)
            """
        )


def read_columnar() -> dict:
    raw = _clickhouse(
        """
        SELECT city, sum(messages) AS messages
        FROM message_stats
        WHERE day = '2024-01-01'
        GROUP BY city
        ORDER BY city
        FORMAT JSONEachRow
        """
    )
    sample = [json.loads(line) for line in raw.splitlines() if line.strip()]
    stored_raw = _clickhouse(
        """
        SELECT day, city, messages
        FROM message_stats
        ORDER BY city
        FORMAT JSONEachRow
        """
    )
    stored = [json.loads(line) for line in stored_raw.splitlines() if line.strip()]
    return {
        "query": "SELECT city, sum(messages) FROM message_stats WHERE day = '2024-01-01' GROUP BY city",
        "sample": sample,
        "shape": {
            "kind": "columns",
            "columns": [
                {"name": name, "values": [row[name] for row in stored]}
                for name in ("day", "city", "messages")
            ],
        },
        "diagram": (
            "day 2024-01-01\n"
            "  Shanghai messages 1200\n"
            "  Beijing messages 900\n"
            "\n"
            "The sum reads the messages column."
        ),
    }


def seed_graph() -> None:
    _neo4j(
        """
        MERGE (a:Person {name:'ada'})
        MERGE (b:Person {name:'bob'})
        MERGE (n:Person {name:'nova'})
        MERGE (a)-[:FRIEND]->(b)
        MERGE (b)-[:FRIEND]->(n)
        """
    )


def read_graph() -> dict:
    rows = _neo4j(
        """
        MATCH (a:Person {name:'ada'})-[:FRIEND]->(b:Person)-[:FRIEND]->(c:Person)
        WHERE c.name <> 'ada'
        RETURN a.name, b.name, c.name
        """
    )
    edges = _neo4j(
        """
        MATCH (a:Person)-[:FRIEND]->(b:Person)
        RETURN a.name, b.name
        ORDER BY a.name, b.name
        """
    )
    sample = [
        {"person": row[0], "friend": row[1], "friend_of_friend": row[2]} for row in rows
    ]
    return {
        "query": "MATCH (ada)-[:FRIEND]->(friend)-[:FRIEND]->(next) RETURN next",
        "sample": sample,
        "shape": {
            "kind": "graph",
            "edges": [{"from": row[0], "to": row[1]} for row in edges],
        },
        "diagram": (
            "ada\n"
            "  |\n"
            "  | FRIEND\n"
            "  v\n"
            "bob\n"
            "  |\n"
            "  | FRIEND\n"
            "  v\n"
            "nova"
        ),
    }


def seed_time_series() -> None:
    with _pg(TIMESCALE_URL) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS msg_rate (
                time TIMESTAMPTZ NOT NULL,
                room TEXT NOT NULL,
                messages INT NOT NULL,
                PRIMARY KEY (time, room)
            )
            """
        )
        conn.execute(
            "SELECT create_hypertable('msg_rate', 'time', if_not_exists => TRUE)"
        ).fetchone()
        conn.execute(
            """
            INSERT INTO msg_rate (time, room, messages) VALUES
                ('2024-01-01 10:00:00+00', 'chat-1', 12),
                ('2024-01-01 10:01:00+00', 'chat-1', 18),
                ('2024-01-01 10:02:00+00', 'chat-1', 9)
            ON CONFLICT DO NOTHING
            """
        )


def read_time_series() -> dict:
    with _pg(TIMESCALE_URL) as conn:
        rows = conn.execute(
            """
            SELECT time, room, messages
            FROM msg_rate
            WHERE room = 'chat-1'
            ORDER BY time
            """
        ).fetchall()
    sample = [
        {
            "time": row["time"].isoformat(),
            "room": row["room"],
            "messages": row["messages"],
        }
        for row in rows
    ]
    return {
        "query": "SELECT time, room, messages FROM msg_rate WHERE room = 'chat-1' ORDER BY time",
        "sample": sample,
        "shape": {
            "kind": "series",
            "points": [
                {"label": row["time"][11:16], "value": row["messages"]} for row in sample
            ],
        },
        "diagram": (
            "chat-1\n"
            "  10:00  12 messages\n"
            "  10:01  18 messages\n"
            "  10:02   9 messages\n"
            "\n"
            "The rows sit in a time chunk."
        ),
    }


def seed_search() -> None:
    _http_json(
        f"{ELASTIC_URL}/messages",
        "PUT",
        {
            "mappings": {
                "properties": {
                    "sender": {"type": "keyword"},
                    "body": {"type": "text"},
                }
            }
        },
        None,
    )
    for doc_id, body in (
        ("1", {"sender": "ada", "body": "lunch at the park"}),
        ("2", {"sender": "bob", "body": "see you tonight"}),
    ):
        _http_json(f"{ELASTIC_URL}/messages/_doc/{doc_id}", "PUT", body, None)
    _http_json(f"{ELASTIC_URL}/messages/_refresh", "POST", None, None)


def read_search() -> dict:
    stored = _http_json(
        f"{ELASTIC_URL}/messages/_search",
        "POST",
        {"query": {"match_all": {}}, "size": 10},
        None,
    )
    found = _http_json(
        f"{ELASTIC_URL}/messages/_search",
        "POST",
        {"query": {"match": {"body": "lunch"}}},
        None,
    )
    def hits(payload: dict) -> list:
        return [
            {"id": item["_id"], "source": item["_source"]}
            for item in payload["hits"]["hits"]
        ]

    stored_hits = hits(stored)
    terms: dict[str, list[str]] = {}
    for item in stored_hits:
        for word in item["source"]["body"].lower().split():
            terms.setdefault(word, [])
            if item["id"] not in terms[word]:
                terms[word].append(item["id"])
    return {
        "query": "match body: lunch",
        "sample": {"stored": stored_hits, "search": "lunch", "hits": hits(found)},
        "shape": {
            "kind": "index",
            "terms": [
                {"term": term, "ids": terms[term]} for term in sorted(terms)
            ],
        },
        "diagram": (
            "lunch\n"
            "  |\n"
            "  v\n"
            "message 1\n"
            "  ada: lunch at the park\n"
            "\n"
            "tonight\n"
            "  |\n"
            "  v\n"
            "message 2\n"
            "  bob: see you tonight"
        ),
    }


SEEDS = {
    "relational": seed_relational,
    "key-value": seed_key_value,
    "document": seed_document,
    "wide-column": seed_wide_column,
    "columnar": seed_columnar,
    "graph": seed_graph,
    "time-series": seed_time_series,
    "search": seed_search,
}

READERS = {
    "relational": read_relational,
    "key-value": read_key_value,
    "document": read_document,
    "wide-column": read_wide_column,
    "columnar": read_columnar,
    "graph": read_graph,
    "time-series": read_time_series,
    "search": read_search,
}


def write_relational() -> dict:
    with _pg(DATABASE_URL) as conn:
        conn.execute(
            """
            INSERT INTO accounts (id, username, phone)
            VALUES (2, 'bob', '555-0101')
            ON CONFLICT (id) DO NOTHING
            """
        )
    return {"statement": DETAILS["relational"]["write_sql"], "result": "bob is stored"}


def write_key_value() -> dict:
    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    value = client.incr("like_count:moment:1")
    client.close()
    return {"statement": DETAILS["key-value"]["write_sql"], "result": str(value)}


def write_document() -> dict:
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=8000)
    client.chat.profiles.update_one({"_id": "ada"}, {"$set": {"badge": "vip"}})
    client.close()
    return {"statement": DETAILS["document"]["write_sql"], "result": "badge is vip"}


def write_wide_column() -> dict:
    cluster, session = _cassandra()
    try:
        session.execute(
            """
            INSERT INTO chat.messages (chat_id, sent_at, sender, body)
            VALUES (%s, %s, %s, %s)
            """,
            (
                "chat-1",
                datetime(2024, 1, 1, 10, 5, tzinfo=timezone.utc),
                "ada",
                "on my way",
            ),
        )
    finally:
        cluster.shutdown()
    return {
        "statement": DETAILS["wide-column"]["write_sql"],
        "result": "chat-1 has the 10:05 message",
    }


def write_columnar() -> dict:
    count = _clickhouse(
        "SELECT count() FROM message_stats WHERE city = 'Guangzhou'"
    ).strip()
    if count == "0":
        _clickhouse(
            "INSERT INTO message_stats VALUES ('2024-01-01', 'Guangzhou', 400)"
        )
    return {
        "statement": DETAILS["columnar"]["write_sql"],
        "result": "Guangzhou is stored",
    }


def write_graph() -> dict:
    _neo4j(
        """
        MERGE (a:Person {name:'ada'})
        MERGE (l:Person {name:'lee'})
        MERGE (a)-[:FRIEND]->(l)
        """
    )
    return {"statement": DETAILS["graph"]["write_sql"], "result": "ada FRIEND lee"}


def write_time_series() -> dict:
    with _pg(TIMESCALE_URL) as conn:
        conn.execute(
            """
            INSERT INTO msg_rate (time, room, messages)
            VALUES ('2024-01-01 10:03:00+00', 'chat-1', 15)
            ON CONFLICT DO NOTHING
            """
        )
    return {"statement": DETAILS["time-series"]["write_sql"], "result": "10:03 is stored"}


def write_search() -> dict:
    _http_json(
        f"{ELASTIC_URL}/messages/_doc/3",
        "PUT",
        {"sender": "ada", "body": "lunch menu"},
        None,
    )
    _http_json(f"{ELASTIC_URL}/messages/_refresh", "POST", None, None)
    return {"statement": DETAILS["search"]["write_sql"], "result": "message 3 is stored"}


WRITES = {
    "relational": write_relational,
    "key-value": write_key_value,
    "document": write_document,
    "wide-column": write_wide_column,
    "columnar": write_columnar,
    "graph": write_graph,
    "time-series": write_time_series,
    "search": write_search,
}


def write_engine(kind: str) -> dict:
    writer = WRITES.get(kind)
    if writer is None:
        return {"ok": False, "code": "write_engine"}
    wrote = writer()
    body = read_engine(kind)
    body["wrote"] = wrote
    body["code"] = "write_engine"
    return body


def seed_all() -> None:
    errors = []
    for kind, seed in SEEDS.items():
        try:
            seed()
        except Exception as exc:
            errors.append(f"{kind}: {exc}")
    if errors:
        raise RuntimeError("; ".join(errors))


def read_engine(kind: str) -> dict:
    meta = _meta(kind)
    reader = READERS.get(kind)
    if not meta or reader is None:
        return {"ok": False, "code": "read_engine"}
    live = reader()
    meta.update(live)
    meta["ok"] = True
    meta["code"] = "read_engine"
    return meta
