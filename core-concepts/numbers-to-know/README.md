# Numbers to Know

**Status:** Notes-only  
**Kind:** Core concept  
**Sources:** [Hello Interview — Numbers to Know](https://www.hellointerview.com/learn/system-design/core-concepts/numbers-to-know) · [Hello Interview — Core concepts cheatsheet](https://www.hellointerview.com/learn/system-design/in-a-hurry/core-concepts) · Alex Xu Vol 1 Ch 2 (back-of-the-envelope)  
**Slug:** `numbers-to-know`

This folder is a **concept lab**, not a product interview. Original notes from the 2026-09-26 session, reorganized 2026-10-03 around key metrics and scale triggers. **No Docker.** Read the cheatsheet, then use a trigger to pick the next lever.

Keep notes original. Link to Hello Interview; cite Alex Xu. Do not paste write-ups.

## What this is

Two columns you can say out loud.

**Key metrics** are what one healthy box can do: latency, throughput, memory, disk, connections. **Scale triggers** are the measurements that say that box is no longer the right shape. A trigger starts a design change. It does not name the change by itself.

Exact vendor benches do not matter. Stay within about 10×, and know which gap is 100×.

Units (say these once so you do not mix ms and ns):

| Unit | Equals |
| --- | --- |
| 1 second | 1,000 ms |
| 1 millisecond (ms) | 1,000 µs |
| 1 microsecond (µs) | 1,000 ns |
| Day | ≈ 10^5 seconds (86,400; use 100,000 in your head) |
| 1 Gbps | ≈ 125 MB/s. A 25 Gbps NIC is ≈ 3 GB/s |

Peak QPS ≈ (daily requests ÷ 10^5) × 3 to 10. Design for peak.

## Latency ladder

Say this before the component card. It decides cache, disk, and region.

| Hop | Time | Use it when |
| --- | --- | --- |
| L1 cache | ~1 ns | Explaining why an in-process hit is free next to a network call |
| RAM | ~100 ns | The data is already in memory. A Redis GET is not this number |
| SSD random read | ~100 µs | One indexed row that misses RAM. Still well under 1 ms |
| HDD seek | ~10 ms | You chose spinning disk. Rare as a primary in 2026 |
| Same AZ | under 1 ms | Redis, a replica, another app server in the same building |
| Same region, other AZ | ~1–2 ms | A second availability zone. Still local |
| Cross-region | ~50–150 ms | NY–London is about 80 ms from the speed of light in fiber. US–Asia can be a few hundred ms |

A Redis GET over the datacenter network is about 1 ms because of the network. RAM itself is nanoseconds. A user on another continent is already ~100 ms away, so one extra millisecond inside the region does not change their page.

## Cheatsheet

Modern boxes are large. A general instance can be hundreds of GB of RAM and on the order of 100 cores. Memory-optimized machines go to multiple TB, and a few go past 10 TB. Local SSD can be tens of TB; object storage is the place for media, and it is not the reason you shard a database. Inside a region, 25 Gbps is a normal NIC and 50–100 Gbps exists on big instances. Sharding at a few hundred GB is extra machinery. A single Postgres is comfortable into the terabytes. The interesting ceilings are writes, hot rows, connections, and a working set that no longer fits RAM.

| Component | Key metrics (one box) | Scale triggers (time to change something) |
| --- | --- | --- |
| Cache (Redis) | ~1 ms from the app, because that is the network. 100k+ simple ops/s per node (some benches land near 200k). Memory-bound; one node can hold a lot, up toward 1 TB on a large instance | Hit rate under ~80%. Latency over ~1 ms. Memory over ~80%. Keys churning so fast the cache never helps (thrash) |
| Database (Postgres) | Simple work up to about 50k transactions/s on a large primary. Durable indexed writes: start the conversation near 10k/s. Cached or indexed reads often under 5 ms. Storage in the tens of TB before size alone forces a split | Writes past ~10k/s and still climbing. Uncached reads past ~5 ms. You need a second geography |
| App server | 100k+ concurrent connections on one process is the top of the range. 8–64 cores, 64–512 GB RAM is ordinary; 2 TB exists | CPU over ~70%. Response time misses the SLA. Connections near 100k on that instance. Memory over ~80% |
| Message queue | Up to about 1 million small messages/s per broker. End-to-end under ~5 ms when consumers keep up. Disk into the tens of TB | Throughput near ~800k messages/s. Partition count near ~200k on the cluster. Consumer lag that keeps growing |

These four rows are the card. The latency ladder and the bandwidth line sit next to them. Alex Xu Vol 1 Ch 2 is the method (QPS, storage, bandwidth). The magnitudes above are the 2026 interview set, which is larger than older textbook ceilings.

## When a trigger fires

A trigger is a measurement. The next lever depends on which column broke.

**Cache hit rate under 80%.** The app is still asking Redis, and Redis is missing.

| Option | What happens | When it wins |
| --- | --- | --- |
| Do nothing | The database serves the misses | Miss QPS still fits the primary, and the data must be fresh (seats, balances) |
| Fix the cache | Longer TTL, a better key, or cache the result of the expensive query | The same keys repeat and the TTL is shorter than the reuse |
| Stop using the cache for this path | Reads go to replicas | The keys do not repeat. Hit rate near 0 means Redis is an extra hop |
| Add Redis nodes | More memory and more ops/s | Memory is over ~80%, or ops are near 100k/s, and the hit rate is already high |

For this study set, a low hit rate on a viral URL is a TTL and singleflight problem. A low hit rate on never-repeated keys is replicas. More Redis nodes win when the working set is hot and the node is full.

**Database writes past 10k/s.**

| Option | What happens | When it wins |
| --- | --- | --- |
| Do nothing | One primary keeps the writes | You are under ~10k durable writes/s and the disk still fits. 50 GB and 100 writes/s, as in the sharding chapter, stay here |
| Bigger primary | More RAM, so the working set stays in memory and reads stay under ~5 ms | The pain is uncached reads or a small disk, and writes are still comfortable |
| Queue in front | The API accepts the spike; workers drain at the database’s pace | Traffic is bursty and a short delay is acceptable. The queue does not raise the durable write ceiling |
| Shard | Several primaries, split by the common key | Sustained writes stay above what one primary can fsync, or the data is tens of TB after cache and replicas |

Say both database numbers. **10k/s** is the conservative durable-write trigger. **50k/s** is simple transactions on a large tuned primary. They are the same order of magnitude. Shard when the writes are real and sustained, not when someone quotes 500 GB.

**App CPU over 70%, or the SLA is missed.**

| Option | What happens | When it wins |
| --- | --- | --- |
| Do nothing | One server keeps the connections | CPU is low and latency meets the SLA |
| More app servers | The load balancer spreads connections. Each box stays under ~70% CPU and well under 100k connections | The work is stateless and the database is fine |
| Change the downstream | Cache, replica, or a smaller query | App CPU is low and the SLA is missed because each request waits on Postgres or Redis |

Adding app servers when Postgres is the wait does not move the SLA. Check which machine is hot before you copy the app.

**Queue lag keeps growing.**

| Option | What happens | When it wins |
| --- | --- | --- |
| Do nothing | A short spike drains after the burst | Lag falls back to zero within the allowed delay |
| More consumers | Parallel workers drain faster | The workers are the limit, and the database can take the extra writes |
| Backpressure | Producers slow down or get a 503 | Consumers are already as fast as the database. A longer queue hides a full primary |
| More brokers | Past ~800k messages/s, or partition counts near ~200k | The broker itself is the ceiling. A task queue at 1k jobs/s never needs this |

The one-time-password chapter is the small version: if SMS jobs cannot drain before the code expires, shed with 503. More queue storage would only hold dead codes.

## Interview default

1. Convert daily traffic to peak QPS with day ≈ 10^5 seconds and a 3–10× peak.
2. Say the latency ladder if the choice is cache, disk, or another region.
3. Put the busy component on the cheatsheet. Quote its key metric, then the trigger that is actually true.
4. Pick the lever that matches that trigger: more app servers, a cache, replicas, a queue, or a shard. In that order for a read-heavy OLTP system: cache for repeated keys, replicas for spread-out reads, shard for writes or for data that no longer fits one primary.

Switch to a finer bench only if they ask about p99 or a named engine.

## Cache vs replica vs shard

1. **Repeating keys** that fit RAM → Redis, usually before replicas.
2. **Lots of reads, keys do not repeat** → read replicas. One Postgres is about 10–50k simple reads/s, so 100k unique-key QPS needs several replicas.
3. **Write pressure** near 10k durable writes/s, or data that no longer fits one primary → shard. Replicas do not take writes.
4. **Shard** means several primaries. Hash a monotonic id. One Postgres `PARTITION BY` is still one machine.

100k QPS on 100k keys that get hit again is one Redis node at its ceiling. 100k QPS on 100k one-shot keys is replicas. 100M redirects/day is about 1k average QPS and often ~10k at peak. Postgres can serve that many primary-key reads. Redis is still the default when a few codes can go viral, because a shard does not move a hot key.

## Pitfalls

- Mixing ns and ms. RAM at “a millisecond” is about 10,000× too slow, and then cache versus disk stops making sense.
- Treating a scale trigger as an order to shard. Hit rate, CPU, and lag each point at a different lever.
- Using the 10k write number as the read ceiling, or the 50k transaction number as a durable fsync promise.
- Redis at 10k GET/s. That is the database’s write neighborhood. Redis is ~100k simple ops/s per node.
- Average QPS with no peak. 100M/day ≈ 1k average, often 3–10k at peak.
- Sharding because the table is “big” while QPS is tiny. A few hundred GB on one primary is normal.
- Forgetting bandwidth. Video dies on the NIC. 1 Gbps ≈ 125 MB/s; say 10–25 Gbps if you are on a modern instance.
- A queue in front of a full database. Lag grows forever unless consumers can commit or producers are slowed.
- Sharding on a monotonic id without hashing. The newest shard takes every insert.

## Local demo

**Notes-only.** No Compose stack. The practice is to take a QPS and a component, name the key metric, name the trigger, and name the lever.

**Cut vs production:** no `redis-benchmark` and no `pgbench`. Hardware in 2026 is faster than these anchors. The anchors stay round on purpose.

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

### 2026-10-03

**Q: The page is thinner than the Hello Interview cheatsheet. Add Key Metrics and Scale Triggers.**  
A: The card is four rows — cache, database, app server, queue — each with what one box can do and the measurement that means the shape should change. Cache: ~1 ms, 100k+ ops/s, up toward 1 TB; act on hit rate under ~80%, latency over ~1 ms, memory over ~80%, or thrash. Database: about 50k simple transactions/s and under 5 ms when the row is cached, with durable writes discussed near 10k/s; act on writes past ~10k/s, uncached reads past ~5 ms, or a second geography. App server: 100k+ connections; act on CPU over ~70%, an SLA miss, connections near 100k, or memory over ~80%. Queue: up to about 1M small messages/s; act near 800k/s, ~200k partitions, or lag that keeps growing. A trigger picks the lever. Low hit rate on repeated keys means fix the cache. Low hit rate on unique keys means replicas. Write pressure means a bigger primary, then a queue for bursts, then a shard. High app CPU means more app servers. Growing lag means more consumers, or backpressure when the database is already full.
