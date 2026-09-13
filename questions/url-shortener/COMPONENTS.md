# Components — URL Shortener

| Component | Definition | Functionality in this design |
| --- | --- | --- |
| Browser / UI | HTML page served by the app | Paste a long URL, show the short link, follow it |
| App (FastAPI) | Stateless HTTP service | Validates URLs, mints Snowflake ids, base62-encodes `code`, INSERT/SELECT, 302s, singleflight on redirect miss |
| Snowflake | In-process 64-bit id generator | Time + worker + sequence; one `WORKER_ID` locally; uniqueness backed by `UNIQUE(code)` |
| L1 cache | In-process LRU, small cap | Hottest codes skip Redis/Postgres on this instance |
| Redis (L2) | Shared in-memory KV | Shared redirect cache; optional on create (write-through, ignore errors) |
| Postgres | Relational source of truth | `code` PK → `url` (**url not unique**); `updated_at` / `expires_at` unused |

## Why these pieces

- **Load-bearing:** UI, API, Postgres. Without them there is no product.
- **Deep dive:** Redis + L1 + singleflight. Needed to explain 10× redirects and hot keys; included locally so the idea is concrete. Snowflake lives in the app, not a separate service.
- **Not in the local system:** CDN, load balancer farm, shards, analytics pipeline, Redis lock across processes.
