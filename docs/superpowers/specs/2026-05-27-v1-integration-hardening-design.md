# v1 Integration Hardening — Design Spec

- **Date:** 2026-05-27
- **Status:** Approved (design); implementation pending
- **Scope:** Close the four cross-layer integration gaps between "Plan 7 works" and "v1 runs a job to done." None of these are Plan 7 core bugs — they are integration seams that only a live end-to-end run exercises.

## Context

A fresh end-to-end run (decompose → launch → run to completion → improve) surfaced four gaps:

1. **Profiles aren't registered on launch.** `Coordinator.launch` installs a template referencing the `pi-openai-reasoning` / `pi-openai-fast` profiles but never registers them, so a launch against a fresh `~/.clawteam` fails until the profiles are registered by hand.
2. **Teardown leaks agents.** `clawteam team cleanup --force` deletes the team record but leaves the tmux session + agent processes running (burning credit). The harness has no teardown that actually stops agents.
3. **Agents get the *what*, not the *how*.** The bridge sets each agent's standing prompt to the task description but never tells the agent the ClawTeam completion protocol, so decomposer-driven agents never mark tasks `completed` → the run hangs until timeout.
4. **Improve loop isn't wired.** Nothing captures trajectory events during a live run, so `on_completion → improve` has no data and raises `ImproveError("No events…")` (the current smoke xfail).

## Goals

- A `Coordinator.launch(...)` against a clean `~/.clawteam` runs a decomposed job to completion and triggers a non-failing improve pass, with no manual setup.
- Teardown stops agents (no leaked tmux session / credit burn).
- All fixes are root-cause and covered by `pytest -m "not smoke"` unit tests.

## Non-goals

- Capturing rich pi-agent stdout tool-call events during a live run (agents run in tmux panes, out of the Coordinator's reach). v1 captures **ClawTeam task transitions only**; richer per-agent stdout capture is a v2 hook.
- Changing the spec/decomposer or topology DAG semantics.
- Graceful agent-shutdown handshake (`clawteam lifecycle request-shutdown/approve-shutdown`); teardown is forceful (kill session, then delete data).

## Run lifecycle (target)

```
launch(spec):
  [#1] register profiles (build_profile_specs, --command = spec.executor)  ── new
  [#4] init_db(config.trajectory_db_path)                                   ── new
  install_template
  launch_team
  seed task DAG          (each agent's `task` now carries [#3] protocol)
wait_for_completion(handle):
  client.wait_for_completion(team, timeout, on_poll=<capture cb>)           [#4]
    → cb writes a task_transition event whenever a task's status changes
on_completion(handle):
  if success:
    improve_runner.run_for_completed_run(run_id, config, session_id=…)      (now has events)
    teardown(handle)                                                        [#2] auto, success-only
teardown(handle):                                                           [#2] also callable directly
  client.kill_tmux_session(team) → client.cleanup_team(team)
```

---

## Fix #1 — Auto-register profiles in `launch`

**Decision:** Auto-register inside `Coordinator.launch` (idempotent). Chosen over an explicit `ensure_profiles()` step so a launch "just works" with zero caller setup.

**Where:** `pi_harness/topology/coordinator.py` `launch`, immediately before `install_template` (currently ~line 124).

**What:**
```python
from dataclasses import replace
from pi_harness.clawteam_profile import build_profile_specs
...
for pspec in build_profile_specs(self._config):
    self._clawteam_client.register_profile(replace(pspec, command=spec.executor))
```

**Notes:**
- `clawteam profile set` is an upsert, so re-registering every launch is safe (and cheap: two subprocess calls).
- ClawTeam's `--agent` accepts only `claude/codex/gemini/kimi/nanobot`. `build_profile_specs` uses `--agent codex`; the chosen executor (`pi` or `codex`) is honored via `--command=spec.executor`. This mirrors exactly what `tests/topology/test_smoke_end_to_end.py:119-121` already proves works.

**Tests:** unit test asserting `launch` calls `register_profile` twice (once per profile) with `command == spec.executor`, before `launch_team`.

---

## Fix #2 — Teardown that actually stops agents

**Decision:** A new explicit `Coordinator.teardown(handle)` method, **plus** auto-teardown at the end of `on_completion` **only on a clean success**. Failed/timed-out runs are left up for debugging.

**Where:**
- `pi_harness/clawteam/client.py`: new `kill_tmux_session(team_name)` — thin `tmux kill-session -t clawteam-{team}` wrapper. ClawTeam names each team's session `clawteam-{team}` (`clawteam/spawn/tmux_backend.py:53,219`). Ignores a "session not found" exit (already-dead session is success). This is a `tmux` call, not a `clawteam` call — a documented sibling exception to the "one clawteam invocation per method" rule, like `install_template`.
- `pi_harness/topology/coordinator.py`: new `teardown(handle)` = `kill_tmux_session(team)` then `cleanup_team(team)`. Order matters: kill the session first so agents stop immediately, then delete team data.

**Auto-teardown:** at the end of `on_completion`, after a successful improve pass, call `self.teardown(handle)`. Guarded by `result.success` (the same gate that runs improve).

**Layering:** the tmux kill goes through the client so Coordinator unit tests (Mock client) never shell out to real tmux.

**Tests:** unit test for teardown order (kill before cleanup) with a Mock client; unit test that `on_completion` tears down on success and does **not** on failure.

---

## Fix #3 — Inject the completion protocol for ALL agents

**Decision:** Inject in `build_template_dict` (covers every caller — bridge, CLI, direct), not in the bridge. This keeps `AgentSpec.task_prompt` as the pure task description (so `tests/spec/test_runspec.py:81`, which asserts `task_prompt == "lead the team"`, stays green) and is the root-cause fix.

**Where:** `pi_harness/topology/base.py`:
- New module-level `completion_protocol(agent_name: str) -> str`.
- In `build_template_dict` (lines 152, 159), set each agent's `task` to `base_prompt + "\n\n" + completion_protocol(name)`, where `base_prompt = task_prompt or default_prompt`.

**Protocol content (generic, role-agnostic):** the board is already seeded — do **not** create new tasks; the team name is in `$CLAWTEAM_TEAM_NAME` (exported into the pane, `tmux_backend.py:60`) and this agent's name is `{agent_name}`; find your task via `clawteam task list "$CLAWTEAM_TEAM_NAME"` (the one owned by `{agent_name}`); if `blocked`, poll every ~10s until unblocked; do the work described above; then `clawteam task update "$CLAWTEAM_TEAM_NAME" <task-id> --status completed`; exit once your task(s) are completed.

**Notes:**
- One generic envelope serves leader + workers (role already lives in the template `type`/`profile`).
- The smoke's hand-written prompts already embed a protocol; after this fix they are redundant but harmless (double instruction). The smoke is opt-in and will not be touched in this pass.

**Tests:** unit test that `build_template_dict` output's `leader.task` and each `agents[].task` contain the protocol markers (`task update`, `--status completed`, the agent's own name) appended to the base prompt. Existing `test_runspec.py:81` must still pass unchanged.

---

## Fix #4 — Capture trajectory during the run

**Decision:** Fold task-transition capture into the existing poll. **Important realization:** the poll loop lives in `ClawTeamClient.wait_for_completion` (`client.py:254-272`), not in the Coordinator. So we realize "fold into the wait loop" by adding an optional **status callback** to the client's wait method; the Coordinator supplies a callback that writes `task_transition` events. The client stays trajectory-agnostic (no layering inversion).

**Where:**
- `pi_harness/clawteam/client.py` `wait_for_completion`: add optional `on_poll: Callable[[list[Mapping]], None] | None = None`, invoked with the freshly fetched `tasks` list each poll iteration (best-effort: a raising callback is caught + logged, never aborts the wait).
- `pi_harness/trajectory/capture.py`: extract the status-diff → events logic currently inline in `capture_clawteam_transitions` into a shared pure helper, e.g. `diff_task_states(prev_state: dict, tasks, *, run_id, now) -> tuple[list[TrajectoryEvent], dict]`. Reuse it from both `capture_clawteam_transitions` and the Coordinator callback (DRY; one definition of "what counts as a transition").
- `pi_harness/topology/coordinator.py`:
  - `launch`: call `init_db(self._config.trajectory_db_path)` so the db file + parent dir exist before any write.
  - `wait_for_completion`: build a capture callback over a local `last_state` dict that calls `diff_task_states(...)` and `write_event(ev, db_path=self._config.trajectory_db_path)` (sync write — we're in a sync poll loop); pass it as `on_poll` to `client.wait_for_completion`.

**Result:** by the time `on_completion` runs, `query_events(run_id=…)` returns the run's task-transition events, so `run_for_completed_run` produces an `ImproveReport` instead of raising `ImproveError`. The smoke's improve xfail closes on the live path.

**Scope note:** task transitions are a thin signal (no tool-call/message events, since agent stdout is in tmux). That is sufficient to *close the loop* end-to-end in v1; richer capture is a separate v2 effort.

**Tests:** unit test that the capture callback writes one `task_transition` per status change into a tmp db; unit test that `launch` calls `init_db` with `config.trajectory_db_path`; unit test (with a fake client whose `wait_for_completion` invokes `on_poll`) that a Coordinator run populates the trajectory store.

---

## Cross-cutting

### Layering
- All subprocess/CLI/tmux interaction stays in `ClawTeamClient`. The Coordinator orchestrates and owns trajectory writes. `trajectory.capture` owns the transition-diff definition (shared with the Coordinator callback). The client never imports the trajectory layer.

### Test strategy
- Everything verifiable with `pytest -m "not smoke"`. Mock/fake `ClawTeamClient` for Coordinator tests; tmp `db_path` for trajectory tests.
- **Watch for mock-hidden signature mismatches:** the new `on_poll` param and the new `kill_tmux_session` / `register_profile`-in-launch calls must match the real client signatures. After each merge, audit the real `ClawTeamClient` against its mocks/fakes in `tests/topology/conftest.py` and `test_coordinator.py`.
- Existing tests expected to need light updates: `test_coordinator.py` on_completion tests (now also call `teardown` on the mock).

### Sequencing (branch-per-fix → merge → downstream audit)
Implement in order, each on its own branch, merged only after `pytest -m "not smoke"` is green, with a downstream audit after each merge:
1. **#1** profile auto-register (small)
2. **#2** teardown (small)
3. **#3** protocol injection (medium)
4. **#4** trajectory capture fold-in (medium; depends on nothing above but is the largest)

### Risks / open items
- **pi executor via codex adapter:** registering `--agent codex --command pi` is the smoke-proven pattern but is only lightly exercised; the default executor for decomposer launches should be confirmed during the live re-run.
- **Auto-teardown vs. inspection:** auto-teardown-on-success removes the tmux session right after improve. This is the chosen behavior; the explicit `teardown(handle)` + "failures left up" gives the debugging escape hatch.
- **Thin improve signal:** with task-transition-only events, improve output will be sparse. Acceptable for closing the loop; flagged for v2.
