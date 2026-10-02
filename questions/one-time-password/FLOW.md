# System flow — One-Time Password

## Happy path

```mermaid
flowchart LR
  client[Client]
  lb[LoadBalancer]
  api[OTP_API]
  redis[(Redis)]
  queue[DeliveryQueue]
  worker[DeliveryWorker]
  provider[SMS_or_Email]
  client --> lb --> api
  api --> redis
  api --> queue --> worker --> provider
```

## Generate

```mermaid
sequenceDiagram
  participant C as Client
  participant A as OTP_API
  participant R as Redis
  participant Q as DeliveryQueue
  participant W as Worker
  participant P as Provider
  C->>A: POST /v1/otps
  A->>R: cooldown and IP cap
  A->>R: SET hash, attempts, TTL 10 min
  A->>Q: destination, channel, plaintext
  A-->>C: 202 expires_in 600
  Q->>W: job
  W->>P: SMS or email
  Note over W: plaintext dropped after accept
```

The API returns only after Redis has the hash and the queue has accepted the job. A code that was never stored is never sent.

## Verify

```mermaid
sequenceDiagram
  participant C as Client
  participant A as OTP_API
  participant R as Redis
  C->>A: POST /v1/otps/verify
  A->>R: read destination plus purpose
  A->>R: Lua on destination plus purpose
  alt hash matches
    R-->>A: key deleted
    A-->>C: 200 ok true
  else wrong, missing, or fifth failure
    R-->>A: attempts incremented, or key deleted at 5
    A-->>C: 400 ok false
  end
```

Success and failure use the same response shape. The body does not say whether the destination was unknown.

## Failure

- Redis write fails: no queue message, the API returns an error, the client may retry.
- Queue write fails after Redis: delete the new key, return an error, so the cooldown does not trap the user with a code that was never sent.
- Provider fails: the worker retries with backoff. The code remains verifiable until the 10-minute TTL. The user can request another code after the 60-second cooldown.
- Two verifies at once: the delete runs as one Redis operation, so only one caller observes success.
