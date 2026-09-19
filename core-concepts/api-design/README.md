# API Design

**Status:** Stub  
**Kind:** Core concept  
**Sources:** [Hello Interview — Core concepts](https://www.hellointerview.com/learn/system-design/in-a-hurry/core-concepts)  
**Slug:** `api-design`

This folder is a **concept lab**, not a product interview. The README must explain the idea in your own words (options, when each wins, pitfalls). Prompt this topic by name to fill the notes and, when it helps, a small local demo.

Keep notes original. Link to Hello Interview; cite Alex Xu. Do not paste write-ups.

## What this is

TBD — one or two sentences: what problem this concept solves in a system design interview.

## Variants to know

Fill a row for **each** option below when this topic is practiced. That comparison is the point of the folder.

| Variant | Fill in: what it is, when it wins, when to skip |
| --- | --- |
| REST + HTTP verbs | TBD — interview default for public APIs |
| RPC-style endpoints | TBD — when resource modeling fights you |
| GraphQL (mention only) | TBD — when clients need flexible reads; usually skip in 45 min |
| Offset pagination | TBD — simple; breaks when rows insert in the middle |
| Cursor pagination | TBD — stable for feeds / realtime appends |
| Auth: session / JWT / API key | TBD — users vs service-to-service |
| Idempotency keys | TBD — retries on POST without double writes |
| Rate limiting (pointer) | TBD — full lab lives under questions/rate-limiter |

## Interview default

TBD — what you say first, and when you switch.

## Pitfalls

- TBD

## Local demo

REST endpoints with offset vs cursor pagination on one list resource. Optional API key vs nothing.

**Cut vs production:** TBD after implement.

## How to run

Not implemented yet. After this topic is prompted:

```bash
cd core-concepts/api-design
./scripts/setup.sh
./scripts/run-scenarios.sh
./scripts/run-functional.sh
./scripts/stop.sh
```

## Session notes

None yet. Prompt `API Design` to fill this folder.
