# Data Modeling

**Status:** Stub  
**Kind:** Core concept  
**Sources:** [Hello Interview — Core concepts](https://www.hellointerview.com/learn/system-design/in-a-hurry/core-concepts)  
**Slug:** `data-modeling`

This folder is a **concept lab**, not a product interview. The README must explain the idea in your own words (options, when each wins, pitfalls). Prompt this topic by name to fill the notes and, when it helps, a small local demo.

Keep notes original. Link to Hello Interview; cite Alex Xu. Do not paste write-ups.

## What this is

TBD — one or two sentences: what problem this concept solves in a system design interview.

## Variants to know

Fill a row for **each** option below when this topic is practiced. That comparison is the point of the folder.

| Variant | Fill in: what it is, when it wins, when to skip |
| --- | --- |
| Relational (Postgres) | TBD — structured data, relationships, transactions |
| NoSQL document / KV | TBD — access-pattern first; fewer joins |
| Normalization | TBD — one source of truth; joins on read |
| Denormalization | TBD — duplicate for a hot read path; update fan-out |
| Access-pattern design | TBD — know the queries before the keys |

## Interview default

TBD — what you say first, and when you switch.

## Pitfalls

- TBD

## Local demo

Postgres: normalized tables vs one denormalized read table. Show a join vs a single-row read.

**Cut vs production:** TBD after implement.

## How to run

Not implemented yet. After this topic is prompted:

```bash
cd core-concepts/data-modeling
./scripts/setup.sh
./scripts/run-scenarios.sh
./scripts/run-functional.sh
./scripts/stop.sh
```

## Session notes

None yet. Prompt `Data Modeling` to fill this folder.
