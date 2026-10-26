# Final design flow — Web Crawler

Redraw this at the end. Interview sequences stay in [FLOW.md](FLOW.md). Component roles stay in [COMPONENTS.md](COMPONENTS.md). Hello Interview is the shape source. These notes are original.

## Overview

The crawler is a pipeline. The control API (the lab's input) puts seeds in. A per-domain scheduler feeds the frontier. Fetchers download, parsers extract, and durable stores keep all progress. Boxes marked `shock` come from the step 4 situations.

```mermaid
flowchart LR
  ctl[Control API]
  sched[Domain scheduler: shock, rate-based limit per domain]
  fq[[Frontier: 4 SQS queues by domain hash]]
  dlq[[Dead-letter queue]]
  fetch[Fetcher service x10]
  dns[DNS cache + several providers]
  redis[(Redis: politeness keys, replica on failover)]
  web((Web servers))
  meta[(Metadata DB: urls, domains, content_hashes)]
  s3h[(S3 html/)]
  pq[[Parse queue]]
  parse[Parser service, autoscaled]
  s3t[(S3 text/)]
  ctl --> meta
  ctl --> sched
  sched --> meta
  sched --> fq
  fq --> fetch
  fq -.-> dlq
  fetch --> redis
  fetch --> dns
  fetch --> web
  fetch --> meta
  fetch --> s3h
  fetch --> pq --> parse
  parse --> s3h
  parse --> s3t
  parse --> meta
```

## Crawl from seed URLs

```
POST /v1/crawls -> 202 Accepted { crawlId, status }
Body: { seeds, maxPages }

Frontier message -> { urlId, url, depth }
```

```mermaid
sequenceDiagram
  participant C as Control API
  participant M as Metadata DB
  participant SC as Scheduler
  participant F as Frontier (SQS)
  participant FE as Fetcher
  participant R as Redis
  participant W as Web server
  participant S as S3
  participant P as Parse queue
  C->>M: insert urls(seed, depth 0, pending) if absent
  SC->>M: pick pending URLs, in_flight under the domain's rate-based limit (about 2 at 1 req/s)
  SC->>F: send { urlId, url, depth }
  F->>FE: receive
  FE->>M: domains row (robots rules, cached in memory)
  alt disallowed, too deep, or domain cap reached
    FE->>M: state = skipped
  else allowed
    FE->>R: SET politeness:{domain} NX PX gap
    alt lost the claim
      FE->>F: ChangeMessageVisibility(PTTL + jitter, whole seconds)
    else won
      FE->>W: GET (Accept text/html, stop past 10 MB)
      alt 200
        FE->>S: put html/{urlId}
        FE->>M: state = fetched
        FE->>P: send { urlId }
        FE->>F: delete message
      else temporary failure
        FE->>M: attempts + 1
        FE->>F: send same body, DelaySeconds = 30 s x 2^(attempt-1) + jitter
        FE->>F: delete the old message
      else permanent failure
        FE->>M: state = failed
        FE->>F: delete message
      end
    end
  end
```

## Extract and store the text

```
Parse message -> { urlId }
Output: S3 text/{urlId}, urls.state = parsed or duplicate, new links inserted and scheduled
```

```mermaid
sequenceDiagram
  participant P as Parse queue
  participant PA as Parser
  participant S as S3
  participant M as Metadata DB
  P->>PA: receive { urlId }
  PA->>S: get html/{urlId}
  PA->>PA: extract text, normalize whitespace, SHA-256
  PA->>M: insert content_hashes(hash) if absent
  alt hash already exists
    PA->>M: state = duplicate (skip text and links)
  else new content
    PA->>S: put text/{urlId}
    PA->>M: state = parsed, text_key, content_hash
    loop each link (normalized, tracking params stripped)
      PA->>M: insert urls(link, depth+1, pending) if absent
    end
  end
  PA->>P: delete message
```

## Services

| Name | When it runs | What it does |
| --- | --- | --- |
| Control API | At crawl start, and for status | Inserts seed rows. Reports pages fetched, frontier size, and domains |
| Domain scheduler | Continuously | Moves `pending` URLs into the frontier, up to a rate-based limit for each domain (about 2 at 1 request a second), up to the domain page cap. Sends to one of 4 frontier queues by domain hash, to stay under the SQS in-flight quota |
| Fetcher service | Always, about 10 machines with async I/O | `robots.txt` check, depth and cap check, Redis politeness claim, DNS through the cache, `GET`, HTML to S3, retries with backoff, parse message |
| Parser service | Always, autoscaled on the parse queue | Text extraction, content-hash dedupe, link extraction and normalization, conditional URL inserts |
| DNS cache | On every fetch | Local caching resolver, plus several upstream providers |
| Redis | On every fetch | Holds `politeness:{domain}` keys with a TTL of the gap. A replica takes over on failure |

## Databases

### Metadata DB (DynamoDB, or Cassandra without lightweight transactions)

`urls`, key `url_hash`: `url`, `domain`, `depth`, `state` (pending, queued, fetched, parsed, duplicate, skipped, failed, dead), `attempts`, `http_status`, `last_error`, `html_key`, `text_key`, `content_hash`, `fetched_at`. About 10 billion rows, about 1 TB.

`content_hashes`, key `hash`: `first_url_hash`. About 480 GB.

`domains`, key `domain`: `robots_rules`, `crawl_delay_sec`, `robots_fetched_at`, `robots_status`, `in_flight` (URLs now in the frontier, under the rate-based limit), `pages_admitted` (for the cap), and `last_fetch_at` (dashboards only).

Index `pending_by_domain`, key `(domain, url_hash)` for rows with `state = pending`. The scheduler reads the next N pending URLs of one domain from this index.

New URLs are written with `PutItem` and `attribute_not_exists(url_hash)`. The lab runs the same call on DynamoDB Local.

### Redis

| Key | Value | TTL |
| --- | --- | --- |
| `politeness:{domain}` | The fetcher id that claimed the slot | The gap: 1 s, or the `Crawl-delay` |

### SQS

| Queue | Message | Settings |
| --- | --- | --- |
| Frontier, 4 queues split by domain hash | `{ urlId, url, depth }` | Visibility timeout 60 s. A politeness deferral (about 1 s) uses `ChangeMessageVisibility`. A retry backoff sends the body again with `DelaySeconds` and deletes the old message, because a delayed message is not in flight (quota about 120,000 for each queue). `maxReceiveCount` 100 as a safety net. Real failures counted in `urls.attempts` |
| Parse | `{ urlId }` | Visibility timeout 60 s. A dead-letter queue for HTML that keeps failing |

### S3

| Key | Holds |
| --- | --- |
| `html/{urlHash}` | Raw HTML, kept for re-extraction |
| `text/{urlHash}` | Extracted text, the output |

Interview sequences are in [FLOW.md](FLOW.md). Component roles are in [COMPONENTS.md](COMPONENTS.md).
