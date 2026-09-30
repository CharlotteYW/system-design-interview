# System flow — Key-Value Store

Original notes from the 2026-09-28 session. The coordinator is any server the client can reach. The key’s copies are three neighbors on the ring.

## Who accepts the call

```mermaid
flowchart LR
  client[Client]
  lb[Load balancer]
  s1[Server 1]
  s2[Server 2]
  s3[Server N]
  client --> lb
  lb -->|round-robin, key ignored| s1
  lb -->|round-robin, key ignored| s2
  lb -->|round-robin, key ignored| s3
```

The server that received the call hashes the key and becomes the coordinator. Every server can do that hash. A gateway that picked the three replicas itself is not in this path.

## Happy path

```mermaid
flowchart LR
  client[Client]
  coord[Coordinator]
  a[Replica A]
  b[Replica B]
  c[Replica C]
  client --> coord
  coord --> a
  coord --> b
  coord --> c
```

## Write path

Put and delete use the same path. Delete stores a tombstone instead of a value. Success is 2 acknowledgements out of 3.

```mermaid
sequenceDiagram
  participant C as Client
  participant S as Coordinator
  participant A as Replica A
  participant B as Replica B
  participant D as Replica C
  C->>S: PUT or DELETE key
  S->>S: hash key, preference list of 3
  par wait for 2
    S->>A: write local LSM
    S->>B: write local LSM
  and
    S->>D: write local LSM
  end
  A-->>S: ack
  B-->>S: ack
  S-->>C: success
```

## Read path

Get asks 2 of the 3 replicas and returns the newer value, unless this coordinator already has the key in its L1 map. If one replica is down, the other two still answer.

```mermaid
sequenceDiagram
  participant C as Client
  participant S as Coordinator
  participant L1 as L1 on that server
  C->>S: GET hot key
  S->>L1: lookup
  alt hit
    L1-->>S: value and version
    S-->>C: cached value
  else miss
    S->>S: one read of 2 replicas fills L1
    S-->>C: newer value
  end
```

On a miss, that one fill reads two replicas and returns the newer version:

```mermaid
sequenceDiagram
  participant C as Client
  participant S as Coordinator
  participant A as Replica A
  participant B as Replica B
  C->>S: GET key
  S->>A: read
  S->>B: read
  A-->>S: value and version
  B-->>S: value and version
  S-->>C: newer value
```

## Failure path

One replica down: put and get still succeed on the remaining pair. The coordinator does not wait for a slow third replica past a timeout; that timeout is for one call, and the server stays on the ring until timeouts repeat. Two replicas down or two timeouts: the coordinator returns an error rather than acknowledging a write that has only one copy. A tombstone that never reaches a replica lets that replica put the old value back during a later repair. The whole region down: every copy is unreachable, and 2-of-3 does not apply.
