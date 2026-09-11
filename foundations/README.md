# Foundations

Study these before (or alongside) the first product questions. This page is a **checklist with source links**, not a copy of those materials.

Read the sources, then practice explaining each item in your own words. When a later question uses a concept, link back here from that question's `COMPONENTS.md` or `README.md`.

## Interview delivery

Practice every question in this order (see `.cursor/rules/06-interview-pattern.mdc`):

1. Requirements and design scope
2. High-level design
3. Low-level design and deep dive
4. Component questions and special situations (10x traffic, rush hour)
5. Summary and future improvements

Then **implement a simplified local system**.

Source reading:

- [ ] [Hello Interview: Introduction](https://www.hellointerview.com/learn/system-design/in-a-hurry/introduction) — what interviewers assess
- [ ] [Hello Interview: How to prepare](https://www.hellointerview.com/learn/system-design/in-a-hurry/how-to-prepare)
- [ ] [Hello Interview: Delivery framework](https://www.hellointerview.com/learn/system-design/in-a-hurry/delivery)
- [ ] Alex Xu, *System Design Interview* Vol 1, Ch 3 — 4-step framework

## Scale and estimation

- [ ] Alex Xu Vol 1, Ch 1 — scale from zero to millions of users
- [ ] Alex Xu Vol 1, Ch 2 — back-of-the-envelope estimation
- [ ] Numbers you will actually say: QPS, storage, bandwidth, machines

## Core concepts

From [Hello Interview: Core concepts](https://www.hellointerview.com/learn/system-design/in-a-hurry/core-concepts) (and the [quick reference](https://www.hellointerview.com/learn/system-design/in-a-hurry/core-concepts/quick-reference)):

- [ ] Networking and protocol choice (HTTP, SSE, WebSockets, gRPC)
- [ ] API design (REST defaults, pagination, auth)
- [ ] Data modeling (relational vs NoSQL, normalize vs denormalize)
- [ ] Indexing
- [ ] Caching
- [ ] Sharding
- [ ] Consistent hashing
- [ ] Consistency, CAP / PACELC

## Key technologies

From [Hello Interview: Key technologies](https://www.hellointerview.com/learn/system-design/in-a-hurry/key-technologies). Pick **one example you can defend** in each category:

- [ ] Relational database (default: Postgres)
- [ ] NoSQL / key-value (default local mock: Redis)
- [ ] Blob / object storage
- [ ] Cache
- [ ] Message queue
- [ ] Load balancer / API gateway
- [ ] Search index
- [ ] CDN

## Common patterns

From [Hello Interview: Patterns](https://www.hellointerview.com/learn/system-design/in-a-hurry/patterns):

- [ ] Pushing realtime updates
- [ ] Managing long-running tasks
- [ ] Dealing with contention
- [ ] Scaling reads
- [ ] Scaling writes
- [ ] Handling large blobs
- [ ] Multi-step processes
- [ ] Proximity-based services

## How this feeds questions

Starter questions in `questions/` map roughly to:

| Concept / pattern | First question to practice it |
| --- | --- |
| Hash IDs, redirects, read-heavy APIs | [URL shortener](../questions/url-shortener/) |
| Counting, windows, 429s | [Rate limiter](../questions/rate-limiter/) |
| Unique IDs at scale | [Unique ID generator](../questions/unique-id-generator/) |
| Caching, replication, eviction | [Key-value store](../questions/key-value-store/) |
| Queues, fan-out, retries | [Notification system](../questions/notification-system/) |
| Fan-out on write vs read | [News feed](../questions/news-feed/) |
| WebSockets, presence, ordering | [Chat system](../questions/chat-system/) |
| Blobs, transcoding, CDN | [YouTube](../questions/youtube/) |
| Crawling, politeness, frontier | [Web crawler](../questions/web-crawler/) |
| Geo, matching, locks | [Uber](../questions/uber/) |
