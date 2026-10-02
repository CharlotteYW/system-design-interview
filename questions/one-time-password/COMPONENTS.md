# Components — One-Time Password

| Component | Definition | Functionality in this design |
| --- | --- | --- |
| Client | Login or payment app | Calls generate, shows “code sent”, submits the digits the user typed |
| Load balancer | Spreads HTTP across API processes | Health checks. No OTP state. |
| OTP API | Stateless FastAPI handlers | Generate, verify, cooldown, attempt count. Does not call the SMS provider. |
| Redis | In-memory keys with TTL | Live code hash, attempts left, per-destination cooldown, per-IP generate counter |
| Delivery queue | Buffer of send jobs | Holds destination, channel, purpose, and the plaintext until a worker takes it |
| Delivery worker | Process that talks to providers | Sends SMS or email, retries, then drops the plaintext |
| SMS / email provider | External channel | Outside our latency budget. Treated as a slow dependency. |

Object storage and a CDN do not appear. The payload is a few digits.

## Why these pieces

- Load-bearing: API, Redis, queue, worker. Without the queue, generate waits on the carrier and misses the 100 ms budget.
- Optional at 1,000/s: a separate API gateway, a Postgres audit of “we sent something” (no digits), a second SMS provider.
- Left in the deep dive: the exact Redis commands for compare-and-delete, the hash function, and what the worker does when the provider is down.

## Store choice

Redis holds the live code. About 600,000 keys, on the order of 60 MB, each gone at 10 minutes. A Postgres row with `used` and `expires_at` is the alternative that wins when the team already runs Postgres and will add a delete job plus a transaction around verify.

A second Postgres table is the audit log: time, destination hash, purpose, channel, and result (`issued`, `delivered`, `verified`, `failed`). It does not store the 6 digits or the code hash. Verify does not read it. This interview leaves that table out. Production adds it when a compliance question is “who was sent a code,” and the write can be async.

Published products: [Twilio Verify](https://www.twilio.com/docs/api/errors/60202) keeps the code inside Twilio (5 checks, then wait out a 10-minute verification). [Auth0 passwordless](https://auth0.com/docs/authenticate/passwordless/best-practices) keeps it inside Auth0 (latest code only, 3 misses, 3 minutes by default). An [AWS sample](https://aws.amazon.com/blogs/messaging-and-targeting/build-a-secure-one-time-password-architecture-with-aws/) stores the live code in DynamoDB, encrypted with KMS, and deletes the item on success. None of those writeups name Postgres as the live-code store.
