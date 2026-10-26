# FAQ — Web Crawler

Practice these out loud. Add questions you actually got stuck on. Same five steps as the README.

## 1. Requirements and design scope

**Q: What are the must-have functional requirements?** (2026-10-24)  
A: Crawl from a set of seed URLs, and extract and store each page's text. The purpose, text for training a model, sets the scope. A search crawler would also rank and index pages.

**Q: What scale numbers would you use, and why?** (2026-10-24)  
A: Hello Interview gives 10 billion pages, about 2 MB each to transfer (about 30 KB of HTML), and a 5-day deadline. That works out to:

- about 23,000 pages a second, all the time;
- about 20 PB transferred, about 370 Gbps;
- about 300 TB of HTML and about 100 TB of text (at an assumed 10 KB of text a page).

The 5 days is a deadline for the whole crawl, not a per-request latency.

**Q: How do politeness and the deadline fit together?** (2026-10-24)  
A: At about 1 request a second per domain, 23,000 pages a second means at least 23,000 domains in flight at once. The crawler wins by keeping many domains busy at the same time, never by hitting one domain faster. Politeness also means obeying `robots.txt`: its disallowed paths and its crawl delay.

**Q: What does fault tolerance mean here?** (2026-10-24)  
A: No machine crash loses progress. The progress is the frontier (URLs still to crawl), the set of URLs already seen, and the pages already stored. All three must live in durable stores, not in a fetcher's memory. A fetch can repeat after a crash, so the store write must be idempotent by URL.

**Q: What would you explicitly cut from a 45-minute interview?** (2026-10-24)  
A: Hello Interview's list:

- processing the text (cleaning, training);
- images and video;
- JavaScript-rendered pages;
- pages behind a login;
- security against malicious actors;
- cost;
- legal compliance.

This session also cuts recrawling for freshness, page ranking, and near-duplicate detection.

## 2. High-level design

**Q: Walk through one URL, from the frontier to stored text.** (2026-10-24)  
A:

1. A fetcher takes `{ urlId, url, depth }` from the frontier and checks the domain's `robots.txt` rules (cached in `domains`).
2. It resolves DNS through a cache, sends `GET`, and writes the raw HTML to S3 at `html/{urlId}`.
3. It marks the row `fetched`, puts `{ urlId }` on the parse queue, and only then deletes the frontier message.
4. A parser reads the HTML from S3 and writes the text to `text/{urlId}`.
5. The parser extracts and normalizes the links. Each link gets a conditional insert into `urls`, and only the winner goes into the frontier at depth + 1.

**Q: Why split the crawler into a fetcher and a parser?** (2026-10-24)  
A: A fetch is the step most likely to fail, and the most expensive to repeat. With the HTML stored after the fetch, a parser crash or bug retries from S3, never from the web. Fetching is network-bound and parsing is CPU-bound, so each stage scales on its own. Hello Interview splits the stages the same way.

**Q: Why keep the raw HTML if we only need text?** (2026-10-24)  
A: About 300 TB of HTML is cheap next to a second crawl, which takes another 5 days and 20 PB. If extraction has a bug, or the training team wants image alt text, the parser runs again from S3.

**Q: How do we stop the same URL from being crawled twice?** (2026-10-24)  
A: Normalize each link first (lowercase host, no fragment, no default port, relative paths resolved). Then insert its `urls` row only if it is absent. That is a conditional put keyed by the URL hash. Only a link that wins the insert enters the frontier. Mark the URL as seen when it is queued, not when it is fetched. Otherwise a popular link is queued millions of times while it waits.

**Q: Why these major boxes and not fewer/more?** (2026-10-24)  
A: Two stages, so failures stay small. Two queues carry ids only. One metadata store (`urls` as the seen set, and `domains` for politeness). S3 holds the HTML and the text. DNS gets its own cache because one lookup per domain, not per URL, matters at 23,000 pages a second.

## 3. Low-level design and deep dive

**Q: What is in the data model?** (2026-10-25)  
A: `urls`, keyed by the SHA-256 of the normalized URL, has about 10 billion rows. It holds the URL, domain, depth, state, attempts, last status, S3 keys, content hash, and fetch time. `domains`, keyed by domain, holds the `robots.txt` rules, the crawl delay, and the last fetch time. Both live in a partitioned key-value store. The URL hash is also the queue `urlId` and the S3 key suffix.

**Q: A fetch fails. Retry how, and when do you give up?** (2026-10-25)  
A: Classify the result first:

- **Temporary** (timeout, connection reset, 500, 502, 504): retry.
- **429, or 503 with `Retry-After`:** defer by `Retry-After` and slow the domain. This is not counted as a failure.
- **Permanent** (404, 410, 403): `failed`, with no retry.
- **Redirect:** treat the target as a new link.
- **Disallowed by `robots.txt`:** `skipped`.

Back off as 30 s × 2^(attempt − 1), with jitter. After 5 attempts, the URL goes to the dead-letter queue as `dead`.

**Q: Kafka with retry topics, or SQS?** (2026-10-25)  
A: Retries are a reason for SQS, not for Kafka. Kafka has no per-message delay. It reads each partition in order and commits one offset per partition. A retry chain needs one topic per delay tier, consumers that wait until a message is due, and a dead-letter topic you build yourself (Uber's engineering blog describes this). SQS gives the primitives directly:

- a visibility timeout that returns a message a dead fetcher held;
- `ChangeMessageVisibility` for backoff;
- `ApproximateReceiveCount` for the attempt number;
- a redrive policy (`maxReceiveCount = 5`) that moves a message to the dead-letter queue.

The same per-message delay also serves politeness: "this domain is busy, come back in 1 second." Pick SQS (Hello Interview's pick). Pick Kafka if the team already runs it and accepts building the retry tiers.

**Q: A fetcher crashes mid-page. What is lost?** (2026-10-25)  
A: Nothing, if the order is right:

1. Fetch.
2. Put `html/{urlId}` in S3.
3. Set `state = fetched`.
4. Send the parse message.
5. Delete the frontier message, as the last step.

A crash before step 5 leaves the message, and it becomes visible again after the timeout (60 s, more than the slowest fetch). The next fetcher sees `state = fetched`, skips the fetch, makes sure the parse message exists, and deletes the frontier message. A parser crash is safe too: the text key is overwritten and the link inserts are conditional.

**Q: What is robots.txt, and how do you read it?** (2026-10-25)  
A: It is a text file at `https://site/robots.txt`, standardized in RFC 9309. Groups start with `User-agent:`. Use the group that names your crawler, or else `*`. `Disallow: /private/` forbids paths that start with `/private/`. `Allow:` re-permits a path inside a forbidden one. The longest matching rule wins, a tie goes to `Allow`, and no match means allowed. `Crawl-delay: 10` asks for 10 s between requests. It is not in the RFC, but we obey it.

If fetching `robots.txt` returns 4xx, everything is allowed. If it returns 5xx or a network error, fetch nothing until it can be read. Cache the rules for up to 24 hours. Python's `urllib.robotparser` implements the matching and `Crawl-delay`.

**Q: How do many fetchers keep one domain at 1 request a second?** (2026-10-25)  
A: A last-fetch-time table alone has a race: two fetchers read the same old time and both go. Make the check and the update one atomic claim:

- Redis: `SET politeness:{domain} {fetcherId} NX PX {gap_ms}`.
- Or a conditional update: `UPDATE domains SET next_allowed_at = now + gap WHERE next_allowed_at <= now`.

The gap is `max(1 s, Crawl-delay)`. Only the winner fetches.

**Q: What happens to a URL whose domain is not ready yet?** (2026-10-25)  
A: Do not sleep, because that wastes a fetch slot. Defer it with `ChangeMessageVisibility` (the time left plus up to 30% jitter) and take the next URL. Jitter stops all the waiting fetchers from retrying at the same instant.

Count real failures in `urls.attempts`, not with SQS `ApproximateReceiveCount`. Every deferral raises the receive count and could send a healthy URL to the dead-letter queue.

**Q: Is the Redis `SET NX PX` key a lock per domain? Do we also store the last fetch time in the database?** (2026-10-25)  
A: It is one key per domain, `politeness:{domain}`, meaning "a request was just sent; the next one waits." It works like a time slot, not a lock you release. Nobody deletes it. It expires after the gap (`PX` = 1,000 ms, or 10,000 for `Crawl-delay: 10`). Deleting it early would let the next request go at once. A fetcher that loses reads `PTTL` (milliseconds left) and defers the URL by that much plus jitter.

Keep the timing in one place only. With the Redis claim, Redis is the only source for "may we fetch now," and `domains.next_allowed_at` is not used (it belongs to the database-claim option). Two stores for the same decision could disagree.

The database keeps what must survive a Redis restart: the `robots.txt` rules and `crawl_delay_sec`, which are expensive to fetch again. It can also keep `last_fetch_at` for dashboards, written after the fetch and never read to decide. If Redis restarts, the keys vanish, and each active domain may get one early request. That is harmless, and the next claim restores the spacing. Redis holds only active domains, because keys expire: tens of thousands of small keys, a few MB.

**Q: Where is the "0.7 s plus jitter" stored, and who computes it?** (2026-10-25)  
A: The fetcher's code computes it when it loses the claim, and it is not stored anywhere. The code reads `PTTL` (the ms left on the Redis key), adds a random amount up to 30% of the gap, and calls `ChangeMessageVisibility` with the result. SQS then holds the message hidden until that time, so the queue is the only thing that "remembers" the wait. The fetcher keeps nothing, so a fetcher crash loses nothing.

SQS counts the visibility timeout in whole seconds (0 to 43,200), so 0.7 s rounds up to 1 s. For sub-second spacing, a fetcher could keep the message and re-check from a small in-memory timer, at the cost of holding a worker slot. Option C (one owner per domain) does this cleanly with a local heap.

**Q: When is a shared lock the wrong tool?** (2026-10-25)  
A: When a few domains have millions of URLs. Fetchers then keep receiving and deferring the same messages. The next step is Mercator's design (Alex Xu's back queues): split the frontier by domain, give each domain one fetcher, and let it pop domains from a heap ordered by next allowed time. Also, politeness caps any one domain at 432,000 pages in 5 days, so a 60-million-page site cannot finish. That is accepted.

**Q: Why this storage model over the alternative?** (2026-10-25)  
A: The metadata is about 10 billion small rows, read and written by key, with a conditional insert for dedupe. A partitioned key-value store (DynamoDB, or Cassandra) spreads hash keys evenly and scales out. Page bytes go to S3, because 300 TB of HTML and 100 TB of text are blobs, not rows.

**Q: How many fetcher machines for 10 billion pages in 5 days?** (2026-10-25)  
A: The crawl needs 23,150 pages a second. Per machine, pages a second = bandwidth × utilization / page size.

- At 2 GB/s and 2 MB, one machine does 1,000 pages a second at 100% use. That is 10^7 s (about 116 days), so 20 machines take 5.8 days, which is too slow.
- Real use is about 30% (Hello Interview), because of slow responses, DNS, politeness waits, and retries. That gives 300 pages a second, so about 78 machines.
- Hello Interview's 200 Gbps network-optimized machines at 30% do 3,750 pages a second. That is 6.2 machines, about 10 with headroom.

Each machine holds about 3,750 requests in flight at once with async I/O, each to a different domain. Because only HTML is fetched (about 30 KB), the real bandwidth is far lower. The limit then becomes connections, DNS, and politeness.

**Q: Is a DNS cache enough?** (2026-10-25)  
A: It is the main fix: a local caching resolver plus an in-process map, keyed by domain, kept for the DNS TTL, so all URLs on a domain share one lookup. Add several upstream providers in round robin, so no single provider's rate limit caps the crawl. Optionally resolve a domain when its first URL is queued. Mercator found DNS took up to 70% of thread time before it built its own resolver.

**Q: How do you skip duplicate content?** (2026-10-25)  
A: Hash the extracted text after normalizing whitespace, not the raw HTML. Copies differ in ads and timestamps but not in their text. Use SHA-256. Do a conditional insert into `content_hashes(hash -> first urlHash)`. A hit marks the row `duplicate`, and skips the text and the links. That is about 500 GB for 10 billion rows. A Bloom filter is overkill (Hello Interview), and near-duplicate SimHash is below the line.

**Q: How do you stop crawler traps?** (2026-10-25)  
A: Combine four guards:

- **Depth 20.** Depth is link hops from a seed, not path depth. 5 to 7 is too shallow, because most of the web is within about 15 to 20 links of popular seeds.
- **A per-domain page cap,** for example 100,000.
- **Skip very long URLs** (over about 2,000 characters) and paths that repeat a segment.
- **Strip session and tracking parameters** during normalization.

Each guard catches a trap the others miss.

**Q: Where is the bottleneck as traffic grows?** (2026-10-25)  
A: In order: fetcher concurrency (connections in flight), then DNS, then politeness (enough distinct ready domains), then the metadata store's write rate (about 23,000 conditional inserts a second for URLs, plus as many for content hashes). Parsers are a small CPU fleet that autoscales on queue depth.

## 4. Component questions and special situations

**Q: Redis, the politeness store, is down for 10 minutes. Stop or continue?** (2026-10-25)  
A: Stop, as the session said, but make the outage short. Use a Redis replica with automatic failover, so it takes seconds, and pause fetching for those seconds. 10 minutes is 0.14% of the 5-day budget, and URLs only wait. Never fail open: fetchers sharing a domain would hit it many times a second. For an outage of hours, fall back to a local limit of 1 request per `gap × fetcher count` per domain on each fetcher, which still holds 1 a second in total.

**Q: One huge domain floods the frontier. What then?** (2026-10-25)  
A: With one queue, fetchers keep receiving the big domain's URLs, losing the politeness claim, and deferring them. Deferrals then take most receives, and other domains starve. Politeness also caps that domain at 432,000 pages in 5 days.

- **The session's separate queue for big domains** is a good first bulkhead.
- **The full fix:** limit what each domain may have in the frontier. New URLs wait in `urls` as `pending`, and a scheduler admits at most about 10 per domain, refilling as they finish, up to the page cap. The frontier then always holds many different domains.
- **The step after that:** one queue per domain (Mercator).

**Q: A fetcher machine dies mid-crawl. What is lost?** (2026-10-25)  
A: Nothing. Its about 3,750 in-flight messages were never deleted, so they return after the 60 s visibility timeout. Pages already stored show `state = fetched` and are skipped, and only half-downloaded pages are fetched again. An auto scaling group replaces the machine in minutes. 10 machines where 6.2 are needed absorb the dip.

**Q: Cassandra for the metadata store?** (2026-10-25)  
A: Writes and spreading are fine, because keys are SHA-256 hashes, so there is no hot partition. "Insert only if absent" needs a lightweight transaction (`IF NOT EXISTS`, Paxos, about four round trips), which is slow at tens of thousands a second. Two choices:

- **DynamoDB:** its conditional put is a normal write (Hello Interview's pick).
- **Cassandra with plain writes:** accept a rare double queue. The second fetch sees `state = fetched` and stops.

Dedupe only has to be almost exact, because a repeat fetch is harmless. The one hot read is a big domain's `domains` row, so cache its rules in fetcher memory.

**Q: The deadline is 1 day, or the web is 100 billion pages. What changes first?** (2026-10-25)  
A: Add fetchers, because they scale in a straight line: about 47 machines for 1 day (116,000 pages a second), about 93 for 100 billion pages (231,000 a second). Then handle what follows:

- **About 116,000 ready domains at once:** broad seeds, and the per-domain frontier limit.
- **5 to 10 times the DNS:** more providers, and resolve ahead.
- **5 to 10 times the metadata writes:** more partitions.
- **Fetchers in several regions,** near the sites (Alex Xu).

**Q: Can a Bloom filter dedupe the page text?** (2026-10-25)  
A: It saves memory and loses data. For 10 billion pages:

- 12 GB at 1% false positives, which drops about 100 million unique pages without notice;
- 18 GB at 0.1% (about 10 million);
- 24 GB at 0.01% (about 1 million).

The exact table is about 480 GB, which a partitioned store holds easily. Keep the table (Hello Interview calls the Bloom filter overkill). If table reads become the limit, put a Bloom filter in front of the table. "Definitely new" skips the table read, and "probably seen" is checked in the table, so no unique page is lost.

**Q: Wikipedia has 50 million pages at 1 request a second. How does it finish in 5 days?** (2026-10-25)  
A: It does not. 50 million seconds is about 579 days. 5 days allows at most 432,000 pages, and 116 requests a second would be needed. The options:

- **A:** accept the cap and crawl the most-linked pages first;
- **B:** raise the rate slowly while the server stays healthy;
- **C:** import the bulk dump;
- **D:** cut the URL count with `robots.txt` and URL hygiene (about 7 million are articles).

Pick C for Wikipedia, and A plus D for other big sites. B stays off, because politeness is a hard requirement.

**Q: What exactly is Option C, the per-domain frontier limit?** (2026-10-25)  
A: SQS cannot reorder or show its messages, so most URLs stay out of it. The steps:

1. Parsers insert new links into `urls` as `pending`, and do not send them to SQS.
2. A scheduler admits up to 10 pending URLs for each domain with `in_flight < 10`, until `pages_admitted` reaches the cap.
3. For each admitted URL, the scheduler sets `queued`, adds 1 to `in_flight`, and sends the URL to SQS.
4. A fetcher subtracts 1 when the URL reaches a final state. A deferral does not change `in_flight`.

Wikipedia then has 10 URLs in SQS, not 50 million, and costs about 10 receives a second instead of thousands. If the scheduler stops, the frontier drains, and `pending` rows stay in the table.

**Q: Why is a DynamoDB conditional put (`attribute_not_exists`) a cheap write?** (2026-10-25)  
A: Each key's partition has one leader replica. Every write for that key goes to the leader in order. The leader checks the condition and writes in one step, then waits for two of three replicas. Paxos runs only to elect a leader, not on each write. So the conditional put costs one write unit, like a plain put. A failed check also costs one unit and returns `ConditionalCheckFailedException`, which the parser reads as "seen."

Cassandra has no leader for a key, so `IF NOT EXISTS` runs Paxos on each write, about four round trips. Postgres `ON CONFLICT DO NOTHING` has the same leader property as DynamoDB, so the lab uses it. A small parser cache of recent URL hashes drops repeated menu links before they cost a write.

**Q: Why does the scheduler cut Wikipedia to about 10 receives a second instead of thousands?** (2026-10-25)  
A: Wikipedia's receive rate is the smaller of two limits:

- its share of the visible messages × all receives;
- its message count ÷ 1 s, because a deferred message hides for at least 1 s.

Example: 50 million of 60 million messages are Wikipedia, and fetchers make 23,000 receives a second. Without the scheduler, the share limit is about 19,000 a second, and the count limit is 50 million. So about 19,000 receives a second go to Wikipedia, 1 fetches, and the rest defer. Other domains get only about 4,000 receives a second. With the scheduler, Wikipedia has 10 messages. The count limit is 10 a second: 1 fetch and at most 9 deferrals. Other domains keep about 23,000 receives a second.

**Q: Does the scheduler put the messages into the frontier, and are 9 workers useless until Wikipedia finishes?** (2026-10-25)  
A: Yes, the scheduler is the only writer to the frontier. Parsers write `pending` rows. The scheduler sends at most 10 URLs for each domain to SQS, and refills when a fetcher reports one finished.

No, the workers are not useless. A worker is one async slot of about 37,500 in the fleet, and it does not belong to a domain. A lost claim costs a few milliseconds:

1. a receive;
2. a Redis `SET NX` that returns nil;
3. a `ChangeMessageVisibility`.

Then the worker receives its next message, which is almost always another domain. The waste is at most 9 attempts a second out of about 23,000 receives, about 0.04%. A rate-based limit (about 2 for 1 request a second) cuts it to 1 a second, if the metrics ever show it. **Changed in step 5:** the SQS in-flight quota makes the rate-based limit the pick (see step 5 risks).

**Q: Is the scheduler in the flow charts?** (2026-10-25)  
A: Yes. `final-design-flow.md` has it in the overview and in the crawl sequence. `FLOW.md` keeps the step 2 path, where the parser queues each link, and adds a "Step 4 change" section, where parsers write `pending` rows and the scheduler is the only writer to the frontier.

**Q: Can the lab use DynamoDB, to see the conditional put?** (2026-10-25)  
A: Yes. The lab uses DynamoDB Local (`amazon/dynamodb-local`), which accepts the same `PutItem` and `ConditionExpression` and returns the same `ConditionalCheckFailedException`. A race panel sends one new URL from two parsers at once with three variants: conditional put (one wins), plain put (both win, double queue), and Postgres `ON CONFLICT DO NOTHING` (one row). DynamoDB Local is one process, so it cannot show partitions, replicas, or the leader. Those stay as notes.

**Q: Can the lab use the Bloom filter in front of the table?** (2026-10-25)  
A: Yes. The lab runs Option C (Bloom filter, then a table check on "probably seen") on its main path. The page shows A (table only), B (Bloom only), and C side by side, with their counters. The lab uses a small bit array, so false positives appear with a few hundred pages. The interview default stays A.

**Q: How do you handle a hot key or a single hot partition?** (2026-10-25)  
A: The hot key here is a big domain, not a database key. Its `domains` row is read on every fetch, so cache it in the fetchers. Its URLs flood the frontier, so cap URLs per domain in the frontier with a scheduler. The `urls` and `content_hashes` keys are SHA-256 hashes, which spread evenly.

## 5. Summary and future improvements

**Q: Walk one URL from seed to text.** (2026-10-25)  
A: The session's order was right:

1. The control API inserts the seed into `urls` as `pending`.
2. The scheduler sends it to the SQS frontier.
3. A fetcher checks `robots.txt`, depth, the cap, and the Redis politeness key. It fetches, stores the HTML in S3, marks `fetched`, sends `{ urlId }` to the parse queue, and deletes the frontier message last.
4. A parser hashes the text and puts it into `content_hashes` with a conditional put. A duplicate stops there.
5. Otherwise the parser writes the text to S3, marks `parsed`, and inserts each link as `pending`.

Failures back off at 30 s × 2^(n−1) plus jitter, and go to the dead-letter queue after 5 attempts.

**Q: What are the main tradeoffs?** (2026-10-25)  
A: Each choice and its cost:

- SQS over Kafka: per-message backoff and a built-in dead-letter queue, but no replay and an in-flight quota.
- DynamoDB conditional puts: exact dedupe, but a write unit for each repeated link.
- Keeping HTML: re-parse, but about 300 TB.
- Two stages: separate scaling, but one more queue.
- The Redis politeness key: one shared clock, but fail closed.
- The scheduler: no domain starves the rest, but one more service.
- The exact hash table: no lost page, but 480 GB.

**Q: What are the biggest risks in this design?** (2026-10-25)  
A: The session named harmful text. It is real, but malicious content is below the line, so a filter stage after the parser handles it. The kept HTML lets that stage run again. The design's own risks:

1. **The SQS in-flight quota** (about 120,000 for a standard queue). Deferred messages count. 23,000 busy domains × up to 9 deferred is about 207,000, which breaks the design at the target rate. Fix: a rate-based limit (about 2 for each domain at 1 request a second), plus 4 frontier queues split by domain hash. This changes the step 4 limit of 10.
2. **Politeness failure.** It harms sites and gets the crawler blocked. Fix: fail closed, per-domain error budgets, and back off on 429 and 503.
3. **Too few ready domains** for 23,000 pages a second. Fix: broad seeds, and watch ready domains.

**Q: What would you add with more time?** (2026-10-25)  
A: The session named three, and Hello Interview names four more:

- **Dynamic pages:** a headless browser pool, only for pages whose text is nearly empty, because rendering costs seconds of CPU each.
- **Images and video:** store their URLs, and do not fetch them.
- **Pages behind a login:** skip them, because it needs accounts and breaks terms. Mark a 401 or 403 as `skipped`.
- **Monitoring:**
  - fetches a second;
  - the share of deferrals;
  - errors for each domain;
  - dead-letter queue depth;
  - the age of the oldest message;
  - ready domains.
- **Large files:** the 10 MB cutoff and `Accept: text/html`.
- **Re-crawl:** conditional `GET` with `If-None-Match`, so an unchanged page is a 304.
- **Priority:** the scheduler admits well-linked domains first.

## Local system

**Q: What did the simplified implementation teach you that the diagram did not?** (2026-10-25)  
A: Five things:

1. **SQS visibility counts whole seconds,** so a deferral waits at least 1 s. Every fake site saw about 1 s between requests, even with a 500 ms gap. A domain allowed more than 1 request a second needs a per-domain queue, not deferral.
2. **A GSI doubles the write cost.** A `urls` put that also writes `pending_by_domain` used 2 write units.
3. **With DynamoDB, the Bloom filter saves reads, not writes.** The conditional put already checks and writes in one call. In one crawl, Option C skipped 36 of 50 table reads and caught 4 false positives that Option B would have lost.
4. **A retry must not count against the domain cap again.** The fix is a one-time `admitted` flag on the URL row.
5. **An idempotent re-parse must accept its own hash row** (`first_url_hash = :me`), or a parser crash marks the page a duplicate of itself.

**Q: Is the SQS in-flight quota about too many messages in the queue? Where does 23,000 come from?** (2026-10-25)  
A: Not the queue size. SQS holds an almost unlimited backlog of visible messages. The quota (about 120,000 for each standard queue) is on in-flight messages: received and not deleted. That means a message being fetched, a message hidden after a lost claim, or a message hidden for backoff.

23,000 is not a count of hot pages. 10 billion pages in 5 days is about 23,000 pages a second. At 1 request a second for each domain, at least 23,000 domains must be busy at once.

- **Limit 10:** each busy domain holds up to 9 hidden deferrals, so 207,000 hidden plus up to 37,500 being fetched, about 245,000 in flight.
- **Limit 2:** each domain has 2 messages in SQS. One is being fetched, and at most one is hidden. The one being fetched is already inside the 37,500 worker slots, so it is not added again. At the target rate that is 23,000 hidden + 23,000 fetching, about 46,000. If every worker is busy, it is 23,000 + 37,500, about 60,500.

The other URLs of a domain are `pending` rows in DynamoDB, not SQS messages.

Retries also count. A 450 s backoff with `ChangeMessageVisibility` keeps a URL in flight that long. At an example 1% failure rate, that is about 103,500 in flight. So a retry backoff now sends the body again with `DelaySeconds` and deletes the old message, because a delayed message is not in flight. A short politeness deferral stays `ChangeMessageVisibility`.

The picks: a rate-based limit of 2, 4 queues split by domain hash, and `DelaySeconds` for backoff. The lab does the last one, and its queue card shows retries as "delayed."

**Q: Does the 120,000 in-flight limit mean how many messages the parsers can handle at once? Where does it come from?** (2026-10-25)  
A: It counts something else. The limit applies to each queue. It counts every message that any consumer has received and not deleted. For the frontier, the consumers are the fetcher workers, not the parsers. The count includes messages being fetched, plus messages hidden for a deferral or a retry. The parse queue has its own 120,000. Its in-flight count is only the messages that parsers are working on, a few hundred at most, so it is safe.

The number is a fixed AWS quota for a standard SQS queue ([SQS message quotas](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/quotas-messages.html)). SQS keeps a timer and a receipt handle for every in-flight message, and AWS caps that state for each queue. It is not a limit of our design or of the workers.

When a queue reaches the limit:

- a short-polling receive gets an `OverLimit` error;
- a long-polling receive gets no error and no messages.

Our fetchers use long polling, so the failure is silent. Workers receive nothing, though millions of messages wait. Fetches drop with no error in the logs. Watch `ApproximateNumberOfMessagesNotVisible`. AWS's guidance is to delete messages promptly and to spread the load over more queues, which matches Options B, C, and D. ElasticMQ in the lab does not enforce this limit.

**Q: What goes wrong above 120,000 in flight? Does the fetch worker fail?** (2026-10-25)  
A: The count can never go above 120,000, because SQS stops handing out messages at that point. No worker crashes:

- messages already in flight keep working, and their deletes succeed;
- sends still succeed, so the backlog keeps growing;
- each new receive returns nothing (long polling) or `OverLimit` (short polling).

The harm is idle workers. Example, with a limit of 10 for each domain: hidden deferrals fill about 100,000 of the 120,000 slots. Only about 20,000 slots are left for real fetches, though 37,500 workers wait. About 17,500 workers sit idle, the fetch rate falls by almost half, and the 5-day deadline slips. Nothing in the logs says why. The fix is to keep slots for real work: a limit of 2, 4 queues, and `DelaySeconds` for backoff.

**Q: Millions can wait in the queue, and only 120,000 can be in flight. Is the other 23,000 inside the 37,500?** (2026-10-25)  
A: Yes. Waiting messages have no cap, so the queue can hold millions. In flight means a worker received the message and has not deleted it. That is a fetch in progress, a politeness deferral, or a retry hidden with `ChangeMessageVisibility`. A retry sent again with `DelaySeconds` is delayed, not in flight.

The scheduler admits at most 2 URLs for each domain, not 2 domains. For each of the 23,000 busy domains:

- 1 URL is being fetched. A worker holds it, so it is one of the 37,500.
- At most 1 URL is hidden after a lost claim. No worker holds it.

So 23,000 × 2 = 46,000 messages in SQS, and the fetching half is already inside the worker count. Adding 46,000 on top of 37,500 would count those fetches twice. The worst case is every worker busy: 23,000 hidden + 37,500 fetching = 60,500, still under 120,000.

**Q: Can the lab crawl a real seed URL?** (2026-10-25)  
A: No. Keep the seeds on the fake sites (`kim.test` and the sites it links to). The fetcher resolves the host, then connects to that IP on port 80. The fake sites answer there through Docker network aliases. A real `https://` URL is sent to port 80, so the TLS handshake fails. A real `http://` URL that redirects to HTTPS comes back as 301 or 302, and the lab treats that as a retry, then a dead-letter entry. The lab also follows every new link, up to the depth and the domain cap, so a real seed would send traffic to other people's servers. Use `http://kim.test/`.

**Q: Does 120,000 mean only 120,000 messages can be in the handling state?** (2026-10-25)  
A: The cap is on the sum. A message in flight is in one of three states: a worker is fetching it, it is hidden after a lost politeness claim, or it is hidden for a retry. Handling is the first state. With the limit of 2, the sum is about 46,000: 23,000 being fetched and 23,000 hidden. Both kinds share the same 120,000 slots.

**Q: What does "the count can never go past 120,000" mean, and how does it relate to the worker count?** (2026-10-25)  
A: It is a gate inside SQS, not a property of our workers. At 119,999 in flight, the next receive succeeds and the count becomes 120,000. At 120,000, the next receive returns nothing, so the count stays at 120,000. When one message is deleted, or its hidden time ends, the count drops to 119,999 and one receive can succeed.

The two numbers come from different places:

| | Interview design | Lab |
| --- | --- | --- |
| Workers | About 37,500 async slots, on about 10 machines with about 3,750 connections each | 12 (2 containers × 6 threads) |
| In-flight cap | 120,000 for each standard SQS queue, an AWS quota | ElasticMQ does not enforce it |

If each worker held exactly one message, 37,500 workers would use 37,500 slots, which is under 120,000. The overflow comes from hiding. One worker receives a URL, loses the politeness claim, hides the message, and receives the next one at once. The hidden message keeps its slot. So one worker can hold many slots.

In-flight count ≈ (messages received each second) × (seconds each one stays hidden). The worker count sets the first term. The hide time sets the second. SQS caps the product at 120,000 by refusing the next receive, which also stops workers from creating more hidden messages. At the cap, nearly every slot holds a deferral, and real fetches get only the slots that are left.

**Q: Why did the lab add `attribute_exists` to every DynamoDB update?** (2026-10-25)  
A: `UpdateItem` is an upsert: on a missing key, it creates the item. A worker that was still busy from the previous crawl updated a row that the reset had deleted. It created a row with no `state`, and the state page failed with a 500. With `attribute_exists(url_hash)` in the condition, the update fails, and the worker drops the stale message. The same trap exists in production, for example a row that a cleanup job deleted while a worker still holds its message.

**Q: How much does the scheduler save in the lab?** (2026-10-25)  
A: The same 8 `wiki.test` pages cost 21 receives with the scheduler (limit 2) and 331 without it. In the full crawl with the scheduler off, 81% of all receives were deferrals.

**Q: How does the lab prove politeness?** (2026-10-25)  
A: The fake sites measure it themselves. Each site records the smallest gap between two requests it received. The test checks that every site saw at least 90% of its gap, with 12 workers on 2 fetcher containers sharing one Redis key per domain.
