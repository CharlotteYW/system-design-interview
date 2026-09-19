# Numbers to Know

**Status:** Stub  
**Kind:** Core concept  
**Sources:** [Hello Interview — Core concepts](https://www.hellointerview.com/learn/system-design/in-a-hurry/core-concepts)  
**Slug:** `numbers-to-know`

This folder is a **concept lab**, not a product interview. The README must explain the idea in your own words (options, when each wins, pitfalls). Prompt this topic by name to fill the notes and, when it helps, a small local demo.

Keep notes original. Link to Hello Interview; cite Alex Xu. Do not paste write-ups.

## What this is

TBD — one or two sentences: what problem this concept solves in a system design interview.

## Variants to know

Fill a row for **each** option below when this topic is practiced. That comparison is the point of the folder.

| Variant | Fill in: what it is, when it wins, when to skip |
| --- | --- |
| Memory vs disk vs network | TBD — ns / µs / ms gaps |
| In-DC vs cross-continent RTT | TBD — 1–10ms vs ~80ms+ NY–London |
| Redis ops/s vs DB TPS | TBD — when cache or replicas beat sharding |
| Single Postgres size / TPS | TBD — when sharding is actually justified |
| Queue / broker throughput | TBD — back-of-envelope for buffers |

## Interview default

TBD — what you say first, and when you switch.

## Pitfalls

- TBD

## Local demo

Notes-only. Recite and use the table in a decision (shard or not, one Redis or not). No Docker unless you want a tiny bench.

**Cut vs production:** TBD after implement.

## How to run

Not implemented yet. After this topic is prompted:

```bash
cd core-concepts/numbers-to-know
./scripts/setup.sh
./scripts/run-scenarios.sh
./scripts/run-functional.sh
./scripts/stop.sh
```

## Session notes

None yet. Prompt `Numbers to Know` to fill this folder.
