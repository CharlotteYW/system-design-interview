# CAP Theorem

**Status:** Implemented  
**Kind:** Core concept  
**Sources:** [Hello Interview — CAP theorem](https://www.hellointerview.com/learn/system-design/core-concepts/cap-theorem) · Eric Brewer (2000), proved by Gilbert and Lynch (2002) · PACELC: Daniel Abadi (2012) · Alex Xu Vol 1 Ch 6 (quorum on the key-value store)  
**Slug:** `cap-theorem`

This folder is a **concept lab**, not a product interview. Original notes from the 2026-10-01 session.

## What this is

CAP is the rule for a store that runs on more than one machine. During a network split you cannot promise both of these at once:

- every read sees the latest write, and
- every machine that is still up answers the request.

The network split is the partition. Real networks drop packets and cut links, so a design that uses more than one machine already has to live through partitions. The interview choice is what you give up **while the split lasts**.

## The three words

| Word | What it means here | What people confuse it with |
| --- | --- | --- |
| Consistency | A read sees the latest write that was acknowledged, or it gets an error. | ACID “the transaction obeys the rules.” CAP is about **which copy** you read, not about a check constraint. |
| Availability | A machine that has not crashed still returns a response. The response may be old. | “The site is 99.9% up.” A CAP-available node can return a stale seat count and still count as available. |
| Partition tolerance | The system keeps running when messages between machines are lost. | An optional feature. On two or more machines it is the normal failure. |

“Pick two of three” is the slogan. The useful form is: **P is already chosen. During a partition, pick C or A.**

A single server can be consistent and available, because there is no second machine to split from. Its failure mode is different: the machine dies and every request fails. That is the corner people call CA. It is one box, not a cluster that ignores partitions.

## Variants to know

| Variant | What it is | When it wins | When to skip |
| --- | --- | --- | --- |
| CP | During a split, refuse the request if you cannot check the other copies. No stale answer. | Seats, inventory, balances, locks, the one-time-password code. A wrong yes is worse than an error. | A feed or a view counter, where an error on every partition is worse than a number that is a second old. |
| AP | During a split, answer from the copy you still have. Copies can disagree until the link returns. | Feeds, timelines, likes, recommendations, “last seen.” Users would rather see something. | The last concert seat, a bank ledger, a lock. Two sides can both say yes. |
| Quorum (the CP shape we already built) | A write succeeds only after enough copies agree. A read asks enough copies to overlap a write. Our key-value store uses 2 of 3. | One dead replica should not stop the store, and a success must not vanish. | When the partition leaves you with only one of the three. You return an error instead of answering from that one. |
| Eventual consistency | After writes stop, copies converge. No promise about the next read. | AP data: a like count that settles. | Anything where the next read must see the write you just acknowledged. |
| Strong consistency | After a write is acknowledged, a later read sees it. | The CP path: quorum read and write. | When that extra round trip breaks the latency budget and staleness is harmless. |
| PACELC | If there is a **P**artition, choose **A** or **C**. **E**lse (the network is fine), choose **L**atency or **C**onsistency. | Naming the normal-day cost. Waiting for two replicas is slower even when nobody is partitioned. | When the interviewer only asked what happens if the link breaks. Answer CAP first, then PACELC if they ask about latency. |

## A split, in one picture

Two servers both hold “seats left = 1.” The link between them breaks.

- **CP.** The side that cannot confirm the other copy refuses to sell. Some buyers see an error. The last seat is not sold twice.
- **AP.** Each side sells from “1.” Both succeed. When the link returns, one of those sales has to be undone.

The key-value store in this repo is the CP line: a put returns only after 2 of 3 write-ahead logs are on disk. If a partition leaves a coordinator able to reach only one replica, the put errors. The one-second L1 cache in front of that store is the other line: a server that missed the write can still serve the previous value until the TTL. That is a small AP window on top of a CP store.

## Interview default

Say this first: partitions happen, so for **this dataset** we pick consistency or availability while the split lasts.

Ask one question: does the next read have to see the latest write?

- Yes → CP. Quorum, or a single primary and refuse if you cannot reach it.
- No → AP. Answer from the local copy, repair when the link returns.

Most user-facing products mix them. The feed is AP. The payment row is CP. One label for the whole system is the pitfall.

## Pitfalls

- Treating partition tolerance as optional on a multi-machine design.
- Using “available” to mean the uptime percentage. In CAP it means a live node still answers, even with old data.
- Using “consistent” to mean ACID. In CAP it means you do not read an older write than one already acknowledged.
- Calling the whole product CP or AP. The choice is per dataset.
- Forgetting PACELC. CAP is the partition. On a healthy network the same system still chooses between a faster local read and a slower quorum read.

## Local demo

Two replicas in one process. No database: the lesson is the split, not storage. Seats start at 1 and are CP. Likes start at 0 and are AP. **Cut the link**, then sell a seat (503, both copies stay at 1) and like on each side (each copy moves alone). **Restore the link** and the like counts add. A connected seat sale writes both copies.

**Cut vs production:** one process pretends to be the network. There is no third replica, no real packet loss, and no quorum timeout. The 2-of-3 rule is the key-value store chapter. This page shows the same refusal with two copies: a seat needs both.

## How to run

```bash
cd core-concepts/cap-theorem
./scripts/setup.sh
./scripts/run-scenarios.sh
./scripts/run-functional.sh
./scripts/stop.sh
```

## Session notes

### 2026-10-01

**Q: Seats, likes, and the 2-of-3 put — CP or AP?**  
A: Seats are CP. A like count is AP and can be merged later. The key-value put that waits for 2 of 3 is also CP. Success means two copies already have the write, so a later 2-of-3 read overlaps that write. If a split leaves only one replica reachable, the put returns an error instead of accepting a write the other side will not see. Answering from that one replica would be the AP choice. “The store still works when one of three is dead” is uptime. CAP availability would mean answering even when a quorum is impossible.

The lab at `http://localhost:8000` is that split: seat sale refuses, likes record locally and add on heal. Confirmed on 2026-10-02: the page and the tests match that choice.
