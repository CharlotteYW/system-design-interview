# High-level design comparison — News Feed

Read this file on the next pass. It compares the database, the high-level path, and every feature. It does not replace [README.md](README.md).

The columns are Hello Interview, Alex Xu volume 1 chapter 11, this session, and production. Production uses a named public post or talk. A store that source does not name stays "not in that source."

## Database choice

This table is the database choice for each kind of data. The feature sections below repeat the store next to the steps.

| Data | Hello Interview | Alex Xu, chapter 11 | This session | Facebook, 2015 Multifeed post | Twitter public notes |
| --- | --- | --- | --- | --- | --- |
| Post text | DynamoDB. The post id is the key. A second index uses the author id and the time. | A post database. The feed cache stores the post id, not the full post. The chapter does not name one SQL brand. | Postgres table `posts`. | An in-memory leaf index of recent actions, plus persistent logs. | A tweet store. A 2017 note names Manhattan as a real-time backing store. It does not say Manhattan is the only tweet database. |
| Image and video bytes | Not in that source. The core post is the record above. | Named as part of a post. The chapter does not name a file bucket. | S3. The Postgres row stores the links. | Not in that source. | A 2017 note lists a blob store among Twitter's storage systems. |
| Follow edge | DynamoDB. The follower id is the partition key. The followee id is the sort key. A second index reverses the pair. A later flag on that row marks a follow that stays out of the precomputed feed. | A graph database. The fan-out service reads friend ids from it. | Postgres table `follows`. One pair. The famous mark sits on `users.famous`. | The post says the system looks up friends. It does not name the graph store. | FlockDB, a graph store on sharded MySQL. Named in the 2017 infrastructure note. |
| Home list | A feed table of post ids, about 200 per user, in the later path. The first path has no home list. It queries posts. | A news-feed cache of post ids. | No home list on the happy path. The read queries `posts`. An inbox appears at 5,000 reads per second. | No prebuilt inbox in that post. Leaves hold each person's recent actions. | A timeline cache of tweet ids. A 2017 note names the Redis-family cache Haplo. |
| Like pair | Not in that source. A like is below the line. | Not in that source. The chapter teaches fan-out. | Postgres table `likes`. The key is user id plus post id. | Not in that source. | Not in the timeline talks cited here. |
| Like count | Not in that source. | Not in that source. | A column on the post. Redis holds it when one post is hot, then writes it back. | Not in that source. | Not in the timeline talks cited here. |
| Comment | Not in that source. A comment is below the line. | Not in that source. | Postgres table `comments`, under one post. | Not in that source. | Not in the timeline talks cited here. |
| User | A user id from the session. The breakdown does not design a user table. | A user store beside the post store. The chapter does not name the brand. | Postgres table `users`. | Not in that source. | Not in the timeline talks cited here. |

This session puts the rows in one Postgres database. Hello Interview puts the post and the follow in DynamoDB. Chapter 11 splits the friend list into a graph database and the home ids into a cache. Facebook's published Multifeed path keeps recent actions in memory leaves. Twitter's published notes split the graph, the timeline cache, and a blob store.

## High-level design choice

| Source | Boxes on the happy path | What publish does before it returns |
| --- | --- | --- |
| Hello Interview | An API gateway, stateless hosts, and DynamoDB. A queue and workers appear when the feed is prebuilt. | Insert the post. The first path stops there. The later path enqueues a copy onto follower feeds. |
| Alex Xu, chapter 11 | A load balancer, web servers, a fan-out service, a news-feed service, a notification service, a queue, and a cache. | Save the post. Send friend ids and the post id to the queue. Workers write the cache. A celebrity skips that copy. |
| This session | A load balancer, a gateway, and five services: Post, Follow, Like, Comment, and Feed. Postgres and S3. A queue, a worker, and Redis are shock boxes. | Upload the file. Post service inserts one row. No queue on the happy path. At 5,000 reads per second, Post service adds one job and the worker writes inbox rows. |
| Facebook, 2015 | An aggregator, memory leaves, and a tailer. | The tailer sends the new action into the leaves. The rank runs on the read. |
| Twitter timeline talks | A fan-out path into follower timelines, and a timeline cache. | The tweet is stored. The id is delivered into follower timelines. |

## Create a post

1. The client sends the text and any file.
2. The service stores the body.
3. The service returns the new id.

| Source | Steps that differ | Database |
| --- | --- | --- |
| Hello Interview | One insert into DynamoDB. The host that takes the call holds no post state. | DynamoDB. |
| Alex Xu, chapter 11 | Save the post, then hand the post id to the fan-out service. | A post database, then a cache of ids. |
| This session | Upload the file to S3. Insert one Postgres row with the text and the links. | Postgres and S3. |
| Facebook, 2015 | A tailer writes the action into the leaf index. | In-memory leaves and persistent logs. |
| Twitter public notes | Store the tweet. Update timeline caches. | A tweet store, a timeline cache, and a blob store for files. |

## Follow

1. The client names the account to follow.
2. The service stores one directed pair.
3. A second follow of the same pair changes nothing.

| Source | Steps that differ | Database |
| --- | --- | --- |
| Hello Interview | Write the pair so home can list "who I follow" and fan-out can list "who follows me." | DynamoDB, with a reverse index. |
| Alex Xu, chapter 11 | Read the friend graph at fan-out time. The chapter uses friends, which are mutual in the early Facebook model. | A graph database. |
| This session | Insert one Postgres pair. The other person does not follow back. | Postgres. |
| Facebook, 2015 | The read looks up friends. The post does not describe the follow write. | Not in that source. |
| Twitter public notes | The graph supplies the follower list for the timeline write. | FlockDB on sharded MySQL. |

## Like

1. The client names the post.
2. The service records one like for this user.
3. A second tap does not add a second like.
4. The card shows a count.

| Source | Steps that differ | Database |
| --- | --- | --- |
| Hello Interview | Out of that breakdown. The four feed lines come first. | Not in that source. |
| Alex Xu, chapter 11 | Out of the chapter's core. A notification service is named. A like table is not. | Not in that source. |
| This session | Insert the pair in Postgres. Add one to the count only when the pair is new. | Postgres. Redis is the later store for one hot count. |
| Facebook, 2015 | The product has likes. This post does not describe the like write. | Not in that source. |
| Twitter public notes | The product has likes. The timeline talks cited here do not describe the like write. | Not in that source. |

## Comment

1. The client sends text, and optional media links, for one post.
2. The service stores one comment from this user.
3. The home list does not copy that comment.
4. The comment list has its own page.

| Source | Steps that differ | Database |
| --- | --- | --- |
| Hello Interview | Out of that breakdown. | Not in that source. |
| Alex Xu, chapter 11 | Out of the chapter's core. | Not in that source. |
| This session | Insert one row under the post. Media links use the same S3 pattern as the post. | Postgres and S3. |
| Facebook, 2015 | The product has comments. This post does not describe the comment write. | Not in that source. |
| Twitter public notes | The product has replies. The timeline talks cited here do not describe the reply write. | Not in that source. |

## Home feed

The home feed includes the page and the order. **Fan-out on read** builds the list when Lee opens home. **Fan-out on write** copies the post when Kim publishes. A **hybrid** copies normal accounts on write and loads a famous account on read.

| Source | When the list is built | What the home read does | Database | Page and order |
| --- | --- | --- | --- | --- |
| Hello Interview | First path: on read. Later path: on write for a normal account, about 200 ids. A famous account stays on read. | Read the prebuilt ids, or query posts by author. Merge. Sort by time. | DynamoDB, then a feed table. | A time cursor. The next page is older than that time. Newest first. |
| Alex Xu, chapter 11 | Hybrid. Most accounts on write. A celebrity on read. | Read cached ids. Load celebrity posts. Merge. Load post bodies. | A news-feed cache, plus the post database for bodies. | The cache is a short recent list. Time order. |
| This session | On read, at about 200 reads per second. Hybrid starts at 5,000 reads per second. A famous account has more than 10,000 followers. | Load about 50 followee ids. Load their posts and Lee's posts. Sort by time. | Postgres. | A cursor of time and post id. Newest first. |
| Facebook, 2015 | On read. | Look up friends. Read recent actions from leaves. Rank and filter. | In-memory leaves. | The post describes rank. It does not describe a time cursor. |
| Twitter timeline talks | On write, into each follower timeline. | Read the cached list of tweet ids. | Haplo, a Redis-family cache, in the 2017 note. | An ordered id list. The early timeline follows tweet time. |

## What this session keeps

The happy path uses one Postgres database for users, follows, posts, likes, and comments. S3 holds the files. The home list is built on read.

The numbers are 1 million daily users, about 200,000 posts a day, about 50 follows, and about 200 home reads per second.

The post and the follow are the start of the Hello Interview path, with Postgres in place of DynamoDB. The like and the comment are extra. Those two are in this session and out of both write-ups. The home list on read matches the first Hello Interview path and the Facebook 2015 gather, without Facebook's rank. Chapter 11 and the later Hello Interview path prebuild the home list. This session does that at the 5,000-read peak, and it keeps the newest 200 post ids per reader. A page past that window uses fan-out on read for normal accounts. Twitter's published timeline path writes ids into a cache on publish.

## Sources

- Hello Interview, FB News Feed: https://www.hellointerview.com/learn/system-design/problem-breakdowns/fb-news-feed
- Alex Xu, *System Design Interview*, volume 1, chapter 11, "Design a News Feed System"
- Facebook, "Serving Facebook Multifeed" (10 March 2015): https://engineering.fb.com/2015/03/10/production-engineering/serving-facebook-multifeed-efficiency-performance-gains-through-redesign/
- Twitter, Raffi Krikorian, "Real-Time Delivery Architecture at Twitter" (InfoQ, recorded 2012): https://www.infoq.com/presentations/Real-Time-Delivery-Twitter/
- Twitter, Arya Asemanfar, "Timelines @ Twitter" (InfoQ, recorded 2012): https://www.infoq.com/presentations/Timelines-Twitter/
- Twitter infrastructure note, InfoQ (2017), Haplo, Manhattan, FlockDB, and a blob store: https://www.infoq.com/news/2017/01/scaling-twitter-infrastructure/
