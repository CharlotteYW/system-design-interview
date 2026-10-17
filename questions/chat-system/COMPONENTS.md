# Components — Chat System

| Component | Definition | Functionality in this design |
| --- | --- | --- |
| Client | Phone or laptop app | Holds a WebSocket. Sends commands. Acks messages. Drains on reconnect |
| Load balancer | Front door for sockets | Sends a new connection to one healthy chat server |
| Chat server | Long-lived socket host | Stores messages. Publishes live pushes. Drains cursors |
| Postgres | Durable row store | Design 1: chats, members, messages, clients, device cursors, last seen. Design 2: the same without messages and device cursors |
| Cassandra | Wide-column store | Design 2 only. `messages_by_chat` keyed `((chat_id, bucket), seq)` with a 30-day TTL, and `device_cursors_by_client` keyed `((client_id), chat_id)` |
| Redis | Counter and live bus | `INCR chat:{id}:seq` assigns `seq`. Pub/Sub channel per user carries the live push. At most once. Not the message store |
| S3 | Object store | Holds image and video bytes. Message row stores the key |

## Why these pieces

- The chat server returns success only after the message store accepts the write.
- Redis carries the live push when Lee and Kim are on different hosts.
- S3 holds media. The chat server does not store the file bytes.
- A worker queue is not on the happy path. Offline delivery is the cursor drain.
- Cassandra replaces Postgres only for the two tables that grow with traffic. The roster stays relational, because create-chat writes the chat and its members in one transaction.
