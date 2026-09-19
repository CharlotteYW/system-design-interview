# Sharding

**Status:** Stub  
**Kind:** Core concept  
**Sources:** [Hello Interview — Core concepts](https://www.hellointerview.com/learn/system-design/in-a-hurry/core-concepts)  
**Slug:** `sharding`

This folder is a **concept lab**, not a product interview. The README must explain the idea in your own words (options, when each wins, pitfalls). Prompt this topic by name to fill the notes and, when it helps, a small local demo.

Keep notes original. Link to Hello Interview; cite Alex Xu. Do not paste write-ups.

## What this is

TBD — one or two sentences: what problem this concept solves in a system design interview.

## Variants to know

Fill a row for **each** option below when this topic is practiced. That comparison is the point of the folder.

| Variant | Fill in: what it is, when it wins, when to skip |
| --- | --- |
| Single primary + replicas | TBD — do this before sharding |
| Hash sharding | TBD — even spread; default |
| Range sharding | TBD — time or tenant ranges; hotspot risk |
| Directory / lookup | TBD — flexible; extra hop |
| Shard key choice | TBD — user_id vs other; cross-shard queries |
| Resharding | TBD — why modulo-N hurts; consistent hashing pointer |
| Hot shard | TBD — celebrity / tenant skew |

## Interview default

TBD — what you say first, and when you switch.

## Pitfalls

- TBD

## Local demo

Two Postgres databases hashed by user_id. Show a user-scoped read (one shard) vs a global scan (both).

**Cut vs production:** TBD after implement.

## How to run

Not implemented yet. After this topic is prompted:

```bash
cd core-concepts/sharding
./scripts/setup.sh
./scripts/run-scenarios.sh
./scripts/run-functional.sh
./scripts/stop.sh
```

## Session notes

None yet. Prompt `Sharding` to fill this folder.
