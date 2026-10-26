"""Fetcher service: frontier message -> robots check -> politeness claim -> GET -> S3 html/ -> parse queue."""

from __future__ import annotations

import json
import math
import os
import random
import socket
import threading
import time
from urllib.parse import urlsplit

import httpx
import redis as redis_lib
from botocore.exceptions import ClientError

from . import common as c

WORKERS = int(os.environ.get("FETCHER_WORKERS", "6"))
HOST = socket.gethostname()[:6]
_local_last: dict[str, float] = {}
_local_lock = threading.Lock()
_domain_cache: dict[str, tuple[dict, float]] = {}


def hide(msg: dict, seconds: int) -> None:
    c.sqs.change_message_visibility(QueueUrl=c.QUEUES["frontier"], ReceiptHandle=msg["ReceiptHandle"],
                                    VisibilityTimeout=max(1, min(seconds, 43200)))


def delete(msg: dict) -> None:
    try:
        c.sqs.delete_message(QueueUrl=c.QUEUES["frontier"], ReceiptHandle=msg["ReceiptHandle"])
    except ClientError:
        pass


def domain_row(domain: str, fresh: bool = False) -> dict:
    hit = _domain_cache.get(domain)
    if hit and not fresh and hit[1] > time.time():
        return hit[0]
    item = c.ddb.get_item(TableName="domains", Key={"domain": {"S": domain}}, ConsistentRead=True).get("Item")
    row = c.from_ddb(item) if item else {}
    if row.get("robots_status", "unknown") != "unknown":
        _domain_cache[domain] = (row, time.time() + 5)
    return row


def gap_ms(row: dict) -> int:
    delay = row.get("crawl_delay_sec")
    return int(float(delay) * 1000) if delay else c.DEFAULT_GAP_MS


def http_get(url: str, accept_html: bool = True) -> tuple[int, str, bytes, str | None]:
    """Returns (status, content type, body, error). Stops reading past MAX_BYTES."""
    parts = urlsplit(url)
    ip = c.resolve(parts.hostname)
    target = f"{parts.scheme}://{ip}:{parts.port or 80}{parts.path or '/'}" + (f"?{parts.query}" if parts.query else "")
    headers = {"Host": parts.hostname, "User-Agent": "labcrawler/1.0"}
    if accept_html:
        headers["Accept"] = "text/html"
    with httpx.Client(timeout=c.FETCH_TIMEOUT, follow_redirects=False) as http:
        with http.stream("GET", target, headers=headers) as resp:
            ctype = resp.headers.get("content-type", "")
            if accept_html and resp.status_code == 200 and "text/html" not in ctype:
                return resp.status_code, ctype, b"", "not html"
            body = bytearray()
            for chunk in resp.iter_bytes():
                body.extend(chunk)
                if len(body) > c.MAX_BYTES:
                    return resp.status_code, ctype, b"", "too large"
            return resp.status_code, ctype, bytes(body), None


def finalize(uid: str, domain: str, cfg: dict, state: str, **fields) -> None:
    c.update_url(uid, state=state, **fields)
    if cfg["scheduler"]:
        c.finish_in_flight(domain)


def claim(domain: str, gap: int, cfg: dict) -> tuple[bool, int, str]:
    """Returns (won, wait ms, how). Redis SET NX PX is the shared clock for every fetcher."""
    if r_down():
        mode = cfg["politeness"]
        if mode == "fail-open":
            return True, 0, "politeness store down: fail open, no limit"
        if mode == "local":
            with _local_lock:
                need = gap * c.FETCHER_PROCESSES / 1000
                last = _local_last.get(domain, 0)
                if time.time() - last >= need:
                    _local_last[domain] = time.time()
                    return True, 0, f"politeness store down: local limit 1 per {need:.1f}s on this machine"
                return False, int((need - (time.time() - last)) * 1000), "local limit"
        return False, -1, "politeness store down: fail closed, pause"
    if c.r.set(f"politeness:{domain}", HOST, nx=True, px=gap):
        return True, 0, f"SET politeness:{domain} NX PX {gap} -> OK"
    pttl = c.r.pttl(f"politeness:{domain}")
    return False, max(pttl, 0), f"SET politeness:{domain} NX PX {gap} -> nil (PTTL {pttl} ms)"


def first_admit(uid: str) -> bool:
    """A retry must not count against the domain cap again."""
    return c.update_existing("urls", {"url_hash": {"S": uid}}, "SET admitted = :one", {":one": {"N": "1"}},
                             condition="attribute_not_exists(admitted)") is not None


def r_down() -> bool:
    return c.r.get("lab:politeness_down") == "1"


def fetch_robots(domain: str, worker: str) -> dict:
    try:
        status, _, body, err = http_get(f"http://{domain}/robots.txt", accept_html=False)
    except (httpx.HTTPError, OSError) as exc:
        status, body, err = 599, b"", str(exc)
    if status == 200:
        parsed = c.parse_robots(body.decode("utf-8", "replace"))
        robots_status = "ok"
    elif 400 <= status < 500:
        parsed, robots_status = {"rules": [], "crawlDelay": None}, f"{status}: allow all"
    else:
        parsed, robots_status = {"rules": [["disallow", "/"]], "crawlDelay": None}, f"{status}: disallow all"
    expr = "SET robots_rules = :r, robots_status = :s, robots_fetched_at = :t"
    vals = {":r": {"S": json.dumps(parsed["rules"])}, ":s": {"S": robots_status}, ":t": {"N": str(time.time())}}
    if parsed["crawlDelay"]:
        expr += ", crawl_delay_sec = :d"
        vals[":d"] = {"N": str(parsed["crawlDelay"])}
    c.update_existing("domains", {"domain": {"S": domain}}, expr, vals)
    c.event(worker, f"GET http://{domain}/robots.txt -> {status} ({robots_status}); the page waits for the next slot")
    _domain_cache.pop(domain, None)
    return domain_row(domain, fresh=True)


_epoch = {"seen": None}


def handle(msg: dict, worker: str) -> None:
    epoch = c.r.get("crawl:epoch")
    if epoch != _epoch["seen"]:
        _epoch["seen"] = epoch
        _domain_cache.clear()
        _local_last.clear()
    body = json.loads(msg["Body"])
    uid, url, depth = body["urlId"], body["url"], int(body["depth"])
    domain = c.domain_of(url)
    cfg = c.config()
    row = c.get_url(uid)
    if row is None:
        delete(msg)
        return
    c.stat("receives", domain=domain)
    if c.update_existing("urls", {"url_hash": {"S": uid}}, "ADD receives :one", {":one": {"N": "1"}}) is None:
        delete(msg)
        return
    if row["state"] in c.FINAL_STATES:
        c.stat("duplicate_deliveries", domain=domain)
        c.event(worker, f"{url} is already {row['state']}; delete the repeated message")
        delete(msg)
        return

    if depth > cfg["maxDepth"]:
        c.stat("skipped_depth", domain=domain)
        c.event(worker, f"{url} depth {depth} > {cfg['maxDepth']}: skipped (trap guard)")
        finalize(uid, domain, cfg, "skipped", last_error=f"depth {depth} > {cfg['maxDepth']}")
        delete(msg)
        return

    drow = domain_row(domain)
    robots_known = drow.get("robots_status", "unknown") != "unknown"
    if robots_known:
        rules = json.loads(drow.get("robots_rules", "[]"))
        path = urlsplit(url).path + (f"?{urlsplit(url).query}" if urlsplit(url).query else "")
        allowed, why = c.robots_allows(rules, path)
        if not allowed:
            c.stat("skipped_robots", domain=domain)
            c.event(worker, f"{url} disallowed: {why}")
            finalize(uid, domain, cfg, "skipped", last_error=f"robots: {why}")
            delete(msg)
            return

    if not cfg["scheduler"] and not row.get("admitted"):
        admitted = int(domain_row(domain, fresh=True).get("pages_admitted", 0))
        if admitted >= cfg["domainCap"] or int(c.r.get("crawl:admitted") or 0) >= cfg["maxPages"]:
            c.stat("skipped_cap", domain=domain)
            finalize(uid, domain, cfg, "skipped", last_error=f"domain cap {cfg['domainCap']} reached")
            delete(msg)
            return

    gap = gap_ms(drow)
    won, wait, how = claim(domain, gap, cfg)
    if not won:
        if wait < 0:
            c.stat("paused", domain=domain)
            c.event(worker, f"{url}: {how}; hide 2 s")
            hide(msg, 2)
            return
        jitter = random.randint(0, 300)
        seconds = max(1, math.ceil((wait + jitter) / 1000))
        c.stat("deferrals", domain=domain)
        c.event(worker, f"{url}: {how}; hide {seconds} s (wait {wait} ms + jitter {jitter} ms, rounded up)")
        hide(msg, seconds)
        return

    if not robots_known:
        fetch_robots(domain, worker)
        hide(msg, max(1, math.ceil(gap / 1000)))
        return

    if not cfg["scheduler"] and first_admit(uid):
        if c.update_existing("domains", {"domain": {"S": domain}}, "ADD pages_admitted :one",
                             {":one": {"N": "1"}, ":cap": {"N": str(cfg["domainCap"])}},
                             condition="pages_admitted < :cap") is not None:
            c.r.incr("crawl:admitted")
        else:
            c.stat("skipped_cap", domain=domain)
            finalize(uid, domain, cfg, "skipped", last_error=f"domain cap {cfg['domainCap']} reached")
            delete(msg)
            return

    c.r.hset(f"lastfetch:{domain}", mapping={"t": time.time(), "by": worker, "how": how})
    try:
        status, ctype, html, err = http_get(url)
    except (httpx.HTTPError, OSError) as exc:
        status, ctype, html, err = 0, "", b"", type(exc).__name__
    if status == 200 and err is None:
        if c.r.getdel("lab:crash_fetcher"):
            c.stat("crashes")
            c.event(worker, f"CRASH after GET {url}, before the S3 write and the delete. "
                            f"The message returns after the {c.VISIBILITY_TIMEOUT} s visibility timeout")
            return
        key = f"html/{uid}"
        c.s3.put_object(Bucket=c.BUCKET, Key=key, Body=html, ContentType="text/html")
        c.update_url(uid, state="fetched", http_status=200, html_key=key, fetched_at=time.time())
        c.sqs.send_message(QueueUrl=c.QUEUES["parse"], MessageBody=json.dumps({"urlId": uid}))
        if cfg["scheduler"]:
            c.finish_in_flight(domain)
        delete(msg)
        c.stat("fetched", domain=domain)
        c.event(worker, f"GET {url} -> 200, {len(html)} B to s3://{c.BUCKET}/{key}; parse queue <- {{urlId}}")
        return
    if status == 200 and err:
        c.stat(f"skipped_{err.replace(' ', '_')}", domain=domain)
        c.event(worker, f"GET {url} -> 200 {ctype}: skipped ({err})")
        finalize(uid, domain, cfg, "skipped", http_status=200, last_error=err)
        delete(msg)
        return
    if 400 <= status < 500 and status != 429:
        c.stat("failed", domain=domain)
        c.event(worker, f"GET {url} -> {status}: permanent, no retry")
        finalize(uid, domain, cfg, "failed", http_status=status, last_error=f"HTTP {status}")
        delete(msg)
        return
    reason = f"HTTP {status}" if status else err
    updated = c.update_existing("urls", {"url_hash": {"S": uid}}, "ADD attempts :one SET last_error = :e",
                                {":one": {"N": "1"}, ":e": {"S": reason}}, returns="UPDATED_NEW")
    if updated is None:
        delete(msg)
        return
    attempts = int(updated["attempts"]["N"])
    if attempts >= c.MAX_ATTEMPTS:
        c.sqs.send_message(QueueUrl=c.QUEUES["dlq"], MessageBody=json.dumps(
            {"urlId": uid, "url": url, "attempts": attempts, "lastError": reason}))
        finalize(uid, domain, cfg, "dead", http_status=status, last_error=reason)
        delete(msg)
        c.stat("dead", domain=domain)
        c.event(worker, f"GET {url} -> {reason}, attempt {attempts}/{c.MAX_ATTEMPTS}: dead, sent to the DLQ")
        return
    backoff = c.BACKOFF_BASE * 2 ** (attempts - 1)
    jitter = random.random() * c.BACKOFF_BASE
    seconds = min(900, math.ceil(backoff + jitter))
    # A hidden message counts as in flight (quota about 120,000). A delayed message does not.
    c.sqs.send_message(QueueUrl=c.QUEUES["frontier"], MessageBody=msg["Body"], DelaySeconds=seconds)
    delete(msg)
    c.stat("retries", domain=domain)
    c.event(worker, f"GET {url} -> {reason}, attempt {attempts}/{c.MAX_ATTEMPTS}: "
                    f"send again with DelaySeconds {seconds} ({c.BACKOFF_BASE} s x 2^{attempts - 1} + jitter), "
                    f"delete the old message")


def loop(idx: int) -> None:
    worker = f"fetch-{HOST}-w{idx}"
    while True:
        try:
            msgs = c.sqs.receive_message(QueueUrl=c.QUEUES["frontier"], MaxNumberOfMessages=1,
                                         WaitTimeSeconds=1).get("Messages", [])
            for msg in msgs:
                handle(msg, worker)
        except (ClientError, redis_lib.RedisError, OSError) as exc:
            print(f"{worker}: {exc}", flush=True)
            time.sleep(1)
        except Exception as exc:  # noqa: BLE001
            print(f"{worker}: unexpected {exc!r}", flush=True)
            time.sleep(1)


def main() -> None:
    c.wait_ready("fetcher")
    threads = [threading.Thread(target=loop, args=(i,), daemon=True) for i in range(WORKERS)]
    for t in threads:
        t.start()
    print(f"fetcher {HOST}: {WORKERS} workers", flush=True)
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
