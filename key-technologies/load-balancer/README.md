# Load Balancer

**Status:** Stub  
**Kind:** Key technology  
**Sources:** [Hello Interview — Key technologies](https://www.hellointerview.com/learn/system-design/in-a-hurry/key-technologies)  
**Slug:** `load-balancer`

This folder is a **concept lab**, not a product interview. The README must explain the idea in your own words (options, when each wins, pitfalls). Prompt this topic by name to fill the notes and, when it helps, a small local demo.

Keep notes original. Link to Hello Interview; cite Alex Xu. Do not paste write-ups.

## What this is

TBD — one or two sentences: what problem this concept solves in a system design interview.

## Variants to know

Fill a row for **each** option below when this topic is practiced. That comparison is the point of the folder.

| Variant | Fill in: what it is, when it wins, when to skip |
| --- | --- |
| DNS / no LB | TBD — one box |
| L4 (TCP) | TBD — fast; sticky for WebSockets |
| L7 (HTTP) | TBD — route by path/host; inspect request |
| Round robin vs least conn | TBD — how work is spread |
| Sticky sessions | TBD — when you must pin a client |
| Health checks | TBD — remove a dead replica |

## Interview default

TBD — what you say first, and when you switch.

## Pitfalls

- TBD

## Local demo

Two identical FastAPI replicas behind nginx; curl in a loop and see both instance ids. Contrast L7 path routing.

**Cut vs production:** TBD after implement.

## How to run

Not implemented yet. After this topic is prompted:

```bash
cd key-technologies/load-balancer
./scripts/setup.sh
./scripts/run-scenarios.sh
./scripts/run-functional.sh
./scripts/stop.sh
```

## Session notes

None yet. Prompt `Load Balancer` to fill this folder.
