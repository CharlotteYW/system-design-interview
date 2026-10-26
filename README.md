# System Design Interview

Personal study repo for **software engineer system design interviews**.

The loop is: pick a **question** → five-step interview → local system; or pick a **core concept / key technology** → explain every variant → small demo.

Sources to study from (do not copy write-ups into this repo):

- [Hello Interview — System Design in a Hurry](https://www.hellointerview.com/learn/system-design/in-a-hurry/introduction)
- [Hello Interview — Core concepts](https://www.hellointerview.com/learn/system-design/in-a-hurry/core-concepts)
- [Hello Interview — Key technologies](https://www.hellointerview.com/learn/system-design/in-a-hurry/key-technologies)
- Alex Xu, *System Design Interview — An Insider's Guide* Vol 1 and Vol 2

## How to use this repo

New chat, or a different tool (Codex, Claude Code)? Start with [HANDOFF.md](HANDOFF.md). It has the current state, how a session runs, and the prompts to resume.

1. Skim [foundations](foundations/README.md) once so the vocabulary is in place.
2. In Cursor, prompt a **question** (`rate limiter`, `url-shortener`) **or** a **concept** (`Networking Essentials`, `message queue`).
3. Before that session starts, previous work is committed so `git status` is clean (see `.cursor/rules/04-commit-before-question.mdc`).
4. **Questions** follow [AGENTS.md](AGENTS.md) and the five-step interview pattern, then a full local stack. **Concepts** follow `.cursor/rules/12-prepare-a-concept.mdc`: teach variants in the README, then a small demo. After either, you can ask more; Q&A is saved in that folder. Practicing **again** updates the same folder.
5. For questions, read `README.md`, `FAQ.md`, `FLOW.md`, and `COMPONENTS.md`. For concepts, the README comparison table is the main doc.
6. Run `./scripts/setup.sh`, then tests, once **Implemented**. When the session is done, `./scripts/stop.sh` tears the stack down.

### Status

| Status | Meaning |
| --- | --- |
| **Stub** | Folder exists; placeholders only. Prompt the question or concept to fill it. |
| **Designed** | Docs filled; no running system yet (questions). |
| **Notes-only** | Concept README filled; no Docker (e.g. numbers-to-know). |
| **Implemented** | Docker stack + setup + tests work. |
| *(no folder)* | Listed in the index; created when you ask to prepare it. |

## Folder contract

Every question lives in `questions/<slug>/`:

| File | Role |
| --- | --- |
| `README.md` | Five interview steps + how to run |
| `FAQ.md` | Q&A in the same five steps |
| `FLOW.md` | System flowcharts (mermaid) |
| `COMPONENTS.md` | Each important piece: definition + functionality |
| `docker-compose.yml` | Local mocked components |
| `scripts/setup.sh` | Activate repo venv, then start frontend, backend, and data stores |
| `scripts/stop.sh` | Stop that question’s Compose stack (run when the session ends) |
| `scripts/run-scenarios.sh` | Integration tests against the running stack |
| `scripts/run-functional.sh` | Functional tests of user-visible flows |
| `src/` | Backend (and static frontend unless split) |
| `tests/` | Integration / functional helpers |

New questions: copy [`_templates/question/`](_templates/question/) to `questions/<slug>/` and add a row below.

## Concept labs

Hello Interview **core concepts** and **key technologies** live next to questions, not inside them. Prompt one topic at a time.

| Root | Index | Template |
| --- | --- | --- |
| [core-concepts/](core-concepts/) | 9 topics (networking, caching, CAP, …) | [`_templates/concept/`](_templates/concept/) |
| [key-technologies/](key-technologies/) | 11 topics (Postgres, Redis, queues, CDN, …) | same |

Each slug has a README whose **variant table** is the main study artifact, plus stub `scripts/` for a later demo. Not the five-step interview format. See `.cursor/rules/12-prepare-a-concept.mdc`.

## Python environment

One host venv for the whole repo: prompt **`system-design-interview`**, directory **`.venv/`** (gitignored). Question `setup.sh` / test scripts create and activate it via [`scripts/use-venv.sh`](scripts/use-venv.sh). App processes still run in Docker. Manual activate: `source .venv/bin/activate`.

## Patterns

The eight shapes that repeat across the questions live in [patterns/](patterns/). Seven come from the [Hello Interview list](https://www.hellointerview.com/blog/patterns). Proximity is the eighth, from their [patterns page](https://www.hellointerview.com/learn/system-design/in-a-hurry/patterns). Each note has the options, the pick, and every question that uses it. The index maps each question to one primary pattern.

## Learning path

Practice in this order. Each row adds one idea, and that idea uses the rows above it. A finished row stays in the list so the sequence stays clear. The next question is the first **Stub**.

This order is not the old starter path. That list only meant "a folder already exists." It is also not the chapter numbers. Volume 1 is finished before Volume 2, because the second book assumes the first. Hello Interview problems sit where their new idea fits.

Two names that are the same design share one folder. Dropbox is Google Drive. The game leaderboard is the real-time gaming leaderboard. Metrics monitoring, ad click aggregation, and the payment system each have one folder for the book chapter and the Hello Interview name.

### Already practiced

| # | Question | The new idea | Status |
| --- | --- | --- | --- |
| 1 | [Unique ID generator](questions/unique-id-generator/) | Issue IDs with no single counter | Implemented |
| 2 | [Rate limiter](questions/rate-limiter/) | Allow or reject one request | Implemented |
| 3 | [URL shortener](questions/url-shortener/) | One key lookup, then a redirect | Implemented |
| 4 | [Key-value store](questions/key-value-store/) | Partition and replicate | Implemented |
| 5 | [Notification system](questions/notification-system/) | A queue between accept and send | Implemented |
| 6 | [News feed](questions/news-feed/) | Fan-out into a home list | Implemented |
| 7 | [Chat system](questions/chat-system/) | Order, and live delivery | Implemented |
| 8 | [Web crawler](questions/web-crawler/) | A polite pipeline | Implemented |
| 9 | [YouTube](questions/youtube/) | A large upload, transcode, and a CDN | Implemented |

### Next

| # | Question | The new idea | Why it is here | Status |
| --- | --- | --- | --- | --- |
| 10 | [Search autocomplete](questions/search-autocomplete/) | A prefix tree and the top suggestions | The last small Volume 1 chapter. It uses counts | Stub |
| 11 | [Google Drive](questions/google-drive/) | Sync, chunks, and conflicts | The last Volume 1 chapter. Upload skills come from YouTube. Dropbox is this question | Stub |
| 12 | [Proximity service](questions/proximity-service/) | Find points near a point | Volume 2 starts here. Uber needs this index | Stub |
| 13 | [Nearby friends](questions/nearby-friends/) | Location plus a friend list | Adds the follow graph from the news feed | Stub |
| 14 | [Uber](questions/uber/) | Match one rider to one driver | The trip is new. The location index already exists | Stub |
| 15 | [Yelp](questions/yelp/) | Search places by area and by word | The geo index plus autocomplete | Stub |
| 16 | [Tinder](questions/tinder/) | Two people must both agree | A smaller match than a trip | Stub |
| 17 | [Google Maps](questions/google-maps/) | Map tiles and a route | Heavier than "find nearby" | Stub |
| 18 | [Local delivery](questions/local-delivery/) | Assign one delivery to one driver | Maps plus the Uber assignment | Stub |
| 19 | [Strava](questions/strava/) | A route and an activity feed | Maps plus the news feed | Stub |
| 20 | [Distributed message queue](questions/distributed-message-queue/) | The queue itself | The crawler and notifications only used a queue | Stub |
| 21 | [Job scheduler](questions/job-scheduler/) | Run work at a set time | It sits on the queue | Stub |
| 22 | [GitHub Actions](questions/github-actions/) | A pipeline of jobs | The scheduler, plus stored logs. Guided practice | Stub |
| 23 | [Metrics monitoring](questions/metrics-monitoring/) | Counters over time | Volume 2 chapter 5 | Stub |
| 24 | [Ad click aggregation](questions/ad-click-aggregation/) | Count events at a high rate | Uses the queue and the metrics | Stub |
| 25 | [YouTube Top K](questions/youtube-top-k/) | The heavy items in a stream | Aggregation, on the YouTube data | Stub |
| 26 | [Hotel reservation](questions/hotel-reservation/) | Hold one room for one guest | Inventory and a transaction | Stub |
| 27 | [Ticketmaster](questions/ticketmaster/) | Hold seats for a short time | The same inventory idea, on a hot event | Stub |
| 28 | [Flash sale](questions/flash-sale/) | One item and a huge burst | The hot row, on purpose | Stub |
| 29 | [Online auction](questions/online-auction/) | Bids and a closing time | The price now moves | Stub |
| 30 | [Distributed email](questions/distributed-email/) | Mailboxes and fan-out | Close to the notification system | Stub |
| 31 | [Object storage](questions/object-storage/) | Store and read large blobs | YouTube and the crawler used S3. This designs it | Stub |
| 32 | [Gaming leaderboard](questions/gaming-leaderboard/) | A ranked top list | The guided game leaderboard is this question | Stub |
| 33 | [Payment system](questions/payment-system/) | Charge a card once | Idempotency is the new idea | Stub |
| 34 | [Donations](questions/donations/) | A payment with a public total | The payment system, plus a counter. Guided practice | Stub |
| 35 | [Digital wallet](questions/digital-wallet/) | A balance and a transfer | Comes after the charge | Stub |
| 36 | [Stock exchange](questions/stock-exchange/) | An order book and a match | The hardest match | Stub |
| 37 | [Robinhood](questions/robinhood/) | A broker in front of the exchange | Uses the exchange and the wallet | Stub |
| 38 | [Instagram](questions/instagram/) | A feed of photos and video | The news feed, plus media from YouTube | Stub |
| 39 | [News aggregator](questions/news-aggregator/) | Collect articles and show a feed | The crawler plus the news feed | Stub |
| 40 | [Price tracking](questions/price-tracking/) | Watch a page and alert on a change | The crawler plus notifications | Stub |
| 41 | [Post search](questions/post-search/) | Search the text of posts | Autocomplete plus the feed | Stub |
| 42 | [Food review](questions/food-review/) | A review, a place, and a feed | Yelp plus the news feed. Guided practice | Stub |
| 43 | [LeetCode](questions/leetcode/) | Run code and judge it | A job queue with a sandbox | Stub |
| 44 | [Live comments](questions/live-comments/) | A live thread on one post | Chat, plus one hot read | Stub |
| 45 | [Google Docs](questions/google-docs/) | Many editors, one document | Drive, plus live updates from chat | Stub |
| 46 | [Online chess](questions/online-chess/) | One game, two players, ordered moves | The ordering idea from chat, on a board | Stub |
| 47 | [ChatGPT](questions/chatgpt/) | Stream a model reply | Needs the queue, the cache, and a stream. Last on purpose | Stub |

### Other prompts

Not a Hello Interview breakdown and not an Alex Xu chapter. Related delivery is the notification system.

| Question | Folder | Status |
| --- | --- | --- |
| One-time password | [questions/one-time-password](questions/one-time-password/) | Implemented |

## Full index

Overlapping names share **one** folder. Every name below has a folder. Prompt the next **Stub** on the learning path to fill it.

### Hello Interview — problem breakdowns

[Question list](https://www.hellointerview.com/learn/system-design/in-a-hurry/how-to-prepare)

| Question | Difficulty | Status | Notes |
| --- | --- | --- | --- |
| Bitly | Easy | [Implemented](questions/url-shortener/) | Same as URL shortener |
| Dropbox | Easy | [Stub](questions/google-drive/) | Same question as Google Drive (Vol 1 Ch 15) |
| Yelp | Easy | [Stub](questions/yelp/) | Related to Proximity Service (Vol 2) |
| Local Delivery Service | Easy | [Stub](questions/local-delivery/) | |
| Ticketmaster | Medium | [Stub](questions/ticketmaster/) | |
| Instagram | Medium | [Stub](questions/instagram/) | Same home-feed shape as news feed. The extra work is large photos and videos, and a much higher post rate. |
| FB News Feed | Medium | [Implemented](questions/news-feed/) | |
| Tinder | Medium | [Stub](questions/tinder/) | |
| LeetCode | Medium | [Stub](questions/leetcode/) | |
| WhatsApp | Medium | [Implemented](questions/chat-system/) | Two logical servers A/B; Redis Pub/Sub hop; Postgres vs Cassandra message store side by side; load test |
| Strava | Medium | [Stub](questions/strava/) | |
| Distributed Cache | Medium | [Implemented](questions/key-value-store/) | |
| Rate Limiter | Medium | [Implemented](questions/rate-limiter/) | |
| Online Auction | Medium | [Stub](questions/online-auction/) | |
| YouTube | Medium | [Implemented](questions/youtube/) | MinIO presigned multipart with per-part SHA-256; S3 event to an ffmpeg chunk x rendition pipeline; HLS through nginx edges and an origin shield |
| Job Scheduler | Medium | [Stub](questions/job-scheduler/) | |
| FB Live Comments | Medium | [Stub](questions/live-comments/) | |
| News Aggregator | Medium | [Stub](questions/news-aggregator/) | |
| Price Tracking Service | Medium | [Stub](questions/price-tracking/) | |
| Notification System | Medium | [Implemented](questions/notification-system/) | Redis lists stand in for the two Kafka topics |
| YouTube Top K | Hard | [Stub](questions/youtube-top-k/) | |
| Uber | Hard | [Stub](questions/uber/) | |
| Robinhood | Hard | [Stub](questions/robinhood/) | Related to Stock Exchange (Vol 2) |
| Google Docs | Hard | [Stub](questions/google-docs/) | |
| Web Crawler | Hard | [Implemented](questions/web-crawler/) | ElasticMQ (SQS API) and DynamoDB Local stand in for SQS and DynamoDB |
| Ad Click Aggregator | Hard | [Stub](questions/ad-click-aggregation/) | Same as Vol 2 Ad Click Event Aggregation |
| FB Post Search | Hard | [Stub](questions/post-search/) | |
| Payment System | Hard | [Stub](questions/payment-system/) | Same as Vol 2 Payment System |
| Metrics Monitoring | Hard | [Stub](questions/metrics-monitoring/) | Same as Vol 2 Metrics Monitoring |
| Online Chess | Hard | [Stub](questions/online-chess/) | |
| ChatGPT | Hard | [Stub](questions/chatgpt/) | |
| Flash Sale | Hard | [Stub](questions/flash-sale/) | |

Guided-practice extras (Hello Interview, no written breakdown required): [Food Review](questions/food-review/) (Stub), Game Leaderboard (same question as [Gaming leaderboard](questions/gaming-leaderboard/)), [Donations](questions/donations/) (Stub), [GitHub Actions](questions/github-actions/) (Stub).

### Alex Xu Vol 1

Ch 1–3 are foundations (scale, estimation, framework) — see [foundations](foundations/README.md). Design chapters:

| Chapter | Question | Status |
| --- | --- | --- |
| 4 | Rate limiter | [Implemented](questions/rate-limiter/) |
| 5 | Consistent hashing | [Implemented](core-concepts/consistent-hashing/) (as a core concept) |
| 6 | Key-value store | [Implemented](questions/key-value-store/) |
| 7 | Unique ID generator | [Implemented](questions/unique-id-generator/) |
| 8 | URL shortener | [Implemented](questions/url-shortener/) |
| 9 | Web crawler | [Implemented](questions/web-crawler/) |
| 10 | Notification system | [Implemented](questions/notification-system/) |
| 11 | News feed | [Implemented](questions/news-feed/) |
| 12 | Chat system | [Implemented](questions/chat-system/) |
| 13 | Search autocomplete | [Stub](questions/search-autocomplete/) |
| 14 | YouTube | [Implemented](questions/youtube/) |
| 15 | Google Drive | [Stub](questions/google-drive/) |

### Alex Xu Vol 2

| Chapter | Question | Status |
| --- | --- | --- |
| 1 | Proximity service | [Stub](questions/proximity-service/). Uber reuses this index |
| 2 | Nearby friends | [Stub](questions/nearby-friends/) |
| 3 | Google Maps | [Stub](questions/google-maps/) |
| 4 | Distributed message queue | [Stub](questions/distributed-message-queue/) |
| 5 | Metrics monitoring | [Stub](questions/metrics-monitoring/) |
| 6 | Ad click event aggregation | [Stub](questions/ad-click-aggregation/) |
| 7 | Hotel reservation | [Stub](questions/hotel-reservation/) |
| 8 | Distributed email service | [Stub](questions/distributed-email/) |
| 9 | S3-like object storage | [Stub](questions/object-storage/) |
| 10 | Real-time gaming leaderboard | [Stub](questions/gaming-leaderboard/) |
| 11 | Payment system | [Stub](questions/payment-system/) |
| 12 | Digital wallet | [Stub](questions/digital-wallet/) |
| 13 | Stock exchange | [Stub](questions/stock-exchange/) |

## Adding a question later

Tell Cursor the question name. It should:

1. Copy `_templates/question/` → `questions/<slug>/`
2. Fill title, sources, and this index
3. Design (README, FAQ, FLOW, COMPONENTS)
4. Implement frontend + backend + database and wire `setup.sh` / `run-scenarios.sh` / `run-functional.sh` / `stop.sh`

## Notes

Original notes only. Link to Hello Interview; cite Alex Xu by volume and chapter. The local systems are teaching models, not production architecture.
