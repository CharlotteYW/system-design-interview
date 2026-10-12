# System flow — Notification System

Each chart runs from the client to the load balancer, the gateway, the service, and the database. The interview sequences are here. Schemas wait for the deep dive.

## Overview

```mermaid
flowchart LR
  client[Client]
  lb[LoadBalancer]
  gw[APIGateway]
  api[NotificationService]
  kv[KeyValueStore]
  pg[Postgres]
  kafka[Kafka]
  scheduler[Scheduler]
  worker[Worker]
  vendor[Vendor]
  client --> lb --> gw --> api
  api --> kv
  api --> pg
  scheduler --> pg
  scheduler --> kafka
  kafka --> worker
  worker --> vendor
  worker --> pg
```

## Save contact

```
PUT /v1/users/{userId}/contact -> 200 OK { userId }
Body: {
  email,
  phone,
  deviceToken
}
```

```mermaid
sequenceDiagram
  participant C as Dashboard
  participant L as LoadBalancer
  participant G as APIGateway
  participant A as NotificationService
  participant K as KeyValueStore
  C->>L: PUT contact
  L->>G: forward
  G->>A: session ok
  A->>K: user id to email, phone, device token
  A-->>C: saved
```

## Save preferences

```
PUT /v1/users/{userId}/preferences -> 200 OK { userId }
Body: {
  push,          // true | false
  email,         // true | false
  sms,           // true | false
  quietStart,    // optional, "22:00"
  quietEnd       // optional, "07:00"
}
```

```mermaid
sequenceDiagram
  participant C as Dashboard
  participant L as LoadBalancer
  participant G as APIGateway
  participant A as NotificationService
  participant K as KeyValueStore
  C->>L: PUT preferences
  L->>G: forward
  G->>A: session ok
  A->>K: user id to channels and quiet hours
  A-->>C: saved
```

## Send one notice now

```
POST /v1/notices -> 202 Accepted { id, status }
Body: {
  userId,
  channel,       // push | email | sms
  content,       // { title, body }
  priority,      // high | low, defaults to low
  scheduledAt,   // optional, defaults to now
  idempotencyKey // caller-generated. The same key returns the first notice
}
```

```mermaid
sequenceDiagram
  participant C as Upstream
  participant L as LoadBalancer
  participant G as APIGateway
  participant A as NotificationService
  participant P as Postgres
  participant S as Scheduler
  participant Q as Kafka
  participant W as Worker
  participant V as Vendor
  C->>L: POST notice
  L->>G: forward
  G->>A: session ok
  A->>P: notice, send record, and schedule row
  A-->>C: accepted
  S->>P: rows that are due
  S->>Q: one job
  S->>P: queued after Kafka accepts
  Q->>W: the job
  W->>V: SMS, email, or phone app push
  W->>P: sent or failed
```

## Send one notice later

Same path as a notice for now. `scheduledAt` is a future time. The schedule row waits until that time. The response is still `202 Accepted { id, status }`.

```
POST /v1/notices -> 202 Accepted { id, status }
Body: {
  userId,
  channel,       // push | email | sms
  content,       // { title, body }
  priority,      // high | low, defaults to low
  scheduledAt,   // future time
  idempotencyKey // caller-generated. The same key returns the first notice
}
```

```mermaid
sequenceDiagram
  participant C as Upstream
  participant L as LoadBalancer
  participant G as APIGateway
  participant A as NotificationService
  participant P as Postgres
  participant S as Scheduler
  participant Q as Kafka
  C->>L: POST notice with a future time
  L->>G: forward
  G->>A: session ok
  A->>P: notice, send record, and schedule row
  A-->>C: accepted
  S->>P: rows that are due
  S->>Q: one job
```

The worker path after Kafka is the same as a notice for now.

## Campaign

```
POST /v1/campaigns -> 202 Accepted { id, status }
Body: {
  userIds,
  channel,       // push | email | sms
  content,       // { title, body }
  scheduledAt,   // optional, defaults to now
  idempotencyKey // caller-generated. The same key returns the first campaign
}
```

```mermaid
sequenceDiagram
  participant C as Upstream
  participant L as LoadBalancer
  participant G as APIGateway
  participant A as NotificationService
  participant P as Postgres
  participant E as Expander
  participant S as Scheduler
  participant Q as Kafka
  C->>L: POST campaign
  L->>G: forward
  G->>A: session ok
  A->>P: one campaign row
  A-->>C: accepted
  E->>P: one notice and one schedule row per user
  S->>Q: one job per user
```

A future campaign stays in the schedule table until the scheduler starts the expander.

## Vendor timeout

The API has already returned. This path starts at the worker.

```mermaid
sequenceDiagram
  participant Q as Kafka
  participant W as Worker
  participant P as Postgres
  participant V as Vendor
  participant S as Scheduler
  Q->>W: notice id
  W->>P: accepted to sending
  W->>V: call
  V-->>W: timeout
  W->>P: accepted, next time, new schedule row
  W->>Q: commit offset
  S->>P: schedule row is due
  S->>Q: same notice id
```
