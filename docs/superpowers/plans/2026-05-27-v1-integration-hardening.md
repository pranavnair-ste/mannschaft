# v1 Integration Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the four integration gaps so `Coordinator.launch` runs a decomposed job to completion against a fresh `~/.clawteam` and triggers a non-failing improve pass.

**Architecture:** Four surgical, root-cause fixes across the Coordinator, the ClawTeam client, the topology template builder, and the trajectory capture layer. Profiles auto-register on launch; teardown kills the tmux session before deleting team data; the ClawTeam completion protocol is appended to every agent's template `task`; trajectory `task_transition` events are written via a status callback threaded through the existing poll loop. Each fix is its own branch, merged after `pytest -m "not smoke"` is green, with a downstream audit after each merge.

**Tech Stack:** Python 3.11, pytest (+ pytest-asyncio), ClawTeam 0.2.0 CLI, sqlite/aiosqlite, tmux backend.

**Spec:** `docs/superpowers/specs/2026-05-27-v1-integration-hardening-design.md`

**Conventions for every task below:**
- Run the suite with `uv run pytest -m "not smoke" -q` (smoke tests launch a real team — never run them here).
- Branch per fix off `main`; merge back with `--no-ff` after green; audit downstream after each merge.
- Local imports inside methods for cross-layer deps (matches the existing pattern in `base.py`).

---

## File Structure

- **Modify** `pi_harness/topology/coordinator.py` — `launch` (init trajectory db + register profiles); new `teardown(handle)`; `on_completion` auto-teardown on success; `wait_for_completion` capture callback.
- **Modify** `pi_harness/clawteam/client.py` — new `kill_tmux_session(team_name)`; `wait_for_completion` gains optional `on_poll` callback; add module logger.
- **Modify** `pi_harness/topology/base.py` — new module-level `completion_protocol(agent_name)`; append it to leader + worker `task` in `build_template_dict`.
- **Modify** `pi_harness/trajectory/capture.py` — extract `diff_task_states(...)` helper; refactor `capture_clawteam_transitions` to use it.
- **Test** `tests/topology/test_coordinator.py` — fixture update + tests for #1, #2, #4.
- **Test** `tests/topology/test_base.py` — test for #3.
- **Test** `tests/test_clawteam_client.py` — tests for `kill_tmux_session` and `on_poll`.
- **Test** `tests/trajectory/test_capture.py` — test for `diff_task_states`.

---

## Task 1: Fix #1 — Auto-register profiles in `launch`

**Files:**
- Modify: `pi_harness/topology/coordinator.py` (imports + `launch`)
- Test: `tests/topology/test_coordinator.py`

- [ ] **Step 1: Branch**

```bash
git switch -c fix/01-profile-autoregister
```

- [ ] **Step 2: Write the failing test**

Add to `tests/topology/test_coordinator.py`, inside `class TestCoordinatorLaunch`:

```python
    def test_launch_registers_both_profiles_with_executor(self, coord, basic_spec):
        """A fresh-launch must register both pi-openai profiles (idempotent
        upsert) before the team launches, with --command set to the executor."""
        coord.launch(basic_spec)
        client = coord._clawteam_client
        assert client.register_profile.call_count == 2
        registered = [c.args[0] for c in client.register_profile.call_args_list]
        assert {p.name for p in registered} == {"pi-openai-reasoning", "pi-openai-fast"}
        assert all(p.command == basic_spec.executor for p in registered)
        # Profiles must exist before the team launches.
        names = [c[0] for c in client.mock_calls]
        assert names.index("register_profile") < names.index("launch_team")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/topology/test_coordinator.py::TestCoordinatorLaunch::test_launch_registers_both_profiles_with_executor -q`
Expected: FAIL — `register_profile.call_count == 0` (assert 0 == 2).

- [ ] **Step 4: Implement**

In `pi_harness/topology/coordinator.py`, add near the top-of-file imports:

```python
from dataclasses import replace
```

and extend the existing profile import:

```python
from pi_harness.clawteam_profile import PROFILE_NAME_FAST, build_profile_specs
```

In `launch`, insert profile registration immediately before step 5 (`self._clawteam_client.install_template(...)`):

```python
        # 4b. Register the profiles the template references (idempotent upsert).
        #     --command carries the chosen executor so `pi` vs `codex` is honored;
        #     ClawTeam's --agent only accepts claude/codex/gemini/kimi/nanobot.
        for pspec in build_profile_specs(self._config):
            self._clawteam_client.register_profile(replace(pspec, command=spec.executor))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/topology/test_coordinator.py -q`
Expected: PASS (new test + all existing launch tests, which tolerate the extra mock calls).

- [ ] **Step 6: Commit + merge + audit**

```bash
git add pi_harness/topology/coordinator.py tests/topology/test_coordinator.py
git commit -m "fix(coordinator): auto-register pi-openai profiles on launch"
git switch main && git merge --no-ff fix/01-profile-autoregister -m "Merge fix #1: profile auto-register"
uv run pytest -m "not smoke" -q
```
Audit: grep for other `register_profile` callers to ensure none now double-register in a way that matters (`grep -rn register_profile pi_harness tests`).

---

## Task 2: Fix #2 — Teardown that stops agents

**Files:**
- Modify: `pi_harness/clawteam/client.py` (new `kill_tmux_session`)
- Modify: `pi_harness/topology/coordinator.py` (new `teardown`; `on_completion` auto-teardown)
- Test: `tests/test_clawteam_client.py`, `tests/topology/test_coordinator.py`

- [ ] **Step 1: Branch**

```bash
git switch -c fix/02-teardown
```

- [ ] **Step 2: Write the failing client test**

First read `tests/test_clawteam_client.py` to reuse its `Config`/client fixture (it constructs a `ClawTeamClient` with a `Config`). Add this test (replace `make_client()` with the file's existing client-construction helper/fixture):

```python
def test_kill_tmux_session_targets_clawteam_session():
    """kill_tmux_session must `tmux kill-session` the `clawteam-{team}` session
    ClawTeam's tmux backend creates, and not raise when it is already gone."""
    from unittest.mock import patch
    client = make_client()  # reuse this file's existing client fixture/helper
    with patch("pi_harness.clawteam.client.subprocess.run") as m:
        m.return_value = subprocess.CompletedProcess([], 0, "", "")
        client.kill_tmux_session("team-abc123")
    m.assert_called_once()
    assert m.call_args.args[0] == ["tmux", "kill-session", "-t", "clawteam-team-abc123"]
    assert m.call_args.kwargs.get("check") is False
```

Add `import subprocess` to the test file if not present.

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/test_clawteam_client.py::test_kill_tmux_session_targets_clawteam_session -q`
Expected: FAIL — `AttributeError: ... has no attribute 'kill_tmux_session'`.

- [ ] **Step 4: Implement the client method**

In `pi_harness/clawteam/client.py`, add under the `# ---- team lifecycle ----` section (after `cleanup_team`):

```python
    def kill_tmux_session(self, team_name: str) -> subprocess.CompletedProcess:
        """Kill the tmux session ClawTeam created for ``team_name``.

        ClawTeam's tmux backend names each team's session ``clawteam-{team}``
        (clawteam/spawn/tmux_backend.py). ``team cleanup`` deletes team data but
        does NOT kill this session, so agents keep running (and burning credit).
        This is a direct ``tmux`` call — a sibling exception to install_template's
        non-clawteam behaviour — so teardown can actually stop agents. A missing
        session is treated as success (already gone).
        """
        session = f"clawteam-{team_name}"
        return subprocess.run(
            ["tmux", "kill-session", "-t", session],
            capture_output=True,
            text=True,
            check=False,
        )
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_clawteam_client.py -q`
Expected: PASS.

- [ ] **Step 6: Write the failing Coordinator teardown tests**

Add to `tests/topology/test_coordinator.py` a new class:

```python
class TestCoordinatorTeardown:
    def test_teardown_kills_session_then_cleans_up(self, coord, basic_spec):
        handle = coord.launch(basic_spec)
        client = coord._clawteam_client
        coord.teardown(handle)
        client.kill_tmux_session.assert_called_once_with(handle.team_name)
        client.cleanup_team.assert_called_once_with(handle.team_name)
        names = [c[0] for c in client.mock_calls]
        assert names.index("kill_tmux_session") < names.index("cleanup_team")

    def test_on_completion_tears_down_on_success(self, coord, basic_spec):
        handle = coord.launch(basic_spec)
        client = coord._clawteam_client
        client.wait_for_completion.return_value = True
        client.list_tasks.return_value = []
        coord.wait_for_completion(handle, timeout=60)
        coord.on_completion(handle)
        client.kill_tmux_session.assert_called_once_with(handle.team_name)
        client.cleanup_team.assert_called_once_with(handle.team_name)

    def test_on_completion_no_teardown_on_failure(self, coord, basic_spec):
        from pi_harness.clawteam import ClawTeamTimeout

        handle = coord.launch(basic_spec)
        client = coord._clawteam_client
        client.wait_for_completion.side_effect = ClawTeamTimeout("nope")
        client.list_tasks.return_value = []
        coord.wait_for_completion(handle, timeout=60)
        coord.on_completion(handle)
        client.kill_tmux_session.assert_not_called()
        client.cleanup_team.assert_not_called()
```

- [ ] **Step 7: Run to verify they fail**

Run: `uv run pytest tests/topology/test_coordinator.py::TestCoordinatorTeardown -q`
Expected: FAIL — `Coordinator` has no `teardown`.

- [ ] **Step 8: Implement the Coordinator side**

In `pi_harness/topology/coordinator.py`, add a `teardown` method and extend `on_completion`:

```python
    def teardown(self, handle: RunHandle) -> None:
        """Stop the run's agents and delete its team data.

        Kills the tmux session first (so agents stop immediately and stop
        burning credit), then removes the team record. Safe to call repeatedly.
        Callable directly; also invoked by on_completion on a clean success.
        """
        self._clawteam_client.kill_tmux_session(handle.team_name)
        self._clawteam_client.cleanup_team(handle.team_name)
```

```python
    def on_completion(self, handle: RunHandle) -> None:
        """Called after wait_for_completion. On a clean success: trigger Plan 4's
        improve run, then tear down the team. Failed/timed-out runs are left up
        for debugging."""
        result = self._last_result.get(handle.run_id)
        if result is not None and result.success:
            self._improve_runner.run_for_completed_run(
                handle.run_id, self._config, session_id=handle.session_id
            )
            self.teardown(handle)
```

- [ ] **Step 9: Run to verify they pass**

Run: `uv run pytest tests/topology/test_coordinator.py -q`
Expected: PASS (incl. existing `test_on_completion_calls_improve_runner_once_on_success` and `test_on_completion_skipped_on_failure`, which still hold).

- [ ] **Step 10: Commit + merge + audit**

```bash
git add pi_harness/clawteam/client.py pi_harness/topology/coordinator.py tests/test_clawteam_client.py tests/topology/test_coordinator.py
git commit -m "fix(teardown): kill clawteam tmux session before cleanup; auto-teardown on success"
git switch main && git merge --no-ff fix/02-teardown -m "Merge fix #2: teardown stops agents"
uv run pytest -m "not smoke" -q
```
Audit: grep for `cleanup_team` callers (`grep -rn "cleanup_team\|teardown" pi_harness tests`) — confirm the smoke's `finally: cleanup_team` is now redundant-but-harmless, and no other caller depended on the old non-killing behaviour.

---

## Task 3: Fix #3 — Inject completion protocol for all agents

**Files:**
- Modify: `pi_harness/topology/base.py` (`completion_protocol` + `build_template_dict`)
- Test: `tests/topology/test_base.py`

- [ ] **Step 1: Branch**

```bash
git switch -c fix/03-completion-protocol
```

- [ ] **Step 2: Write the failing test**

Add to `tests/topology/test_base.py`:

```python
class TestCompletionProtocolInjection:
    def test_build_template_dict_appends_protocol_to_every_agent(self):
        from pi_harness.topology.base import (
            AgentSpec, ModelTier, Role, RunSpec, SyncMode, TopologyMode,
        )
        from pi_harness.topology.sequential import SequentialTopology

        spec = RunSpec(
            goal="ship it",
            agents=[
                AgentSpec(name="lead", role=Role.ORCHESTRATOR,
                          model_tier=ModelTier.REASONING, task_prompt="lead the team"),
                AgentSpec(name="bob", role=Role.BUILDER,
                          model_tier=ModelTier.FAST, task_prompt="build the thing"),
            ],
            mode=TopologyMode.SEQUENTIAL,
            sync_mode=SyncMode.PER_AGENT,
            corpus_classifications=[],
        )
        dct = SequentialTopology().build_template_dict(spec)

        leader = dct["template"]["leader"]
        assert leader["task"].startswith("lead the team")
        assert "clawteam task update" in leader["task"]
        assert "--status completed" in leader["task"]
        assert "'lead'" in leader["task"]  # interpolated own name

        builder = dct["template"]["agents"][0]
        assert builder["task"].startswith("build the thing")
        assert "--status completed" in builder["task"]
        assert "'bob'" in builder["task"]

    def test_protocol_appended_to_default_prompt_too(self):
        """Agents with no task_prompt still get the protocol after the default."""
        from pi_harness.topology.base import (
            AgentSpec, ModelTier, Role, RunSpec, SyncMode, TopologyMode,
        )
        from pi_harness.topology.sequential import SequentialTopology

        spec = RunSpec(
            goal="ship it",
            agents=[
                AgentSpec(name="solo", role=Role.BUILDER, model_tier=ModelTier.FAST),
            ],
            mode=TopologyMode.SEQUENTIAL,
            sync_mode=SyncMode.PER_AGENT,
            corpus_classifications=[],
        )
        dct = SequentialTopology().build_template_dict(spec)
        leader = dct["template"]["leader"]
        assert "--status completed" in leader["task"]
        assert "'solo'" in leader["task"]
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/topology/test_base.py::TestCompletionProtocolInjection -q`
Expected: FAIL — `"--status completed"` not in `task`.

- [ ] **Step 4: Implement**

In `pi_harness/topology/base.py`, add a module-level function (after the dataclasses, before `class Topology`):

```python
def completion_protocol(agent_name: str) -> str:
    """Standing ClawTeam completion instructions appended to every agent's task.

    Decomposer-driven agents otherwise receive only the task description (the
    *what*) and never learn how to CLOSE a task on the ClawTeam board, so the
    run hangs until timeout. This envelope teaches the *how*; the agent name is
    interpolated and the team name is read from the pane's CLAWTEAM_TEAM_NAME.
    """
    return (
        "\n\n---\n"
        "ClawTeam protocol (how to complete your work):\n"
        f"- Your agent name is '{agent_name}'. Your team name is in the "
        "$CLAWTEAM_TEAM_NAME environment variable.\n"
        "- The task board is ALREADY seeded — do NOT create new tasks.\n"
        "- Find your task: run `clawteam task list \"$CLAWTEAM_TEAM_NAME\"` and "
        f"pick the task whose owner is '{agent_name}'.\n"
        "- If it is `blocked`, re-run that command every ~10s until it is "
        "unblocked (its blockers were completed by other agents).\n"
        "- Do the work described above.\n"
        "- Then mark it done: `clawteam task update \"$CLAWTEAM_TEAM_NAME\" "
        "<your-task-id> --status completed`.\n"
        "- Exit once your task(s) are completed."
    )
```

In `build_template_dict`, change the leader and worker `task` values to append the protocol:

```python
                "leader": {
                    "name": leader.name,
                    "type": leader.role.value,
                    "task": (leader.task_prompt or self._default_leader_prompt(spec))
                    + completion_protocol(leader.name),
                    "profile": ROLE_PROFILE_MAP.get(leader.role.value, ""),
                },
                "agents": [
                    {
                        "name": a.name,
                        "type": a.role.value,
                        "task": (a.task_prompt or self._default_worker_prompt(spec, a))
                        + completion_protocol(a.name),
                        "profile": ROLE_PROFILE_MAP.get(a.role.value, ""),
                    }
                    for a in workers
                ],
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/topology/test_base.py tests/spec/test_runspec.py tests/topology/test_synthesis.py -q`
Expected: PASS — including `test_runspec.py::...` asserting `task_prompt == "lead the team"` (unchanged, because injection is at template-build time, not in the bridge) and the synthesis profile tests (profile unaffected).

- [ ] **Step 6: Commit + merge + audit**

```bash
git add pi_harness/topology/base.py tests/topology/test_base.py
git commit -m "fix(topology): inject ClawTeam completion protocol into every agent's task"
git switch main && git merge --no-ff fix/03-completion-protocol -m "Merge fix #3: completion protocol injection"
uv run pytest -m "not smoke" -q
```
Audit: grep template-`task` consumers (`grep -rn '\["task"\]\|task_prompt' pi_harness tests`) — confirm nothing asserts an exact, protocol-free `task` string in a non-smoke test.

---

## Task 4: Fix #4 — Capture trajectory during the run

**Files:**
- Modify: `pi_harness/trajectory/capture.py` (extract `diff_task_states`; refactor `capture_clawteam_transitions`)
- Modify: `pi_harness/clawteam/client.py` (`wait_for_completion` `on_poll` param + logger)
- Modify: `pi_harness/topology/coordinator.py` (`launch` init_db; `wait_for_completion` capture callback)
- Test: `tests/trajectory/test_capture.py`, `tests/test_clawteam_client.py`, `tests/topology/test_coordinator.py` (fixture update)

- [ ] **Step 1: Branch**

```bash
git switch -c fix/04-trajectory-capture
```

- [ ] **Step 2: Write the failing `diff_task_states` test**

Add to `tests/trajectory/test_capture.py` (note: this is a sync test, so mark it to bypass the module's asyncio default):

```python
@pytest.mark.asyncio(loop_scope="function")
def test_diff_task_states_emits_only_on_change():
    from datetime import datetime, timezone
    from pi_harness.trajectory.capture import diff_task_states

    now = datetime.now(timezone.utc)
    state: dict[str, str] = {}

    first = diff_task_states(
        state,
        [{"task_id": "t1", "owner": "builder", "status": "pending"}],
        run_id="run-x",
        now=now,
    )
    assert len(first) == 1
    assert first[0].classification == "task_transition"
    assert first[0].output["status"] == "pending"
    assert first[0].input["prev_status"] is None
    assert state == {"t1": "pending"}

    # No change -> no events.
    same = diff_task_states(
        state,
        [{"task_id": "t1", "owner": "builder", "status": "pending"}],
        run_id="run-x",
        now=now,
    )
    assert same == []

    # Change -> one event, state updated.
    changed = diff_task_states(
        state,
        [{"task_id": "t1", "owner": "builder", "status": "completed"}],
        run_id="run-x",
        now=now,
    )
    assert len(changed) == 1
    assert changed[0].output["status"] == "completed"
    assert state["t1"] == "completed"
```

> If pytest-asyncio's default mode makes a plain `def` test awkward here, define it in a new sync test module `tests/trajectory/test_diff_task_states.py` (no `pytestmark`) instead — the assertions are identical.

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/trajectory/ -k diff_task_states -q`
Expected: FAIL — `cannot import name 'diff_task_states'`.

- [ ] **Step 4: Implement `diff_task_states` + refactor**

In `pi_harness/trajectory/capture.py`, add the helper (above `capture_clawteam_transitions`):

```python
def diff_task_states(
    prev_state: dict[str, str],
    tasks: list[Mapping[str, Any]],
    *,
    run_id: str,
    now: datetime,
) -> list[TrajectoryEvent]:
    """Return a task_transition event for each task whose status changed since
    the last poll (a never-seen task counts as a change, prev_status=None).

    ``prev_state`` (task_id -> status) is updated in place. Shared by
    ``capture_clawteam_transitions`` (async) and the Coordinator's sync wait
    callback so both agree on what counts as a transition.
    """
    events: list[TrajectoryEvent] = []
    for task in tasks:
        task_id = str(task.get("task_id") or task.get("id") or "")
        if not task_id:
            continue
        status = str(task.get("status") or task.get("state") or "")
        prev = prev_state.get(task_id)
        if prev == status:
            continue
        events.append(
            TrajectoryEvent(
                run_id=run_id,
                agent_id=str(task.get("owner") or task.get("agent") or "") or "_team",
                step_id=f"clawteam-{task_id}-{status}",
                ts=now,
                model="",
                tool="",
                input={"task_id": task_id, "prev_status": prev},
                output={"task_id": task_id, "status": status, "raw": task},
                duration_ms=0,
                tokens_in=0,
                tokens_out=0,
                outcome="success",
                classification="task_transition",
            )
        )
        prev_state[task_id] = status
    return events
```

Replace the body of `capture_clawteam_transitions` (the `last_state`/`first_poll` loop) with a call to the helper:

```python
async def capture_clawteam_transitions(
    *,
    run_id: str,
    team_name: str,
    db_path: Path | str | None = None,
    poll_interval_s: float = 2.0,
) -> None:
    """Poll `clawteam task list --json` and write a task_transition event on
    each status change. Runs until cancelled; poll errors are logged + retried."""
    last_state: dict[str, str] = {}
    while True:
        try:
            tasks = await _clawteam_list_tasks(team_name)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("capture: clawteam poll failed: %s", exc)
            await asyncio.sleep(poll_interval_s)
            continue
        now = datetime.now(timezone.utc)
        for ev in diff_task_states(last_state, tasks, run_id=run_id, now=now):
            try:
                await awrite_event(ev, db_path=db_path)
            except Exception as exc:  # noqa: BLE001
                log.exception("capture: failed writing task_transition: %s", exc)
        await asyncio.sleep(poll_interval_s)
```

- [ ] **Step 5: Run to verify diff + existing capture tests pass**

Run: `uv run pytest tests/trajectory/ -q`
Expected: PASS — new diff test + existing `test_capture_clawteam_transitions_emits_on_state_change` (behavior preserved).

- [ ] **Step 6: Write the failing client `on_poll` test**

Add to `tests/test_clawteam_client.py` (reuse this file's client fixture/helper + its `list_tasks` patching pattern):

```python
def test_wait_for_completion_invokes_on_poll_each_poll(monkeypatch):
    """on_poll receives the freshly-listed tasks on every poll iteration."""
    client = make_client()  # reuse this file's existing client fixture/helper
    polls = [
        [{"id": "t1", "status": "in_progress"}],
        [{"id": "t1", "status": "completed"}],
    ]
    seen = []
    monkeypatch.setattr(client, "list_tasks", lambda team: polls[min(len(seen), len(polls) - 1)])
    client.wait_for_completion(
        "team-1", timeout=5.0, poll_interval=0.0,
        on_poll=lambda tasks: seen.append([t["status"] for t in tasks]),
    )
    assert ["in_progress"] in seen
    assert ["completed"] in seen
```

> If `make_client` does not exist, build a client from a tmp `Config`: `ClawTeamClient(load_config(env_file=None))` with `OPENAI_API_KEY` set via monkeypatch — match whatever the file already does.

- [ ] **Step 7: Run to verify it fails**

Run: `uv run pytest tests/test_clawteam_client.py -k on_poll -q`
Expected: FAIL — `wait_for_completion() got an unexpected keyword argument 'on_poll'`.

- [ ] **Step 8: Implement `on_poll` on the client**

In `pi_harness/clawteam/client.py`: add `import logging` and `log = logging.getLogger(__name__)` near the top; add `Callable` to the `typing` import. Change the `wait_for_completion` signature and loop:

```python
    def wait_for_completion(
        self,
        team_name: str,
        timeout: float,
        poll_interval: float = 5.0,
        on_poll: Optional[Callable[[List[Mapping[str, Any]]], None]] = None,
    ) -> bool:
        """Block until every task on the board reaches a terminal status.

        ``on_poll`` (optional) is called with the freshly-listed tasks on every
        poll iteration — used by the Coordinator to capture trajectory events.
        A raising callback is logged and ignored; it never aborts the wait.
        """
        deadline = time.monotonic() + timeout
        while True:
            tasks = self.list_tasks(team_name)
            if on_poll is not None:
                try:
                    on_poll(tasks)
                except Exception:  # noqa: BLE001 — capture must never break the wait
                    log.exception("wait_for_completion: on_poll callback failed")
            if tasks:
                failed = [t for t in tasks if t.get("status") in FAILURE_STATUSES]
                if failed:
                    failed_ids = ", ".join(
                        str(t.get("task_id", t.get("id", "?"))) for t in failed
                    )
                    raise ClawTeamRunFailure(
                        f"team={team_name!r} task(s) failed: {failed_ids}"
                    )
                if all(t.get("status") in TERMINAL_STATUSES for t in tasks):
                    return True
            if time.monotonic() >= deadline:
                raise ClawTeamTimeout(
                    f"team={team_name!r} did not finish within {timeout:.1f}s"
                )
            time.sleep(poll_interval)
```

- [ ] **Step 9: Run to verify it passes**

Run: `uv run pytest tests/test_clawteam_client.py -q`
Expected: PASS.

- [ ] **Step 10: Update the `coord` fixture + write the failing Coordinator capture tests**

In `tests/topology/test_coordinator.py`, update the `coord` fixture to give the config a real trajectory db path and concrete model names (so `init_db` and `build_profile_specs` work):

```python
@pytest.fixture
def coord(mock_clawteam_client, mock_corpus_reader, mock_improve_runner, tmp_path):
    cfg = MagicMock()
    cfg.trajectory_db_path = tmp_path / "trajectory.db"
    cfg.reasoning_model = "gpt-5"
    cfg.fast_model = "gpt-5-mini"
    return Coordinator(
        config=cfg,
        clawteam_client=mock_clawteam_client,
        corpus_reader=mock_corpus_reader,
        improve_runner=mock_improve_runner,
    )
```

Add a new class:

```python
class TestCoordinatorTrajectoryCapture:
    def test_launch_initializes_trajectory_db(self, coord, basic_spec):
        coord.launch(basic_spec)
        assert coord._config.trajectory_db_path.exists()

    def test_wait_for_completion_captures_task_transitions(self, coord, basic_spec):
        from pi_harness.trajectory.store import query_events

        handle = coord.launch(basic_spec)
        client = coord._clawteam_client

        def fake_wait(team_name, timeout, poll_interval=5.0, on_poll=None):
            on_poll([{"task_id": "t1", "owner": "a", "status": "pending"}])
            on_poll([{"task_id": "t1", "owner": "a", "status": "completed"}])
            return True

        client.wait_for_completion.side_effect = fake_wait
        client.list_tasks.return_value = [{"id": "t1", "status": "completed"}]

        result = coord.wait_for_completion(handle, timeout=60)
        assert result.success is True

        events = query_events(
            run_id=handle.run_id, db_path=coord._config.trajectory_db_path
        )
        statuses = [
            e.output["status"] for e in events if e.classification == "task_transition"
        ]
        assert "pending" in statuses
        assert "completed" in statuses
```

- [ ] **Step 11: Run to verify they fail**

Run: `uv run pytest tests/topology/test_coordinator.py::TestCoordinatorTrajectoryCapture -q`
Expected: FAIL — db not created (no `init_db` in launch) / no events captured (no `on_poll` wiring).

- [ ] **Step 12: Implement the Coordinator wiring**

In `pi_harness/topology/coordinator.py` `launch`, add as the FIRST statement of the method body:

```python
        # Ensure the trajectory store exists before any capture write.
        from pi_harness.trajectory.store import init_db
        init_db(self._config.trajectory_db_path)
```

Rewrite the head of `wait_for_completion` to pass a capture callback:

```python
    def wait_for_completion(self, handle: RunHandle, timeout: float) -> RunResult:
        """Block on Plan 1's wait_for_completion, capturing task transitions into
        the trajectory store as they happen, then summarize as RunResult."""
        from pi_harness.trajectory.capture import diff_task_states
        from pi_harness.trajectory.store import write_event

        capture_state: dict[str, str] = {}

        def _capture(tasks) -> None:
            events = diff_task_states(
                capture_state, tasks, run_id=handle.run_id,
                now=datetime.now(timezone.utc),
            )
            for ev in events:
                try:
                    write_event(ev, db_path=self._config.trajectory_db_path)
                except Exception:  # noqa: BLE001 — capture must never break the wait
                    pass

        error: Exception | None = None
        success = False
        try:
            success = self._clawteam_client.wait_for_completion(
                handle.team_name, timeout=timeout, poll_interval=5.0, on_poll=_capture
            )
        except (ClawTeamTimeout, ClawTeamRunFailure) as exc:
            error = exc
            success = False
        # ... (rest of the method — terminal-status snapshot, RunResult, store — unchanged)
```

- [ ] **Step 13: Run to verify they pass**

Run: `uv run pytest tests/topology/test_coordinator.py -q`
Expected: PASS — capture tests + all existing Coordinator tests (now running against a real tmp db).

- [ ] **Step 14: Commit + merge + audit**

```bash
git add pi_harness/trajectory/capture.py pi_harness/clawteam/client.py pi_harness/topology/coordinator.py tests/trajectory/ tests/test_clawteam_client.py tests/topology/test_coordinator.py
git commit -m "fix(trajectory): capture task transitions during the run so improve has data"
git switch main && git merge --no-ff fix/04-trajectory-capture -m "Merge fix #4: live trajectory capture"
uv run pytest -m "not smoke" -q
```
Audit: confirm `run_for_completed_run` queries the same `config.trajectory_db_path` the capture writes to; grep `wait_for_completion` callers (CLI, editor `/launch`) to ensure none pass positional args that collide with the new `on_poll` kwarg.

---

## Task 5: Full-suite verification + smoke note

- [ ] **Step 1: Run the whole non-smoke suite from `main`**

Run: `uv run pytest -m "not smoke" -q`
Expected: all green.

- [ ] **Step 2: Verify the improve-handoff gap is closed in code (no smoke run)**

Confirm by reading, not running: with `launch` calling `init_db` and `wait_for_completion` capturing transitions, `on_completion → run_for_completed_run` now finds events for the run, so the `tests/topology/test_smoke_end_to_end.py` try/except `pytest.xfail` block is no longer triggered (the test would pass through). Leave the smoke file unchanged — it self-heals and must not be run here.

- [ ] **Step 3: Report back to Pranav** with: branches merged, test counts before/after, the four behavioral changes, and the smoke note.

---

## Self-Review

**Spec coverage:**
- #1 profile auto-register → Task 1. ✅
- #2 teardown (kill session + cleanup; explicit method + auto on success) → Task 2. ✅
- #3 protocol injection in `build_template_dict` for all agents → Task 3. ✅
- #4 trajectory capture folded into the wait poll via `on_poll`, `diff_task_states` shared helper, `init_db` in launch → Task 4. ✅
- Sequencing (branch-per-fix → merge → audit), `pytest -m "not smoke"` → every task. ✅
- Non-goal (no pi-agent stdout capture) → respected (only `task_transition` events). ✅

**Placeholder scan:** No TBD/TODO. The two "reuse this file's existing client fixture/helper" notes in Tasks 2/4 point at a real, readable file (`tests/test_clawteam_client.py`) with explicit fallback construction — resolved at execution by reading it, not a content gap.

**Type/signature consistency:** `kill_tmux_session(team_name)`, `teardown(handle)`, `completion_protocol(agent_name)`, `diff_task_states(prev_state, tasks, *, run_id, now) -> list[TrajectoryEvent]` (mutates `prev_state`), and `wait_for_completion(..., on_poll=Optional[Callable[[List[Mapping]], None]])` are used identically across their definition and call sites (Coordinator callback, refactored async capture). `config.trajectory_db_path` is the single db path for both capture writes and improve reads.
