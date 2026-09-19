# Database Indexing

**Status:** Stub  
**Kind:** Core concept  
**Sources:** [Hello Interview — Core concepts](https://www.hellointerview.com/learn/system-design/in-a-hurry/core-concepts)  
**Slug:** `database-indexing`

This folder is a **concept lab**, not a product interview. The README must explain the idea in your own words (options, when each wins, pitfalls). Prompt this topic by name to fill the notes and, when it helps, a small local demo.

Keep notes original. Link to Hello Interview; cite Alex Xu. Do not paste write-ups.

## What this is

TBD — one or two sentences: what problem this concept solves in a system design interview.

## Variants to know

Fill a row for **each** option below when this topic is practiced. That comparison is the point of the folder.

| Variant | Fill in: what it is, when it wins, when to skip |
| --- | --- |
| No index / seq scan | TBD — baseline cost |
| B-tree | TBD — equality + range; default in Postgres |
| Hash index | TBD — equality only |
| Composite index | TBD — leftmost prefix; order of columns |
| Covering / INCLUDE | TBD — index-only scans |
| Full-text (GIN / Elasticsearch) | TBD — search vs primary store; CDC lag |
| Geospatial | TBD — PostGIS / geo index; nearby queries |
| Write cost | TBD — every index slows INSERT/UPDATE |

## Interview default

TBD — what you say first, and when you switch.

## Pitfalls

- TBD

## Local demo

Postgres: query with EXPLAIN before/after a B-tree on email or (city, date).

**Cut vs production:** TBD after implement.

## How to run

Not implemented yet. After this topic is prompted:

```bash
cd core-concepts/database-indexing
./scripts/setup.sh
./scripts/run-scenarios.sh
./scripts/run-functional.sh
./scripts/stop.sh
```

## Session notes

None yet. Prompt `Database Indexing` to fill this folder.
