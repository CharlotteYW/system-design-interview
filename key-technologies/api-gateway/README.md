# API Gateway

**Status:** Stub  
**Kind:** Key technology  
**Sources:** [Hello Interview — Key technologies](https://www.hellointerview.com/learn/system-design/in-a-hurry/key-technologies)  
**Slug:** `api-gateway`

This folder is a **concept lab**, not a product interview. The README must explain the idea in your own words (options, when each wins, pitfalls). Prompt this topic by name to fill the notes and, when it helps, a small local demo.

Keep notes original. Link to Hello Interview; cite Alex Xu. Do not paste write-ups.

## What this is

TBD — one or two sentences: what problem this concept solves in a system design interview.

## Variants to know

Fill a row for **each** option below when this topic is practiced. That comparison is the point of the folder.

| Variant | Fill in: what it is, when it wins, when to skip |
| --- | --- |
| Reverse proxy as gateway | TBD — nginx / Caddy locally |
| Managed (API Gateway, Kong, Apigee) | TBD — what interviewers picture |
| Routing | TBD — path → service |
| Cross-cutting | TBD — auth, rate limit, logging |
| vs load balancer | TBD — gateway is L7 policy; LB is spreading |

## Interview default

TBD — what you say first, and when you switch.

## Pitfalls

- TBD

## Local demo

nginx or a FastAPI facade: route /users to service A and /orders to service B; optional API-key check.

**Cut vs production:** TBD after implement.

## How to run

Not implemented yet. After this topic is prompted:

```bash
cd key-technologies/api-gateway
./scripts/setup.sh
./scripts/run-scenarios.sh
./scripts/run-functional.sh
./scripts/stop.sh
```

## Session notes

None yet. Prompt `API Gateway` to fill this folder.
