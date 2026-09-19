# CDN

**Status:** Stub  
**Kind:** Key technology  
**Sources:** [Hello Interview — Key technologies](https://www.hellointerview.com/learn/system-design/in-a-hurry/key-technologies)  
**Slug:** `cdn`

This folder is a **concept lab**, not a product interview. The README must explain the idea in your own words (options, when each wins, pitfalls). Prompt this topic by name to fill the notes and, when it helps, a small local demo.

Keep notes original. Link to Hello Interview; cite Alex Xu. Do not paste write-ups.

## What this is

TBD — one or two sentences: what problem this concept solves in a system design interview.

## Variants to know

Fill a row for **each** option below when this topic is practiced. That comparison is the point of the folder.

| Variant | Fill in: what it is, when it wins, when to skip |
| --- | --- |
| Origin only | TBD — every byte from your region |
| Edge cache for static | TBD — images, JS, video segments |
| Cache API / HTML | TBD — rare; short TTL; invalidation |
| TTL vs purge | TBD — stale vs origin load |
| CloudFront / Cloudflare / Akamai | TBD — names to say |
| Local nginx cache | TBD — teaches hit/miss, not geography |

## Interview default

TBD — what you say first, and when you switch.

## Pitfalls

- TBD

## Local demo

nginx as a caching reverse proxy in Docker (TTL, cache hit header). Cannot mock global PoPs locally — say that in the README.

**Cut vs production:** TBD after implement.

## How to run

Not implemented yet. After this topic is prompted:

```bash
cd key-technologies/cdn
./scripts/setup.sh
./scripts/run-scenarios.sh
./scripts/run-functional.sh
./scripts/stop.sh
```

## Session notes

None yet. Prompt `CDN` to fill this folder.
