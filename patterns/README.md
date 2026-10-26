# Patterns

A **pattern** is a shape that shows up in many designs. Name the shape, then pick among its options. That is faster than inventing a design for every question.

Hello Interview lists seven patterns in [this post](https://www.hellointerview.com/blog/patterns). The [patterns page](https://www.hellointerview.com/learn/system-design/in-a-hurry/patterns) adds an eighth, proximity. This folder has those eight. The notes are original. They link to the source. They do not copy it.

A question uses more than one pattern. The table gives each question one **primary** pattern, the shape to recognize first. The other patterns are real. They are not the headline.

## The eight

| Pattern | The problem in one line | Note |
| --- | --- | --- |
| [Scaling reads](scaling-reads.md) | Too many people read the same data | Start with a better query, then replicas, then a cache |
| [Scaling writes](scaling-writes.md) | Too many people change data | Shard by a key that spreads. Queue a burst |
| [Real-time updates](realtime-updates.md) | The server must speak first | Poll, server-sent events, or a WebSocket. Then pub/sub or a sticky server |
| [Long-running tasks](long-running-tasks.md) | The work outlives the request | Accept, queue, return an id. A worker finishes |
| [Dealing with contention](dealing-with-contention.md) | Many people want one row | One conditional write on one database |
| [Large blobs](large-blobs.md) | The file is too big for the API | The client uploads straight to object storage |
| [Multi-step processes](multi-step-processes.md) | A crash lands between steps | One transaction, a saga, or a workflow engine |
| [Proximity](proximity.md) | "What is near this point?" | Scan a small set, a geohash, or a spatial tree |

## How to use this

Before a question, open its primary note. Read the options and the pick. Then read the "also" rows, so you can name the second pattern if the interviewer asks.

When you practice, say the pattern name out loud before you draw a box. "This seat sale is contention. I start with one conditional update."

## Every question

The order is the [learning path](../README.md). One-time password sits at the end. It is implemented, and it is not on that path.

| # | Question | Primary | Also |
| --- | --- | --- | --- |
| 1 | [Unique ID generator](../questions/unique-id-generator/) | [Scaling writes](scaling-writes.md) | Contention, because one counter would be the hot row |
| 2 | [Rate limiter](../questions/rate-limiter/) | [Contention](dealing-with-contention.md) | Scaling reads, because every call reads the counter |
| 3 | [URL shortener](../questions/url-shortener/) | [Scaling reads](scaling-reads.md) | |
| 4 | [Key-value store](../questions/key-value-store/) | [Scaling writes](scaling-writes.md) | Scaling reads |
| 5 | [Notification system](../questions/notification-system/) | [Long-running tasks](long-running-tasks.md) | Real-time updates, for the phone push |
| 6 | [News feed](../questions/news-feed/) | [Scaling reads](scaling-reads.md) | Scaling writes, for fan-out |
| 7 | [Chat system](../questions/chat-system/) | [Real-time updates](realtime-updates.md) | Scaling writes |
| 8 | [Web crawler](../questions/web-crawler/) | [Long-running tasks](long-running-tasks.md) | Scaling writes, contention, multi-step, large blobs |
| 9 | [YouTube](../questions/youtube/) | [Large blobs](large-blobs.md) | Long-running tasks, multi-step, scaling reads, real-time updates |
| 10 | [Search autocomplete](../questions/search-autocomplete/) | [Scaling reads](scaling-reads.md) | |
| 11 | [Google Drive](../questions/google-drive/) | [Large blobs](large-blobs.md) | Contention, when two devices write one file |
| 12 | [Proximity service](../questions/proximity-service/) | [Proximity](proximity.md) | |
| 13 | [Nearby friends](../questions/nearby-friends/) | [Proximity](proximity.md) | Real-time updates |
| 14 | [Uber](../questions/uber/) | [Proximity](proximity.md) | Real-time updates, contention, multi-step |
| 15 | [Yelp](../questions/yelp/) | [Proximity](proximity.md) | Scaling reads |
| 16 | [Tinder](../questions/tinder/) | [Proximity](proximity.md) | Real-time updates |
| 17 | [Google Maps](../questions/google-maps/) | [Proximity](proximity.md) | Large blobs, scaling reads |
| 18 | [Local delivery](../questions/local-delivery/) | [Proximity](proximity.md) | Multi-step, contention |
| 19 | [Strava](../questions/strava/) | [Proximity](proximity.md) | Scaling reads, large blobs, real-time updates |
| 20 | [Distributed message queue](../questions/distributed-message-queue/) | [Long-running tasks](long-running-tasks.md) | Scaling writes. This question builds the queue |
| 21 | [Job scheduler](../questions/job-scheduler/) | [Long-running tasks](long-running-tasks.md) | |
| 22 | [GitHub Actions](../questions/github-actions/) | [Long-running tasks](long-running-tasks.md) | Multi-step |
| 23 | [Metrics monitoring](../questions/metrics-monitoring/) | [Scaling writes](scaling-writes.md) | Scaling reads, real-time updates |
| 24 | [Ad click aggregation](../questions/ad-click-aggregation/) | [Scaling writes](scaling-writes.md) | Long-running tasks |
| 25 | [YouTube Top K](../questions/youtube-top-k/) | [Scaling writes](scaling-writes.md) | Long-running tasks |
| 26 | [Hotel reservation](../questions/hotel-reservation/) | [Contention](dealing-with-contention.md) | Multi-step |
| 27 | [Ticketmaster](../questions/ticketmaster/) | [Contention](dealing-with-contention.md) | Real-time updates, multi-step |
| 28 | [Flash sale](../questions/flash-sale/) | [Contention](dealing-with-contention.md) | Scaling reads, real-time updates |
| 29 | [Online auction](../questions/online-auction/) | [Contention](dealing-with-contention.md) | Real-time updates |
| 30 | [Distributed email](../questions/distributed-email/) | [Long-running tasks](long-running-tasks.md) | Scaling writes, large blobs, multi-step |
| 31 | [Object storage](../questions/object-storage/) | [Large blobs](large-blobs.md) | Scaling writes |
| 32 | [Gaming leaderboard](../questions/gaming-leaderboard/) | [Scaling reads](scaling-reads.md) | Scaling writes |
| 33 | [Payment system](../questions/payment-system/) | [Multi-step processes](multi-step-processes.md) | Contention |
| 34 | [Donations](../questions/donations/) | [Multi-step processes](multi-step-processes.md) | Scaling reads |
| 35 | [Digital wallet](../questions/digital-wallet/) | [Contention](dealing-with-contention.md) | Multi-step |
| 36 | [Stock exchange](../questions/stock-exchange/) | [Contention](dealing-with-contention.md) | Scaling writes, real-time updates |
| 37 | [Robinhood](../questions/robinhood/) | [Multi-step processes](multi-step-processes.md) | Real-time updates, contention |
| 38 | [Instagram](../questions/instagram/) | [Scaling reads](scaling-reads.md) | Large blobs, scaling writes |
| 39 | [News aggregator](../questions/news-aggregator/) | [Long-running tasks](long-running-tasks.md) | Scaling reads |
| 40 | [Price tracking](../questions/price-tracking/) | [Long-running tasks](long-running-tasks.md) | Real-time updates |
| 41 | [Post search](../questions/post-search/) | [Scaling reads](scaling-reads.md) | |
| 42 | [Food review](../questions/food-review/) | [Scaling reads](scaling-reads.md) | Proximity |
| 43 | [LeetCode](../questions/leetcode/) | [Long-running tasks](long-running-tasks.md) | |
| 44 | [Live comments](../questions/live-comments/) | [Real-time updates](realtime-updates.md) | Scaling writes, contention |
| 45 | [Google Docs](../questions/google-docs/) | [Real-time updates](realtime-updates.md) | Contention |
| 46 | [Online chess](../questions/online-chess/) | [Real-time updates](realtime-updates.md) | Contention |
| 47 | [ChatGPT](../questions/chatgpt/) | [Real-time updates](realtime-updates.md) | Long-running tasks, scaling reads, large blobs, multi-step |
| | [One-time password](../questions/one-time-password/) | [Contention](dealing-with-contention.md) | Long-running tasks, for the send |

## Shapes that are not a ninth pattern

These ideas show up often. Hello Interview folds them into the eight. This repo does the same.

- **Fan-out.** A post is copied into many feed rows. The copy is a write-scaling choice. The home list is then a read.
- **Search rank.** Autocomplete and post search are reads of a prepared index. The index is the cache.
- **Idempotency.** A retry must not do the work twice. It is the safety rule inside contention and inside a multi-step process.
- **Consistent hashing.** A way to pick a shard or a sticky server. It is a [core concept](../core-concepts/consistent-hashing/), used by scaling writes and by real-time updates.
