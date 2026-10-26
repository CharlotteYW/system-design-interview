"""Parser service: parse message -> HTML from S3 -> text -> content dedupe -> S3 text/ -> new links."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import threading
import time

import redis as redis_lib
from botocore.exceptions import ClientError

from . import common as c

WORKERS = int(os.environ.get("PARSER_WORKERS", "2"))
HOST = socket.gethostname()[:6]


def delete(msg: dict) -> None:
    try:
        c.sqs.delete_message(QueueUrl=c.QUEUES["parse"], ReceiptHandle=msg["ReceiptHandle"])
    except ClientError:
        pass


def dedupe(uid: str, url: str, content_hash: str, worker: str) -> bool:
    """Option C on the main path: the Bloom filter first, then the table only on "probably seen".
    Options A and B are counted from the same events. Returns True when the text is new."""
    probably_seen = c.bloom_check(content_hash)
    c.stat("bloom_pages")
    if probably_seen:
        c.stat("bloom_table_reads")
        item = c.ddb.get_item(TableName="content_hashes", Key={"hash": {"S": content_hash}},
                              ConsistentRead=True).get("Item")
        if item and item["first_url_hash"]["S"] != uid:
            c.stat("bloom_true_duplicates")
            c.event(worker, f"{url}: Bloom says probably seen; table has hash {content_hash[:10]} "
                            f"from {item['first_url']['S']}: duplicate")
            return False
        if not item:
            c.stat("bloom_false_positives")
            c.event(worker, f"{url}: Bloom says probably seen, but the table has no {content_hash[:10]}: "
                            f"false positive caught (Option B would drop this unique page)")
    else:
        c.stat("bloom_reads_skipped")
    try:
        c.ddb.put_item(TableName="content_hashes", Item={
            "hash": {"S": content_hash}, "first_url_hash": {"S": uid}, "first_url": {"S": url}},
            ConditionExpression="attribute_not_exists(#h) OR first_url_hash = :me",
            ExpressionAttributeNames={"#h": "hash"}, ExpressionAttributeValues={":me": {"S": uid}})
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        c.stat("bloom_true_duplicates")
        c.event(worker, f"{url}: another parser stored {content_hash[:10]} first: duplicate")
        return False
    c.bloom_add(content_hash)
    return True


def handle(msg: dict, worker: str) -> None:
    uid = json.loads(msg["Body"])["urlId"]
    row = c.get_url(uid)
    if row is None or row["state"] != "fetched":
        delete(msg)
        return
    url, depth, domain = row["url"], int(row["depth"]), row["domain"]
    cfg = c.config()
    html = c.s3.get_object(Bucket=c.BUCKET, Key=row["html_key"])["Body"].read().decode("utf-8", "replace")
    text, links = c.extract(html)
    content_hash = hashlib.sha256(text.encode()).hexdigest()

    if not dedupe(uid, url, content_hash, worker):
        c.update_url(uid, state="duplicate", content_hash=content_hash)
        c.stat("duplicates", domain=domain)
        delete(msg)
        return

    key = f"text/{uid}"
    c.s3.put_object(Bucket=c.BUCKET, Key=key, Body=text.encode(), ContentType="text/plain")
    if c.r.getdel("lab:crash_parser"):
        c.stat("crashes")
        c.event(worker, f"CRASH after writing s3://{c.BUCKET}/{key}, before the state update. "
                        f"The parse message returns; the same key is written again")
        return

    found = new = 0
    seen_here: set[str] = set()
    for href in links:
        link = c.normalize(href, base=url)
        if not link or link in seen_here:
            continue
        seen_here.add(link)
        found += 1
        link_domain = c.domain_of(link)
        c.ensure_domain(link_domain)
        if c.insert_url(link, depth + 1, pending=cfg["scheduler"]):
            new += 1
            if not cfg["scheduler"]:
                c.send_frontier(c.url_hash(link), link, depth + 1)
    c.update_url(uid, state="parsed", text_key=key, content_hash=content_hash, links_found=found, links_new=new)
    c.stat("parsed", domain=domain)
    c.stat("links_found", found)
    c.stat("links_new", new)
    target = "pending rows (the scheduler admits them)" if cfg["scheduler"] else "the frontier directly"
    c.event(worker, f"{url}: {len(text)} chars to s3://{c.BUCKET}/{key}; {found} links, {new} new -> {target}")
    delete(msg)


def loop(idx: int) -> None:
    worker = f"parse-{HOST}-w{idx}"
    while True:
        try:
            for msg in c.sqs.receive_message(QueueUrl=c.QUEUES["parse"], MaxNumberOfMessages=1,
                                             WaitTimeSeconds=1).get("Messages", []):
                handle(msg, worker)
        except (ClientError, redis_lib.RedisError, OSError) as exc:
            print(f"{worker}: {exc}", flush=True)
            time.sleep(1)
        except Exception as exc:  # noqa: BLE001
            print(f"{worker}: unexpected {exc!r}", flush=True)
            time.sleep(1)


def main() -> None:
    c.wait_ready("parser")
    threads = [threading.Thread(target=loop, args=(i,), daemon=True) for i in range(WORKERS)]
    for t in threads:
        t.start()
    print(f"parser {HOST}: {WORKERS} workers", flush=True)
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
