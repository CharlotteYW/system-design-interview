# System flow — Web Crawler

The crawler has no user-facing API. Each chart runs from the input (seed URLs, or the lab's control API), through the frontier and the two services, into the named store. Hello Interview is the shape source. These notes are original.

## Overview

```mermaid
flowchart LR
  ctl[Control API: start crawl]
  fq[[Frontier queue]]
  fetch[Fetcher service]
  dns[DNS cache]
  web((Web servers))
  meta[(Metadata DB)]
  s3h[(S3 html/)]
  pq[[Parse queue]]
  parse[Parser service]
  s3t[(S3 text/)]
  ctl --> meta
  ctl --> fq
  fq --> fetch --> dns
  fetch --> web
  fetch --> meta
  fetch --> s3h
  fetch --> pq --> parse
  parse --> s3h
  parse --> s3t
  parse --> meta
  parse --> fq
```

## Crawl from seed URLs

```
POST /v1/crawls -> 202 Accepted { crawlId, status }
Body: { seeds, maxPages }

Frontier message -> { urlId, url, depth }
Parse message    -> { urlId }
```

```mermaid
sequenceDiagram
  participant C as Control API
  participant M as Metadata DB
  participant F as Frontier queue
  participant FE as Fetcher
  participant W as Web server
  participant S as S3
  participant P as Parse queue
  participant PA as Parser
  C->>M: insert urls(seed, depth 0, queued) if absent
  C->>F: send { urlId, url, depth: 0 }
  F->>FE: receive URL
  FE->>M: domains row (robots rules)
  alt robots not cached
    FE->>W: GET /robots.txt
    FE->>M: save rules
  end
  alt disallowed
    FE->>M: urls.state = skipped
  else allowed
    FE->>W: GET page
    FE->>S: put html/{urlId}
    FE->>M: urls.state = fetched, html_key
    FE->>P: send { urlId }
  end
  FE->>F: delete message
  P->>PA: receive urlId
  PA->>S: get html/{urlId}
  PA->>PA: extract links, normalize
  loop each new link
    PA->>M: insert urls(link, depth+1) if absent
    alt inserted
      PA->>F: send { urlId, url, depth+1 }
    end
  end
```

## Extract and store the text

```
Parse message -> { urlId }
Output: S3 text/{urlId}, and the urls row (state parsed, text_key, content_hash)
```

```mermaid
sequenceDiagram
  participant P as Parse queue
  participant PA as Parser
  participant S as S3
  participant M as Metadata DB
  P->>PA: receive { urlId }
  PA->>S: get html/{urlId}
  PA->>PA: strip tags, scripts, styles
  PA->>S: put text/{urlId}
  PA->>M: urls.state = parsed, text_key, content_hash
  PA->>P: delete message
```

## Step 4 change: the domain scheduler feeds the frontier

The two charts above are the step 2 path: the parser sends each new link straight to the frontier. Step 4 (situation 2, one huge domain) changes that. The parser and the control API only write `pending` rows. The scheduler is the only writer to the frontier, with at most 10 URLs for each domain in flight. Step 5 lowers that to a rate-based limit (about 2 at 1 request a second), because of the SQS in-flight quota. The final picture is in [final-design-flow.md](final-design-flow.md).

```mermaid
flowchart LR
  ctl[Control API]
  parse[Parser service]
  meta[(Metadata DB: urls pending, domains in_flight)]
  sched[Domain scheduler]
  fq[[Frontier queue]]
  fetch[Fetcher service]
  ctl -->|insert pending| meta
  parse -->|insert pending| meta
  sched -->|read pending by domain, in_flight < 10| meta
  sched -->|send at most 10 per domain| fq
  fq --> fetch
  fetch -->|final state, in_flight - 1| meta
```

```
Scheduler -> frontier message { urlId, url, depth }
Fetcher, on a final state -> urls.state = fetched | failed | skipped | dead, domains.in_flight - 1
```

```mermaid
sequenceDiagram
  participant PA as Parser
  participant M as Metadata DB
  participant SC as Scheduler
  participant F as Frontier queue
  participant FE as Fetcher worker
  participant R as Redis
  PA->>M: insert urls(wiki/11, pending) if absent
  SC->>M: domains(en.wikipedia.org): in_flight = 10
  Note over SC: no room, next domain
  FE->>M: wiki/1 fetched, in_flight 10 -> 9
  SC->>M: in_flight = 9, read 1 pending URL: wiki/11
  SC->>M: wiki/11 queued, in_flight 9 -> 10, pages_admitted + 1
  SC->>F: send { urlId: wiki/11, url, depth }
  F->>FE: receive wiki/11
  FE->>R: SET politeness:en.wikipedia.org NX PX 1000
  alt lost the claim
    FE->>F: ChangeMessageVisibility (1 s to 10 s), in_flight unchanged
    Note over FE: the worker receives its next message, usually another domain
  else won
    FE->>FE: fetch, as in the chart above
  end
```

## Failure path: the parser dies after the fetch

```mermaid
sequenceDiagram
  participant P as Parse queue
  participant PA1 as Parser 1
  participant PA2 as Parser 2
  participant S as S3
  P->>PA1: receive { urlId }
  PA1->>S: get html/{urlId}
  PA1--xPA1: crash before delete
  Note over P: message not deleted, so it becomes visible again
  P->>PA2: receive { urlId }
  PA2->>S: get html/{urlId}
  PA2->>S: put text/{urlId} (same key, safe to repeat)
```

The web server is not asked again. The HTML is already in S3.
