# System flow — Search Autocomplete

The read path and the record path are different speeds. The read uses yesterday's snapshot. The record only appends. Alex Xu Volume 1, chapter 13, is the shape source. These notes are original.

## Overview

```mermaid
flowchart LR
  client[Client]
  lb[Load balancer]
  gw[API gateway]
  query[Query service]
  build[Daily builder]
  pg[(Postgres: searches, suggestions)]
  client --> lb --> gw --> query
  gw --> pg
  build --> pg
  query -.->|load snapshot, not each request| pg
```

## Return the top suggestions

```
GET /v1/suggestions?q=ki&limit=5 -> 200 { suggestions: [{ text, frequency }] }
```

```mermaid
sequenceDiagram
  participant C as Client
  participant LB as Load balancer
  participant G as API gateway
  participant Q as Query service
  participant P as Postgres suggestions
  C->>LB: GET /v1/suggestions?q=ki
  LB->>G: forward
  G->>Q: q=ki, limit=5
  Note over Q: memory map, loaded from suggestions
  Q-->>C: 200, first 5 of the stored top 10
```

The arrow from the query service to Postgres is not on this request. The service loaded `suggestions` at startup and after each daily build.

## Record a finished search

```
POST /v1/searches -> 202 Accepted { status }
Body: { query }
```

```mermaid
sequenceDiagram
  participant C as Client
  participant LB as Load balancer
  participant G as API gateway
  participant P as Postgres searches
  participant B as Daily builder
  participant Q as Query service
  C->>LB: POST /v1/searches { query: kitchen }
  LB->>G: forward
  G->>P: insert searches(kitchen, now)
  G-->>C: 202
  Note over B: once a day
  B->>P: count searches, replace suggestions
  Q->>P: load the new snapshot into memory
```

## Failure path: the builder does not finish

```mermaid
sequenceDiagram
  participant B as Daily builder
  participant P as Postgres
  participant Q as Query service
  participant C as Client
  B->>P: start a new suggestions snapshot
  B--xB: crash before the snapshot is published
  Note over P: yesterday's suggestions stay the published set
  C->>Q: GET /v1/suggestions?q=ki
  Q-->>C: 200, yesterday's top 5
```

Kim still gets a list. The frequencies are one more day old. The `searches` rows she added are still in the log for the next build.
