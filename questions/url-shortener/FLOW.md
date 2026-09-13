# System flow — URL Shortener

## Happy path

```mermaid
flowchart LR
  browser[Browser]
  app[FastAPI]
  l1[L1_cache]
  redis[Redis]
  pg[Postgres]
  browser -->|"POST /api/shorten"| app
  app --> pg
  browser -->|"GET /code"| app
  app --> l1
  l1 -->|miss| redis
  redis -->|miss| pg
  app -->|"302 Location"| browser
```

## Write path

```mermaid
sequenceDiagram
  participant C as Client
  participant S as App
  participant D as Postgres
  C->>S: POST /api/shorten url
  S->>S: validate http(s) URL
  S->>S: next snowflake id, code = base62(id)  -- ~11 chars if lossless
  S->>D: insert code, url
  alt code collision
    S->>S: next id and retry
  end
  S->>S: write-through L1 and Redis (ignore Redis errors)
  S-->>C: 200 code plus short_url
```

## Read path

```mermaid
sequenceDiagram
  participant C as Client
  participant S as App
  participant L1 as L1
  participant R as Redis
  participant D as Postgres
  C->>S: GET /code
  S->>L1: get
  alt L1 hit
    L1-->>S: url
    S-->>C: 302 Location url
  else L1 miss
    S->>R: get
    alt Redis hit
      R-->>S: url
      S->>L1: set
      S-->>C: 302 Location url
    else Redis miss
      S->>S: singleflight load by code
      S->>D: select by code
      alt postgres down
        D-->>S: error
        S-->>C: 503
      else found
        D-->>S: url
        S->>R: set
        S->>L1: set
        S-->>C: 302 Location url
      else missing
        S-->>C: 404
      end
    end
  end
```

## Failure / overload path

- Postgres down: create → 503; redirect cache hit → 302; redirect cache miss → **503** (not 404).
- Redis down: create still 200 if Postgres is up (write-through skipped); redirect uses L1 then Postgres.
- Hot key / 10× redirects: serve from L1/Redis; **one DB fill per code** via singleflight on miss.
