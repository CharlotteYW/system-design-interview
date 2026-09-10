# Agent instructions

This repo is a personal study workspace for **software engineer system design interviews**.

Learn by designing a system in interview style, then implementing a **simplified local version** (frontend + backend + database, Python/FastAPI + Docker Compose) with setup, integration, and functional tests.

## When the user names a question

Follow `.cursor/rules/` in order:

1. `00-repo-purpose.mdc` — study by building, original notes only
2. `04-commit-before-question.mdc` — commit previous work; require a clean git tree
3. `01-prepare-a-question.mdc` — interview delivery + implement locally
4. `02-question-folder.mdc` — required files in `questions/<slug>/`
5. `03-local-implementation.mdc` — Docker, scripts, integration and functional tests
6. `05-implement-the-system.mdc` — if the system does not exist, build frontend + backend + database and make the scripts pass

## New vs existing questions

- **Exists** under `questions/<slug>/` → fill design docs, then implement.
- **New** → copy `_templates/question/` to `questions/<slug>/`, add a row to the root README index, then design and implement.

## Do not

- Copy Hello Interview or Alex Xu write-ups verbatim. Cite the source and write original notes.
- Spin up cloud accounts. Mock components with local Docker.
- Skip FAQ, FLOW, or COMPONENTS. Every question folder needs all three plus README.
- Stop at design docs. If the local system is missing, implement it (UI + API + database + tests).
