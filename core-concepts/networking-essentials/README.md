# Networking Essentials

**Status:** Stub  
**Kind:** Core concept  
**Sources:** [Hello Interview — Core concepts](https://www.hellointerview.com/learn/system-design/in-a-hurry/core-concepts)  
**Slug:** `networking-essentials`

This folder is a **concept lab**, not a product interview. The README must explain the idea in your own words (options, when each wins, pitfalls). Prompt this topic by name to fill the notes and, when it helps, a small local demo.

Keep notes original. Link to Hello Interview; cite Alex Xu. Do not paste write-ups.

## What this is

TBD — one or two sentences: what problem this concept solves in a system design interview.

## Variants to know

Fill a row for **each** option below when this topic is practiced. That comparison is the point of the folder.

| Variant | Fill in: what it is, when it wins, when to skip |
| --- | --- |
| HTTP over TCP | TBD — default request/response; 90% of interviews |
| HTTPS / TLS | TBD — what changes vs plain HTTP in an interview |
| Long polling | TBD — client waits; still HTTP; vs SSE/WS |
| Server-Sent Events (SSE) | TBD — server → client only; one HTTP request then push |
| WebSockets | TBD — true bidirectional; stateful; L4 / sticky sessions |
| gRPC | TBD — internal RPC; HTTP/2 + protobuf; not browser-native |
| L4 vs L7 load balancing | TBD — TCP vs HTTP routing; persistent connections |
| Geography / RTT | TBD — speed of light; why multi-region and CDNs exist |

## Interview default

TBD — what you say first, and when you switch.

## Pitfalls

- TBD

## Local demo

A small FastAPI UI: one HTTP request, one SSE stream, one WebSocket echo. Optional gRPC is out unless we add it. Goal: feel stateful vs stateless connections.

**Cut vs production:** TBD after implement.

## How to run

Not implemented yet. After this topic is prompted:

```bash
cd core-concepts/networking-essentials
./scripts/setup.sh
./scripts/run-scenarios.sh
./scripts/run-functional.sh
./scripts/stop.sh
```

## Session notes

None yet. Prompt `Networking Essentials` to fill this folder.
