# Distributed Cache

**Status:** Stub  
**Kind:** Key technology  
**Sources:** [Hello Interview — Key technologies](https://www.hellointerview.com/learn/system-design/in-a-hurry/key-technologies)  
**Slug:** `distributed-cache`

This folder is a **concept lab**, not a product interview. The README must explain the idea in your own words (options, when each wins, pitfalls). Prompt this topic by name to fill the notes and, when it helps, a small local demo.

Keep notes original. Link to Hello Interview; cite Alex Xu. Do not paste write-ups.

## What this is

TBD — one or two sentences: what problem this concept solves in a system design interview.

## Variants to know

Fill a row for **each** option below when this topic is practiced. That comparison is the point of the folder.

| Variant | Fill in: what it is, when it wins, when to skip |
| --- | --- |
| Memcached | TBD — simple KV |
| Redis | TBD — default here; many data structures |
| Eviction: LRU / LFU / FIFO / TTL | TBD — what leaves when full |
| Write-through / around / back | TBD — how writes hit cache |
| What you store | TBD — say the structure, not just 'in cache' |
| Core-concepts/caching | TBD — patterns; this folder is the product |

## Interview default

TBD — what you say first, and when you switch.

## Pitfalls

- TBD

## Local demo

Redis: string vs sorted set. LRU eviction (maxmemory). Invalidate one key after a Postgres update.

**Cut vs production:** TBD after implement.

## How to run

Not implemented yet. After this topic is prompted:

```bash
cd key-technologies/distributed-cache
./scripts/setup.sh
./scripts/run-scenarios.sh
./scripts/run-functional.sh
./scripts/stop.sh
```

## Session notes

None yet. Prompt `Distributed Cache` to fill this folder.
