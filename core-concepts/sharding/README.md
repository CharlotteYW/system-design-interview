# Sharding

**Status:** Implemented  
**Kind:** Core concept  
**Sources:** [Hello Interview — Sharding](https://www.hellointerview.com/learn/system-design/core-concepts/sharding) · Alex Xu Vol 1 Ch 5 (consistent hashing) and Ch 6 (the key-value ring is sharding by key)  
**Slug:** `sharding`

This folder is a **concept lab**, not a product interview. Original notes from the 2026-10-02 session.

## What this is

Sharding splits one dataset across **several independent databases**. Each shard holds some of the rows. Together they hold all of them.

You do this when one database cannot hold the bytes or cannot take the writes. A read replica helps reads. It does not give you a second place to write, and it does not cut the table in half. The key-value store in this repo is already sharded: the ring sends each key to three servers, not to one shared Postgres.

Partitioning inside one Postgres (a table split into chunks on the same machine) is a smaller tool. It helps a big local scan. It does not add a second machine’s disk or write rate.

## Variants to know

| Variant | What it is | When it wins | When to skip |
| --- | --- | --- | --- |
| One primary, plus read replicas | All writes go to one database. Extra databases serve reads. | The table fits, and writes are the smaller stream. A tuned Postgres handles thousands of simple writes per second and terabytes before you must shard. The key-value chapter’s “12 QPS” case is this. | Writes are the bottleneck, or the table is larger than one machine wants to hold. Replicas copy the whole table. They do not split it. |
| Hash sharding | `shard = hash(shard_key) % N`, or a ring. Rows spread evenly. | The usual interview default once you have justified more than one database. User-scoped reads hit one shard. | You need an ordered scan of a range (“all keys from A to M”) on one machine. Hash scatters that range. |
| Range sharding | Shard 1 holds ids 1–1,000,000, shard 2 holds the next million, or each tenant gets a range. | The query is already a range, or each tenant is naturally isolated. | The newest range gets all the writes (today’s orders, the latest user ids). One shard is hot and the others are idle. |
| Directory / lookup | A small table says “user 42 lives on shard 7.” You can move one user without a formula. | One tenant must move off a hot shard, and you can pay an extra lookup on every request. | The interview default. The lookup is another database that every request needs. If it is down, routing stops. |
| Shard key | The column that picks the shard. `user_id` puts one user’s rows together. `order_id` spreads orders and splits a user’s history. | The key matches the query you do most: “my orders” wants `user_id`. | A key nobody filters on. Every query then asks every shard. |
| Resharding | Adding a shard. `hash % 4` changed to `hash % 5` moves almost every row. A ring moves only the arc the new shard takes. That ring is the consistent-hashing chapter. | You will add machines. Say the ring, or say you accept a big move. | A fixed shard count you will never change. Modulo is enough, and it is simpler. |
| Hot shard | One key, or one tenant, is a large fraction of the traffic. More shards do not move that one key. | Isolate it: a cache in front, or its own shard. The key-value L1 was this idea. | Even traffic. Hashing is enough. |
| Denormalized recent table | On each order write, also store a copy in a small “recent orders” table. The global screen reads that table. | “Every order in the last hour” is a real screen and must not call every shard on each view. | The recent table gets every write. At a very high order rate it becomes the new hot database, and an async copy can be a few seconds behind. |

## A query decides the key

Orders table. The screen people open is “my orders.”

Shard by `user_id`. All of user 42’s orders sit on one shard. That screen is one query.

“Every order placed in the last hour, across all users” has no `user_id`. It must ask every shard and merge the rows. That is the cost of the key that made “my orders” cheap.

Shard by `order_id` instead and the global hour is still a scatter, and “my orders” becomes a scatter too. You made both screens expensive.

## Interview default

Do the capacity math before you shard. If one primary can take the writes and hold the bytes, say so, and add read replicas only if reads are the extra load.

When the numbers do not fit:

1. Name the shard key from the common query (`user_id` for a user’s own rows).
2. Place rows with a hash. Mention the ring if servers will be added, because modulo-N moves almost everything.
3. Say which query now hits every shard.
4. If one user is a celebrity, more shards do not save that shard. Cache that user’s reads, or give them their own shard.

## After the key is chosen

These are the follow-ups once you have already said “one database for now, and `account_id` if we shard later.”

**Adding a machine.** `hash(account_id) % 4` changed to `% 5` sends almost every account to a different shard, because the remainder changes. A consistent-hash ring (already practiced, Vol 1 Ch 5) moves only the arc the new machine takes. Another way to get the same small move is many logical shards (for example 256) mapped onto a few machines. Adding a machine means handing it some of those 256 buckets. The account’s hash does not change.

**A celebrity account.** One account can be a large fraction of traffic and still sit on one shard, because the key is the account id. More shards leave that account where it is. If the traffic is reads, a cache in front of that shard absorbs them. If the traffic is writes, give that account its own shard through a directory entry. A random suffix on the key spreads the writes and forces “my orders” to read every suffix, so it fights the reason you chose `account_id`.

**A write that names two accounts.** “Place my order” stays on one shard. “Move $10 from account 42 to account 7” touches shard0 and shard1. One database transaction cannot cover both machines. The usual interview answer is a saga: debit 42, then credit 7, and undo the debit if the credit fails. Two-phase commit locks both shards until both say yes. It is correct and slow, and it is the wrong default for this order system. Design the common write so it names one account.

**A filter that is not the shard key.** “Orders for this product” has no account id. Scatter-gather works and gets expensive. The same idea as the recent table applies: a second copy sharded by `product_id`, written when the order is placed. You now have two writers to keep in sync.

## Pitfalls

- Sharding because it sounds scalable, before one database is actually full or write-bound.
- Picking a shard key that is not in the common `WHERE` clause.
- Treating read replicas as sharding. Replicas duplicate. Shards divide.
- Using `hash % N` and then adding a shard without a plan for the move.
- Expecting a hot user to cool down because you added machines. That user’s rows still share one shard.
- A transaction that updates two users’ rows. They may be on different shards. The interview answer is to keep one user’s rows together so the common transaction stays on one shard.

## Local demo

One Postgres with three schemas, labeled shard0, shard1, and recent. Even account ids go to shard0. Odd account ids go to shard1. “My orders” reads one schema. Placing an order also writes the recent schema. The hourly button reads only recent. Scatter reads both shards.

The interview answer at 100 writes/s and 50 GB is still one database. The lab forces two shards so the routing is visible.

**Cut vs production:** the schemas share one Postgres process. A real shard is its own machine. The recent write is in the same request, so this demo does not show a lagging async copy.

## How to run

```bash
cd core-concepts/sharding
./scripts/setup.sh
./scripts/run-scenarios.sh
./scripts/run-functional.sh
./scripts/stop.sh
```

## Session notes

### 2026-10-02

**Q: 100 writes/s and 50 GB. Shard? Which key? What does the hourly screen do?**  
A: Do not shard. One primary holds 50 GB and 100 writes/s. If the table later outgrows one machine, shard by `account_id` so “my orders” is one shard. “Every order in the last hour” would otherwise read every shard. A recent-orders table, written when the order is placed, serves that screen from one place. Scatter-gather stays correct and gets expensive as shards are added. The recent table can itself become the hot writer if every order and every viewer use it.

### 2026-10-03

**Q: What is left after the key and the hourly screen?**  
A: Resharding, a hot account, and a two-account write. `hash % N` moves almost every row when N changes; a ring, or 256 logical buckets mapped onto fewer machines, moves only a slice. A celebrity account stays on one shard; cache the reads, or give that account its own shard if the load is writes. A transfer between account 42 and account 7 cannot be one transaction; use a saga (debit, then credit, undo the debit if the credit fails). A filter on `product_id` is another scatter, or another denormalized table sharded by product.

**Q: Are the celebrity account and the two-account write in the README or the FAQ?**  
A: Both are in this README under **After the key is chosen**, and again in the note above. This concept has no FAQ. Confirmed and closed 2026-10-03.
