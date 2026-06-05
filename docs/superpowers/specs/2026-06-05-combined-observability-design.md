# Combined Observability — Design (Approach A: fork-as-primary)

**Date:** 2026-06-05
**Status:** Approved (design); implementation plan to follow
**Branch:** `design/combined-observability`

## 1. Goal

Surface the best of both observability layers — mannschaft's **Symphony** dashboard (Next.js, in-repo) and the **pi-agent-observability fork** (`pranavnair-ste/pi-agent-observability`, Bun) — into one experience, driven by three needs (ranked by the user):

- **A — Debug agent behavior:** read *what each agent actually said and reasoned*, not just which tools ran.
- **B — Live ops / mission control:** watch N agents run in real time (race/swimlane), cost, errors, throughput.
- **D — Demos / legibility:** a polished, human-readable surface.
- **C — Reproducibility (secondary):** run registry, reliability, branch-from-step. Kept, not optimized for.

**Hard, cross-cutting requirement:** fork-grade human readability everywhere. The current Symphony surfaces leak raw IDs and unparsed blobs; the fork's event rendering (color pills, human summaries, humanized tool names, search, keyboard nav, truncation) is the target style.

## 2. Key insight

Everything the bridge "can't show" (assistant text, thinking, per-turn timing) **is already in the `pi --print --mode json` stream** that `agent_wrapper` pipes through today — `turn_end.message.content[]` carries the full text + thinking; `message_update` carries `text_*`/`thinking_*` deltas + timing (verified in `pi_harness/trajectory/CAPTURE_FORMAT.md` §2–3). `agent_capture.py` deliberately discards them ("skip in v1", lines 13, 116–117). So recovering the prose is a **capture-side change**, not a new data source — and it feeds *both* dashboards.

## 3. Chosen approach (A)

The **fork becomes the primary observability UI**. **Symphony is demoted** to a run-level control plane (run list, reliability gauges, branch — the secondary C features) that **deep-links into the fork** for event detail; we stop using Symphony's raw-JSON event inspector. Rejected alternatives:
- **B (rebuild fork's style inside Symphony):** one stack, keeps C natively, but re-implements the fork's three views + readability system in React — highest effort, rebuilds value we already have.
- **C (two dashboards cross-linked):** lowest disruption, but two UIs + two readability implementations maintained forever; the unreadable-Symphony problem still needs its own fix.

A wins because the fork *already is* the A/B/D + readability target, so the work collapses to recovering prose at capture + productionizing the (already-validated) bridge.

## 4. Architecture

```
① pi --print --mode json   (per agent, already piped through agent_wrapper)    [unchanged]
        │   carries tool I/O, cost, AND content[] text+thinking, delta timing
        ▼
② agent_capture.py  — ENRICHED                                                  [NEW]
        │   message rows also keep output.text (+ output.thinking when unencrypted)
        │   stored in the EXISTING output JSON blob → no schema migration
        ▼
③ TrajectoryEvent   SQLite · ~/.pi-harness/trajectory.db   (single source)      [unchanged]
        ▼
④ live bridge       — tails store.query_events_after(run_id, after_id)          [NEW]
        │   translates rows → fork ObsEventEnvelope (now WITH prose), POSTs ≤50/batch
        ▼
⑤ fork UI (PRIMARY) — race · swimlane · single, now showing real prose          [CHANGED · our fork]
                      + custom renderer for task_transition/guide_fired/sensor_fired

   Symphony (SECONDARY) — run list · reliability · branch (C, kept)              [DEMOTED]
                          deep-links → fork for event detail
```

### Component boundaries
- **Capture enrichment** (`pi_harness/trajectory/agent_capture.py`): pure function over the pi stream; input = NDJSON line, output = `TrajectoryEvent` with richer `output`. Independently testable against the captured fixture.
- **Bridge** (`pi_harness/observability/bridge.py`, new): pure `translate(TrajectoryEvent, ctx) -> envelope` + a tailer loop. The translator is independently testable (golden envelopes); the tailer is the only stateful/IO piece.
- **Fork changes**: isolated to `app.js` rendering (custom-event summaries/pills); upstream-mergeable commits on a branch in our fork.

## 5. Section 2 — Capture enrichment

`agent_capture.PiEventParser._turn_message` currently extracts `usage/cost/stopReason/responseId` and ignores `message.content`. Enrich:

- **Text (Phase 1):** concatenate `message.content[]` parts of type `text` → `output["text"]`. This is the guaranteed A/D win.
- **Thinking (Phase 2):** concatenate `content[]` thinking/reasoning parts → `output["thinking"]` **when present and unencrypted**. For the current default (`gpt-5.4-mini`, openai-responses) reasoning is encrypted → `output["thinking"]` will be empty; with Claude models it populates. Capture-if-present, never error.
- **Timing (Phase 2):** consume `message_update` `text_*`/`thinking_*` delta arrival times (via `now_fn()`, since pi events lack per-event ts) and `turn_start` time to compute `prefill_ms` (TTFT), `generation_ms`, `output_tps` → stored in `output`. Requires the parser to stop skipping `turn_start`/`message_update` purely for timing.
- **Defensive:** malformed content must not abort the stream (audit #29 coercion pattern).
- **Truncation:** stored full in trajectory (assistant texts are small); the **bridge** truncates to fork limits (`MAX_TEXT_FIELD=32000`) before POST.
- **Tests:** extend the captured-NDJSON fixture assertions to cover text (and thinking when a Claude sample is added).

No schema migration: `text`/`thinking`/timing live in the message row's existing `output` JSON column.

## 6. Section 3 — The bridge

New module `pi_harness/observability/bridge.py` + CLI entrypoint (e.g. `ms observe`).

**Translator** `translate(event, ctx) -> dict` — the mapping validated in the PoC, now reading `output.text`/`output.thinking`:
- `tool_call` → `tool_call {tool_call_id=step_id, tool_name=tool, args=input, args_truncated}`
- `tool_result` → `tool_result {tool_call_id=step_id, tool_name=tool, content_text=extract(output.content[].text), is_error=(outcome=='error')}`
- `message` → `assistant_message {text=output.text, thinking=output.thinking, usage={input=tokens_in, output=tokens_out, cost_total=output.cost_usd, ...}, stop_reason=output.stopReason}` + synthesized `turn_end`
- `task_transition`/`guide_fired`/`sensor_fired` → `custom {custom_type, data}`

**Tailer loop** (per run_id): maintain `after_id` cursor; poll `store.query_events_after(run_id, after_id)`; emit per-agent `session_start` (once) and synthesized `turn_start`/`turn_end` around message rows; POST in batches ≤50; advance cursor.

**Identifiers (derived, no coordinator change needed):** the bridge reads the `runs` table + trajectory rows, so it derives `pool=run_id`, `tags=[team_name, topology]`, `agent_name=agent_id`, `session_id=f"{run_id}:{agent_id}"` itself. (Coordinator may *optionally* auto-launch the bridge on run start and stop it on teardown; not required for correctness.)

**Restart-safe & idempotent (improvement over the PoC):**
- `event_id = uuid5(NS, f"{run_id}:{agent_id}:{row_id}:{subtype}")` — deterministic, so re-tails/restarts dedupe via the fork's `event_id` PK + `INSERT OR IGNORE`. Synthesized events get deterministic ids too (`...:turn:{n}:start`, `...:session:start`).
- `seq` = deterministic index within the session's ordered emission (recomputable from rowid order), not mannschaft's global rowid.
- `ts` = the trajectory row's real `ts` (preserves swimlane wall-clock spacing); synthesized turn/session events borrow the bounding row's ts.

**CLI:** `ms observe --run <id>` tails a live run **or backfills a past run** into the fork (exactly the manual replay we did for `run-ea742e20…`). Config: `OBS_SERVER_URL`, `OBS_AUTH_TOKEN` from env.

## 7. Section 4 — Fork-side changes (our fork)

On a branch in `pranavnair-ste/pi-agent-observability`:
- **Custom-event renderer** in `apps/observability/public/app.js` `summaryFor()`: render `custom` events whose `custom_type ∈ {task_transition, guide_fired, sensor_fired}` as a distinct pill with a human summary (e.g. `task X: in_progress → done`). Today they render as a plain unstyled pill.
  - *Pre-req:* confirm what `task_transition` rows actually carry — in the sample real run their `input`/`output` were empty, so the board-transition detail source must be verified before the renderer is built.
- Keep changes small and upstream-mergeable; no auth/runtime changes here.

## 8. Section 5 — Orchestration, deep-links, non-goals

- **Launcher:** extend `ms local` / add `ms observe up` to boot the fork server (Bun, `:43190`), the bridge (tailing active runs), and optionally Symphony; `doctor` checks for Bun.
- **Symphony deep-link:** "Open in observability" link on the run detail page + run list → fork race view (`#view=race&pool=<run_id>&race_lanes=…`).
- **Auth/exposure:** keep loopback + shared token for the PoC; production hardening is Phase 3.

**Non-goals (YAGNI):**
- Unified wall-clock-merged timeline (desired view 3) — neither tool has it; deferred.
- Animated replay scrubber — deferred (Symphony's branch-from-step covers reproducibility).
- The pi-extension path — explicitly NOT used (blocked by `--no-extensions`; unnecessary now that capture is enriched).
- Cost reconciliation between the two DBs — accept divergence for the PoC; document it.
- Multi-tenant/remote auth — deferred.

## 9. Phasing

- **Phase 1 — demoable win:** enrich capture for **text** · productionize bridge (translator + tailer + `ms observe` backfill) · deep-link from run page. Real runs render with prose in race/swimlane.
- **Phase 2 — depth:** **thinking** (where unencrypted) · **timing** (TTFT/tps from deltas) · fork custom-event renderer.
- **Phase 3 — make it real:** one-command launcher (fork+bridge+Symphony) · auth/port hardening · Symphony→fork deep-links wired.

## 10. Risks / caveats

- **Thinking is provider-dependent** — encrypted for the current default model; the text view is the guaranteed win.
- **`task_transition` payload may be thin** — verify before building its renderer.
- **Two-DB cost divergence** — fork sums `usage.cost_total`; mannschaft prefers pi's `cost_usd`. Accepted for PoC.
- **Bun dependency** — the primary UI is a Bun process beside the Python/Next.js stack.
- **Smoke-test hazard** — any end-to-end must NOT launch a real ClawTeam team (those git-commit to your branch). Use the existing real run in `~/.pi-harness/trajectory.db` as the bridge e2e fixture; run pytest with `-m "not smoke"`.

## 11. Testing strategy

- **Capture:** unit tests over the captured NDJSON fixture asserting `output.text` extraction (and thinking/timing in Phase 2).
- **Bridge translator:** golden-envelope tests per classification (pure function, no IO).
- **Bridge e2e:** tail the real `run-ea742e20…` fixture → assert envelope count + idempotency on re-run (no smoke team).
- **Fork renderer:** snapshot/visual check of a `custom` event rendering.
