# Components — URL Shortener

| Component | Definition | Functionality in this design |
| --- | --- | --- |
| Browser / UI | HTML page served by the app | Paste a long URL, show the short link, follow it |
| App (FastAPI) | Stateless HTTP service | Validates URLs, generates codes, reads/writes mappings, issues 302s |
| L1 cache | In-process dict, small cap | Hottest codes skip Redis/Postgres on this instance |
| Redis (L2) | Shared in-memory KV | Shared redirect cache across app processes |
| Postgres | Relational source of truth | Stores `code` PK → `url`; unique `url` for idempotent create |

## Why these pieces

- **Load-bearing:** UI, API, Postgres. Without them there is no product.
- **Deep dive:** Redis + L1. Needed to explain 10× redirects and hot keys; included locally so the idea is concrete.
- **Not in the local system:** CDN, load balancer farm, shards, analytics pipeline.
