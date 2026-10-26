"""Control API and lab page for the web crawler."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Literal

import httpx
import psycopg
import redis as redis_lib
from botocore.exceptions import ClientError
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from . import common as c

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:app@postgres:5432/app")
FAKEWEB = os.environ.get("FAKEWEB_URL", "http://fakeweb")
STATIC = Path(__file__).parent / "static"
ALL_SEEDS = ["http://kim.test/"]

app = FastAPI(title="Web crawler lab")
rbin = redis_lib.Redis.from_url(c.REDIS_URL)


@app.on_event("startup")
def startup() -> None:
    for _ in range(60):
        try:
            c.ensure_tables()
            c.ensure_queues()
            c.ensure_bucket()
            with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
                conn.execute("CREATE TABLE IF NOT EXISTS race_urls (url_hash text PRIMARY KEY, url text, writer text)")
            return
        except Exception as exc:  # noqa: BLE001
            print(f"startup: waiting ({exc})", flush=True)
            time.sleep(1)
    raise RuntimeError("stores never became ready")


@app.get("/healthz")
def healthz() -> dict:
    c.r.ping()
    c.ddb.list_tables()
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


# ---------- control API ----------

class CrawlIn(BaseModel):
    seeds: list[str] = Field(default_factory=lambda: list(ALL_SEEDS))
    maxPages: int = 500
    # Lab knobs. The interview API is { seeds, maxPages }.
    domainCap: int = 20
    maxDepth: int = 4
    scheduler: bool = True
    limit: int = 2
    politeness: Literal["fail-closed", "local", "fail-open"] = "fail-closed"


@app.post("/v1/crawls", status_code=202)
def start_crawl(body: CrawlIn) -> dict:
    reset_data()
    crawl_id = uuid.uuid4().hex[:12]
    c.r.hset("config", mapping={
        "scheduler": "on" if body.scheduler else "off", "limit": body.limit, "domainCap": body.domainCap,
        "maxDepth": body.maxDepth, "maxPages": body.maxPages, "politeness": body.politeness})
    c.r.set("crawl:started", time.time())
    seeded = []
    for raw in body.seeds:
        url = c.normalize(raw)
        if not url:
            continue
        c.ensure_domain(c.domain_of(url))
        if c.insert_url(url, 0, pending=body.scheduler):
            if not body.scheduler:
                c.send_frontier(c.url_hash(url), url, 0)
            seeded.append(url)
    c.r.set("crawl:id", crawl_id)
    c.event("control", f"crawl {crawl_id}: {len(seeded)} seeds as "
                       f"{'pending (scheduler on)' if body.scheduler else 'frontier messages (scheduler off)'}")
    return {"crawlId": crawl_id, "status": "running"}


@app.get("/v1/crawls/{crawl_id}")
def crawl_status(crawl_id: str) -> dict:
    if c.r.get("crawl:id") != crawl_id:
        raise HTTPException(404, "unknown crawl")
    urls = scan("urls")
    progress = status_of(urls)
    return {"crawlId": crawl_id, "status": progress["status"],
            "pagesFetched": sum(1 for u in urls if u.get("html_key")),
            "frontierSize": progress["queues"]["frontier"]["total"],
            "domains": len({u["domain"] for u in urls})}


# ---------- lab state ----------

def scan(table: str) -> list[dict]:
    items, kwargs = [], {"TableName": table, "ConsistentRead": True}
    while True:
        page = c.ddb.scan(**kwargs)
        rows = [c.from_ddb(i) for i in page.get("Items", [])]
        if table == "urls":
            rows = [u for u in rows if "state" in u and "domain" in u]
        items += rows
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def queue_counts(name: str) -> dict:
    a = c.sqs.get_queue_attributes(QueueUrl=c.QUEUES[name], AttributeNames=["All"])["Attributes"]
    out = {"visible": int(a.get("ApproximateNumberOfMessages", 0)),
           "inFlight": int(a.get("ApproximateNumberOfMessagesNotVisible", 0)),
           "delayed": int(a.get("ApproximateNumberOfMessagesDelayed", 0))}
    out["total"] = sum(out.values())
    return out


def status_of(urls: list[dict]) -> dict:
    queues = {q: queue_counts(q) for q in ("frontier", "parse", "dlq")}
    if not c.r.get("crawl:id"):
        return {"status": "idle", "queues": queues, "admissible": 0}
    cfg = c.config()
    admissible = 0
    if cfg["scheduler"] and int(c.r.get("crawl:admitted") or 0) < cfg["maxPages"]:
        pending_by_domain: dict[str, int] = {}
        for u in urls:
            if u["state"] == "pending":
                pending_by_domain[u["domain"]] = pending_by_domain.get(u["domain"], 0) + 1
        for d in scan("domains"):
            if pending_by_domain.get(d["domain"]) and int(d.get("pages_admitted", 0)) < cfg["domainCap"]:
                admissible += pending_by_domain[d["domain"]]
    busy = queues["frontier"]["total"] or queues["parse"]["total"] or admissible
    if busy:
        c.r.delete("crawl:quiet_since")
        status = "running"
    else:
        c.r.set("crawl:quiet_since", time.time(), nx=True)
        status = "done" if time.time() - float(c.r.get("crawl:quiet_since")) >= 2 else "running"
    if status == "done" and c.r.set("crawl:recorded", 1, nx=True):
        record_run(urls)
    return {"status": status, "queues": queues, "admissible": admissible}


def record_run(urls: list[dict]) -> None:
    cfg = c.config()
    stats = c.r.hgetall("stats")
    wiki = c.r.hgetall("dstats:wiki.test")
    started = float(c.r.get("crawl:started") or time.time())
    receives = int(stats.get("receives", 0))
    deferrals = int(stats.get("deferrals", 0))
    c.r.lpush("runs", json.dumps({
        "crawlId": c.r.get("crawl:id"), "scheduler": cfg["scheduler"], "limit": cfg["limit"],
        "seconds": round(time.time() - started, 1), "fetched": int(stats.get("fetched", 0)),
        "receives": receives, "deferrals": deferrals,
        "deferralShare": round(deferrals / receives, 3) if receives else 0,
        "wikiReceives": int(wiki.get("receives", 0)), "wikiDeferrals": int(wiki.get("deferrals", 0)),
        "wikiFetched": int(wiki.get("fetched", 0)), "urls": len(urls)}))
    c.r.ltrim("runs", 0, 9)


def fakeweb_stats() -> dict:
    try:
        return httpx.get(f"{FAKEWEB}/__lab/stats", timeout=2).json()
    except httpx.HTTPError:
        return {}


@app.get("/v1/lab/state")
def lab_state() -> dict:
    urls = scan("urls")
    progress = status_of(urls)
    by_state: dict[str, int] = {}
    for u in urls:
        by_state[u["state"]] = by_state.get(u["state"], 0) + 1
    server = fakeweb_stats()
    domains = []
    for d in sorted(scan("domains"), key=lambda x: x["domain"]):
        ds = c.r.hgetall(f"dstats:{d['domain']}")
        gap = int(float(d["crawl_delay_sec"]) * 1000) if d.get("crawl_delay_sec") else c.DEFAULT_GAP_MS
        seen = server.get(d["domain"], {})
        domains.append({**d, "gapMs": gap, "stats": ds, "server": seen,
                        "pending": sum(1 for u in urls if u["domain"] == d["domain"] and u["state"] == "pending")})
    politeness = []
    for key in c.r.scan_iter("politeness:*"):
        politeness.append({"key": key, "value": c.r.get(key), "pttl": c.r.pttl(key)})
    bits = rbin.get("bloom:content") or b""
    try:
        html_n = c.s3.list_objects_v2(Bucket=c.BUCKET, Prefix="html/").get("KeyCount", 0)
        text_n = c.s3.list_objects_v2(Bucket=c.BUCKET, Prefix="text/").get("KeyCount", 0)
    except ClientError:
        html_n = text_n = 0
    hashes = scan("content_hashes")
    started = c.r.get("crawl:started")
    return {
        "crawlId": c.r.get("crawl:id"), "config": c.config(), **progress,
        "elapsed": round(time.time() - float(started), 1) if started else 0,
        "byState": by_state, "urlCount": len(urls),
        "urls": sorted(urls, key=lambda u: -float(u.get("updated_at", 0)))[:80],
        "domains": domains, "contentHashes": len(hashes),
        "redis": {"politeness": politeness, "down": c.r.get("lab:politeness_down") == "1",
                  "crawlAdmitted": int(c.r.get("crawl:admitted") or 0)},
        "bloom": {"bits": c.BLOOM_BITS, "k": c.BLOOM_K, "hex": bits.hex(),
                  "set": sum(bin(b).count("1") for b in bits)},
        "stats": c.r.hgetall("stats"),
        "s3": {"html": html_n, "text": text_n},
        "events": [json.loads(e) for e in c.r.lrange("events", 0, 79)],
        "runs": [json.loads(x) for x in c.r.lrange("runs", 0, 9)],
        "settings": {"defaultGapMs": c.DEFAULT_GAP_MS, "visibilityTimeout": c.VISIBILITY_TIMEOUT,
                     "backoffBase": c.BACKOFF_BASE, "maxAttempts": c.MAX_ATTEMPTS,
                     "fetchTimeout": c.FETCH_TIMEOUT, "maxBytes": c.MAX_BYTES},
    }


@app.get("/v1/lab/urls")
def all_urls() -> list[dict]:
    return sorted(scan("urls"), key=lambda u: u["url"])


@app.get("/v1/lab/text/{url_id}", response_class=PlainTextResponse)
def page_text(url_id: str) -> str:
    try:
        return c.s3.get_object(Bucket=c.BUCKET, Key=f"text/{url_id}")["Body"].read().decode()
    except ClientError:
        raise HTTPException(404, "no text for this url")


# ---------- reset ----------

def clear_table(table: str, key: str) -> None:
    for item in scan(table):
        c.ddb.delete_item(TableName=table, Key={key: {"S": item[key]}})


def reset_data() -> None:
    c.r.delete("crawl:id")
    for q in c.QUEUES.values():
        try:
            c.sqs.purge_queue(QueueUrl=q)
        except ClientError:
            pass
    for table, key in (("urls", "url_hash"), ("content_hashes", "hash"), ("domains", "domain")):
        clear_table(table, key)
    try:
        objs = c.s3.list_objects_v2(Bucket=c.BUCKET).get("Contents", [])
        if objs:
            c.s3.delete_objects(Bucket=c.BUCKET, Delete={"Objects": [{"Key": o["Key"]} for o in objs]})
    except ClientError:
        pass
    keep = {"runs", "crawl:epoch"}
    for pattern in ("stats", "dstats:*", "politeness:*", "lastfetch:*", "events", "bloom:content", "config",
                    "crawl:*", "lab:*"):
        for key in c.r.scan_iter(pattern):
            if key not in keep:
                c.r.delete(key)
    c.r.incr("crawl:epoch")
    try:
        httpx.post(f"{FAKEWEB}/__lab/reset", timeout=2)
    except httpx.HTTPError:
        pass


@app.post("/v1/lab/reset")
def reset() -> dict:
    reset_data()
    clear_table("race_urls", "url_hash")
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute("TRUNCATE race_urls")
    return {"ok": True, "cleared": ["urls", "content_hashes", "domains", "race_urls", "frontier", "parse", "dlq",
                                    "s3 html/ and text/", "redis keys (runs kept)", "postgres race_urls"]}


@app.delete("/v1/lab/runs")
def clear_runs() -> dict:
    c.r.delete("runs")
    return {"ok": True}


# ---------- failure buttons ----------

@app.post("/v1/lab/crash-fetcher")
def crash_fetcher() -> dict:
    c.r.set("lab:crash_fetcher", 1)
    return {"armed": "the next fetcher worker that gets a 200 crashes before the S3 write and the delete"}


@app.post("/v1/lab/crash-parser")
def crash_parser() -> dict:
    c.r.set("lab:crash_parser", 1)
    return {"armed": "the next parser worker crashes after the text write, before the state update"}


class PolitenessIn(BaseModel):
    down: bool
    mode: Literal["fail-closed", "local", "fail-open"] = "fail-closed"


@app.post("/v1/lab/politeness-store")
def politeness_store(body: PolitenessIn) -> dict:
    c.r.hset("config", "politeness", body.mode)
    if body.down:
        c.r.set("lab:politeness_down", "1")
    else:
        c.r.delete("lab:politeness_down")
    return {"down": body.down, "mode": body.mode}


# ---------- race panel: two parsers insert the same new URL at the same instant ----------

class RaceIn(BaseModel):
    variant: Literal["dynamo-conditional", "dynamo-plain", "postgres"]


def race_one(variant: str, parser: str, url: str, uid: str, barrier: threading.Barrier) -> dict:
    if variant == "postgres":
        sql = "INSERT INTO race_urls (url_hash, url, writer) VALUES (%s, %s, %s) ON CONFLICT (url_hash) DO NOTHING"
        request = {"sql": sql, "params": [uid[:12] + "…", url, parser]}
        with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
            barrier.wait()
            t0 = time.perf_counter()
            cur = conn.execute(sql, (uid, url, parser))
            ms = (time.perf_counter() - t0) * 1000
        won = cur.rowcount == 1
        return {"parser": parser, "request": request, "response": {"status": f"INSERT 0 {cur.rowcount}"},
                "queued": won, "ms": round(ms, 1)}
    request = {"TableName": "race_urls",
               "Item": {"url_hash": {"S": uid}, "url": {"S": url}, "state": {"S": "pending"},
                        "writer": {"S": parser}},
               "ReturnConsumedCapacity": "TOTAL"}
    if variant == "dynamo-conditional":
        request["ConditionExpression"] = "attribute_not_exists(url_hash)"
    barrier.wait()
    t0 = time.perf_counter()
    try:
        out = c.ddb.put_item(**request)
        response = {"status": 200, "body": {"ConsumedCapacity": out.get("ConsumedCapacity")}}
        won = True
    except ClientError as exc:
        response = {"status": exc.response["ResponseMetadata"]["HTTPStatusCode"],
                    "body": {"__type": exc.response["Error"]["Code"], "message": exc.response["Error"]["Message"]}}
        won = False
    ms = (time.perf_counter() - t0) * 1000
    shown = json.loads(json.dumps(request))
    shown["Item"]["url_hash"]["S"] = uid[:12] + "…"
    return {"parser": parser, "request": {"PutItem": shown}, "response": response, "queued": won, "ms": round(ms, 1)}


@app.post("/v1/lab/race")
def race(body: RaceIn) -> dict:
    url = f"https://race.test/new-page-{uuid.uuid4().hex[:6]}"
    uid = c.url_hash(url)
    barrier = threading.Barrier(2)
    results: list[dict] = [{}, {}]

    def run(i: int) -> None:
        results[i] = race_one(body.variant, f"P{i + 1}", url, uid, barrier)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if body.variant == "postgres":
        with psycopg.connect(DATABASE_URL) as conn:
            row = conn.execute("SELECT url_hash, url, writer FROM race_urls WHERE url_hash = %s", (uid,)).fetchone()
        stored = {"url_hash": row[0][:12] + "…", "url": row[1], "writer": row[2]} if row else None
    else:
        item = c.ddb.get_item(TableName="race_urls", Key={"url_hash": {"S": uid}}, ConsistentRead=True).get("Item")
        stored = c.from_ddb(item) if item else None
        if stored:
            stored["url_hash"] = stored["url_hash"][:12] + "…"
    queued = sum(1 for x in results if x["queued"])
    verdict = {
        "dynamo-conditional": "One parser wins. The other gets ConditionalCheckFailedException and reads it as 'seen'.",
        "dynamo-plain": "Both writes succeed (last write wins). Both parsers think the URL is new: it is queued twice.",
        "postgres": "The primary checks and writes in one step. One INSERT adds 1 row; the other adds 0.",
    }[body.variant]
    return {"variant": body.variant, "url": url, "parsers": results, "queuedCount": queued,
            "storedItem": stored, "verdict": verdict}
