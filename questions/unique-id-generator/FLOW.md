# System flow — Unique ID Generator

Replace this stub with the real request and write paths when you design the system.

## Happy path

```mermaid
flowchart LR
  client[Client]
  api[API_or_Gateway]
  service[CoreService]
  store[PrimaryStore]
  client --> api --> service --> store
```

## Write path

```mermaid
sequenceDiagram
  participant C as Client
  participant S as Service
  participant D as Store
  C->>S: request
  S->>D: persist
  D-->>S: ack
  S-->>C: response
```

## Read path

TBD

## Failure / overload path

TBD — timeouts, retries, queues, degraded reads
