# High-level design comparison — Chat System

Read this file on the next pass. It compares the database, the high-level path, and every feature. It does not replace [README.md](README.md).

The columns are Hello Interview (WhatsApp), Alex Xu volume 1 chapter 12, this session, and production. Hello Interview puts every row in DynamoDB. Alex Xu splits generic data into a relational database and chat history into a key-value store. This session keeps one Postgres for the lab and the interview happy path. Production cites Discord's public posts on message storage only.

## Database choice

| Data | Hello Interview | Alex Xu, chapter 12 | This session | Production |
| --- | --- | --- | --- | --- |
| Chat | DynamoDB `Chat` table | Relational database for generic data | Postgres `chats` | Not in a cited post |
| Chat member | DynamoDB `ChatParticipant`. Partition key `chatId`, sort key `participantId`. A GSI on `participantId` lists chats for a user | Not named as its own table. Generic data sits in the relational database | Postgres `chat_members`. Primary key `(chat_id, user_id)` | Not in a cited post |
| Device | DynamoDB `Clients` table, by user id | A key-value store keeps the latest message id for each device | Postgres `clients` | Not in a cited post |
| Message | DynamoDB `Message` table, with a TTL | Key-value store. The chapter names HBase and Cassandra as examples. Group rows are keyed by channel id and message id | Lab: Postgres `messages`, unique `(chat_id, seq)`. Interview at scale: wide-column store (Cassandra), primary key `((chat_id, bucket), seq)`, 30-day TTL | Discord: Cassandra from 2017, later ScyllaDB. Key `((channel_id, bucket), message_id)`, about 10 days per bucket. Facebook Messenger: HBase from 2010, moved to MyRocks (MySQL on RocksDB) in 2018 |
| Undelivered work | DynamoDB `Inbox`, per client. Ack deletes the row | A message sync queue for each recipient in a small group | No inbox. `device_cursors` with `last_seq` per `(client_id, chat_id)` | Not in a cited post |
| Last seen | DynamoDB table of the last disconnect, with a conditional write | Presence servers and a key-value store | Postgres `last_seen` | Not in a cited post |
| Live bus | Redis Pub/Sub, a channel per user. Rates a Kafka topic per user as not working, and consistent-hashed chat servers as Good | Not in that source | Redis Pub/Sub `user:{id}`. `chat:{id}` for 25 or more members | Slack: channel servers on a consistent hash ring by channel id, with gateway servers that hold the WebSockets |
| Media file | Blob storage with a pre-signed URL | Not in that source | S3. The message row keeps `media_key` | Not in a cited post |

## High-level design choice

| Source | Boxes on the happy path | What a send does before it returns |
| --- | --- | --- |
| Hello Interview | L4 load balancer, chat servers with WebSockets, DynamoDB, Redis Pub/Sub, blob storage | Write the message and an inbox row for each recipient, then return SUCCESS |
| Alex Xu, chapter 12 | Stateless API servers, stateful chat servers, presence servers, key-value store, service discovery | Store the message, then push or put it in each recipient's sync queue |
| This session | Load balancer, gateway, chat servers A and B, Postgres, Redis Pub/Sub, S3 | Assign `seq` with Redis `INCR`, insert into `messages`, move the sender cursor, return. Then publish |
| Production | Discord's posts cover only the message store | Not in a cited post |

## Send a message

1. Lee's phone sends `sendMessage` with `chatId` and the body.
2. The chat server checks that Lee is a member.
3. The server stores the message, returns success, then pushes to members.

| Source | Steps that differ | Database |
| --- | --- | --- |
| Hello Interview | Query `ChatParticipant` by `chatId`. Write `Message` and one `Inbox` row per recipient client | DynamoDB |
| Alex Xu, chapter 12 | The message id is ordered inside the channel. Push to online users | Key-value store |
| This session | Read `chat_members`, insert one `messages` row, publish on `user:{id}` | Postgres and Redis |

## Start a group chat

1. Lee names two to 100 user ids.
2. The service writes the chat and one member row per user.

| Source | Steps that differ | Database |
| --- | --- | --- |
| Hello Interview | One DynamoDB transaction for up to 100 items. Batch near the limit | DynamoDB `Chat` and `ChatParticipant` |
| Alex Xu, chapter 12 | Small groups copy each message into each member's queue | Relational for generic data |
| This session | One Postgres transaction writes `chats` and `chat_members` | Postgres |

## Offline delivery

1. Kim's phone reconnects.
2. The server finds what Kim missed.
3. The server sends it, and Kim acks.

| Source | Steps that differ | Database |
| --- | --- | --- |
| Hello Interview | Read the client's `Inbox`, load each message, delete the inbox row on ack | DynamoDB |
| Alex Xu, chapter 12 | Each device keeps its latest message id and fetches newer ones | Key-value store |
| This session | Read Kim's chats from `chat_members`, then `seq > last_seq` in each chat | Postgres |

## Image or video

1. The phone uploads the file.
2. The message carries the object key.
3. Each device downloads with a short-lived URL.

| Source | Steps that differ | Database |
| --- | --- | --- |
| Hello Interview | Upload to blob storage with a pre-signed URL. Skip the CDN at 100 members | Blob storage |
| Alex Xu, chapter 12 | Not in that source | Not in that source |
| This session | Upload to S3. Store `media_key` on the message row | S3 and Postgres |

## Multiple devices

1. Kim has a phone and a laptop.
2. Each device gets the message and acks on its own.

| Source | Steps that differ | Database |
| --- | --- | --- |
| Hello Interview | `Clients` table by user. The inbox is per client. Limit about 3 clients | DynamoDB |
| Alex Xu, chapter 12 | Each device keeps its own latest message id | Key-value store |
| This session | `clients` per user. One cursor per `(client_id, chat_id)` | Postgres |

## What this session keeps

- One Postgres for the lab and the interview happy path. The tables are small except `messages`.
- `chat_members` stays in Postgres with a primary key `(chat_id, user_id)` and an index on `user_id`. The two indexes answer the same two queries as the Hello Interview GSI.
- Cursors in place of an inbox. One row per device per chat is smaller than one row per message per device.
- At about 100,000 writes per second (the Hello Interview estimate), move `messages` to a wide-column store such as Cassandra. The partition key is `(chat_id, bucket)`, and the clustering key is `seq`. A bucket holds a fixed time window, so one old chat does not grow one partition forever. The TTL drops rows after 30 days. Sharded Postgres by `chat_id` is the other valid path. DynamoDB is a third.
- `chats`, `chat_members`, and `clients` stay in Postgres. They change rarely, and create-chat needs one transaction.
- `seq` still comes from Redis `INCR`. Cassandra has no safe per-chat counter for this use.
- The lab runs both: design 1 on port 8000 (Postgres) and design 2 on port 8001 (Cassandra). `/compare` shows them side by side. See the README section "Two message-store designs."
- The happy path is closest to Hello Interview for the live bus. It is closest to Alex Xu for the per-device cursor.

## Sources

- Hello Interview, "Design WhatsApp": https://www.hellointerview.com/learn/system-design/problem-breakdowns/whatsapp
- Alex Xu, *System Design Interview* volume 1, chapter 12, "Design a Chat System."
- Discord, "How Discord Stores Billions of Messages" (2017): https://discord.com/blog/how-discord-stores-billions-of-messages
- Discord, "How Discord Stores Trillions of Messages" (2023): https://discord.com/blog/how-discord-stores-trillions-of-messages
- Slack Engineering, "Real-time Messaging" (2023): https://slack.engineering/real-time-messaging/
- Facebook Engineering, "Migrating Messenger storage to optimize performance" (2018): https://engineering.fb.com/2018/06/26/core-infra/migrating-messenger-storage-to-optimize-performance/
