# System flow — Rate Limiter

## Happy path (under the cap)

```mermaid
flowchart LR
  c[Client]
  mw[Middleware]
  r[Redis_INCR]
  h[Handler]
  c --> mw --> r
  r -->|count_le_limit| h
  h --> ok[200_plus_headers]
```

## Over the cap

```mermaid
flowchart LR
  c[Client]
  mw[Middleware]
  r[Redis_INCR]
  c --> mw --> r
  r -->|count_gt_limit| deny[429_Retry_After]
```

## Allow vs 429 (sequence)

```mermaid
sequenceDiagram
  participant C as Client
  participant M as Middleware
  participant R as Redis
  participant H as Handler
  C->>M: GET /api/ping or POST /api/work
  M->>M: rule from memory identity plus route
  M->>R: INCR key set TTL
  alt over limit
    R-->>M: count
    M-->>C: 429 Retry-After X-RateLimit
  else under or equal
    R-->>M: count
    M->>H: next
    H-->>C: 200 plus headers
  end
```

## Redis down (degraded, not SQL)

```mermaid
sequenceDiagram
  participant C as Client
  participant M as Middleware
  participant R as Redis
  participant L as LocalFixedWindow
  participant H as Handler
  C->>M: request
  M->>R: INCR
  R-->>M: error or timeout
  M->>L: emergency cap in this process
  alt local count over emergency limit
    M-->>C: 429
  else under local cap
    M->>H: allow and log degraded
    H-->>C: product response
  end
```

Emergency limit is **smaller than the global rule** (about global/N). Do **not** `SELECT`/`UPDATE` Postgres to decide 429. A dead region uses this path only; a healthy region still uses Redis.
