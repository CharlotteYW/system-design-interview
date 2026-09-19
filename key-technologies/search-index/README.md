# Search Index

**Status:** Stub  
**Kind:** Key technology  
**Sources:** [Hello Interview — Key technologies](https://www.hellointerview.com/learn/system-design/in-a-hurry/key-technologies)  
**Slug:** `search-index`

This folder is a **concept lab**, not a product interview. The README must explain the idea in your own words (options, when each wins, pitfalls). Prompt this topic by name to fill the notes and, when it helps, a small local demo.

Keep notes original. Link to Hello Interview; cite Alex Xu. Do not paste write-ups.

## What this is

TBD — one or two sentences: what problem this concept solves in a system design interview.

## Variants to know

Fill a row for **each** option below when this topic is practiced. That comparison is the point of the folder.

| Variant | Fill in: what it is, when it wins, when to skip |
| --- | --- |
| LIKE / table scan | TBD — why it does not scale |
| Inverted index | TBD — term → posting list of docs |
| Tokenize / stem | TBD — running vs run |
| Fuzzy / edit distance | TBD — typos |
| Elasticsearch | TBD — interview default for serious search |
| PG FTS / GIN | TBD — smaller footprint; good local lab |

## Interview default

TBD — what you say first, and when you switch.

## Pitfalls

- TBD

## Local demo

Postgres FTS (tsvector/GIN) on a documents table vs LIKE '%term%'. Elasticsearch only if we add a container later.

**Cut vs production:** TBD after implement.

## How to run

Not implemented yet. After this topic is prompted:

```bash
cd key-technologies/search-index
./scripts/setup.sh
./scripts/run-scenarios.sh
./scripts/run-functional.sh
./scripts/stop.sh
```

## Session notes

None yet. Prompt `Search Index` to fill this folder.
