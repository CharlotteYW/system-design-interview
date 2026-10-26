# High-level design comparison — Web Crawler

Read this file on the next pass. It compares the stores, the high-level path, and each feature. It does not replace [README.md](README.md).

The columns are Hello Interview (Web Crawler), Alex Xu volume 1 chapter 9 (Design a Web Crawler), this session, and production. Production cites public sources only. A store that no public source names stays "not in a cited source."

## Database choice

| Data | Hello Interview | Alex Xu, chapter 9 | This session | Production |
| --- | --- | --- | --- | --- |
| Frontier (URLs to crawl) | A queue. Kafka, Redis, or SQS at first. SQS chosen, for retries and deferral | A URL frontier: front queues for priority, back queues for politeness, one back queue per host | SQS holding `{ urlId, url, depth }`, with a visibility-timeout backoff and a dead-letter queue after 5 attempts (deep dive 1) | Mercator (1999): per-host FIFO subqueues on disk, so each host is crawled by one thread. Uber: Kafka retry topics plus a dead-letter topic, for retries on Kafka |
| Seen URLs | URL table in the metadata DB (DynamoDB, or Postgres or MySQL) | "URL seen?" with a Bloom filter or a hash table | `urls` in a partitioned key-value store, with a conditional insert keyed by the URL hash | Mercator: a disk-based seen-URL set with an in-memory cache |
| Domain state (robots.txt, last fetch) | Domain table in the metadata DB, and Redis for the per-domain lock and rate limit | A robots.txt cache in the downloader. Politeness by one back queue per host | `domains` in the metadata DB (rules, crawl delay, `next_allowed_at`), and a Redis `SET NX PX` claim per fetch | RFC 9309: cache robots.txt for at most 24 hours, 4xx means allow all, 5xx means disallow all |
| Raw HTML | S3 blob storage | Content storage, on disk, with popular content in memory | S3 `html/{urlHash}` | Common Crawl: WARC files on S3 |
| Extracted text | S3 blob storage | Not in that source as its own store | S3 `text/{urlHash}` | Common Crawl: WET files (extracted plain text) on S3 |
| Content hashes | A hash column with an index in the metadata DB. A Bloom filter as the other option | "Content seen?" by comparing hashes | `content_hash` on `urls`, deep dive 3 | Not in a cited source |
| DNS | A cache in the crawlers, and several DNS providers | A DNS cache | A DNS cache in the fetcher | Mercator: a custom DNS resolver, because lookups had taken up to 70% of a thread's time |

## High-level design choice

| Source | Boxes on the happy path | How work moves |
| --- | --- | --- |
| Hello Interview | Frontier queue, URL fetcher, HTML in S3, parse queue, text and URL extraction, text in S3, metadata DB, DNS, Redis for politeness | Two stages joined by a queue. Messages carry the URL id |
| Alex Xu, chapter 9 | Seed URLs, URL frontier, HTML downloader with DNS resolver, content parser, content seen, link extractor, URL filter, URL seen, URL storage | One loop. The frontier's back queues enforce politeness per host |
| This session | Frontier queue, fetcher service, DNS cache, metadata DB, S3 `html/`, parse queue, parser service, S3 `text/` | Two stages joined by a queue. Messages carry the URL id. The conditional insert dedupes links |
| Production | Mercator: per-host queues, one host per thread, a custom DNS resolver. Common Crawl publishes WARC, WAT, and WET files | Not in a cited source as one diagram |

## Crawl from seed URLs

1. Seeds go into the frontier.
2. A fetcher checks robots.txt, resolves DNS, and fetches.
3. The parser finds links, dedupes them, and queues the new ones.

| Source | Steps that differ | Store |
| --- | --- | --- |
| Hello Interview | Dedupe by checking the URL table before queueing. SQS visibility timeout for retries and deferral | Queue, DynamoDB, S3, Redis |
| Alex Xu, chapter 9 | The frontier routes each host to one back queue, so a worker never hits one host twice at once | Queues, URL storage, Bloom filter |
| This session | Normalize the link, then a conditional insert keyed by the URL hash. Only the winner is queued | Queue, key-value store, S3 |

## Extract and store the text

1. The parser reads the raw HTML.
2. It keeps the visible text.
3. It stores the text and records where it is.

| Source | Steps that differ | Store |
| --- | --- | --- |
| Hello Interview | The HTML is kept in S3, so extraction can change without a refetch | S3, metadata DB |
| Alex Xu, chapter 9 | The content parser validates pages. "Content seen?" drops duplicates before storage | Content storage |
| This session | `text/{urlHash}` in S3, with `content_hash` on the row | S3, key-value store |

## What this session keeps

- 10 billion pages in 5 days, about 23,000 pages a second (Hello Interview's numbers).
- Two stages and two queues, with ids only in the messages.
- Raw HTML kept: about 300 TB against a 20 PB recrawl.
- The seen set as a conditional insert in a partitioned key-value store, about 1 TB at about 100 bytes a row.
- The happy path is closest to Hello Interview. Alex Xu's per-host back queues are the option for politeness in deep dive 2.

## Sources

- Hello Interview, "Design a Web Crawler": https://www.hellointerview.com/learn/system-design/problem-breakdowns/web-crawler
- Alex Xu, *System Design Interview* volume 1, chapter 9, "Design a Web Crawler."
- Allan Heydon and Marc Najork, "Mercator: A Scalable, Extensible Web Crawler," World Wide Web, 1999.
- Common Crawl, data formats (WARC, WAT, WET): https://commoncrawl.org/get-started
- Uber Engineering, "Building Reliable Reprocessing and Dead Letter Queues with Apache Kafka": https://www.uber.com/blog/reliable-reprocessing/
- RFC 9309, "Robots Exclusion Protocol" (2022): https://www.rfc-editor.org/rfc/rfc9309.html
