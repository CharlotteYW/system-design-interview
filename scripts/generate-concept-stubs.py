"""Generate stub folders for core concepts and key technologies. Run from repo root."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "_templates" / "concept"
README_TMPL = (TEMPLATE / "README.md").read_text()

HI_CORE = (
    "[Hello Interview — Core concepts]"
    "(https://www.hellointerview.com/learn/system-design/in-a-hurry/core-concepts)"
)
HI_TECH = (
    "[Hello Interview — Key technologies]"
    "(https://www.hellointerview.com/learn/system-design/in-a-hurry/key-technologies)"
)


def table(rows: list[tuple[str, str]]) -> str:
    lines = [
        "| Variant | Fill in: what it is, when it wins, when to skip |",
        "| --- | --- |",
    ]
    for name, hint in rows:
        lines.append(f"| {name} | TBD — {hint} |")
    return "\n".join(lines)


CORE = [
    {
        "slug": "networking-essentials",
        "title": "Networking Essentials",
        "demo": "A small FastAPI UI: one HTTP request, one SSE stream, one WebSocket echo. Optional gRPC is out unless we add it. Goal: feel stateful vs stateless connections.",
        "variants": [
            ("HTTP over TCP", "default request/response; 90% of interviews"),
            ("HTTPS / TLS", "what changes vs plain HTTP in an interview"),
            ("Long polling", "client waits; still HTTP; vs SSE/WS"),
            ("Server-Sent Events (SSE)", "server → client only; one HTTP request then push"),
            ("WebSockets", "true bidirectional; stateful; L4 / sticky sessions"),
            ("gRPC", "internal RPC; HTTP/2 + protobuf; not browser-native"),
            ("L4 vs L7 load balancing", "TCP vs HTTP routing; persistent connections"),
            ("Geography / RTT", "speed of light; why multi-region and CDNs exist"),
        ],
    },
    {
        "slug": "api-design",
        "title": "API Design",
        "demo": "REST endpoints with offset vs cursor pagination on one list resource. Optional API key vs nothing.",
        "variants": [
            ("REST + HTTP verbs", "interview default for public APIs"),
            ("RPC-style endpoints", "when resource modeling fights you"),
            ("GraphQL (mention only)", "when clients need flexible reads; usually skip in 45 min"),
            ("Offset pagination", "simple; breaks when rows insert in the middle"),
            ("Cursor pagination", "stable for feeds / realtime appends"),
            ("Auth: session / JWT / API key", "users vs service-to-service"),
            ("Idempotency keys", "retries on POST without double writes"),
            ("Rate limiting (pointer)", "full lab lives under questions/rate-limiter"),
        ],
    },
    {
        "slug": "data-modeling",
        "title": "Data Modeling",
        "demo": "Postgres: normalized tables vs one denormalized read table. Show a join vs a single-row read.",
        "variants": [
            ("Relational (Postgres)", "structured data, relationships, transactions"),
            ("NoSQL document / KV", "access-pattern first; fewer joins"),
            ("Normalization", "one source of truth; joins on read"),
            ("Denormalization", "duplicate for a hot read path; update fan-out"),
            ("Access-pattern design", "know the queries before the keys"),
        ],
    },
    {
        "slug": "database-indexing",
        "title": "Database Indexing",
        "demo": "Postgres: query with EXPLAIN before/after a B-tree on email or (city, date).",
        "variants": [
            ("No index / seq scan", "baseline cost"),
            ("B-tree", "equality + range; default in Postgres"),
            ("Hash index", "equality only"),
            ("Composite index", "leftmost prefix; order of columns"),
            ("Covering / INCLUDE", "index-only scans"),
            ("Full-text (GIN / Elasticsearch)", "search vs primary store; CDC lag"),
            ("Geospatial", "PostGIS / geo index; nearby queries"),
            ("Write cost", "every index slows INSERT/UPDATE"),
        ],
    },
    {
        "slug": "caching",
        "title": "Caching",
        "demo": "FastAPI + Redis cache-aside: hit, miss, TTL, invalidate on write. Optional tiny L1 dict.",
        "variants": [
            ("No cache", "always hit DB"),
            ("Cache-aside (lazy)", "interview default for reads"),
            ("Write-through", "write cache + DB together"),
            ("Write-back", "faster writes; loss if cache dies"),
            ("TTL + invalidate", "freshness vs extra deletes"),
            ("Stampede / singleflight", "hot key expiry; one loader"),
            ("L1 in-process vs Redis L2", "per box vs shared"),
            ("CDN (pointer)", "edge/static; see key-technologies/cdn"),
        ],
    },
    {
        "slug": "sharding",
        "title": "Sharding",
        "demo": "Two Postgres databases hashed by user_id. Show a user-scoped read (one shard) vs a global scan (both).",
        "variants": [
            ("Single primary + replicas", "do this before sharding"),
            ("Hash sharding", "even spread; default"),
            ("Range sharding", "time or tenant ranges; hotspot risk"),
            ("Directory / lookup", "flexible; extra hop"),
            ("Shard key choice", "user_id vs other; cross-shard queries"),
            ("Resharding", "why modulo-N hurts; consistent hashing pointer"),
            ("Hot shard", "celebrity / tenant skew"),
        ],
    },
    {
        "slug": "consistent-hashing",
        "title": "Consistent Hashing",
        "demo": "A Python ring with virtual nodes: add/remove a node and print how many keys move vs hash % N.",
        "variants": [
            ("hash(key) % N", "add a node → almost all keys remap"),
            ("Hash ring", "key → next node clockwise"),
            ("Virtual nodes", "smoother load; more ring points per server"),
            ("Where it shows up", "Redis Cluster, Cassandra, some LBs, CDNs"),
        ],
    },
    {
        "slug": "cap-theorem",
        "title": "CAP Theorem",
        "demo": "Optional: two app replicas + a toggle that drops the network; show stale read vs 503. Notes-only is OK.",
        "variants": [
            ("Consistency", "all nodes agree on the latest write"),
            ("Availability", "every request gets a (maybe stale) answer"),
            ("Partition tolerance", "network splits happen; you still pick C or A"),
            ("CP vs AP", "refuse vs serve during a split"),
            ("PACELC", "even without a partition: latency vs consistency"),
            ("Eventual vs strong", "feed vs money/inventory/seats"),
        ],
    },
    {
        "slug": "numbers-to-know",
        "title": "Numbers to Know",
        "demo": "Notes-only. Recite and use the table in a decision (shard or not, one Redis or not). No Docker unless you want a tiny bench.",
        "variants": [
            ("Memory vs disk vs network", "ns / µs / ms gaps"),
            ("In-DC vs cross-continent RTT", "1–10ms vs ~80ms+ NY–London"),
            ("Redis ops/s vs DB TPS", "when cache or replicas beat sharding"),
            ("Single Postgres size / TPS", "when sharding is actually justified"),
            ("Queue / broker throughput", "back-of-envelope for buffers"),
        ],
    },
]

TECH = [
    {
        "slug": "relational-database",
        "title": "Relational Database",
        "demo": "Postgres: table, PK, join, transaction that all-or-nothing inserts two rows.",
        "variants": [
            ("Postgres (default here)", "SQL, ACID, many indexes"),
            ("MySQL", "fine in interviews; pick one and go deep"),
            ("Joins", "power and bottleneck"),
            ("Transactions / ACID", "multi-row integrity"),
            ("Read replicas", "scale reads, not writes"),
        ],
    },
    {
        "slug": "nosql-database",
        "title": "NoSQL Database",
        "demo": "Redis hashes or a tiny document JSON in Postgres JSONB as a stand-in. Show partition-key style lookup vs a scan.",
        "variants": [
            ("Key-value", "Redis / DynamoDB simple item"),
            ("Document", "MongoDB; flexible schema"),
            ("Wide column", "Cassandra; write-heavy"),
            ("Graph", "relationships as first class; rare in 45 min"),
            ("Partition + sort key", "design for the query you have"),
            ("Consistency knobs", "strong vs eventual on that product"),
        ],
    },
    {
        "slug": "blob-storage",
        "title": "Blob Storage",
        "demo": "MinIO in Docker: upload, get URL, metadata row in Postgres. Optional presigned PUT.",
        "variants": [
            ("S3 / GCS / Azure Blob", "interview default: S3"),
            ("MinIO (local)", "S3 API without a cloud account"),
            ("Metadata in a DB", "never query the blob store as your catalog"),
            ("Presigned URL", "client upload/download without proxying bytes"),
            ("Multipart / chunking", "large video/file resume"),
            ("CDN in front", "origin + edge; see cdn"),
        ],
    },
    {
        "slug": "search-index",
        "title": "Search Index",
        "demo": "Postgres FTS (tsvector/GIN) on a documents table vs LIKE '%term%'. Elasticsearch only if we add a container later.",
        "variants": [
            ("LIKE / table scan", "why it does not scale"),
            ("Inverted index", "term → posting list of docs"),
            ("Tokenize / stem", "running vs run"),
            ("Fuzzy / edit distance", "typos"),
            ("Elasticsearch", "interview default for serious search"),
            ("PG FTS / GIN", "smaller footprint; good local lab"),
        ],
    },
    {
        "slug": "api-gateway",
        "title": "API Gateway",
        "demo": "nginx or a FastAPI facade: route /users to service A and /orders to service B; optional API-key check.",
        "variants": [
            ("Reverse proxy as gateway", "nginx / Caddy locally"),
            ("Managed (API Gateway, Kong, Apigee)", "what interviewers picture"),
            ("Routing", "path → service"),
            ("Cross-cutting", "auth, rate limit, logging"),
            ("vs load balancer", "gateway is L7 policy; LB is spreading"),
        ],
    },
    {
        "slug": "load-balancer",
        "title": "Load Balancer",
        "demo": "Two identical FastAPI replicas behind nginx; curl in a loop and see both instance ids. Contrast L7 path routing.",
        "variants": [
            ("DNS / no LB", "one box"),
            ("L4 (TCP)", "fast; sticky for WebSockets"),
            ("L7 (HTTP)", "route by path/host; inspect request"),
            ("Round robin vs least conn", "how work is spread"),
            ("Sticky sessions", "when you must pin a client"),
            ("Health checks", "remove a dead replica"),
        ],
    },
    {
        "slug": "message-queue",
        "title": "Message Queue",
        "demo": "Redis list or RabbitMQ: producer HTTP, worker container, retry + poison message. Kafka only if the topic needs a log.",
        "variants": [
            ("Synchronous no queue", "when p99 must stay tiny"),
            ("Queue as buffer", "absorb a spike"),
            ("Competing consumers", "scale workers independently"),
            ("FIFO vs priority", "ordering"),
            ("Retries + DLQ", "poison messages"),
            ("Backpressure", "queue is not infinite capacity"),
            ("SQS vs Kafka-as-queue", "pick one you can defend"),
        ],
    },
    {
        "slug": "stream-processing",
        "title": "Streams",
        "demo": "Redis stream or Kafka in Docker: two consumer groups on the same topic (dashboard vs archive).",
        "variants": [
            ("Queue vs stream", "consume-and-delete vs retain and replay"),
            ("Event sourcing", "state = replay of events"),
            ("Partitions + key", "ordering within a key"),
            ("Consumer groups", "independent readers"),
            ("Windowing", "aggregates over time"),
            ("Kafka / Kinesis / Flink", "interview names"),
        ],
    },
    {
        "slug": "distributed-lock",
        "title": "Distributed Lock",
        "demo": "Redis SET key NX EX: two workers, only one holds the ticket lock. Show expiry after crash.",
        "variants": [
            ("DB row lock / transaction", "short, same database"),
            ("Redis SET NX + TTL", "simple distributed lock"),
            ("Redlock / ZooKeeper", "multi-instance; extra complexity"),
            ("Fencing tokens", "expire then old holder still writes"),
            ("Granularity", "one seat vs a section"),
            ("Deadlock", "lock order; never lock A then B vs B then A"),
        ],
    },
    {
        "slug": "distributed-cache",
        "title": "Distributed Cache",
        "demo": "Redis: string vs sorted set. LRU eviction (maxmemory). Invalidate one key after a Postgres update.",
        "variants": [
            ("Memcached", "simple KV"),
            ("Redis", "default here; many data structures"),
            ("Eviction: LRU / LFU / FIFO / TTL", "what leaves when full"),
            ("Write-through / around / back", "how writes hit cache"),
            ("What you store", "say the structure, not just 'in cache'"),
            ("Core-concepts/caching", "patterns; this folder is the product"),
        ],
    },
    {
        "slug": "cdn",
        "title": "CDN",
        "demo": "nginx as a caching reverse proxy in Docker (TTL, cache hit header). Cannot mock global PoPs locally — say that in the README.",
        "variants": [
            ("Origin only", "every byte from your region"),
            ("Edge cache for static", "images, JS, video segments"),
            ("Cache API / HTML", "rare; short TTL; invalidation"),
            ("TTL vs purge", "stale vs origin load"),
            ("CloudFront / Cloudflare / Akamai", "names to say"),
            ("Local nginx cache", "teaches hit/miss, not geography"),
        ],
    },
]


def write_topic(parent: Path, kind: str, sources: str, folder_prefix: str, item: dict) -> None:
    dest = parent / item["slug"]
    if dest.exists():
        print(f"skip existing {dest.relative_to(ROOT)}")
        return
    shutil.copytree(TEMPLATE, dest, ignore=shutil.ignore_patterns("README.md"))
    text = README_TMPL
    text = text.replace("{{CONCEPT_TITLE}}", item["title"])
    text = text.replace("{{KIND}}", kind)
    text = text.replace("{{SOURCES}}", sources)
    text = text.replace("{{SLUG}}", item["slug"])
    text = text.replace("{{VARIANT_TABLE}}", table(item["variants"]))
    text = text.replace("{{DEMO_HINT}}", item["demo"])
    text = text.replace("{{FOLDER}}", f"{folder_prefix}/{item['slug']}")
    (dest / "README.md").write_text(text)
    (dest / "src").mkdir(exist_ok=True)
    (dest / "src" / ".gitkeep").write_text("")
    for script in (dest / "scripts").glob("*.sh"):
        script.chmod(0o755)


def main() -> None:
    core_root = ROOT / "core-concepts"
    tech_root = ROOT / "key-technologies"
    core_root.mkdir(exist_ok=True)
    tech_root.mkdir(exist_ok=True)
    for item in CORE:
        write_topic(core_root, "Core concept", HI_CORE, "core-concepts", item)
    for item in TECH:
        write_topic(tech_root, "Key technology", HI_TECH, "key-technologies", item)
    print(f"Wrote {len(CORE)} core-concepts and {len(TECH)} key-technologies")


if __name__ == "__main__":
    main()
