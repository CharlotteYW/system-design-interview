# Components — Rate Limiter

Each row is a piece you would name on the whiteboard.

| Component | Definition | Functionality in this design |
| --- | --- | --- |
| Client | Browser / HTTP client | Hits UI and `/api/ping`, `/api/work`; shows 429 vs 200 |
| Load balancer | Distributes across app replicas | Optional locally (one app). In interview: many boxes, **same Redis** so caps are global |
| Middleware (gateway stand-in) | Code on the request path before the handler | Identity, rule lookup **in memory**, Redis `INCR`, 429 or `next()`, headers |
| Route handlers | `/api/ping`, `/api/work`, `/api/limiter/me` | Real work **after** allow. Different **rules**, same limiter |
| Redis | In-memory counter store | Fixed-window key `rl:{identity}:{route}:{window_start}`. `INCR` + TTL. One RTT. Not product source of truth |
| Postgres | Product database | **Not** on the check path. Local stack may use it for `/api/work` rows |
| In-process cap | Fixed-window counter in this process when Redis errors | Emergency limit ≈ global/N, not the full global cap. Not the steady-state limiter |
| CDN / WAF | Edge DDoS | **Out of scope** — different layer from app 429s |
| Message queue / worker / object store | Async / blobs | Unused |

## Why these pieces

- **Load-bearing:** middleware + Redis. Without shared Redis, each replica has its own cap.
- **Optional in interview, required in this repo’s local stack:** Postgres for a real DB next to the API, not for `INCR`.
- **Deep dive later:** algorithm (fixed window vs token bucket), Lua for “don’t count 429s,” hot user key.
