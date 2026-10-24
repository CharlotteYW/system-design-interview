# Claude Code instructions

This repo's workflow is defined in `AGENTS.md` and the rule files in `.cursor/rules/`. Claude Code does not load those files automatically, so read them first.

@AGENTS.md

Before you start any question, concept, or re-practice:

1. Read every file in `.cursor/rules/` in numeric order (`00-` to `21-`). They are plain Markdown with a short front matter. Treat them as binding instructions, the same as this file.
2. Read the root `README.md` index to see what is Implemented and what comes next.
3. For the topic the user names, read its folder: `README.md` (status, What we implemented, Session notes), `FAQ.md` (Session questions), `FLOW.md`, `COMPONENTS.md`, `final-design-flow.md`, and `high-level-design-comparision.md` when present.
