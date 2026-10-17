"""Measure how many sends per second the local lab takes.

Lee's phone on server A sends to lee-kim. Kim's phone is online on server B,
so every send pays the store write and the Redis hop. The script reports
throughput, latency percentiles, errors, and how many pushes reached Kim.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time

import httpx


async def worker(client: httpx.AsyncClient, stop_at: float, latencies: list, errors: list) -> None:
    n = 0
    while time.perf_counter() < stop_at:
        n += 1
        started = time.perf_counter()
        try:
            response = await client.post(
                "/v1/messages",
                json={"chatId": "lee-kim", "message": f"load-{n}", "serverId": "A", "clientId": "lee-phone"},
            )
            if response.status_code != 202:
                errors.append(response.status_code)
                continue
        except httpx.HTTPError as exc:
            errors.append(type(exc).__name__)
            continue
        latencies.append((time.perf_counter() - started) * 1000)


def sent_count(latencies: list) -> int:
    return len(latencies)


def pct(values: list, p: float) -> float:
    if not values:
        return float("nan")
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * p))]


async def run(base_url: str, concurrency: int, seconds: float) -> dict:
    limits = httpx.Limits(max_connections=concurrency + 4)
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0, limits=limits) as client:
        await client.post("/v1/lab/reset")
        await client.post("/v1/lab/connect", json={"serverId": "A", "clientId": "lee-phone"})
        await client.post("/v1/lab/connect", json={"serverId": "B", "clientId": "kim-phone"})
        await asyncio.sleep(0.5)

        latencies: list = []
        errors: list = []
        stop_at = time.perf_counter() + seconds
        started = time.perf_counter()
        await asyncio.gather(*(worker(client, stop_at, latencies, errors) for _ in range(concurrency)))
        elapsed = time.perf_counter() - started

        # Wait until Kim's mailbox stops growing. The wait is the receive backlog.
        drain_started = time.perf_counter()
        delivered, stable_since = -1, time.perf_counter()
        while time.perf_counter() - drain_started < 60:
            total = (await client.get("/v1/lab/mailbox/kim-phone")).json()["total"]
            if total != delivered:
                delivered, stable_since = total, time.perf_counter()
            elif total >= sent_count(latencies) or time.perf_counter() - stable_since > 3:
                break
            await asyncio.sleep(0.2)
        backlog_s = max(0.0, stable_since - drain_started)
        await client.post("/v1/lab/reset")

    sent = len(latencies)
    return {
        "concurrency": concurrency,
        "sent": sent,
        "per_second": sent / elapsed,
        "p50_ms": pct(latencies, 0.50),
        "p99_ms": pct(latencies, 0.99),
        "mean_ms": statistics.fmean(latencies) if latencies else float("nan"),
        "errors": len(errors),
        "delivered_live": delivered,
        "backlog_s": backlog_s,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", action="append", required=True, help="name=url, repeatable")
    parser.add_argument("--concurrency", default="1,8,32")
    parser.add_argument("--seconds", type=float, default=10.0)
    args = parser.parse_args()

    print(
        f"{'design':10} {'conc':>4} {'sent':>6} {'msg/s':>7} {'p50 ms':>7} {'p99 ms':>7} "
        f"{'errors':>6} {'kim got':>8} {'backlog s':>9}"
    )
    for entry in args.url:
        name, url = entry.split("=", 1)
        for conc in (int(c) for c in args.concurrency.split(",")):
            r = asyncio.run(run(url, conc, args.seconds))
            print(
                f"{name:10} {r['concurrency']:>4} {r['sent']:>6} {r['per_second']:>7.0f} "
                f"{r['p50_ms']:>7.1f} {r['p99_ms']:>7.1f} {r['errors']:>6} {r['delivered_live']:>8} "
                f"{r['backlog_s']:>9.1f}"
            )


if __name__ == "__main__":
    main()
