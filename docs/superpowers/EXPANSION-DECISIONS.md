# Expansion Decisions — Sovereign Session Restructure

- **Date:** 2026-06-30
- **Companion to:** `docs/superpowers/specs/2026-06-30-sovereign-session-restructure-design.md`
  and `docs/superpowers/plans/2026-06-30-sovereign-session-restructure.md`
- **Status:** v1 (Phases 1–3) shipped. This note records the enhancements the
  design **deliberately deferred**, each with the decision made for v1 and the
  rationale — so a future implementer doesn't relitigate them from scratch.

v1 ships an interactive sovereign session (`ms chat`) as the front door, the team
pipeline as a background-dispatched skill, on-demand `ms status` narration + the
fork-dashboard deep-link for observability, an interactive `shape-spec` skill
(linter demoted to advisory), and a `choose-team-models` skill. The four items
below were scoped *out* of v1 on purpose.

---

## 1. Phase 4 — live, inline streaming of team events into the chat

**Decision (v1):** Deferred. v1 observation is **on-demand**: the `pi-harness`
dispatch skill calls `ms status <run_id> --json` and narrates the result in plain
language, and surfaces the observability-fork dashboard deep-link
(`<dashboard>/runs/<run_id>`) for the live visual view. There is no token-by-token
team feed inside the chat transcript itself.

**Rationale.** `pi` tool calls are request/response — a skill cannot stream a live
feed into a single turn (a `tail -f` would block the turn indefinitely). Streaming
a live team feed *inline* requires a `pi` **extension** (an npm/git package) that
registers `dispatch_team` / `team_status` tools capable of pushing events into the
transcript as they arrive. That's a different delivery mechanism (extension, not
`SKILL.md`) and a meaningfully larger build. v1 gets ~90% of the observability
value from `ms status` + the existing dashboard at ~10% of the cost, and the
dashboard already streams live and is deep-linkable. Phase 4 is the **immediate
fast-follow (track B)**, not abandoned.

**When to revisit.** When users find on-demand status insufficient (e.g. they want
to watch a team build without leaving the terminal), build the extension. The
`ms status --json` contract built in v1 is the natural data source for those
extension tools, so the work composes.

---

## 2. Per-run model overrides (vs sticky settings)

**Decision (v1):** Sticky. `choose-team-models` applies the chosen orchestrator /
builder roster by writing `HarnessSettings` via `ms models set --bucket … `, which
**persists as the new default**. There is no "use these models for *this run only*,
leave my defaults untouched" path on `ms launch`.

**Rationale.** Sticky is zero net-new code — `choose-team-models` simply drives the
existing `ms models set` / `ms models list` surface, and `HarnessSettings` +
`models.json` are reused unchanged. True per-run isolated overrides would mean a
new override-passing path through `ms launch` → coordinator → bucket resolution,
plus careful handling so a concurrent run / the interactive session don't observe
each other's transient override. For v1, the cost of that isolation outweighs the
benefit: in practice users pick a roster for a stretch of work, not a fresh roster
every single dispatch, and "sticky + re-run `choose-team-models` to change it" is a
fine ergonomic.

**When to revisit.** When users routinely run back-to-back dispatches with
different rosters and find re-setting the sticky defaults annoying — or when
multiple runs must coexist with different models. The clean shape is an
`ms launch --orchestrator-model … --builder-model …` (or a `--models` profile) that
threads an override through to bucket resolution without touching saved settings.

---

## 3. Auto-boot / health-managed dashboard from `ms chat`

**Decision (v1):** No auto-boot. `ms chat` does **not** start the observability
stack. When a team is dispatched, the `pi-harness` skill surfaces the run's
deep-link and, if the dashboard isn't up, instructs the user to run `ms up`.
Observation degrades gracefully to `ms status` text and never blocks.

**Rationale.** The dashboard is a multi-process stack (Bun fork server, the live
bridge tailer, the FastAPI dashboard, the Next.js UI — see `ms up`) with its own
ports (`43190` / `8800` / `3000`), health checks, and teardown semantics. Booting
and health-managing all of that as a side effect of starting an interactive coding
session is heavy, slow, and surprising — most `ms chat` sessions are solo work that
never dispatch a team and so never need the dashboard at all. Keeping `ms up`
explicit keeps `ms chat` fast to start and keeps the dashboard lifecycle in one
obvious command. The deep-link is always surfaced regardless, so the user is one
copy-paste away once they do run `ms up`.

**When to revisit.** If team dispatch from the session becomes the dominant path,
an opt-in "ensure dashboard is up before I dispatch" (e.g. a flag or a setting that
has the dispatch skill run `ms up` in the background and wait on its health checks)
would remove the manual step — reusing the existing supervisor + health-check
machinery rather than inventing new lifecycle code.

---

## 4. Bare-`ms` aliasing to `ms chat`

**Decision (v1):** No alias. Bare `ms` (no subcommand) keeps showing **help**. The
sovereign session is reached explicitly via `ms chat`.

**Rationale.** `ms` is the harness's whole CLI surface (`launch`, `status`, `stop`,
`up`, `models`, `spec`, `lint`, `doctor`, …). Making bare `ms` *do something* (drop
into a chat session) rather than *describe itself* breaks the discoverability
contract every other subcommand relies on, and would surprise scripts and muscle
memory that expect `ms` → help. Worse, a bare-`ms` that launches an interactive
session has a real footgun in non-interactive / CI contexts. v1 keeps the front
door explicit (`ms chat`) and the help affordance intact. The convenience of bare
`ms` is low-value relative to that risk.

**When to revisit.** Only if `ms chat` is so overwhelmingly the entry point that
the extra word is genuine friction — and even then, prefer an opt-in alias (a shell
alias the user sets, or a config flag) over changing the default no-arg behavior of
the CLI.

---

## Summary table

| # | Enhancement | v1 decision | Core rationale |
|---|---|---|---|
| 1 | Live inline team-event streaming | Deferred to Phase 4 (pi extension) | pi tool calls are request/response; live inline needs an extension, not a skill. `ms status` + dashboard cover v1. |
| 2 | Per-run model overrides | Sticky settings only | Sticky = zero new code (reuses `ms models set`); isolated overrides need a new override path + concurrency care. |
| 3 | Auto-boot the dashboard | Explicit `ms up` | The stack is heavy + multi-process; most sessions never dispatch a team. Keep `ms chat` fast; degrade to `ms status`. |
| 4 | Bare-`ms` → `ms chat` | Bare `ms` stays help | Preserves CLI discoverability + avoids a CI footgun; the alias is low value. |
