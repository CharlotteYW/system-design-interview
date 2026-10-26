"""Shared clients, tables, and crawl rules for the API, the fetcher, the parser, and the scheduler."""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import time
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import boto3
import redis
from botocore.config import Config
from botocore.exceptions import ClientError

AWS = dict(region_name="us-east-1", aws_access_key_id="lab", aws_secret_access_key="lab")
BOTO_CFG = Config(retries={"max_attempts": 3, "mode": "standard"}, max_pool_connections=32)

DDB_URL = os.environ.get("DDB_URL", "http://dynamodb:8000")
SQS_URL = os.environ.get("SQS_URL", "http://elasticmq:9324")
S3_URL = os.environ.get("S3_URL", "http://minio:9000")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
BUCKET = "crawl"

DEFAULT_GAP_MS = int(os.environ.get("DEFAULT_GAP_MS", "500"))
VISIBILITY_TIMEOUT = int(os.environ.get("VISIBILITY_TIMEOUT", "10"))
BACKOFF_BASE = int(os.environ.get("BACKOFF_BASE", "1"))
MAX_ATTEMPTS = int(os.environ.get("MAX_ATTEMPTS", "5"))
FETCH_TIMEOUT = float(os.environ.get("FETCH_TIMEOUT", "2.0"))
MAX_BYTES = int(os.environ.get("MAX_BYTES", "1000000"))
BLOOM_BITS = int(os.environ.get("BLOOM_BITS", "1024"))
BLOOM_K = int(os.environ.get("BLOOM_K", "3"))
FETCHER_PROCESSES = int(os.environ.get("FETCHER_PROCESSES", "2"))
ROBOTS_TTL = 24 * 3600

FINAL_STATES = {"fetched", "parsed", "duplicate", "skipped", "failed", "dead"}
TRACKING_PARAMS = {"sid", "sessionid", "ref", "fbclid", "gclid"}

ddb = boto3.client("dynamodb", endpoint_url=DDB_URL, config=BOTO_CFG, **AWS)
sqs = boto3.client("sqs", endpoint_url=SQS_URL, config=BOTO_CFG, **AWS)
s3 = boto3.client("s3", endpoint_url=S3_URL, aws_access_key_id="minio", aws_secret_access_key="minio12345",
                  region_name="us-east-1", config=Config(s3={"addressing_style": "path"}))
r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

QUEUES = {"frontier": None, "parse": None, "dlq": None}


# ---------- setup ----------

def ensure_tables() -> None:
    existing = set(ddb.list_tables()["TableNames"])
    specs = {
        "urls": dict(
            KeySchema=[{"AttributeName": "url_hash", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "url_hash", "AttributeType": "S"},
                                  {"AttributeName": "pending_domain", "AttributeType": "S"}],
            GlobalSecondaryIndexes=[{
                "IndexName": "pending_by_domain",
                "KeySchema": [{"AttributeName": "pending_domain", "KeyType": "HASH"},
                              {"AttributeName": "url_hash", "KeyType": "RANGE"}],
                "Projection": {"ProjectionType": "ALL"}}]),
        "content_hashes": dict(
            KeySchema=[{"AttributeName": "hash", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "hash", "AttributeType": "S"}]),
        "domains": dict(
            KeySchema=[{"AttributeName": "domain", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "domain", "AttributeType": "S"}]),
        "race_urls": dict(
            KeySchema=[{"AttributeName": "url_hash", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "url_hash", "AttributeType": "S"}]),
    }
    for name, spec in specs.items():
        if name not in existing:
            ddb.create_table(TableName=name, BillingMode="PAY_PER_REQUEST", **spec)


def ensure_queues() -> dict:
    dlq = sqs.create_queue(QueueName="frontier-dlq")["QueueUrl"]
    dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    # The redrive policy is only a safety net. Real failures are counted in urls.attempts.
    redrive = json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": "100"})
    QUEUES["dlq"] = dlq
    QUEUES["frontier"] = sqs.create_queue(QueueName="frontier", Attributes={
        "VisibilityTimeout": str(VISIBILITY_TIMEOUT), "RedrivePolicy": redrive})["QueueUrl"]
    QUEUES["parse"] = sqs.create_queue(QueueName="parse", Attributes={
        "VisibilityTimeout": str(VISIBILITY_TIMEOUT), "RedrivePolicy": redrive})["QueueUrl"]
    return QUEUES


def ensure_bucket() -> None:
    try:
        s3.head_bucket(Bucket=BUCKET)
    except ClientError:
        s3.create_bucket(Bucket=BUCKET)


def wait_ready(role: str) -> None:
    while True:
        try:
            names = set(ddb.list_tables()["TableNames"])
            if {"urls", "content_hashes", "domains"} <= names:
                ensure_queues()
                r.ping()
                return
        except Exception as exc:  # noqa: BLE001
            print(f"{role}: waiting for stores ({exc})", flush=True)
        time.sleep(1)


# ---------- config, stats, events ----------

def config() -> dict:
    c = r.hgetall("config")
    return {
        "scheduler": c.get("scheduler", "on") == "on",
        "limit": int(c.get("limit", "2")),
        "domainCap": int(c.get("domainCap", "20")),
        "maxDepth": int(c.get("maxDepth", "4")),
        "maxPages": int(c.get("maxPages", "500")),
        "politeness": c.get("politeness", "redis"),
    }


def stat(field: str, n: int = 1, domain: str | None = None) -> None:
    pipe = r.pipeline()
    pipe.hincrby("stats", field, n)
    if domain:
        pipe.hincrby(f"dstats:{domain}", field, n)
    pipe.execute()


def event(who: str, msg: str) -> None:
    pipe = r.pipeline()
    pipe.lpush("events", json.dumps({"t": round(time.time(), 3), "who": who, "msg": msg}))
    pipe.ltrim("events", 0, 299)
    pipe.execute()


# ---------- URLs ----------

def normalize(url: str, base: str | None = None) -> str | None:
    if base:
        url = urljoin(base, url)
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    host = parts.hostname.lower()
    port = parts.port
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS]
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    return urlunsplit((parts.scheme.lower(), netloc, path, urlencode(sorted(query)), ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def domain_of(url: str) -> str:
    return urlsplit(url).hostname or ""


def ensure_domain(domain: str) -> None:
    try:
        ddb.put_item(TableName="domains", Item={
            "domain": {"S": domain}, "in_flight": {"N": "0"}, "pages_admitted": {"N": "0"},
            "robots_status": {"S": "unknown"}},
            ConditionExpression="attribute_not_exists(#d)", ExpressionAttributeNames={"#d": "domain"})
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise


def insert_url(url: str, depth: int, pending: bool) -> bool:
    """Conditional put: True means this caller inserted a new URL."""
    domain = domain_of(url)
    item = {"url_hash": {"S": url_hash(url)}, "url": {"S": url}, "domain": {"S": domain},
            "depth": {"N": str(depth)}, "state": {"S": "pending" if pending else "queued"},
            "attempts": {"N": "0"}, "receives": {"N": "0"}, "updated_at": {"N": str(time.time())}}
    if pending:
        item["pending_domain"] = {"S": domain}
    try:
        ddb.put_item(TableName="urls", Item=item, ConditionExpression="attribute_not_exists(url_hash)")
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def send_frontier(uid: str, url: str, depth: int) -> dict:
    body = {"urlId": uid, "url": url, "depth": depth}
    sqs.send_message(QueueUrl=QUEUES["frontier"], MessageBody=json.dumps(body))
    return body


def get_url(uid: str) -> dict | None:
    item = ddb.get_item(TableName="urls", Key={"url_hash": {"S": uid}}, ConsistentRead=True).get("Item")
    return from_ddb(item) if item else None


def from_ddb(item: dict) -> dict:
    out = {}
    for k, v in item.items():
        if "S" in v:
            out[k] = v["S"]
        elif "N" in v:
            n = float(v["N"])
            out[k] = int(n) if n.is_integer() else n
        elif "BOOL" in v:
            out[k] = v["BOOL"]
    return out


def update_url(uid: str, **fields) -> bool:
    """UpdateItem creates a missing item, so every update requires the row to exist.
    False means the row is gone (the lab was reset under this worker)."""
    fields["updated_at"] = time.time()
    names, values, sets = {}, {}, []
    for i, (k, v) in enumerate(fields.items()):
        names[f"#f{i}"] = k
        values[f":v{i}"] = {"N": str(v)} if isinstance(v, (int, float)) else {"S": str(v)}
        sets.append(f"#f{i} = :v{i}")
    return update_existing("urls", {"url_hash": {"S": uid}}, "SET " + ", ".join(sets), values,
                           names=names) is not None


def update_existing(table: str, key: dict, expr: str, values: dict, names: dict | None = None,
                    condition: str | None = None, returns: str = "NONE") -> dict | None:
    key_name = next(iter(key))
    names = dict(names or {}, **{"#pk": key_name})
    cond = "attribute_exists(#pk)" + (f" AND ({condition})" if condition else "")
    try:
        out = ddb.update_item(TableName=table, Key=key, UpdateExpression=expr, ConditionExpression=cond,
                              ExpressionAttributeNames=names, ExpressionAttributeValues=values,
                              ReturnValues=returns)
        return out.get("Attributes", {})
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return None
        raise


def finish_in_flight(domain: str) -> None:
    """A URL reached a final state. The scheduler may admit the next URL of this domain."""
    update_existing("domains", {"domain": {"S": domain}}, "ADD in_flight :m",
                    {":m": {"N": "-1"}, ":z": {"N": "0"}}, condition="in_flight > :z")


# ---------- robots.txt (RFC 9309: the longest matching rule wins; a tie goes to Allow) ----------

def parse_robots(text: str, agent: str = "labcrawler") -> dict:
    groups: list[tuple[list[str], list[tuple[str, str]], float | None]] = []
    agents: list[str] = []
    rules: list[tuple[str, str]] = []
    delay = None
    last_was_agent = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, val = (s.strip() for s in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if not last_was_agent and agents:
                groups.append((agents, rules, delay))
                agents, rules, delay = [], [], None
            agents.append(val.lower())
            last_was_agent = True
            continue
        last_was_agent = False
        if key in ("allow", "disallow"):
            rules.append((key, val))
        elif key == "crawl-delay":
            try:
                delay = float(val)
            except ValueError:
                pass
    if agents:
        groups.append((agents, rules, delay))
    chosen = next((g for g in groups if agent in g[0]), None) or next((g for g in groups if "*" in g[0]), None)
    if not chosen:
        return {"rules": [], "crawlDelay": None}
    return {"rules": [[k, v] for k, v in chosen[1] if v or k == "allow"], "crawlDelay": chosen[2]}


def robots_allows(rules: list, path: str) -> tuple[bool, str]:
    best = None
    for kind, pattern in rules:
        regex = "^" + re.escape(pattern).replace(r"\*", ".*").replace(r"\$", "$")
        if re.match(regex, path):
            if best is None or len(pattern) > len(best[1]) or (len(pattern) == len(best[1]) and kind == "allow"):
                best = (kind, pattern)
    if best is None:
        return True, "no rule matches"
    return best[0] == "allow", f"{best[0].capitalize()}: {best[1]} (longest match)"


# ---------- DNS cache ----------

_dns: dict[str, tuple[str, float]] = {}


def resolve(host: str) -> str:
    hit = _dns.get(host)
    if hit and hit[1] > time.time():
        stat("dns_hits")
        return hit[0]
    ip = socket.gethostbyname(host)
    _dns[host] = (ip, time.time() + 30)
    stat("dns_lookups")
    return ip


# ---------- text extraction ----------

class _Extract(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.links: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.text.append(data)


def extract(html: str) -> tuple[str, list[str]]:
    p = _Extract()
    p.feed(html)
    return " ".join(" ".join(p.text).split()), p.links


# ---------- Bloom filter in Redis ----------

def bloom_positions(key: str) -> list[int]:
    digest = hashlib.sha256(("bloom:" + key).encode()).digest()
    return [int.from_bytes(digest[i * 4:(i + 1) * 4], "big") % BLOOM_BITS for i in range(BLOOM_K)]


def bloom_check(key: str) -> bool:
    """True means "probably seen". False means "definitely not seen"."""
    pipe = r.pipeline()
    for pos in bloom_positions(key):
        pipe.getbit("bloom:content", pos)
    return all(pipe.execute())


def bloom_add(key: str) -> None:
    pipe = r.pipeline()
    for pos in bloom_positions(key):
        pipe.setbit("bloom:content", pos, 1)
    pipe.execute()
