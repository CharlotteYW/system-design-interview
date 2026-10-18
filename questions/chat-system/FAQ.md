# FAQ — Chat System

Practice these out loud. Add questions you actually got stuck on. Same five steps as the README.

## 1. Requirements and design scope

**Q: What are the must-have functional requirements?** (2026-10-12)  
A: Send and receive a message. Start a group of at most 100 people. A two-person chat is the same kind of chat. Deliver messages that arrived while the user was offline, and keep them for 30 days. Allow an image or a video on a message. Deliver the same message to each device the user has open, such as a phone and a laptop.

**Q: What are the non-functional requirements?** (2026-10-12)  
A: About 1 billion accounts. Hello Interview says billions, and a later example on that page uses about 200 million connected clients. The requirements section does not give one message rate. An online recipient sees the message in under 500 milliseconds. The sender's success is the stored row, not the other phone's screen. The server stores the message before that success. One dead chat server does not drop a stored message. Delivery is at least once. The server drops the stored copy after every device acks, or after 30 days.

**Q: What is below the line?** (2026-10-12)  
A: Hello Interview cuts audio and video calling, business interactions, and registration or profile management. It also cuts an exhaustive security design, and spam or scraping detection. The socket is still encrypted. This session also cuts a news feed. That feed cut is ours, not theirs.

## 2. High-level design

**Q: Where do the image and the video go?** (2026-10-14)  
A: The bytes go to S3. `messages.media_key` stores the object key, not the bytes and not a forever public URL. Lee uploads the file first, then sends the key with the text. One Trip photo is one object. Each device gets a short-lived URL when the message is pushed or drained, and downloads from S3. Deleting the message row also deletes the object.

**Q: How does one `messages` table hold Trip and a two-person chat?** (2026-10-14)  
A: One row is one message. `chat_id` says which chat. `seq` is the number inside that chat. Trip's "hi" can be seq 7 while Lee and Kim's other chat is also on seq 7. Those are different rows because the chat id differs. The pair `(chat_id, seq)` is unique. A device cursor is not stored on the message row.

**Q: How does a group message move the cursors?** (2026-10-13)  
A: A group uses the same send as a two-person chat. Any member can send. One `messages` table stores the row, and the chat id is a column. Each device has a cursor per chat. Kim's laptop can be at 7 in Trip while Kim's phone is at 6 and Ada is still behind. The row stays until every live device in that chat is past it, or until 30 days. A physical table per group would be one table per chat. A cursor shared by the whole group would let Ada's ack hide the text from Kim.

**Q: How do a phone and a laptop share one message?** (2026-10-13)  
A: Each device stores a cursor. A cursor is the latest message number that device has acked. The laptop can move to 11 while the phone stays at 10. The server keeps message 11 until every live device cursor has passed it, or until 30 days. When the phone connects, the drain sends messages after 10. A new laptop starts at the current number and does not drain old messages. One cursor for the whole user would let the laptop ack hide the text from the phone.

**Q: What does inbox drain mean?** (2026-10-13)  
A: An inbox in the cursor design is every `messages` row in a chat with `seq` after that device's `last_seq`. A drain is the send of that list. Kim's phone connects. The server sends those rows on the socket. After `RECEIVED`, it moves the cursor. Lee does not send the text again.

**Q: Kim's phone is off. Where does "hi" wait?** (2026-10-12)  
A: Lee still gets success when the row is stored, and "delivered" only after Kim acks. The server stores the message. Kim's phone cursor does not move. When Kim opens the app, the socket connects, the drain sends rows after that cursor, and Kim sends `RECEIVED`. The cursor then moves forward. A vendor banner can wake the phone. The text still comes from Postgres. If Kim never connects, the row is deleted after 30 days.

**Q: Lee sends "hi" and Kim's phone is online. What happens?** (2026-10-12)  
A: Lee's phone sends `sendMessage` on its socket. The chat server stores the message in Postgres, then tells Lee success. That success means stored, not that Kim saw it. The server pushes `newMessage` on Kim's open socket. Kim's app shows the text and sends `RECEIVED`. The server then moves that device's cursor. Kim's phone keeps the text. A vendor banner is for an app with no socket. This online path does not use one.

**Q: Why these major boxes and not fewer/more?**  
A: TBD

## 3. Low-level design and deep dive

**Q: What does the cursor table look like?** (2026-10-15)  
A: Primary key is `(client_id, chat_id)`. Columns are `last_seq` and `updated_at`. Kim's phone can be at Trip 6 while Kim's laptop is at Trip 7. A single latest id for the whole user would hide Trip from a device that is still behind in that chat.

**Q: If Kim is offline, is the Redis publish gone? What sends the message when she returns?** (2026-10-15)  
A: Yes. If no chat server has `SUBSCRIBE user:kim`, that live publish is dropped. The message is already in Postgres. When Kim opens the app, the phone connects to a chat server. That server drains every `messages` row after that device's cursor, then moves the cursor on `RECEIVED`. Redis is not replayed. A later live message can use Pub/Sub again after the subscribe.

**Q: Why Redis Pub/Sub, and not Kafka or Amazon SQS?** (2026-10-15)  
A: The live hop is Redis Pub/Sub. A publishes. Subscribed chat servers get the push in memory. There is no disk log per user channel. That is fine because Postgres already stores the message. Kafka is a durable log. One topic per user fails at about 1 billion topics. One shared Kafka topic needs another way to reach only Kim's server. Amazon SQS is a pull queue. A worker must poll. That adds delay for a 500-millisecond chat. Amazon SNS can fan out, and it still sits outside the hot path we pick here. Use a queue for work that must wait on disk. Use Redis Pub/Sub for the best-effort live push.

**Q: Is Redis SUBSCRIBE the same as a map `user:kim -> B`?** (2026-10-15)  
A: No. `SUBSCRIBE user:kim` tells Redis: send every future PUBLISH on the channel named `user:kim` to this connection. It does not store the value B. A separate presence key can store `user:kim -> B` for ops. The live path uses Pub/Sub. On B, a local map holds `kim -> websocket`. After Redis delivers the publish to B, B looks up that local map and writes the socket.

**Q: Who subscribes to Kim's Redis channel, Kim or server B?** (2026-10-15)  
A: Server B. When Kim's laptop opens a socket to B, B calls Redis SUBSCRIBE on the channel named for Kim. Lee's phone talks only to A. A stores the row, then PUBLISH on Kim's channel. Redis delivers that publish to B. B writes `newMessage` on Kim's socket. Kim's phone is not a Redis consumer. It only holds the WebSocket to B.

**Q: When "bye" arrives before "hi", what does the UI do?** (2026-10-15)  
A: The app shows "bye" as soon as it arrives. When "hi" arrives later, the app inserts it above "bye" by `seq`. The list is sorted again. The user can see "bye" first for a moment.

**Q: Lee is on chat server A and Kim is on chat server B. How does "hi" reach Kim?** (2026-10-15)  
A: A stores the message in Postgres, then publishes to Redis Pub/Sub on Kim's user channel. B is subscribed because Kim's laptop is on B. B writes the socket. A Redis map of user to server is optional presence. It is not enough by itself. Kafka with one topic per user fails at about 1 billion topics.

**Q: What does out of order mean in chat?** (2026-10-15)  
A: Lee sends "hi", then "bye". Kim can get "bye" on the socket before "hi". The app still shows "hi" above "bye" by server `seq` or `created_at`. It does not wait to hold "bye" until "hi" arrives. A late "hi" can pop in above "bye". Exact send-time order across servers is not the promise.

**Q: Is the live path per user or per chat?** (2026-10-15)  
A: Per user. One subscribe when Kim connects. One publish to reach Kim. Per chat wins only when most chats are large. This product is mostly one-to-one. A chat of 100 people can later use a chat channel as a hybrid.

**Q: What if the socket dies?** (2026-10-15)  
A: A ping every 15 seconds and a 5-second pong timeout close a dead socket. The client reconnects to any healthy chat server. That server subscribes to Kim's Redis channel and drains after the device cursor. Waiting for TCP alone can take minutes.

**Q: What if Redis drops the live publish?** (2026-10-15)  
A: The message is already in Postgres. At least once means the device gets it on the next drain. A second publish with no durable row is not enough. A heartbeat that carries the latest seq can also show the client that it is behind.

**Q: How do we order messages that arrive out of order?** (2026-10-15)  
A: Display by server `created_at` or by `(chat_id, seq)`. Do not delay new messages to wait for a late packet. A late message can pop in above another. Exact send-time order is not the promise.

**Q: How does last seen stay cheap?** (2026-10-15)  
A: Write last seen when the last socket for that user closes. Do not write on every heartbeat. A getLastSeen reads that time, and a live chat server can still answer ONLINE.

**Q: Why this storage model over the alternative?**  
A: One `messages` table with `chat_id` and `seq`. One `device_cursors` row per device per chat. S3 holds media bytes. Redis Pub/Sub carries the live push. Postgres holds the durable copy.

**Q: Where is the bottleneck as traffic grows?**  
A: Open sockets and the live bus. Add chat servers and shard Redis channels by user id. The message table grows with seq per chat. Shard messages by `chat_id` when one primary cannot hold the write rate.

## 4. Component questions and special situations

**Q: What if one chat server dies with 50,000 sockets?** (2026-10-15)  
A: Those sockets are gone. Clients reconnect to healthy hosts. Each host resubscribes and drains after the device cursor. Stored messages stay in Postgres. Do not wait for that one host to come back before users reconnect.

**Q: What if Redis is down for 2 minutes?** (2026-10-15)  
A: Live pushes stop. Sends still commit in Postgres and return success. Devices catch up by drain or by a heartbeat seq that is ahead of the cursor. Do not fail Lee's send because Redis is down.

**Q: What would you change for 10x traffic or rush hour?** (2026-10-15)  
A: Add chat servers. Shard Redis by user id. Check Postgres insert capacity. Jitter reconnects after an outage so 200 million clients do not return in one second.

**Q: How do you handle a hot Trip chat?** (2026-10-15)  
A: Above about 25 online members, publish once to `chat:trip` and have those members subscribe to that chat channel. Small chats stay on the per-user channel.

**Q: What if the Postgres primary region is lost?** (2026-10-15)  
A: Fail over to a replica in another availability zone. Async cross-region copy is disaster recovery and can lag. Do not wait for two regions to commit before Lee's success.

## 5. Summary and future improvements

**Q: What did we design, and what risk remains?** (2026-10-15)  
A: Online Kim gets the text on the socket. If Lee and Kim are on different chat servers, Redis Pub/Sub moves the live push. Offline Kim gets a drain from Postgres after the device cursor. Redis is not replayed. The risk that remains is a huge `messages` table. Shard by `chat_id` when one primary is not enough. A second push after a lost ack is still possible. At least once stays the promise.

**Q: Who decides the sequence number, client or server?** (2026-10-15)  
A: The server. An atomic counter per `chat_id` assigns the next `seq` when the row is stored. A client seq can collide when two devices send at once, and a bad client can lie. Redis `INCR chat:{id}:seq` or a Postgres sequence per chat both work. This session would use one atomic counter per chat on the write path.

**Q: How would spam filtering fit later?** (2026-10-15)  
A: Score the message after the store, before the Redis publish and before a drain sends it. If it is spam, mark the row and do not push. Lee can still see his own send. Kim does not. A full spam system was below the line for the core interview.

## Local system

**Q: What did the simplified implementation teach you that the diagram did not?** (2026-10-15)  
A: The page shows every Postgres table and the Redis Pub/Sub log after each send. Cross-server needs Lee on A and Kim on B. Offline needs a disconnect before send, then connect to see `via: drain`. Two logical servers live in one process. The hop is still Redis.

## Session questions

**Q: Kim is online. Why does the cursor for `kim-phone` not move after Lee sends?** (2026-10-15)  
A: Kim sees the message when the push lands in her mailbox (`via: user-channel`). The device cursor means "this device confirmed." Only `POST /v1/ack` moves it. If the server moved the cursor on push, a phone crash before save would lose the message. Drain would skip that seq.

**Q: What does each store hold?** (2026-10-15)  
A: Postgres holds the durable truth: `users`, `chats`, `chat_members`, `clients`, `messages`, `device_cursors`, and `last_seen`. Redis holds the live hop (`user:{id}` channels), the presence hint, and the `seq` counters. Each chat server holds its own socket map in memory. The lab page lists all of them at the bottom.

**Q: How do the tables split when they grow?** (2026-10-16)  
A: `messages` splits first, by a hash of `chat_id`. Then one chat, its `seq`, and its drain stay on one shard. `device_cursors` splits next. `chat_members` splits by `chat_id` only when it is huge. `chats`, `clients`, `users`, and `last_seen` stay as one table for a long time. Redis shards by channel name.

**Q: When does the system read `chat_members`?** (2026-10-16)  
A: The system writes it on create, invite, and leave. It reads it on five paths:

1. Send: check that the sender is a member. A non-member gets 403.
2. Fan-out: list the users to publish to (`user:lee`, `user:kim`).
3. Hot chat: count members. At 25 or more, publish once on `chat:{id}`.
4. Chat-channel receive: filter local sockets to members only.
5. Drain on connect: list every chat for this user, then pull `seq > last_seq` in each.

`clients` answers "which devices does this user have." `chat_members` answers "which users are in this chat." Do not merge them.

**Q: Why not put `chat_members` in a DynamoDB-style table?** (2026-10-16)  
A: That is a valid choice. Hello Interview uses it: partition key `chatId`, sort key `participantId`, and a GSI (global secondary index) on `participantId`. The table has two access patterns. "Who is in this chat" serves the send. "Which chats is this user in" serves the drain. Postgres answers both with the primary key `(chat_id, user_id)` and an index on `(user_id, chat_id)`. The roster is small and changes rarely, so one Postgres instance holds it for a long time. Postgres also keeps the chat row and its members in one transaction with the other tables. Pick DynamoDB when the whole chat store moves to DynamoDB at about 100,000 writes per second, not for this table alone. The GSI updates asynchronously. A new member can miss the drain for a short time.

**Q: Is HBase or Cassandra a good choice for `messages`?** (2026-10-16)  
A: Yes, at the Hello Interview scale. The table is append-only. Every read is "one chat, after this seq." Rows expire after 30 days. A wide-column store fits all three. The partition key `(chat_id, bucket)` keeps one chat together, and a time bucket stops one old chat from growing one partition forever. The clustering key `seq` sorts the rows inside the partition, so drain is one range read. A TTL expires old rows with no batch delete. The costs:

- No per-chat counter. Keep Redis `INCR`, or use a time-ordered id such as Snowflake.
- No transaction with the cursor. Store first, then move the cursor. At least once covers the gap.
- Last write wins. A late ack can move a cursor back, and the device then gets a duplicate. Dedupe by message id.
- Deletes become tombstones. Many deletes in one chat slow its reads. Discord saw this in 2017.

Discord moved to Cassandra in 2017 and later to ScyllaDB. Facebook Messenger used HBase from 2010 and moved to MyRocks in 2018. Sharded Postgres by `chat_id` is the other valid path. Keep `chats`, `chat_members`, and `clients` in Postgres.

**Q: What changes when `messages` moves to Cassandra, and what can I see in the lab?** (2026-10-16)  
A: Two tables move: `messages` becomes `messages_by_chat ((chat_id, bucket), seq)`, and `device_cursors` becomes `device_cursors_by_client ((client_id), chat_id)`. The roster, the Redis counter, and Pub/Sub stay the same. Port 8001 runs design 2, and `/compare` puts it next to design 1. Watch three differences:

1. Partitions. Six sends to `lee-kim` make two partitions, `(lee-kim, 0)` and `(lee-kim, 1)`, with different tokens. The drain reads each bucket from `last_seq + 1`. Postgres reads one index range.
2. Late ack. Postgres `GREATEST` ignores it. A Cassandra upsert moves the cursor back, and the device gets a duplicate that it drops by message id. An LWT keeps the cursor, at the cost of Paxos on every ack.
3. Retention. Each Cassandra row shows `ttl_seconds` counting down from 30 days. Postgres needs a delete job.

The README section "Two message-store designs" has the full table.

**Q: Why does the page show "partitions of messages_by_chat" and "messages_by_chat"? Are they two tables?** (2026-10-16)  
A: No. Cassandra has one table, `messages_by_chat`. The partitions card is a view of the same rows, grouped by the partition key `(chat_id, bucket)`. It shows how Cassandra stores the data. Each partition sits on one node and its replicas, sorted by `seq`. The token is the hash of the partition key, and it picks the node. Seq 1 to 4 sit in `(lee-kim, 0)` and seq 5 starts `(lee-kim, 1)` on a different token.

**Q: Why can `ada-phone` not send to Kim?** (2026-10-16)  
A: A send names a chat, not a person. Ada was only in `trip`. `lee-kim` correctly returns 403, because Ada is not a member. The lab had no way to start a chat. It now has "Start a chat" (`POST /v1/chats`). Ada picks Kim, and the server writes `chats` and `chat_members` for `ada-kim`. The id of a two-person chat is the sorted pair, so a second click returns the same chat (`created: false`) and does not make a duplicate. WhatsApp does the same thing when you open a contact the first time.

**Q: Why do the cursors move to Cassandra too?** (2026-10-16)  
A: They write more often than messages do. This session estimates about 40,000 sender-cursor updates and about 80,000 recipient acks per second, against about 40,000 message inserts. Each write is a small overwrite. Postgres writes a new row version for each update, and vacuum must clean up after it. Cassandra appends with no read. The drain reads cursors by device, so the partition key is `client_id`. The cost is last write wins: a late ack moves the cursor back and causes a duplicate. Coalesce acks on the client (send the highest seq for each chat, once a second) to cut the rate in any store.

**Q: So we use Cassandra at 40,000 messages per second or more? What else matters?** (2026-10-16)  
A: 40,000 is the Hello Interview design point, not a hard cutoff. Also check these:

- The rate in two or three years, because a migration later is expensive.
- Total bytes. Retention forever favors wide-column at a lower rate.
- Reads by key only. Search needs a second system.
- Edits and deletes, which make tombstones.
- `LOCAL_QUORUM` on the write and on the drain read.
- Hot group partitions.
- Multi-region replication.
- The team's ops skill and the cost of three replicas.

If the team runs MySQL well, sharded MySQL (as at Messenger) or a managed store (DynamoDB, ScyllaDB) is a valid answer at the same rate.

**Q: Besides Redis Pub/Sub, could the live hop use Kafka, RabbitMQ, or gRPC directly to Kim's server?** (2026-10-17)  
A: All of them can move a message. They differ in how A finds Kim's server and what each connect costs.

- **Kafka with one topic per user** fails. Hello Interview gives about 50 KB per topic, so about 50 TB for 1 billion users. One topic per server still needs a registry, and it adds a disk write. Kafka fits the side paths: push for offline users, search, and analytics.
- **RabbitMQ** binds `user.kim` to B's queue on each connect. Binding churn at 200 million online users is the limit. Its acks repeat what the store and the drain already do.
- **Direct gRPC with a presence registry** removes the broker. A stale entry sends the push to the wrong server. Two devices on two servers need a set.
- **Direct gRPC with consistent hashing** (Hello Interview "Good") needs no lookup. Resharding forces reconnects, and messages go to both owners during the move. Slack's channel servers work this way.
- **Redis Pub/Sub** (Hello Interview "Great", our pick) is an in-memory pointer per user channel, sharded by user id. It is at most once, and the store plus the drain cover a drop.

See the README section "Live bus options."

**Q: How much traffic can this design take?** (2026-10-17)  
A: Two answers.

- **Interview design, at the Hello Interview scale.** The inputs are 200 million sockets and about 46,000 messages per second, with a 140,000 peak (this session's three-times choice). The boxes fill in this order:
  1. Cassandra storage: about 110 TB with RF 3 and compaction room, so about 55 nodes at 2 TB each.
  2. The `chat_members` read: about 250,000 per second from sends and reconnects. Add replicas, or cache the roster on each chat server.
  3. Cursor writes: coalesce acks, and drop the sender-cursor write.
  4. Chat servers: 200 to 2,000 hosts, sized by sockets and reconnect storms.
  5. Redis: 6 to 10 nodes, not the bottleneck.
- **Local lab, measured.** About 400 messages per second for Design 1 and about 640 for Design 2, with Kim getting every push and no backlog. The app process is the limit, not the stores. Before the connection pool, Design 1 did about 100 per second, and the live push fell 6 to 12 seconds behind.

Every per-node figure is a planning assumption. The README "Capacity estimate" section shows each one.

**Q: Where in the code does Kim's server read the Pub/Sub message and send it to Kim?** (2026-10-17)  
A: In `src/main.py`, in six steps:

1. On connect, Kim's server records `sockets["B"]["kim-laptop"] = websocket` and `socket_owner["kim-laptop"] = "kim"`.
2. `subscribe_user` adds `user:kim` to `subscribed["B"]`.
3. `redis_listener` runs `SUBSCRIBE user:kim` on its Redis connection.
4. Lee's send stores the row. Then `publish_live` reads the members and runs `PUBLISH user:kim`.
5. `redis_listener` gets the message and routes it to every server whose `subscribed` set holds that channel.
6. `handle_redis_message` finds Kim's local sockets through `socket_owner`. Then `push_to_socket` writes the frame on the event loop.

Before 2026-10-17, step 6 only filled the lab mailbox. A real WebSocket client got no live push. A test now opens `/ws/B/kim-laptop` and checks the frame. The lab runs A and B in one process with one Redis connection. In production, each chat server has its own subscriber connection, and the routing in step 5 is not needed.

**Q: Does each chat server run its own Redis listener? Why does the push use `run_coroutine_threadsafe`?** (2026-10-17)  
A: Yes. Each real chat server runs one listener on one subscriber connection, and it subscribes only to the users that server holds. The lab runs one listener for both logical servers, so it must look up `subscribed` to route. The `targets` lines find every socket on this server that belongs to that user. A user can have two devices on the same server, so there can be more than one.

A FastAPI WebSocket belongs to the asyncio event loop. `send_json` is a coroutine, and asyncio objects are not thread-safe. The listener is a plain thread that blocks on Redis. It cannot `await`, and it must not touch the socket directly. `run_coroutine_threadsafe` puts the write on the loop's queue, and the loop runs it.

- **Option A: An async listener** (`redis.asyncio`) as a task on the same loop. There is no thread and no handoff. This is the clean Python default.
- **Option B: A thread plus `run_coroutine_threadsafe`.** This is what the lab does. It is simple, and it keeps the sync Redis client.
- **Option C: A bounded queue and one writer task per socket.** This keeps the order on each socket and handles a slow phone. Drop or close the socket when the queue fills, and let the drain catch up.
- **Option D: One thread per socket.** Each thread needs about 1 MB of stack (a typical default), so 1 million sockets needs about 1 TB. This option does not scale.

One server holds about 100,000 to 1 million sockets, and that is why chat servers use an event loop. The lab keeps Option B. Production would use Option C on an async runtime.

**Q: What is `seq` for? Does the timestamp decide the order? If a later message reaches the server first, which one is first?** (2026-10-17)  
A: The server's accept order decides it. The sequencer (Redis `INCR`) hands out `seq` as sends arrive. The first send it accepts is first, whatever the client clocks say. For two people this is the only fair answer. No device can see the real send times, so the promise is that every device shows the same order.

`seq` gives the display order, the drain (`seq > last_seq`), gap detection (holding 7 and getting 9 means 8 is missing), and a unique key `(chat_id, seq)`. `created_at` is a label only. Clocks on two servers differ by milliseconds, two messages can share a millisecond, and a timestamp cannot show a gap. Hello Interview orders by the server receive time, and that is fine for display.

For one sender, TCP keeps order on one socket. A swap needs a retry or a second device. The client sends from an ordered outbox with a client message id, so a retry returns the first `seq`.

On the receive side, the client inserts by `seq` and acks only the highest contiguous seq. Otherwise `GREATEST` skips a missing message forever. The contiguous ack also covers the race where seq 6 commits before seq 5.

Gaps in the lab: there is no client message id yet, and "Ack all" acks each item without a contiguity check. See the README section "Message ordering."

**Q: Does a client local id keep the send order? How do servers with different clocks agree? Where is `seq` generated, and does the lab do it?** (2026-10-17)  
A: A client id keeps one device's own order. Lee's phone can number its own sends 1, 2, 3, but Kim's phone has its own 1, 2, 3, and the two cannot be compared. The server must merge them into one order. A client message id (a UUID) is a different tool. It makes a retry return the first `seq`, and it does not order anything.

Server clocks do not matter for the order. `seq` comes from Redis `INCR chat:{chat_id}:seq`, a single shared counter. Redis runs commands one at a time, so it never hands out the same number twice. The server then stores that number in the `seq` column in Postgres or Cassandra. The database stores the number, and Redis makes it. The clock only fills `created_at`, the time label. Ordering by server time instead (Hello Interview) lets a few milliseconds of skew swap two near-simultaneous messages, and NTP keeps that rare.

The lab does generate `seq` this way: `next_seq` in `src/main.py` is called by `send_message` before the insert. A demo fired 20 sends at once through servers A and B and got seq 1 to 20, unique and with no holes. Lee's 10 parallel sends were stored as `#1, #4, #2, #7, ...`, which shows why a phone sends from an ordered outbox on one socket. The test `test_concurrent_sends_get_unique_contiguous_seq` now checks this on both designs.

**Q: Which client fields go to the server, and why? If "a" is delayed, can "b" go first? What if the `seq` server dies?** (2026-10-17)  
A: Both fields go in every send body.

- `clientMsgId` is a UUID per message. A retry reuses it, so the server returns the first `seq` with `duplicate: true` and stores nothing new.
- `clientSeq` is the device's own counter in that chat. The server cannot order one device's sends without it. The server keeps the highest `clientSeq` per device per chat and flags a lower late one `outOfOrder: true`. The server `seq` still decides the display.

With one ordered socket, `clientSeq` is a detector. With parallel sends, it is the only way to see a swap.

On one TCP connection, a lost packet holding "a" blocks "b" until TCP resends "a" (head-of-line blocking). So "a" cannot fall behind "b" on the wire. "b" goes first only when the app writes it first:

- "a" is a photo still uploading.
- The socket dropped and "a" is resent on a new one.
- "b" came from another device.

The server order then wins.

The counter is one key on one Redis primary. A dead primary stops sends for its chats until a replica takes over in seconds, while other shards keep working. The risk is a replica that comes back with a low or missing counter, which hands out an old `seq`. Postgres catches that with `UNIQUE (chat_id, seq)` and returns 409. Cassandra overwrites the old row silently.

The lab guard rebuilds a missing counter from the highest stored `seq`. Production also uses `WAIT`, a fencing epoch, or a counter that does not live in Redis (Option D or E).

**Q: Short version. What do the two client fields prevent? When can two messages get the same `seq`, and what happens?** (2026-10-18)  
A: `clientMsgId` prevents a duplicate message when a retry repeats a send. `clientSeq` detects one device's messages arriving in the wrong order.

`seq` is per chat, so `lee-kim` seq 5 and `trip` seq 5 are both normal. The problem is two messages in the same chat with the same seq. `INCR` is atomic, so a healthy primary never repeats a number. A repeat needs the counter to go back, and that has four causes:

- Failover to a replica that lagged.
- Split brain: the old primary keeps writing after a replica is promoted.
- A restart without persistence.
- Eviction of the key under `maxmemory`.

When it happens, Postgres rejects the second insert through `UNIQUE (chat_id, seq)`, and nothing is lost. Cassandra overwrites the first message: devices that already had it keep it, and others never see it.

Prevent each cause:

- A lagged failover: `WAIT`, a fencing epoch, or `IF NOT EXISTS`.
- Split brain: `min-replicas-to-write`.
- A restart: append-only file persistence.
- Eviction: `noeviction` or a separate Redis for counters.

Options D and E avoid Redis for order. `WAIT`, the epoch, and Options D and E prevent the repeat. `IF NOT EXISTS` and the Postgres `UNIQUE` detect it at write time.

**Q: Where is the `clientMsgId` code, and are the fields stored? How does `WAIT` help? Can a lower `seq` have a later timestamp?** (2026-10-18)  
A: The check is in `send_message` in `src/main.py`. `SET idem:{clientId}:{clientMsgId} pending NX EX 86400` claims the id. If the claim fails, `replay_idempotent` returns the saved first answer with `duplicate: true`. The Redis key does the dedupe. Both fields are also stored on the message row (Postgres columns, Cassandra columns) as a record, but no unique index uses them. A stronger option is a unique index on `(sender client, client_msg_id)` in Postgres.

`WAIT 1 timeout` blocks until one replica has every earlier write from this connection. Without it:

1. `INCR` returns 5.
2. The message is stored.
3. The primary dies before the replica gets 5.
4. The promoted replica says 4, so the next send gets 5 again.

With `WAIT 1 50` between `INCR` and the insert, the replica already holds 5, and Sentinel promotes the most up-to-date replica. It costs one replica round trip (under about 1 ms in one data center). Use a short timeout, not 0, which waits forever. If no replica answers, fail the send. `WAIT` narrows the window, but Redis still is not strongly consistent.

With healthy Redis, two messages in one chat never share a `seq`. The chat's key lives on one primary, and `INCR` is atomic.

A lower `seq` can carry a later `created_at`, because server clocks differ by milliseconds. The order is unaffected, because devices sort by `seq`. Only the label can look a few milliseconds off. To make them agree, take the time from Redis `TIME` in the same script as `INCR`, so one clock stamps every message in the chat. Or the client shows `max(previous time, created_at)`.

**Q: What does a repeated `clientMsgId` return? Where is the `WAIT` code? Is my summary of the two fields right?** (2026-10-18)  
A: A repeat returns the saved first answer. That answer holds the server `seq` the message got the first time, plus the same `messageId` and `clientSeq`, with `duplicate: true`.

`WAIT` is not in the lab. It is a production measure, and the lab Redis has no replica for it to wait on. Adding it needs a replica container and one `WAIT 1 50` call between `INCR` and the insert.

The summary is right, with one change. `clientMsgId` stops a retry from storing the same message twice. `clientSeq` is one device's own counter, so two devices can both send `clientSeq` 3. It records that device's send order, but it does not decide the chat order; the server `seq` does. The lab only flags a swap (`outOfOrder`). Keeping the order would need the server to hold or reject the early one (Option B).

**Q: When do cases 3 and 4 happen in our design? Is Option D the only fix for case 4? What does the 0 in `WAIT 1 0` mean?** (2026-10-18)  
A: Case 3, where Kim receives 9 before 8, happens three ways:

- Pub/Sub drops the push of 8. It is at most once.
- Kim reconnects. Connect subscribes first and drains second, so a live 9 can land while the drain is still reading 8.
- 8 and 9 come from senders on different servers, so their publishes race.

Case 4, where 6 is visible before 5, happens when two servers send into one chat at once. `INCR` and the insert are two steps, and server A is slower (a GC pause or a slow write). If A crashes between them, 5 never exists.

The client rule handles both: insert by `seq`, ack only the highest contiguous seq, fill the gap, and skip a hole after a few seconds. Option D is not required. It and Option E make case 4 disappear, because the number and the row commit together, or one server writes in order. In Postgres, a crash in the transaction also rolls back the number, so no hole is left.

Lab gap: "Ack contiguous" fills holes, but it never skips a permanent one. A seq taken by a failed send keeps the cursor below it.

`WAIT 1 0` means wait for one replica with no time limit. If the replica is down, every send hangs, so use a timeout such as `WAIT 1 50`.

**Q: Case 3 is solved by re-sorting, right? Is the case 4 hole a big deal, and does the retry get seq 7?** (2026-10-18)  
A: Case 3, yes. The app inserts each message by `seq`, so a late 8 slots in between 7 and 9. The cursor waits until 8 is there.

Case 4 leaves a hole at 5. It is not a big deal for the data. Nothing was stored, and nobody saw a message there. It matters in two places:

- **Kim's cursor** must skip the hole after a few seconds, or every drain resends the rows after 5. The skip time must be longer than the server's longest write, so a slow real 5 is not skipped.
- **Lee's retry** gets a new seq, 7, with the same `clientMsgId`. The lab had a bug here. The dead server's "pending" claim lasted 24 hours, so the retry got 409 for a day. The claim now lasts 5 seconds, and the 24-hour key is written only after the answer is saved.

"Crash server mid-send" and the test `test_crash_mid_send_leaves_a_hole_and_the_retry_stores_later` show it.

**Q: So the client handles holes and decides the ack, and the backend just stores it?** (2026-10-18)  
A: Yes for the decision. Only the device knows what it holds, so the device sends the highest contiguous seq. It slots a late message in by `seq` and skips a hole after a few seconds.

The backend keeps the cursor simple: one number per device per chat. It still enforces two rules.

- **Forward only.** Postgres uses `GREATEST`, so a late ack never moves the cursor back. In Cassandra, a plain upsert can move it back, and an LWT stops that.
- **No ack past the chat's newest seq.** A bug that acks 1,000,000 would skip every future message for that device. The lab now returns 422 for that.

The backend also still assigns `seq`, stores rows, serves the gap fill and the drain, and checks membership.

- **Option A: Client-side contiguous ack.** One number per device per chat. This is our pick.
- **Option B: Server tracks each delivery** (Hello Interview's inbox, a row per message per device). The server knows exactly, but it pays a write and a delete for every message.
- **Option C: Server checks for holes before it accepts an ack.** This costs a range read on every ack.

A message that arrives after its hole was skipped still shows by live push. An offline device never drains it, because the cursor is past it. So the skip time must be longer than the server's longest write.

**Q: What are Options A to F for who hands out the order?** (2026-10-18)  
A: The README section "Message ordering" has the full list. In short:

- **A: Client timestamp.** Never. Phone clocks are wrong, and users can change them.
- **B: Server receive time (Hello Interview).** Simple. No gap detection, and ties need a tie-break.
- **C: Per-chat counter in Redis (this design).** Dense numbers, so the drain and gap detection work. It needs the contiguous ack, and a counter that comes back low reuses a `seq`.
- **D: Per-chat counter in the Postgres transaction.** `UPDATE chats SET last_seq = last_seq + 1 RETURNING last_seq` with the insert. Commit order matches `seq`, and a crash rolls the number back. A busy chat waits on that row. Postgres only.
- **E: One owner server per chat.** Consistent hashing puts each chat on one server, which orders sends in memory (Slack's channel servers). You run the hash ring.
- **F: Time-ordered id (Snowflake, Discord).** No coordination. The numbers have gaps by design, so no gap detection.

**Q: In the hole case, did the message reach the server? What does "ack only the highest contiguous seq, gap fill" mean?** (2026-10-18)  
A: The message did reach server A, and A took seq 5 from Redis. A died before it stored the message or replied, so 5 has no row. Nobody saw a message at 5, and Lee's phone retries the same `clientMsgId`, which is stored as a later seq. Only the number is lost.

"Contiguous" means no gaps. "Gap fill" means asking the server for what is missing. Kim's phone has its cursor at 6. Live pushes brought 7 and 9, and the push of 8 was lost.

| Step | The phone holds | What it does |
| --- | --- | --- |
| 1 | 7, 9 | Walk up from the cursor (6): 7 is there, 8 is missing, so stop. The highest contiguous seq is 7. Ack 7, not 9. |
| 2 | 7, 9 | Gap fill: `GET /v1/chats/lee-kim/messages?afterSeq=7` |
| 3 | 7, 8, 9 | The server returned 8 and 9. Walk again: all present. Ack 9. |
| 3b | 7, 9 | 8 was not returned, so it was never stored (a hole). Wait a few seconds, then skip 8 and ack 9. |

Why not ack 9 at step 1? The cursor would become 9, and the drain sends only `seq > 9`. The phone would never get 8. The code is the "Ack contiguous" handler in `src/static/index.html`, and the server check is `ack_message` in `src/main.py`.

**Q: How does Hello Interview's timestamp order compare with our `seq`?** (2026-10-18)  
A: Hello Interview has each chat server stamp the message with its own clock on arrival. NTP keeps the clocks within a few milliseconds of each other in the background, and no server asks a central clock per message. Devices sort by that time. Completeness comes from an inbox row per message per device, not from the order. Our design uses a per-chat Redis counter, because our cursor drain needs dense numbers.

| | Server timestamp | Per-chat `seq` |
| --- | --- | --- |
| Good | No sequencer, no extra call, nothing to fail over | One exact order, gap detection, simple drain, no ties |
| Bad | Rare swaps inside the clock skew, ties need a tie-break, no gap detection, needs an inbox | Redis on the send path, a counter can come back low, Cassandra needs a guard |

The README section "Message ordering" has the full table, row by row.

**Q: If Redis is down, do we fall back to a sequence in Postgres or Cassandra, or stop accepting messages? What failure takes the whole system down?** (2026-10-18)  
A: We stop accepting sends for the affected chats, and return 503 "nothing stored, retry." The phone keeps the message in its outbox and retries, and a Redis failover takes seconds. Do not switch to a local counter during the outage. Servers that still reach Redis and servers on the fallback would both hand out the same `seq`. If the counter must survive Redis loss, use Option D (a counter row in Postgres `chats`) all the time.

Redis's three jobs fail differently:

- Counter loss stops sends for the chats on that shard.
- Pub/Sub loss stops only the live push. Sends succeed with `livePush: failed`, and devices catch up by gap fill or drain.
- Idempotency loss risks a duplicate on retry.

The total outage is Postgres. In design 1 it holds everything. In design 2 every send and drain reads the roster from Postgres, unless each chat server caches it.

The lab bug: a Pub/Sub failure after the store returned 500, so the retry could store the message twice. Sends now succeed when only the push fails. Reads now fall back to the stored maximum when Redis is down. The README section "What fails, and what still works" has the full table.

**Q: Can the whole Redis cluster fail? What then?** (2026-10-18)  
A: Yes, rarely. The causes:

- A bad config push or upgrade reaches every node.
- One shard loses both its primary and its replica. With the default `cluster-require-full-coverage yes`, the whole cluster then refuses requests.
- Memory exhaustion, for example from slow Pub/Sub subscribers.
- A zone or network split.

The system becomes read-only. Every send gets 503, and there is no live push. Reads, drains, and acks still work, because they fall back to the store.

- **Option A (pick):** accept read-only, and make it rare. Use replicas across zones, `cluster-require-full-coverage no`, and one-node-at-a-time rollouts. The outbox holds the messages.
- **Option B:** Option D for the counter, so sends survive. It costs a Postgres write per send.
- **Option C:** Option E, an owner server per chat. The hash ring becomes the dependency.
- **Option D:** an emergency switch to a backup sequencer. It risks two sequencers.

Polling `GET .../messages?afterSeq=` is the live-push backstop.

**Q: When is last seen written? How do I know if someone is online? Is typing a periodic message to the other side?** (2026-10-18)  
A: `last_seen` is written when a user's last device disconnects (socket close or a missed heartbeat), and the newer time wins. Hello Interview writes on disconnect only. Writing on connect too is an option for when a chat server crashes.

"Online" is not stored. The requester's server reads `last_seen` and publishes `getLastSeen` on the target's user channel. If a server holds the target, it answers `ONLINE` on the requester's channel. The client shows ONLINE if that answer comes, otherwise the stored time.

Typing is a throttled, unstored event: about one every 3 seconds while typing, published to members' user channels, hidden 5 seconds after the last one. It has no `seq`, no ack, and no drain. Read receipts come from the device cursor. The README table "Presence features: last seen, online, typing" compares all four. The lab fix: `last_seen` now keeps the newer time with `GREATEST`. The lab has no `getLastSeen` or `typing`.

**Q: Summarize every out-of-order case, server side and client side.** (2026-10-18)  
A: The README section "Message ordering" starts with two summary tables. They give each case, when it happens, what users would see, the fix, and how serious it is.

The one serious case is a counter that goes back after a Redis failover or restart. Postgres rejects the reused `seq`, but Cassandra overwrites the old message. Every other case is either correct by design (the server order wins), or fixed by `clientMsgId`, the contiguous ack, the gap fill, and the hole skip.
