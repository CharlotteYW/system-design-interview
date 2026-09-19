# CAP Theorem

**Status:** Stub  
**Kind:** Core concept  
**Sources:** [Hello Interview — Core concepts](https://www.hellointerview.com/learn/system-design/in-a-hurry/core-concepts)  
**Slug:** `cap-theorem`

This folder is a **concept lab**, not a product interview. The README must explain the idea in your own words (options, when each wins, pitfalls). Prompt this topic by name to fill the notes and, when it helps, a small local demo.

Keep notes original. Link to Hello Interview; cite Alex Xu. Do not paste write-ups.

## What this is

TBD — one or two sentences: what problem this concept solves in a system design interview.

## Variants to know

Fill a row for **each** option below when this topic is practiced. That comparison is the point of the folder.

| Variant | Fill in: what it is, when it wins, when to skip |
| --- | --- |
| Consistency | TBD — all nodes agree on the latest write |
| Availability | TBD — every request gets a (maybe stale) answer |
| Partition tolerance | TBD — network splits happen; you still pick C or A |
| CP vs AP | TBD — refuse vs serve during a split |
| PACELC | TBD — even without a partition: latency vs consistency |
| Eventual vs strong | TBD — feed vs money/inventory/seats |

## Interview default

TBD — what you say first, and when you switch.

## Pitfalls

- TBD

## Local demo

Optional: two app replicas + a toggle that drops the network; show stale read vs 503. Notes-only is OK.

**Cut vs production:** TBD after implement.

## How to run

Not implemented yet. After this topic is prompted:

```bash
cd core-concepts/cap-theorem
./scripts/setup.sh
./scripts/run-scenarios.sh
./scripts/run-functional.sh
./scripts/stop.sh
```

## Session notes

None yet. Prompt `CAP Theorem` to fill this folder.
