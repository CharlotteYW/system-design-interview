# Consistent Hashing

**Status:** Implemented  
**Kind:** Core concept  
**Sources:** [Hello Interview — Core concepts](https://www.hellointerview.com/learn/system-design/in-a-hurry/core-concepts) · Alex Xu Vol 1 Ch 5  
**Slug:** `consistent-hashing`

This folder is a **concept lab**, not a product interview. Original notes from the 2026-09-27 session.

It answers: when keys are spread across servers, how does a key pick a server so that adding or removing one server does not move almost every key? One hot key still lands on one server. This does not split that key.

## Variants to know

| Variant | What it is | When it wins | When to skip |
| --- | --- | --- | --- |
| `hash(key) % N` | Remainder picks server `0 … N-1` | Fixed N forever (a small lab, a static shard count you refuse to change) | You will add or remove a node. Most keys change server, about `N/(N+1)` when N grows by one |
| Hash ring | Servers and keys are points on a circle. A key belongs to the **next server clockwise** (wrap to the first) | Cache or KV cluster that grows. Only keys on the arc the new server takes will move | One server. A ring with one node is just “everything lives here” |
| Virtual nodes | Each physical server owns many points on the ring (tens or hundreds) | Even load, and a dead server’s keys scatter to many neighbors instead of one next server. Give a bigger box more points | A handful of keys, or you already use fixed slots (Redis Cluster’s 16384 hash slots are the same idea: stable ownership without a hand-drawn ring) |
| Where it shows up | Distributed cache, Cassandra/Dynamo-style stores, some load balancers and CDNs | The key→node map is the problem | A single Postgres primary (that is a B-tree, not a ring). One Redis for the rate limiter. A hot user is still one key on one node even after you add virtual nodes |

## Interview default

For a **distributed cache** or sharded KV store: hash ring plus virtual nodes. Say `hash % N` only to explain why you are not using it. One hot key stays on one node. Adding a node moves about `1/N` of the keys, the arc that node now owns.

## Pitfalls

- Saying every key moves when one cache node is added. That is the `% N` failure. On a ring, only the neighboring arc moves.
- Expecting virtual nodes to split one hot key. They balance many keys. One key still has one owner.
- A ring with one point per server. Random placement can give one server half the circle.
- Using this for a Postgres primary-key lookup. That index is a B-tree on one machine until you shard.

## Local demo

A FastAPI page with the 0–100 circle (only k2 moves when D is added at 55) and a count of 1000 keys: `hash % N` versus a ring with 100 virtual nodes per server. No database. One hot key is still one owner; this lab does not split a key.

**Cut vs production:** no replication, no real Redis Cluster slots, no weighted capacity beyond “more virtual nodes.”

## How to run

Leave the stack up while you click the two buttons.

```bash
cd core-concepts/consistent-hashing
./scripts/setup.sh
./scripts/run-scenarios.sh
./scripts/run-functional.sh
```

Open http://localhost:8000. Stop later with `./scripts/stop.sh`.

## Session notes

**2026-09-27**

**Q: `% N`, the ring, virtual nodes, where do you use it?**  
A (user): `% N` makes all data move and be recalculated. Adding or removing a server only affects the next data node. Virtual nodes spread data evenly. Use it for a distributed cache.

Taught: `% N` moves **most** keys (about `N/(N+1)` when you add one server), not a special subset. On a ring the key goes to the **next server clockwise**. Only that arc moves. Virtual nodes even out arc sizes and spread a dead server’s keys across many neighbors. Home is a distributed cache or KV cluster, not one Postgres and not one rate-limiter Redis. A hot key is still one owner.

**Q: After D is added at 55, which of k1, k2, k3 move?**  
A (user): only k2.

Taught: k2 at 50 sat in the arc B→C and now stops at D. k1 still reaches B. k3 still wraps to A.

**Close:** User said this was clear. Lab check: k2 is the only example key that moves (C → D). On 1000 keys, 4 servers then a 5th, `hash % N` moved 813 and the ring with 100 virtual nodes moved 236 (about `1/N`). No further questions.
