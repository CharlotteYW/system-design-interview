# Scaling writes

**Source:** [Hello Interview: Scaling Writes](https://www.hellointerview.com/learn/system-design/patterns/scaling-writes). One of the [seven patterns](https://www.hellointerview.com/blog/patterns).

A **write** changes stored data. This pattern keeps writes correct when one database can no longer take them all. A **shard** is one piece of the data on its own machine. The **shard key** is the value that picks the piece.

## The problem

The web crawler inserts about 23,000 URL rows a second. One Postgres primary cannot take that. An ad click stream is larger. A metrics system is larger still.

A write is harder than a read. The row must land on the one shard that owns that key. Two writers must not create two rows for one key. A burst must not take the database down.

## Options

- **Option A: Stay on one database.** Add CPU, or pick a database that writes faster. Cost: a hard ceiling. Wins while the write rate fits one machine.
- **Option B: Shard by a key that spreads.** A user id, a URL hash, or a click id spreads the rows. A product category does not. One category can hold most of the writes. Cost: a query that is not the shard key must ask every shard. Wins when the write rate is the ceiling and each key is independent.
- **Option C: Put a queue in front of the database.** The API accepts the write and returns. Workers drain the queue. Cost: the row is not visible at once. The queue can grow without bound if workers are slower than the burst. Wins for a short spike, such as a product launch.
- **Option D: Shed load.** Refuse the less important writes when the system is full. Cost: those callers see an error. Wins when a slow system is worse than a refused write. A metrics sample can drop. A payment cannot.
- **Option E: Batch.** Group many small writes into one database call, or roll them up. One minute of clicks becomes one count. Cost: you lose the single events. Wins when the product needs the total, not each event.

We pick A until it fails, then B. We add C for bursts and E when the product can stand a delay. We use D only for data the product can lose.

The shard key in this repo is a hash for the crawler URL table. It is a user id for a chat message. It is a time bucket for metrics.

## What an interviewer probes

- Two shards cannot share one transaction. A transfer from an account on shard 0 to an account on shard 1 is no longer one database write. That problem moves to [multi-step processes](multi-step-processes.md).
- A hot key still burns one shard. A celebrity account does this. Split that key, or cache the read, or give that account its own shard.
- A queue hides a slow database. It does not make the database faster. If the drain rate stays below the arrival rate, the backlog grows forever.

## Questions

| Question | What the write is |
| --- | --- |
| [Unique ID generator](../questions/unique-id-generator/) | Issue ids with no single counter. One counter would be a hot key |
| [Key-value store](../questions/key-value-store/) | The store itself. The partition is the shard |
| [Metrics monitoring](../questions/metrics-monitoring/) | The ingest path. Batch and drop a sample |
| [Ad click aggregation](../questions/ad-click-aggregation/) | A huge click stream. Roll clicks into counts |
| [YouTube Top K](../questions/youtube-top-k/) | Count views as they arrive |

| Question | How it also uses writes |
| --- | --- |
| [Web crawler](../questions/web-crawler/) | About 23,000 URL inserts a second, sharded by hash |
| [Chat system](../questions/chat-system/) | Append a message. The shard key is the chat id |
| [News feed](../questions/news-feed/) | A post write, then fan-out into many feed rows |
| [Instagram](../questions/instagram/) | The same fan-out, at a higher post rate |
| [Notification system](../questions/notification-system/) | One accept, then many delivery rows |
| [Distributed email](../questions/distributed-email/) | One message, then one row per recipient |
| [Live comments](../questions/live-comments/) | A hot post receives comments faster than one shard likes |
| [Stock exchange](../questions/stock-exchange/) | Orders arrive faster than one book machine can match |
| [Distributed message queue](../questions/distributed-message-queue/) | The log of the queue is itself a high-rate write |
| [Object storage](../questions/object-storage/) | The metadata row for each object |
