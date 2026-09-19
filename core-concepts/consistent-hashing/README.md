# Consistent Hashing

**Status:** Stub  
**Kind:** Core concept  
**Sources:** [Hello Interview — Core concepts](https://www.hellointerview.com/learn/system-design/in-a-hurry/core-concepts)  
**Slug:** `consistent-hashing`

This folder is a **concept lab**, not a product interview. The README must explain the idea in your own words (options, when each wins, pitfalls). Prompt this topic by name to fill the notes and, when it helps, a small local demo.

Keep notes original. Link to Hello Interview; cite Alex Xu. Do not paste write-ups.

## What this is

TBD — one or two sentences: what problem this concept solves in a system design interview.

## Variants to know

Fill a row for **each** option below when this topic is practiced. That comparison is the point of the folder.

| Variant | Fill in: what it is, when it wins, when to skip |
| --- | --- |
| hash(key) % N | TBD — add a node → almost all keys remap |
| Hash ring | TBD — key → next node clockwise |
| Virtual nodes | TBD — smoother load; more ring points per server |
| Where it shows up | TBD — Redis Cluster, Cassandra, some LBs, CDNs |

## Interview default

TBD — what you say first, and when you switch.

## Pitfalls

- TBD

## Local demo

A Python ring with virtual nodes: add/remove a node and print how many keys move vs hash % N.

**Cut vs production:** TBD after implement.

## How to run

Not implemented yet. After this topic is prompted:

```bash
cd core-concepts/consistent-hashing
./scripts/setup.sh
./scripts/run-scenarios.sh
./scripts/run-functional.sh
./scripts/stop.sh
```

## Session notes

None yet. Prompt `Consistent Hashing` to fill this folder.
