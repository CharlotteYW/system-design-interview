# Components — Notification System

| Component | Definition | Functionality in this design |
| --- | --- | --- |
| Client | Dashboard or an upstream service | Saves contact and preferences. Posts a notice or a campaign |
| Load balancer | Front door | Sends each call to one healthy gateway |
| API gateway | Session check | Routes contact, preference, notice, and campaign calls |
| Notification service | Intake API | Writes contact and preference. Stores a notice or a campaign and returns |
| Key-value store | One value per key | Holds contact, preference, and the provider token buckets |
| Postgres | Row store | Holds the notice, the schedule row, the campaign, and the send record |
| Kafka | Durable queue | One job per notice. `notices-high` and `notices-low` |
| Scheduler | Timer | The only publisher. Reads due schedule rows, publishes the notice id, then sets the row queued |
| Expander | Campaign fan-out | Writes one notice and one schedule row per user. It does not publish |
| Worker | Vendor caller | Takes a provider token, then claims the send record and calls the vendor |
| Vendor | Outside sender | Twilio for SMS. An email vendor. Apple or Google for a phone app notification |

## Why these pieces

- The load balancer, the gateway, Notification service, the key-value store, and Postgres carry contact and preference writes.
- Kafka, the scheduler, the expander, and the workers carry delivery. The API returns before the vendor call.
- `notices-high` has its own workers. `notices-low` has its own workers. A campaign does not occupy the high workers.
- An object store and a CDN are out. This system does not store the image or the video.
