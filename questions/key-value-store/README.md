# Key-Value Store

**Status:** Stub  
**Sources:** Hello Interview (Distributed Cache); Alex Xu Vol 1 Ch 6  
**Slug:** `key-value-store`

Replace placeholders when preparing this question. Keep notes original; link to Hello Interview / cite Alex Xu instead of copying write-ups.

## Problem

Design a distributed key-value store / cache: get/put/delete, replication, eviction, and handling node failure.

## Requirements

### Functional

- [ ] TBD — gather with the interviewer (or from the prompt)

### Non-functional

- [ ] Scale (QPS, DAU, storage) — put numbers here
- [ ] Latency targets
- [ ] Consistency / availability tradeoff
- [ ] Durability / failure handling

## Core entities

| Entity | Description |
| --- | --- |
| TBD | |

## APIs

Sketch 4–5 endpoints, then move on.

```
POST   /v1/...
GET    /v1/...
```

## High-level design

Summarize the request path and the main stores. Details belong in [FLOW.md](FLOW.md) and [COMPONENTS.md](COMPONENTS.md).

## Data model

Tables / keys / partitions for the hot paths.

## Deep dives

The interesting parts of *this* problem (the ones an interviewer will probe):

1. TBD
2. TBD
3. TBD

## Local implementation

Not implemented yet.

- Setup: `./scripts/setup.sh`
- Scenarios: `./scripts/run-scenarios.sh`

## Interview checklist

- [ ] Requirements and scale numbers stated out loud
- [ ] APIs sketched quickly
- [ ] End-to-end design that actually works
- [ ] One or two deep dives with tradeoffs
- [ ] FAQ practiced out loud
