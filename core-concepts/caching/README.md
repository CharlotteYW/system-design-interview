# Caching

**Status:** Stub  
**Kind:** Core concept  
**Sources:** [Hello Interview — Core concepts](https://www.hellointerview.com/learn/system-design/in-a-hurry/core-concepts)  
**Slug:** `caching`

This folder is a **concept lab**, not a product interview. The README must explain the idea in your own words (options, when each wins, pitfalls). Prompt this topic by name to fill the notes and, when it helps, a small local demo.

Keep notes original. Link to Hello Interview; cite Alex Xu. Do not paste write-ups.

## What this is

TBD — one or two sentences: what problem this concept solves in a system design interview.

## Variants to know

Fill a row for **each** option below when this topic is practiced. That comparison is the point of the folder.

| Variant | Fill in: what it is, when it wins, when to skip |
| --- | --- |
| No cache | TBD — always hit DB |
| Cache-aside (lazy) | TBD — interview default for reads |
| Write-through | TBD — write cache + DB together |
| Write-back | TBD — faster writes; loss if cache dies |
| TTL + invalidate | TBD — freshness vs extra deletes |
| Stampede / singleflight | TBD — hot key expiry; one loader |
| L1 in-process vs Redis L2 | TBD — per box vs shared |
| CDN (pointer) | TBD — edge/static; see key-technologies/cdn |

## Interview default

TBD — what you say first, and when you switch.

## Pitfalls

- TBD

## Local demo

FastAPI + Redis cache-aside: hit, miss, TTL, invalidate on write. Optional tiny L1 dict.

**Cut vs production:** TBD after implement.

## How to run

Not implemented yet. After this topic is prompted:

```bash
cd core-concepts/caching
./scripts/setup.sh
./scripts/run-scenarios.sh
./scripts/run-functional.sh
./scripts/stop.sh
```

## Session notes

None yet. Prompt `Caching` to fill this folder.
