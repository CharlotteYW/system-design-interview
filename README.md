# System Design Interview

Personal study repo for **software engineer system design interviews**.

The loop is: pick a question → walk the **five-step interview pattern** (scope → high-level → deep dive → special situations → summary) → implement a **simplified local system** (Python + FastAPI + Docker) → run setup and tests until the idea is concrete.

Sources to study from (do not copy write-ups into this repo):

- [Hello Interview — System Design in a Hurry](https://www.hellointerview.com/learn/system-design/in-a-hurry/introduction)
- Alex Xu, *System Design Interview — An Insider's Guide* Vol 1 and Vol 2

## How to use this repo

1. Skim [foundations](foundations/README.md) once so the vocabulary is in place.
2. In Cursor, prompt a question by name (`rate limiter`, `design Uber`, `url-shortener`, or a new one).
3. Before that question starts, previous work is committed so `git status` is clean (see `.cursor/rules/04-commit-before-question.mdc`).
4. The agent should follow [AGENTS.md](AGENTS.md) and `.cursor/rules/`: you answer each interview step; the agent analyzes it, covers options and tradeoffs, then implements. Practicing a question **again** updates that folder’s docs and code.
5. Read that folder's `README.md`, `FAQ.md`, `FLOW.md`, and `COMPONENTS.md`.
6. Run `./scripts/setup.sh` (creates/activates the `system-design-interview` venv, then starts Docker), then `./scripts/run-scenarios.sh` (integration) and `./scripts/run-functional.sh` (functional) once it is **Implemented**.

### Status

| Status | Meaning |
| --- | --- |
| **Stub** | Folder exists; placeholders only. Prompt the question to fill it. |
| **Designed** | Docs filled; no running system yet. |
| **Implemented** | Docker stack (UI + API + DB) + setup + integration + functional tests work. |
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
| `scripts/run-scenarios.sh` | Integration tests against the running stack |
| `scripts/run-functional.sh` | Functional tests of user-visible flows |
| `src/` | Backend (and static frontend unless split) |
| `tests/` | Integration / functional helpers |

New questions: copy [`_templates/question/`](_templates/question/) to `questions/<slug>/` and add a row below.

## Python environment

One host venv for the whole repo: prompt **`system-design-interview`**, directory **`.venv/`** (gitignored). Question `setup.sh` / test scripts create and activate it via [`scripts/use-venv.sh`](scripts/use-venv.sh). App processes still run in Docker. Manual activate: `source .venv/bin/activate`.

## Starter path (folders exist)

Recommended order. Prompt a question to fill a stub. URL shortener is **Implemented**.

| # | Question | Folder | Sources |
| --- | --- | --- | --- |
| 1 | URL shortener (Bitly) | [questions/url-shortener](questions/url-shortener/) | Hello Interview · Alex Xu Vol 1 Ch 8 · **Implemented** |
| 2 | Rate limiter | [questions/rate-limiter](questions/rate-limiter/) | Hello Interview · Alex Xu Vol 1 Ch 4 |
| 3 | Unique ID generator | [questions/unique-id-generator](questions/unique-id-generator/) | Alex Xu Vol 1 Ch 7 |
| 4 | Key-value store / distributed cache | [questions/key-value-store](questions/key-value-store/) | Hello Interview · Alex Xu Vol 1 Ch 6 |
| 5 | Notification system | [questions/notification-system](questions/notification-system/) | Hello Interview · Alex Xu Vol 1 Ch 10 |
| 6 | News feed | [questions/news-feed](questions/news-feed/) | Hello Interview (FB News Feed) · Alex Xu Vol 1 Ch 11 |
| 7 | Chat system (WhatsApp) | [questions/chat-system](questions/chat-system/) | Hello Interview · Alex Xu Vol 1 Ch 12 |
| 8 | YouTube | [questions/youtube](questions/youtube/) | Hello Interview · Alex Xu Vol 1 Ch 14 |
| 9 | Web crawler | [questions/web-crawler](questions/web-crawler/) | Hello Interview · Alex Xu Vol 1 Ch 9 |
| 10 | Uber / ride matching | [questions/uber](questions/uber/) | Hello Interview · related: Alex Xu Vol 2 Proximity Service |

## Full index

Overlapping names share **one** future folder. Prompt any of these to add the folder from the template.

### Hello Interview — problem breakdowns

[Question list](https://www.hellointerview.com/learn/system-design/in-a-hurry/how-to-prepare)

| Question | Difficulty | Status | Notes |
| --- | --- | --- | --- |
| Bitly | Easy | [Implemented](questions/url-shortener/) | Same as URL shortener |
| Dropbox | Easy | listed | Related to Google Drive (Vol 1 Ch 15) |
| Yelp | Easy | listed | Related to Proximity Service (Vol 2) |
| Local Delivery Service | Easy | listed | |
| Ticketmaster | Medium | listed | |
| Instagram | Medium | listed | Related to news feed |
| FB News Feed | Medium | [Stub](questions/news-feed/) | |
| Tinder | Medium | listed | |
| LeetCode | Medium | listed | |
| WhatsApp | Medium | [Stub](questions/chat-system/) | |
| Strava | Medium | listed | |
| Distributed Cache | Medium | [Stub](questions/key-value-store/) | |
| Rate Limiter | Medium | [Stub](questions/rate-limiter/) | |
| Online Auction | Medium | listed | |
| YouTube | Medium | [Stub](questions/youtube/) | |
| Job Scheduler | Medium | listed | |
| FB Live Comments | Medium | listed | |
| News Aggregator | Medium | listed | |
| Price Tracking Service | Medium | listed | |
| Notification System | Medium | [Stub](questions/notification-system/) | |
| YouTube Top K | Hard | listed | |
| Uber | Hard | [Stub](questions/uber/) | |
| Robinhood | Hard | listed | Related to Stock Exchange (Vol 2) |
| Google Docs | Hard | listed | |
| Web Crawler | Hard | [Stub](questions/web-crawler/) | |
| Ad Click Aggregator | Hard | listed | Same as Vol 2 Ad Click Event Aggregation |
| FB Post Search | Hard | listed | |
| Payment System | Hard | listed | Same as Vol 2 Payment System |
| Metrics Monitoring | Hard | listed | Same as Vol 2 Metrics Monitoring |
| Online Chess | Hard | listed | |
| ChatGPT | Hard | listed | |
| Flash Sale | Hard | listed | |

Guided-practice extras (Hello Interview, no written breakdown required): Food Review App, Game Leaderboard (related to Vol 2 leaderboard), Donations Website, GitHub Actions.

### Alex Xu Vol 1

Ch 1–3 are foundations (scale, estimation, framework) — see [foundations](foundations/README.md). Design chapters:

| Chapter | Question | Status |
| --- | --- | --- |
| 4 | Rate limiter | [Stub](questions/rate-limiter/) |
| 5 | Consistent hashing | listed |
| 6 | Key-value store | [Stub](questions/key-value-store/) |
| 7 | Unique ID generator | [Stub](questions/unique-id-generator/) |
| 8 | URL shortener | [Implemented](questions/url-shortener/) |
| 9 | Web crawler | [Stub](questions/web-crawler/) |
| 10 | Notification system | [Stub](questions/notification-system/) |
| 11 | News feed | [Stub](questions/news-feed/) |
| 12 | Chat system | [Stub](questions/chat-system/) |
| 13 | Search autocomplete | listed |
| 14 | YouTube | [Stub](questions/youtube/) |
| 15 | Google Drive | listed |

### Alex Xu Vol 2

| Chapter | Question | Status |
| --- | --- | --- |
| 1 | Proximity service | listed (related: [Uber](questions/uber/)) |
| 2 | Nearby friends | listed |
| 3 | Google Maps | listed |
| 4 | Distributed message queue | listed |
| 5 | Metrics monitoring | listed |
| 6 | Ad click event aggregation | listed |
| 7 | Hotel reservation | listed |
| 8 | Distributed email service | listed |
| 9 | S3-like object storage | listed |
| 10 | Real-time gaming leaderboard | listed |
| 11 | Payment system | listed |
| 12 | Digital wallet | listed |
| 13 | Stock exchange | listed |

## Adding a question later

Tell Cursor the question name. It should:

1. Copy `_templates/question/` → `questions/<slug>/`
2. Fill title, sources, and this index
3. Design (README, FAQ, FLOW, COMPONENTS)
4. Implement frontend + backend + database and wire `setup.sh` / `run-scenarios.sh` / `run-functional.sh`

## Notes

Original notes only. Link to Hello Interview; cite Alex Xu by volume and chapter. The local systems are teaching models, not production architecture.
