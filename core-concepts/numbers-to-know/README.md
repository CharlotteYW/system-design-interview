# Numbers to Know

**Status:** Notes-only  
**Kind:** Core concept  
**Sources:** [Hello Interview — Core concepts](https://www.hellointerview.com/learn/system-design/in-a-hurry/core-concepts) · Alex Xu Vol 1 Ch 2 (back-of-the-envelope) · [Hello Interview Redis deep dive](https://www.hellointerview.com/learn/system-design/deep-dives/redis) (≈100k ops/s per node)  
**Slug:** `numbers-to-know`

This folder is a **concept lab**, not a product interview. Original notes from the 2026-09-26 session. **No Docker.** Recite the ladder, then use it to pick cache / replica / shard.

Keep notes original. Link to Hello Interview; cite Alex Xu. Do not paste write-ups.

## What this is

A small set of **order-of-magnitude** latencies and throughputs so you can decide, in the interview, whether one box is enough or you need a cache, a replica, a queue, or a shard. Exact vendor benches do not matter. Being **within ~10×** and knowing **which gap is 100×** does.

Units (say these once so you do not mix ms and ns):

| Unit | Equals |
| --- | --- |
| 1 second | 1,000 ms |
| 1 millisecond (ms) | 1,000 µs |
| 1 microsecond (µs) | 1,000 ns |
| Day | ≈ 10^5 seconds (86,400; use 100,000 in your head) |

## Variants to know

| Variant | What it is | When it wins | When to skip |
| --- | --- | --- | --- |
| Memory vs disk vs network | **L1 ~1 ns, RAM ~100 ns, SSD random ~100 µs, HDD ~10 ms, same-DC RTT ~0.5–1 ms.** RAM is **not** milliseconds. A Redis GET over the DC network is ~1 ms because of **the network**, not because RAM is slow. | Justifying cache (RAM+simple op vs disk+query) or saying “the user is 100 ms away, extra 1 ms in-region does not matter” | Quoting ns to a PM; they care about p99 of the API |
| In-DC vs cross-continent | Same building: **~1 ms**. NY–London: **~80–150 ms** (speed of light in fiber). US–Asia can be **~150–300 ms**. | CDN / multi-region / “we cannot sync every click across oceans synchronously” | Using ocean RTT as the cost of a **local** Redis GET |
| Redis ops/s vs DB TPS | Interview anchors: **Redis ~100k simple ops/s per node**; **Postgres ~10k durable writes/s** on one primary (indexed reads often higher, messy joins much lower). Hello Interview: Redis command is µs; over the network you still see sub-ms. | Cache or counter in Redis when read QPS would melt the primary; keep Postgres as source of truth | Treating Redis as 10k/s (that is the **DB** number). Treating Postgres as 100k durable writes (it will not fsync that) |
| Single Postgres size / TPS | One well-run primary: **~10k writes/s**, **~10k–50k simple PK reads/s**, **multi-TB** of data is still common before you *must* shard. Connections and **one hot row** fail first, not “we have 200 GB.” | Shard when **writes** or **dataset+working set** no longer fit one primary after cache + replicas | Sharding a 2k QPS shortener “for scale theater” |
| Queue / broker throughput | Interview anchor: **~10 MB/s per Kafka partition** (tiny messages → high msg/s; 1 MB blobs → far fewer). A queue **buys time**, it does not raise the DB’s write ceiling unless consumers are parallel and idempotent. | Spike absorb, email/fan-out, decoupling | Using a queue to “make Postgres do 100k durable writes/s” without more consumers or a different store |

## Interview default

Say the **ladder** (ns / µs / ms) and **three anchors**: Redis **100k/s**, Postgres **10k writes/s**, DC **~1 ms** vs ocean **~100 ms**. Convert DAU → average QPS with **day ≈ 10^5 s**, then **×3–10 for peak**. Then pick levers in order: **cache (hot reads) → read replicas (more even reads) → shard (writes or data no longer fit one primary)**. Switch to finer numbers only if the interviewer asks about p99 or a specific engine.

## Cache vs replica vs shard

**Simple rules to say:**

1. **Repeating keys** (hot or a working set that fits RAM) → **Redis**, usually before replicas.
2. **Lots of reads, keys do not repeat** (cache hit rate ≈ 0) → **read replicas**. One Postgres is only ~10–50k simple reads/s, so **100k unique-key QPS needs several replicas**, not one.
3. **Write pressure** (~10k writes/s) or **data no longer fits one primary** → **shard**. Replicas do not help writes.
4. **Shard = split data across multiple primaries** (horizontal partition). For KV, shard key is usually the **primary key** (hash it if ids are time-ordered). That is not the same as Postgres `PARTITION BY` on **one** instance.

100k QPS on **100k keys that get hit again** is still Redis (100k small rows fit in memory; you are at one Redis node’s ceiling). 100k QPS on **100k one-shot keys** is replicas, not Redis.

100M redirects/day ≈ **1k average QPS**, peak often **~10k**. Postgres can take that many **simple PK reads**. Redis is still the default if a few codes can go viral.

| Decision | When | Why the numbers |
| --- | --- | --- |
| **Skip Redis** | Peak QPS is hundreds; keys are **almost never reused** (every read a new row); **write-heavy**; or stale cache is worse than extra DB load (money, seats) | Hit rate would be ~0, or writes already dominate. “Even spread” alone is not enough — 10k QPS of distinct keys still 10k DB hits |
| **Cache, do not shard** | Repeated **hot keys**, or total **read** QPS would crowd the primary, while **writes ≪ 10k/s** and data still fits one Postgres | Redis ~100k/s eats 10k reads. Sharding a hot key **does not help**: that key still lives on **one** shard |
| **Replicas, still no shard** | Reads are **spread across many keys** (poor cache hit rate) but still fit “lots of reads, modest writes” | Replicas scale **reads**. They do not raise **write** TPS on the primary |
| **Shard** | **Writes** approach ~10k/s, or **data + indexes + working set** no longer fit one primary **after** cache and replicas | Split write load and disk. Typical key-value shard key = id. Sequential ids (time-ordered Snowflake) can **hot-shard** the newest partition — hash the id or use a non-monotonic key |

## Pitfalls

- Mixing **ns and ms**: RAM at “a millisecond” is **~10,000×** too slow (100 ns vs 1 ms). Then cache vs DB stops making sense.
- Putting SSD/HDD in **seconds**. Random SSD is **~0.1 ms**; HDD seek is **~10 ms**. Seconds is a slow HTTP handler or a lock wait, not a disk read.
- Same-DC “under a second” and ocean “about a second.” Both are **milliseconds**. A second is a bad API, not a ping to London.
- **Redis = 10k GET/s.** That underestimates Redis by ~10× and you will shard Redis too early (or skip cache because “it is as slow as Postgres”).
- **QPS without peak.** 100M/day ≈ **1k average QPS**, peak often **3–10k**. Design for peak.
- Sharding because storage is “big” while **QPS is tiny**. Storage and TPS are different ceilings.
- Forgetting **1 Gbps ≈ 125 MB/s**. Video and image designs die on bandwidth, not on Redis GET/s.
- **“Evenly distributed reads ⇒ skip Redis.”** Even spread with **repeats** still caches. Skip cache when there is **no reuse** (unique keys) or QPS is tiny. Cache also protects the DB when you do **not** have a tight latency SLO.
- **Sharding to “lower read burden.”** Reads: cache, then replicas. Shard when **writes** or **size** break one primary. A viral key is a cache + singleflight problem, not a shard problem.
- Sharding on a **monotonic** primary key (time, autoincrement, Snowflake) without hashing — newest shard takes all new writes.

## Local demo

**Notes-only.** No Compose stack. The “demo” is reciting the table, then using it on a real question (URL shortener, then rate limiter).

**Cut vs production:** no `redis-benchmark`, no `pgbench`. Hardware in 2026 is faster; interview numbers stay conservative on purpose.

## How to run

There is nothing to start. Read this file.

```bash
cd core-concepts/numbers-to-know
./scripts/setup.sh   # prints notes-only; exit 0
```

`run-scenarios.sh` / `run-functional.sh` also exit 0 (no live system). `stop.sh` is a no-op.

## Session notes

**2026-09-26**

**Q: Latency ladder + Redis vs Postgres throughput?**  
A (user): L1/L2 in ms or ns; RAM in ms; SSD and HDD in seconds; same-DC under a second; cross-continent close to a second. GET &lt; 10k/s; Postgres ~10k ops/s.

Taught: units (ns/µs/ms). Ladder is **L1 ~1 ns, RAM ~100 ns, SSD ~100 µs, HDD ~10 ms, DC ~1 ms, ocean ~100 ms**. Postgres **~10k writes/s** is the right anchor. **GET &lt; 10k/s is the DB/app number, not Redis (~100k/s).**

**Q: Skip Redis vs cache-without-shard vs shard?**  
A (user): Skip Redis if reads are even or latency is not tight. Redis for hot keys without sharding Postgres. Shard to lower read and write load, usually by primary key.

Taught: skip Redis when **no reuse** or QPS is tiny (or write-heavy / cannot be stale) — not merely “even.” Hot key → Redis + singleflight; **shard does not spread one key**. Scale reads with cache then **replicas**; shard when **writes or data** miss one primary. PK shard is fine for a shortener id; sequential PK can hot-shard.

**Q: 100k QPS on 100k keys ⇒ replicas, no Redis; write pressure ⇒ shard on PK?**  
A (user): Yes, that simplification.

Taught: **only if those 100k keys do not repeat.** Repeating 100k keys → Redis first (fits RAM; ~100k/s is one Redis node). No reuse → replicas (several of them at 100k QPS). Writes → shard. Shard = **multiple primaries**; PK is the usual key; hash if monotonic. Not `PARTITION` on a single Postgres.

**Q: Wrap up?**  
A: User confirmed the three-line tree. Session closed 2026-09-26. Notes-only; `./scripts/stop.sh` is a no-op.
