"""Domain scheduler: the only writer to the frontier when it is on.

For each domain with room (in_flight < limit, pages_admitted < cap), read pending URLs from the
pending_by_domain index and admit them: count the slot, mark the URL queued, send it to SQS.
"""

from __future__ import annotations

import time

from botocore.exceptions import ClientError

from . import common as c


def admit(domain: str, item: dict, cfg: dict) -> bool:
    uid = item["url_hash"]["S"]
    try:
        c.ddb.update_item(
            TableName="domains", Key={"domain": {"S": domain}},
            UpdateExpression="ADD in_flight :one, pages_admitted :one",
            ConditionExpression="in_flight < :limit AND pages_admitted < :cap",
            ExpressionAttributeValues={":one": {"N": "1"}, ":limit": {"N": str(cfg["limit"])},
                                       ":cap": {"N": str(cfg["domainCap"])}})
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise
    try:
        c.ddb.update_item(
            TableName="urls", Key={"url_hash": {"S": uid}},
            UpdateExpression="SET #s = :q, updated_at = :t REMOVE pending_domain",
            ConditionExpression="#s = :p", ExpressionAttributeNames={"#s": "state"},
            ExpressionAttributeValues={":q": {"S": "queued"}, ":p": {"S": "pending"}, ":t": {"N": str(time.time())}})
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        c.update_existing("domains", {"domain": {"S": domain}}, "ADD in_flight :m, pages_admitted :m",
                          {":m": {"N": "-1"}})
        return True
    c.r.incr("crawl:admitted")
    body = c.send_frontier(uid, item["url"]["S"], int(item["depth"]["N"]))
    c.stat("admitted", domain=domain)
    c.event("scheduler", f"admit {body['url']} ({domain} in_flight < {cfg['limit']}); frontier <- "
                         f"{{urlId: {uid[:8]}…, url, depth: {body['depth']}}}")
    return True


def tick() -> None:
    cfg = c.config()
    if not cfg["scheduler"] or not c.r.get("crawl:id"):
        return
    for raw in c.ddb.scan(TableName="domains", ConsistentRead=True).get("Items", []):
        row = c.from_ddb(raw)
        domain = row["domain"]
        room = cfg["limit"] - int(row.get("in_flight", 0))
        cap_left = cfg["domainCap"] - int(row.get("pages_admitted", 0))
        total_left = cfg["maxPages"] - int(c.r.get("crawl:admitted") or 0)
        n = min(room, cap_left, total_left)
        if n <= 0:
            continue
        pending = c.ddb.query(TableName="urls", IndexName="pending_by_domain", Limit=n,
                              KeyConditionExpression="pending_domain = :d",
                              ExpressionAttributeValues={":d": {"S": domain}}).get("Items", [])
        for item in pending:
            if not admit(domain, item, cfg):
                break


def main() -> None:
    c.wait_ready("scheduler")
    print("scheduler running", flush=True)
    while True:
        try:
            tick()
        except Exception as exc:  # noqa: BLE001
            print(f"scheduler: {exc!r}", flush=True)
            time.sleep(1)
        time.sleep(0.25)


if __name__ == "__main__":
    main()
