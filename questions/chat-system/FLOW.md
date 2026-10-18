# System flow — Chat System

Each chart runs from the client to the load balancer, the chat server, and the store. Hello Interview is the shape source. These notes are original.

## Overview

```mermaid
flowchart LR
  lee[LeePhone]
  lb[LoadBalancer]
  a[ChatServerA]
  b[ChatServerB]
  pg[Postgres]
  redis[RedisPubSub]
  kim[KimLaptop]
  s3[S3]
  lee --> lb --> a
  kim --> lb --> b
  a --> pg
  a --> redis
  redis --> b
  b --> kim
  lee --> s3
  kim --> s3
```

## Send while online

```
sendMessage -> { messageId, status, seq, duplicate }
Body: {
  chatId,
  message,
  attachments,
  clientMsgId, // UUID per message. A retry sends the same one and gets the first seq back
  clientSeq    // this device's own counter in this chat. Detects a swap
}
```

```mermaid
sequenceDiagram
  participant L as LeePhone
  participant A as ChatServerA
  participant P as Postgres
  participant R as Redis
  participant B as ChatServerB
  participant K as KimLaptop
  L->>A: sendMessage
  A->>P: insert message
  A-->>L: success stored
  A->>R: PUBLISH user:kim
  R->>B: deliver
  B->>K: newMessage
  K-->>B: RECEIVED
  B->>P: move device cursor
```

## Send while offline

Same store. No Redis listener. On connect, drain after the device cursor.

```mermaid
sequenceDiagram
  participant L as LeePhone
  participant A as ChatServerA
  participant P as Postgres
  participant K as KimPhone
  participant C as ChatServerC
  L->>A: sendMessage
  A->>P: insert message
  A-->>L: success stored
  K->>C: connect
  C->>P: rows after cursor
  C->>K: newMessage list
  K-->>C: RECEIVED
  C->>P: move device cursor
```

## Design 2: send with Cassandra

The roster check stays in Postgres. The message row goes to Cassandra. The live push is the same.

```
POST /v1/messages -> 202 Accepted { messageId, status, seq, duplicate, outOfOrder, storedIn }
Body: {
  chatId,
  message,
  mediaKey,    // optional
  serverId,    // A | B
  clientId,
  clientMsgId, // optional UUID per message
  clientSeq    // optional device counter
}
storedIn: { store: "cassandra", table: "messages_by_chat", partition: { chat_id, bucket }, clustering: { seq }, ttlSeconds }
```

```mermaid
sequenceDiagram
  participant L as LeePhone
  participant A as ChatServerA
  participant P as Postgres
  participant R as Redis
  participant C as Cassandra
  participant B as ChatServerB
  participant K as KimLaptop
  L->>A: sendMessage
  A->>P: is lee in lee-kim? who are the members?
  A->>R: INCR chat:lee-kim:seq -> 6
  A->>C: INSERT messages_by_chat partition (lee-kim, 1), seq 6, TTL 30 days
  A->>C: UPDATE device_cursors_by_client lee-phone -> 6
  A-->>L: success stored
  A->>R: PUBLISH user:kim
  R->>B: deliver
  B->>K: newMessage
```

## Design 2: drain across buckets

```
POST /v1/lab/connect -> 200 OK { serverId, clientId, userId, status, drained, reads }
Body: {
  serverId, // A | B
  clientId
}
```

```mermaid
sequenceDiagram
  participant K as KimPhone
  participant B as ChatServerB
  participant P as Postgres
  participant R as Redis
  participant C as Cassandra
  K->>B: connect
  B->>P: chats for kim (chat_members by user_id)
  B->>C: cursor for kim-phone in lee-kim -> 3
  B->>R: GET chat:lee-kim:seq -> 6
  B->>C: partition (lee-kim, 0) WHERE seq > 3
  B->>C: partition (lee-kim, 1) WHERE seq > 3
  B->>K: newMessage 4, 5, 6
```

## Design 2: late ack

```
POST /v1/ack -> 200 OK { clientId, chatId, seq, cursor }
Body: {
  clientId,
  chatId,
  seq,
  mode // upsert (default) | lwt
}
```

```mermaid
sequenceDiagram
  participant K as KimLaptop
  participant B as ChatServerB
  participant C as Cassandra
  K->>B: ack 6
  B->>C: UPDATE last_seq = 6
  K->>B: delayed ack 4
  alt mode = upsert
    B->>C: UPDATE last_seq = 4 (last write wins)
    Note over K,C: next drain sends 5 and 6 again. Client drops by message id
  else mode = lwt
    B->>C: UPDATE last_seq = 4 IF last_seq < 4
    C-->>B: applied = false. Cursor stays 6
  end
```

## Image or video

```mermaid
sequenceDiagram
  participant L as LeePhone
  participant S as S3
  participant A as ChatServerA
  participant P as Postgres
  L->>S: upload bytes
  S-->>L: media key
  L->>A: sendMessage with media_key
  A->>P: insert row
```
