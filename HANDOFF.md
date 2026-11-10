# Handoff: start here

Read this first in any new chat, in any tool (Cursor, Codex, Claude Code). It says where the study is, how a session runs, and what the learner expects. The binding rules are in `.cursor/rules/` (read every file, `00-` to `21-`). This file does not replace them.

Last updated: 2026-11-09.

## Where the study is

| Area | Done | Not started |
| --- | --- | --- |
| Questions (`questions/`) | url-shortener, rate-limiter, unique-id-generator, key-value-store, notification-system, news-feed, chat-system, youtube, one-time-password, web-crawler, search-autocomplete, google-drive, proximity-service, yelp | Every other name in the root README learning path is a stub. Next: `nearby-friends` |
| Core concepts (`core-concepts/`) | api-design, caching, cap-theorem, consistent-hashing, data-modeling, database-indexing, networking-essentials, sharding, numbers-to-know (notes only) | none |
| Key technologies (`key-technologies/`) | none | all 11 are stubs |
| Patterns (`patterns/`) | 8 Hello Interview patterns, each question mapped to one primary | none |

The table above is a snapshot from the date at the top. The root `README.md` **learning path** is the source of truth for status and the practice order. Check it before you pick the next topic. At the end of each session, update the index, this table, and the date.

The two most recent questions are the best examples of a finished folder:

- `questions/chat-system/`: two message-store designs side by side (Postgres and Cassandra), ordering and failure deep dives, and long FAQ session questions.
- `questions/youtube/`: a full five-step design, a lab with MinIO, ffmpeg workers, and nginx CDN edges, and a call-by-call flow table.
- `questions/web-crawler/`: DynamoDB Local, ElasticMQ (an SQS-compatible queue), MinIO, and Redis, with a fake local web; a scheduler on/off comparison, a Bloom filter variant panel, and a two-parser race panel.

## How a question session runs

1. **Clean tree first** (rule 04). Commit and push earlier work.
2. **Five steps, one at a time** (rules 06, 17, 20, 21, 14). The learner answers each step in a few lines. After each answer, the agent teaches before moving on (rule 08):
   - what is right, and what an interviewer would probe;
   - the full story;
   - labeled options (`Option A`, `Option B`, …) with what happens, the cost, and when each wins;
   - one line that names the pick and the number behind it.
   
   Step 1 also teaches every non-functional requirement and every Hello Interview below-the-line item. Steps 3 and 4 cover every Hello Interview deep dive (open the page and list its "Deep Dives" headings).
3. **Write as you go.** Write each step into `README.md`, `FAQ.md`, `FLOW.md`, and `COMPONENTS.md` right after teaching it. Write `high-level-design-comparision.md` after step 2, and `final-design-flow.md` after step 4.
4. **Build the lab** after step 5 (rules 03, 05, 07, 16): frontend, FastAPI, the stores in Docker Compose, the variants side by side, and an API trace on the page. `scripts/setup.sh`, `run-scenarios.sh`, `run-functional.sh`, and `stop.sh` must all pass. Check the page in a browser when you can.
5. **Close** (rules 10, 11):
   - write "What we implemented" in the README;
   - invite questions;
   - record every question and answer in `FAQ.md` "Session questions" (dated) and in the README session notes;
   - when the learner is done, run `stop.sh`, then commit and push.

Concepts and key technologies use rule 12 instead of the five steps: a variant table first, then a small lab.

## How this learner likes to be taught

These come from the sessions so far. Follow them alongside the rules.

- **Follow-up questions are frequent and deep**, especially on correctness: ordering, idempotency, retries, failover, and what each field is for. Answer each one, then record it in `FAQ.md` "Session questions" with the date. The learner reads those notes later.
- **Use concrete named cases.** Lee, Kim, and Ada as users. Chat `lee-kim` and `trip`. Video `abc123`, 20 GB, 400 parts. Real numbers, not "some data."
- **Use tables for comparisons and step-by-step call flows.** When asked "what calls what," give a table: the step, from → to, what is sent, what comes back, and what happens next.
- **Show code when asked.** Cite exact line ranges from the repo, then explain each block.
- **When the learner says "clearer and shorter," give a short version.** Use a few sentences or one table, without a full lesson.
- **Keep option letters stable.** When an answer says "Option D," that list must be written in the README or the FAQ, so the learner can look it up later.
- **Labs:**
  - show each store as its own card, with a change highlight;
  - start from an empty state, with a reset button;
  - show every call's method, path, body, and response;
  - add buttons that trigger each failure path (crash, drop, duplicate, damaged data).
- **Correct earlier answers plainly** when a follow-up shows they were wrong or the lab disagrees with the notes. Fix the notes and the code in the same turn.
- Explanations follow ASD-STE100 (rule 15): short sentences, active voice, one topic per sentence, and terms defined on first use.

## Environment and traps

- **Docker Desktop must be running.** Host scripts use the repo venv `.venv` through `scripts/use-venv.sh`. Never use the system Python.
- **Run one lab at a time.** Most labs bind port 8000. chat-system uses 8000 and 8001. youtube uses 8300 to 8305 and 9000. web-crawler uses 8400. search-autocomplete uses 8410. Run the other lab's `scripts/stop.sh` first. `stop.sh` keeps the volumes.
- **`minio/minio` is no longer on Docker Hub.** Use `cgr.dev/chainguard/minio` (see `questions/youtube/docker-compose.yml`). That image has no curl, wget, or grep, so its healthcheck uses bash `/dev/tcp`. MinIO bucket events need `_<ID>` on every env var, for example `MINIO_NOTIFY_REDIS_ADDRESS_YT`. Events reach Redis as a JSON array.
- **AWS stand-ins that work offline:** `amazon/dynamodb-local` (run with `-sharedDb -inMemory`, so tables reset on stop) and `softwaremill/elasticmq-native` (the SQS API, including `ChangeMessageVisibility`). boto3 talks to both with `endpoint_url` and dummy keys.
- **Cassandra (chat-system design 2) needs about a minute to start.** `setup.sh` waits for it.
- **Hello Interview pages:** fetch the problem breakdown, read its requirements, below-the-line list, and "Deep Dives" headings, then cite it. Never paste its text.

## Committing

- Commit at the end of every session, and before starting a new topic (rule 04). Do not commit `.venv`, `.env`, or caches.
- A commit message says what the work does, for example "Design and implement the YouTube lab."
- Push after committing. Never force-push.

## Prompts to resume in a new chat

Start every new chat with:

> Read HANDOFF.md, AGENTS.md, and every file in .cursor/rules/ in numeric order, and follow them as binding instructions.

Then say what you want. Replace `<slug>` with the folder name, for example `web-crawler` or `chat-system`:

- **A new question:** "Prepare the question `<slug>` end to end."
- **Re-practice:** "Re-practice `<slug>`. Read its README and FAQ session notes first."
- **Resume mid-question:** "Continue `<slug>`. Step N is done. Start step N+1."
- **Questions about a lab:** "Answer my questions about the `<slug>` lab and record them in its FAQ."
- **Not sure what is next:** "Check the root README index and suggest the next topic."

## Most recent completed session — Google Drive, 2026-11-01

All five design steps are complete. The full-stack lab is implemented. Setup, 12 integration scenarios, and 4 functional checks pass. Browser upload/download, Kim sharing and replay, and CDC comparison were checked. Read questions/google-drive/README.md section 6 for limits and ports. Region replication is simulated in one database.

The learner closed the chapter after end-of-session Q&A on 2026-11-01. Answers are recorded in FAQ and README. The next recommended topic is proximity-service. Run git status before a new topic and follow rule 04.

Google Drive follow-up fixes: inspector cards now update in place, preserving expanded rows. Local TLS uses a host-only CA signing key and separate server certificate. The current user Keychain trusts only the exact non-CA server certificate for SSL; browser and ordinary macOS HTTPS checks passed. Run trust-local-cert.sh after server certificate renewal. Do not replace this with hostname-scoped macOS CA trust: Chromium ignores that policy constraint. Practice data was preserved.

Chapter closure: scripts/stop.sh completed successfully on 2026-11-01. All Google Drive containers are stopped and named data volumes are preserved. End-of-session Q&A is complete. Next recommended question: proximity-service.

## Most recent completed session — Proximity Service, 2026-11-08

The learner finished the five-step interview and end-of-session questions. The local lab runs nginx, two FastAPI services, and PostgreSQL with PostGIS. The core page compares PostGIS, Geohash, and full scan. The advanced page compares Quadtree, k-d tree, S2, and H3 with PostGIS. S2 and H3 use business_cell_keys, which Business Service maintains in the registration transaction. Read the question README and FAQ for the index storage examples and chooser.

Setup, eight integration scenarios, and three functional tests passed. Browser verification covered the core and advanced search results, profile lookup, and the table inspectors. The stop script removed the containers and preserved proximity-service_pgdata. Start the lab again with questions/proximity-service/scripts/setup.sh.

Next in the learning path is Nearby Friends. Start with the requirements prompt. The change from Proximity Service is that user locations move and visibility depends on friendship and sharing settings.

## Paused session — Nearby Friends, 2026-11-08

Step 1 prompt is recorded in the question README and FAQ. The learner will define functional requirements, quality targets, and exclusions. Proximity Service is closed and pushed. No Nearby Friends architecture or lab has been selected.

## Most recent completed session — Yelp, 2026-11-09

All five interview steps are complete. The learner chose queued review submission for the lab and identified direct writes as the simpler production starting point if measured peak traffic permits. Direct writes use atomic SQL increments. The lab compares direct and queued writes, optional batch ratings, radius and boundary search, precomputed membership, word and substring search, and a process-local cache. The design comparison and final flow are in the question folder.

Five integration scenarios and four functional checks passed. Browser checks covered search variants and the business profile with reviews. The README and FAQ record where to find all eight tables. The stop script removed the containers and preserved the data volume. Restart with `questions/yelp/scripts/setup.sh` and open http://127.0.0.1:8440/.

Resume Nearby Friends at step 1. The requirements prompt is already in the question README.
