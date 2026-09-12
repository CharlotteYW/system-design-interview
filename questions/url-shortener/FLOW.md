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
  S->>D: select by url
  alt already exists
    D-->>S: existing code
  else new
    S->>S: code = base62(sha256(salt:url))[:7]
    S->>D: insert code, url
    alt code collision
      S->>S: salt += 1 and retry
    end
  end
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
  else L1 miss
    S->>R: get
    alt Redis hit
      R-->>S: url
      S->>L1: set
    else Redis miss
      S->>D: select by code
      alt found
        D-->>S: url
        S->>R: set
        S->>L1: set
      else missing
        S-->>C: 404
      end
    end
  end
  S-->>C: 302 Location url
```

## Failure / overload path

- Postgres down: create → 503; redirect cache hit → 302; redirect cache miss → 503.
- Redis down: create unchanged; redirect uses Postgres.
- Hot key / 10× redirects: serve from L1/Redis; one DB fill on miss.
