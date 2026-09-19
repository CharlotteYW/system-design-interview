# NoSQL Database

**Status:** Stub  
**Kind:** Key technology  
**Sources:** [Hello Interview — Key technologies](https://www.hellointerview.com/learn/system-design/in-a-hurry/key-technologies)  
**Slug:** `nosql-database`

This folder is a **concept lab**, not a product interview. The README must explain the idea in your own words (options, when each wins, pitfalls). Prompt this topic by name to fill the notes and, when it helps, a small local demo.

Keep notes original. Link to Hello Interview; cite Alex Xu. Do not paste write-ups.

## What this is

TBD — one or two sentences: what problem this concept solves in a system design interview.

## Variants to know

Fill a row for **each** option below when this topic is practiced. That comparison is the point of the folder.

| Variant | Fill in: what it is, when it wins, when to skip |
| --- | --- |
| Key-value | TBD — Redis / DynamoDB simple item |
| Document | TBD — MongoDB; flexible schema |
| Wide column | TBD — Cassandra; write-heavy |
| Graph | TBD — relationships as first class; rare in 45 min |
| Partition + sort key | TBD — design for the query you have |
| Consistency knobs | TBD — strong vs eventual on that product |

## Interview default

TBD — what you say first, and when you switch.

## Pitfalls

- TBD

## Local demo

Redis hashes or a tiny document JSON in Postgres JSONB as a stand-in. Show partition-key style lookup vs a scan.

**Cut vs production:** TBD after implement.

## How to run

Not implemented yet. After this topic is prompted:

```bash
cd key-technologies/nosql-database
./scripts/setup.sh
./scripts/run-scenarios.sh
./scripts/run-functional.sh
./scripts/stop.sh
```

## Session notes

None yet. Prompt `NoSQL Database` to fill this folder.
