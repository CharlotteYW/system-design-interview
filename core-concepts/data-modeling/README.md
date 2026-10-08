# Data Modeling

**Status:** Implemented  
**Kind:** Core concept  
**Sources:** [Hello Interview — Data Modeling](https://www.hellointerview.com/learn/system-design/core-concepts/data-modeling) · Alex Xu, *System Design Interview*, Vol. 1, Ch. 11 (the news feed copies a post into each follower inbox)  
**Slug:** `data-modeling`

This folder is a **concept lab**, not a product interview. Original notes from the 2026-10-06 session.

Keep notes original. Link to Hello Interview. Cite Alex Xu. Do not paste write-ups.

## What this is

Data modeling chooses the store, the tables, and the key for each query. In an interview you name those three choices. Then you move on.

A **primary key** identifies one row. A **foreign key** points at a row in another table. An **access pattern** is the query an API must answer.

## Variants to know

| Variant | What it is | When it wins | When to skip |
| --- | --- | --- | --- |
| Postgres | Tables, foreign keys, and one transaction around a write. | Users, posts, likes, and orders. This is the interview default. | The write rate or the bytes no longer fit one machine. Say that limit first. |
| Document | One JSON object. Related rows sit inside it. | One screen always loads one object, and the fields change often. | A feed mixes many authors. You would load many documents, or you would copy each post again. |
| Key-value | A value for one exact key. Redis is the usual store. | A cache, a session, or a hot counter. | You need "who liked this" and you stored only a count. Add a key per question, or keep the rows in Postgres. |
| Wide column | Rows for one **partition key**, sorted by time. Cassandra is the usual store. | Append-only events at a very high write rate. | A normal social app. Postgres plus an index answers the same range. |
| Graph | Nodes and edges as the main store. | The product is the hop itself, and the interviewer asks for it. | Follows, likes, and friends. Two joins in Postgres answer a short hop. |
| Columnar | Values of one column sit together. The scan sums that column. | A report such as messages per city per day. | The path that sends a chat message. That write wants a row store. |
| Time-series | Rows chunked by time. The read is a time range. | A count per minute, or a metric. | A user account. Time is not the main key. |
| Search | An inverted index maps a word to the rows that contain it. | Find messages that contain one word. | A lookup by id. A key-value get is the smaller tool. |
| Normalized | Each fact lives in one place. The author name lives on the user. | The name can change. One update fixes every screen. | The hot read cannot pay for the join. Then copy the field. |
| Denormalized | A copy of a fact sits on the row you read. | The read is most of the QPS, and the copied fact changes rarely. | The copied fact changes often. The repair touches every copy. |
| Access pattern | You name the query, then you choose the key and the index. | Every table in the interview. | A key that no API filters on. Every read then asks every machine. |

## Interview default

1. Say Postgres for users, posts, and likes.
2. Keep each fact in one table. Name the primary key and the foreign key.
3. Add an index on `(user_id, created_at)` for recent posts of one user.
4. Copy a field only after you name the hot read and the cost of a later update.
5. Put Redis in front of a hot count. Postgres stays the source of truth.
6. Shard by `user_id` only when one Postgres is full. The sharding lab covers the split.

## Your three choices

**Store.** Postgres for the user and for the post is the right start. A key-value store for every like is a second step. A like is a pair `(user_id, post_id)`. One Postgres table answers the count, the list of people, and "did this user like it." Redis answers a hot count. The count can lag by a short time. A bare counter grows on a double click. A member key stops that second increment.

**Copied name.** The read becomes one table, and that part is true. A username change must update every copy. One missed copy shows two names. Keep the name on the user until the feed read is the hot path and name changes are rare.

**Partition.** `user_id` is the right key for recent posts of that user. The first tool is the index, on one Postgres. Extra app servers still send that user to the same database. A read replica adds read capacity for that shard. The write stays on the primary. Salt adds a number to a hot key so the writes spread. The read then asks every salt bucket and merges the rows. Salt fits a counter you never list in time order. It fights a timeline.

## After the first schema

These are the probes after the tables are chosen.

**A username change.** Ada has two posts. The user row says `ada_new`. Each `post_copies` row still says `ada` until you update it.

| Option | What happens | When it wins |
| --- | --- | --- |
| Do nothing | The join reads the user row. The name is always current. | Name changes happen, and the feed QPS is moderate. |
| Copy, then fan out | One rename updates every post copy and every inbox row. | The feed is the hot read, and a rename is rare. |
| Copy, and allow a lag | The user row updates now. A job fixes the copies. | A few seconds of the old name is acceptable. |

This lab keeps the user row as the source of truth. The button that leaves the copies shows the stale name. The other button updates the two copies in the same step.

**A celebrity user.** Nova is user 7. `7 % 4` is shard 3. All eight posts sit there. Four app servers still call shard 3.

| Option | What happens | When it wins |
| --- | --- | --- |
| Do nothing | One shard holds the user. | That shard can take the reads and the writes. |
| Read replica | Reads can use the replica. Writes stay on the primary. | The celebrity is read-heavy. |
| Cache the timeline | The hot read hits the cache. Postgres stays behind it. | One user is a large fraction of the QPS. |
| Salt | Writes spread. The timeline read merges every bucket. | The hot key is a counter, not an ordered list. |

For this interview, keep `user_id` and add a cache for the celebrity. Skip salt on a timeline. The sharding chapter has the same hot key.

**A home feed.** Bob follows Ada and Nova. The screen is not "posts of one author." Ada is on shard 1. Nova is on shard 3.

| Option | What happens | When it wins |
| --- | --- | --- |
| Fan-out on read | The read asks each author shard and merges the posts. | Bob follows a few people. The merge is small. |
| Fan-out on write | Each new post is copied into Bob's inbox. His read is one query. | The home screen is the hot read. The copy can lag. |
| Do nothing | There is no home screen. Each profile reads one `user_id`. | The product is a profile, not a merged feed. |

Alex Xu's news feed chapter uses the inbox copy. This lab shows both. The inbox partition key is the reader, because the query is "Bob's feed."

**A short graph hop.** Ada follows Bob. Bob follows Nova. Two joins return Nova. The edges stay in Postgres. Add a graph database only when the interviewer makes the hop the product.

## What we implemented

The page at `http://localhost:8000` shows the variants side by side.

| Control | What you see |
| --- | --- |
| Copied author name | A rename updates `users`. The copies stay old, or you update both copies. |
| Likes | A second Postgres like returns the first row. A member key increments once. A bare counter increments again. |
| Partition key | Nova's posts stay on shard 3. Salt splits the read. Extra app servers still use shard 3. |
| Home feed | Bob's feed scatters across shard 1 and shard 3, or reads one inbox on shard 2. |
| Graph hops | Ada to Bob to Nova, with two joins in Postgres. The Graph button reads the same hop from Neo4j. |
| Eight types | One click reads the live engine. You see the use, the structure, the storage, the industry names, and the rows. |

**Cut vs production:** one engine runs for each type. MySQL, Oracle, SQL Server, DynamoDB, RocksDB, Couchbase, Firestore, ScyllaDB, HBase, Snowflake, BigQuery, Redshift, DuckDB, Neptune, JanusGraph, InfluxDB, Prometheus, OpenSearch, and Solr are named on the page and do not start here. The four chat shards in `partition_map` are still a formula. The [sharding](../sharding/) lab splits real databases.

## How to run

```bash
cd core-concepts/data-modeling
./scripts/setup.sh
./scripts/run-scenarios.sh
./scripts/run-functional.sh
./scripts/stop.sh
```

## Session notes

**Q: What do "Copied author name" and the sections below it demonstrate?**  
A: The tabs choose the database type. The lower sections lay out the data inside PostgreSQL. Copied author name is normalization against denormalization. Likes is a composite key with a cache beside it. Partition key is the index and the shard key from the access pattern. Home feed is the query that the key does not serve. Graph hops is a graph in PostgreSQL. The first three test your first answer.

**Q: The old "Show Postgres, document, and key-value" button returned `Not Found`. Why?**  
A: The browser showed a cached copy of the old page. That button called `/api/stores`, and the server no longer has that address. A hard reload fetched the new page. The page now sends `Cache-Control: no-store`, so a normal reload gets the latest version.

**Q: Why does one section still show PostgreSQL, a document, and key-value together? Add a summary table above the tabs.**  
A: The old "Three stores" section put those three types in one box. That section is gone. Each type now appears only in its own tab. A summary table above the tabs lists each engine, when to say it in the interview, and the requirement.

**Q: Give each database type its own tab, with the data shape, a write, a read, and the interview requirement.**  
A: Each tab is one engine. The picture shows the shape: a row, a key, a document, a partition, columns, an edge, a time bar, or a word index. Run the write sends one statement to that Docker engine. Run the read returns the rows. The interview line names the requirement that makes you choose that type. PostgreSQL stays the default.

**Q: Run each database type, and show the data shape, the storage, the fitting use, and the industry names.**  
A: The page lists eight types. One engine runs for each type: PostgreSQL, Redis, MongoDB, Cassandra, ClickHouse, Neo4j, TimescaleDB, and Elasticsearch. A click shows the common use, the structure, the storage, the industry list, and a live sample. A WeChat account stays in Postgres. A like count stays in Redis. Chat messages for one conversation stay in Cassandra. A word search stays in Elasticsearch. The interview default is still Postgres.

**Q: Postgres for users and posts, a key-value store for likes, copy the author name, and partition by user id with extra servers and salt?**  
A: Postgres is the default for the user, the post, and the like. Redis is a second copy of a hot count, and a member key stops a double click. The author name stays on the user until the feed is the hot read. Then a rename must update every copy. `user_id` plus an index serves recent posts of one user. Extra app servers do not move that user. A read replica adds read capacity. Salt spreads a counter and splits a timeline, so this design skips salt for the timeline.
