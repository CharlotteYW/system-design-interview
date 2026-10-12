# High-level design comparison — Notification System

Read this file on the next pass. It compares the database, the high-level path, and every feature. It does not replace [README.md](README.md).

The columns are Hello Interview, Alex Xu volume 1 chapter 10, this session, and production. The open Hello Interview page names the behavior and the 5,000-notice peak. It does not name a store. A store that source does not name stays "not in that source." No public post is cited here for a full production platform.

## Database choice

| Data | Hello Interview | Alex Xu, chapter 10 | This session | Production |
| --- | --- | --- | --- | --- |
| Contact | Not in that source | A database of user contact and device info | Key-value store. The key is the user id | Not in a cited post |
| Preference | Not in that source | A database of user settings | Key-value store. The key is the user id | Not in a cited post |
| Notice | Not in that source | Not named as its own table in the chapter summary used here | Postgres | Not in a cited post |
| Schedule row | Not in that source | Not in that source | Postgres | Not in a cited post |
| Campaign | Not in that source | Not in that source | Postgres | Not in a cited post |
| Send record | Not in that source | A record that a notice was attempted | Postgres. The key is notice id plus channel | Not in a cited post |
| Queue job | Not in that source | A message queue | Kafka. `notices-high` for a login code. `notices-low` for a campaign | Not in a cited post |

## High-level design choice

| Source | Boxes on the happy path | What a send does before it returns |
| --- | --- | --- |
| Hello Interview | Not drawn on the open page. The page stresses a 5,000-notice surge | Not in that source |
| Alex Xu, chapter 10 | A notification service, a message queue, workers, and third-party senders | Accept the request and hand it to the queue |
| This session | Load balancer, gateway, Notification service, key-value store, Postgres, scheduler, Kafka, expander, workers, vendors | One Postgres commit writes the notice and a schedule row. The scheduler publishes |
| Production | Not in a cited post | Not in a cited post |

## Save contact

1. The dashboard sends email, phone number, and device token.
2. The service stores them under the user id.
3. The call returns.

| Source | Steps that differ | Database |
| --- | --- | --- |
| Hello Interview | The core lines assume the contact exists. They do not draw this write | Not in that source |
| Alex Xu, chapter 10 | Workers read device info from the user store | A database |
| This session | Dashboard, load balancer, gateway, Notification service, key-value store | Key-value store |

## Save preferences

1. The dashboard sends channel switches and quiet hours.
2. The service stores them under the user id.
3. The worker reads them again at send time.

| Source | Steps that differ | Database |
| --- | --- | --- |
| Hello Interview | Users set channel opt-outs and quiet hours | Not in that source |
| Alex Xu, chapter 10 | Settings live with the user record. A send respects them | A database |
| This session | The same path as contact. The worker checks quiet hours at send time | Key-value store |

## Send one notice

1. An upstream service names one user, one channel, the text, and a time.
2. The service stores the notice and returns.
3. A worker calls the vendor.

| Source | Steps that differ | Database |
| --- | --- | --- |
| Hello Interview | Send now or at a future time, by push, email, or SMS | Not in that source |
| Alex Xu, chapter 10 | Queue, then a worker, then a third party | A message queue and a database |
| This session | Now and later both commit a schedule row. The scheduler publishes after that commit. The API does not call Kafka | Postgres and Kafka |

## Send a campaign

1. An upstream service names many users and one message.
2. The service stores one campaign and returns.
3. An expander adds one job per user.
4. The same workers call the vendors.

| Source | Steps that differ | Database |
| --- | --- | --- |
| Hello Interview | One message to a segment, now or scheduled. The surge is 5,000 per second | Not in that source |
| Alex Xu, chapter 10 | The chapter focuses on one-user delivery and third parties | Not in that source |
| This session | The expander writes one schedule row per user. The scheduler publishes those ids | Postgres and Kafka |

## Send record

1. The accept path inserts the record.
2. The worker sets sent or failed after the vendor call.
3. Sent means the vendor accepted the call.

| Source | Steps that differ | Database |
| --- | --- | --- |
| Hello Interview | Open rate and click-through are below the line | Not in that source |
| Alex Xu, chapter 10 | Track success and failure so a send can be retried | A database |
| This session | Key is notice id plus channel. Status is accepted, sending, sent, or failed. A temporary failure inserts a schedule row | Postgres |

## What this session keeps

The average is about 1 million notices a day, about 12 per second. The design point is 5,000 per second. The caller returns after Postgres has the notice. A single notice should reach an allowed channel within 2 minutes. A high notice should reach the vendor within 5 seconds. Each vendor budget reserves 100 sends per second for that high path.

The happy path is closest to Alex Xu chapter 10: a service, a queue, workers, and third-party vendors. This session adds an explicit schedule table, a campaign expander, and a key-value store for contact and preference. Hello Interview supplies the three core actions and the surge number. The open page does not name the stores.

## Sources

- Hello Interview, Notification System: https://www.hellointerview.com/learn/system-design/problem-breakdowns/notification-system
- Alex Xu, *System Design Interview*, volume 1, chapter 10, "Design a Notification System"
