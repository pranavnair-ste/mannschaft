---
name: shape-spec
description: >
  Use when the user wants to define WHAT to build before building it — "let's
  plan a feature", "write a spec/PRD", "I want to build X but it's fuzzy", or as
  the on-ramp before dispatching an agentic team. Interactively accretes goal,
  constraints, non-goals, and acceptance criteria through dialogue, writes a
  harness spec, and hands off to model selection + team dispatch. Linting is
  advisory here, never a gate.
version: 1.0.0
---

# shape-spec — turn a fuzzy idea into a launchable spec

Replace rigid spec-writing + a blocking linter with a short collaborative
conversation. The output is a spec the mannschaft pipeline can decompose.

## Protocol

1. **Understand the idea.** Ask focused questions ONE at a time to pin down:
   - **Goal** — one or two sentences: what should exist when done.
   - **Acceptance criteria** — concrete, checkable statements ("`POST /todos`
     returns 201 with a generated id").
   - **Constraints** — language/runtime/libraries/scope limits.
   - **Non-goals** — explicitly out of scope.
   Don't over-ask; stop when the four are clear.

2. **Write the spec.** Scaffold and fill it via Bash:
   `ms spec new <id> --title "<title>"`
   then edit `~/.pi-harness/specs/<id>.md` to fill goal / acceptance_criteria /
   constraints / non_goals (use your edit tool).

3. **Advisory lint (not a gate).** Run `ms lint ~/.pi-harness/specs/<id>.md --json`
   and weave any findings into the conversation as SUGGESTIONS. Offer to tighten
   the spec, but never refuse to proceed.

4. **Hand off.** Ask if they want to build it now. If yes, run `choose-team-models`,
   then the `pi-harness` dispatch skill with the spec path. If they'd rather you
   build it solo, just do the work hands-on.

## Do NOT
- Do not block on lint findings — they are advice.
- Do not invent acceptance criteria the user didn't agree to.
