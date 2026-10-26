# Handoff: start here

Read this first in any new chat, in any tool (Cursor, Codex, Claude Code). It says where the study is, how a session runs, and what the learner expects. The binding rules are in `.cursor/rules/` (read every file, `00-` to `21-`). This file does not replace them.

Last updated: 2026-10-25.

## Where the study is

| Area | Done | Not started |
| --- | --- | --- |
| Questions (`questions/`) | url-shortener, rate-limiter, unique-id-generator, key-value-store, notification-system, news-feed, chat-system, youtube, one-time-password, web-crawler | Every other name in the root README learning path is a stub. Next: `search-autocomplete` |
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
- **Run one lab at a time.** Most labs bind port 8000. chat-system uses 8000 and 8001. youtube uses 8300 to 8305 and 9000. web-crawler uses 8400. Run the other lab's `scripts/stop.sh` first. `stop.sh` keeps the volumes.
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
