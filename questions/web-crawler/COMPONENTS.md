# Components — Web Crawler

| Component | Definition | Functionality in this design |
| --- | --- | --- |
| Seed loader / control API | The input | Inserts seed `urls` rows at depth 0. In step 2 it sends them to the frontier. After step 4 it writes them as `pending`, and the domain scheduler sends them |
| Frontier queue | Durable queue of URLs to crawl | Holds `{ urlId, url, depth }`. Gives a URL back if its fetcher dies. SQS, picked in deep dive 1 for per-message visibility and backoff |
| Fetcher service | Network-bound workers | Checks `robots.txt` from the `domains` table, resolves DNS through a cache, sends `GET`, writes raw HTML to S3, and puts the URL id on the parse queue |
| DNS resolver and cache | Name lookups | Caches each domain's IP, so millions of URLs on one site make one lookup |
| Parse queue | Durable queue between the stages | Holds `{ urlId }`. The HTML stays in S3 |
| Parser service | CPU-bound workers | Extracts text to S3, extracts and normalizes links, and inserts new URLs with a conditional put. In step 2 it queues each new URL. After step 4 it only writes `pending` rows |
| Metadata DB | Partitioned key-value store (DynamoDB, or Cassandra without lightweight transactions) | `urls` (state, depth, S3 keys, content hash), `content_hashes` (content dedupe), and `domains` (robots rules, crawl delay, pages admitted) |
| Redis | Politeness store | One key per domain, `politeness:{domain}`, set with `NX PX gap`. The winner fetches. A replica takes over on failure |
| Domain scheduler | Frontier feeder (from step 4), the only writer to the frontier | Reads `pending` URLs by domain. Sends a domain's URLs only while its `in_flight` is under its rate-based limit (about 2 at 1 request a second; 10 in the step 4 sketch, changed in step 5 for the SQS in-flight quota) and `pages_admitted` is under the cap. Fetchers lower `in_flight` when a URL reaches a final state. One huge domain cannot starve the rest |
| S3 `html/` | Object store | Raw HTML, kept so extraction can run again without a refetch |
| S3 `text/` | Object store | The output: extracted text per page |

## Why these pieces

- Two stages, so a parse failure never refetches a page, and network-bound and CPU-bound work scale separately.
- All progress is durable: the frontier, the `urls` rows (the seen set), and S3. A fetcher or parser can die at any moment.
- Queue messages carry ids only. Pages of 30 KB to 2 MB stay in S3.
- The conditional insert on `urls` is the dedupe. Each URL enters the frontier once, even when many pages link to it.
