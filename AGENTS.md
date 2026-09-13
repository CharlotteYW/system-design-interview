# Agent instructions

This repo is a personal study workspace for **software engineer system design interviews**.

Learn by designing a system in interview style, then implementing a **simplified local version** (frontend + backend + database, Python/FastAPI + Docker Compose) with setup, integration, and functional tests.

## When the user names a question

Follow `.cursor/rules/` in order:

1. `00-repo-purpose.mdc` — study by building, original notes only
2. `04-commit-before-question.mdc` — commit previous work; require a clean git tree
3. `06-interview-pattern.mdc` — five steps: scope, high-level, deep dive, special situations, summary
4. `08-teach-after-each-answer.mdc` — after each user answer: analyze, options, tradeoffs, why we chose this; then implementation wrap-up
5. `01-prepare-a-question.mdc` — interview delivery + implement locally
6. `02-question-folder.mdc` — required files in `questions/<slug>/`
7. `03-local-implementation.mdc` — Docker, scripts, integration and functional tests
8. `05-implement-the-system.mdc` — if the system does not exist, build frontend + backend + database and make the scripts pass
9. `07-python-venv.mdc` — one host venv (`.venv`, prompt `system-design-interview`); setup and test scripts must use it (`stop.sh` does not)
10. `09-update-on-repractice.mdc` — practicing an existing question again means update docs and code from this conversation
11. `10-end-of-session-questions.mdc` — invite questions at the end, answer them, record Q&A in FAQ and README
12. `11-stop-service-at-session-end.mdc` — when the user is done, ensure `scripts/stop.sh` exists and run it so Compose is not left up

## New vs existing questions

- **Exists** under `questions/<slug>/` → practice again, then **update** that folder’s docs and code to match this conversation (`09-update-on-repractice.mdc`).
- **New** → copy `_templates/question/` to `questions/<slug>/`, add a row to the root README index, then design and implement.

## Do not

- Copy Hello Interview or Alex Xu write-ups verbatim. Cite the source and write original notes.
- Spin up cloud accounts. Mock components with local Docker.
- Skip FAQ, FLOW, or COMPONENTS. Every question folder needs all three plus README.
- Stop at design docs. If the local system is missing, implement it (UI + API + database + tests).
- Answer the user's design with a one-line verdict. After each step, teach options, tradeoffs, and why we chose this (`08-teach-after-each-answer.mdc`).
- Leave an already-Implemented folder unchanged after we practice it again. Update docs and code from the latest conversation (`09-update-on-repractice.mdc`).
- Skip the end-of-session Q&A. After the implementation summary, invite questions, answer them, and write them into FAQ/README (`10-end-of-session-questions.mdc`).
- Leave the local stack running after the question is done. Run `scripts/stop.sh` (`11-stop-service-at-session-end.mdc`).
- Use system Python or a per-question venv. Host scripts use `.venv` (`system-design-interview`).
