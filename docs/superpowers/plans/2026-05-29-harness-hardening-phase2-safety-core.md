# Harness Hardening — Phase 2 (Safety Core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a launched run safe by default — isolated on its own `run/<id>` branch, consolidated back automatically, always torn down (with a debuggable snapshot on failure) — and fix the dashboard finalizer so API-launched runs actually finalize.

**Architecture:** ClawTeam already owns git-worktree isolation (`clawteam launch --workspace --repo`, per-agent worktrees forked off `base_branch = current_branch(repo)`, manual `clawteam workspace merge`). The harness currently opts out by passing neither flag. Phase 2 makes `Coordinator.launch` create a dedicated run worktree on branch `run/<id>`, point ClawTeam at it (so agents sub-isolate off `run/<id>`), then on success consolidate each agent branch back into `run/<id>` via `clawteam workspace merge` and tear the team down; on failure it snapshots then tears down (unless `--keep-alive`). The user's checked-out branch is never touched; `run/<id>` is left for review-then-merge.

**Tech Stack:** Python 3.11, Typer CLI, `subprocess` over the `clawteam` 0.2.x CLI, `git worktree`, pytest + `unittest.mock` (MagicMock fixtures). Run tests with `uv run pytest` (default selector already excludes `smoke`; **never** add smoke-triggering tests).

---

## File Structure

- **Create** `pi_harness/clawteam/git_workspace.py` — harness-owned thin `git worktree` helpers (repo-root detection, create/remove a run worktree on a new branch). Kept separate from `pi_harness/clawteam/client.py` (which wraps the `clawteam` CLI) because these are plain local-git operations the harness owns, not ClawTeam calls.
- **Modify** `pi_harness/clawteam/client.py` — add `workspace`/`repo` args to `launch_team`; add `merge_workspace` and `snapshot_team` methods.
- **Modify** `pi_harness/topology/base.py` — extend `RunHandle` with isolation state (`run_branch`, `workspace_repo`, `agent_names`, `keep_alive`).
- **Modify** `pi_harness/topology/coordinator.py` — isolation wiring in `launch`, a new `consolidate`, and new `on_completion`/`teardown` policy (always tear down; snapshot on failure; consolidate on success).
- **Modify** `pi_harness/cli.py` — add `--in-place` / `--keep-alive` flags to `launch`, thread them through, and print the run branch.
- **Modify** `pi_harness/spec/editor.py` — fix the `_finalize_run` timeout bug.
- **Tests:** `tests/clawteam/test_git_workspace.py` (new), `tests/clawteam/test_client.py` (extend), `tests/topology/test_coordinator.py` (extend + update one inverted test), `tests/spec/test_editor_finalizer.py` (new), `tests/test_cli_launch_flags.py` (new).

> Exact test paths assume the existing layout (`tests/clawteam/`, `tests/topology/`, `tests/spec/`). If `tests/clawteam/` does not exist, create it with an empty `__init__.py` to match sibling packages.

---

## Task 1: Fix the dashboard finalizer timeout bug

`spec/editor.py:64` calls `coordinator.wait_for_completion(handle)` but the real signature is `wait_for_completion(self, handle, timeout)` (`coordinator.py:268`, `timeout` required positional). The `TypeError` is swallowed by the broad `except`, so dashboard-launched runs never wait/improve/teardown — the spec just resets to `decomposed`. This task is self-contained (no isolation work) and is the quickest win.

**Files:**
- Modify: `pi_harness/spec/editor.py:58-69`
- Test: `tests/spec/test_editor_finalizer.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/spec/test_editor_finalizer.py`:

```python
"""Regression: _finalize_run must call wait_for_completion with a timeout."""
from __future__ import annotations

from unittest.mock import MagicMock

from pi_harness.spec import editor


class _RealishCoordinator:
    """Mimics Coordinator's real signature: timeout is a required positional."""

    def __init__(self) -> None:
        self.waited_with = None

    def wait_for_completion(self, handle, timeout):  # noqa: ANN001 - test stub
        self.waited_with = timeout
        return MagicMock(success=True)

    def on_completion(self, handle):  # noqa: ANN001 - test stub
        pass


def test_finalize_run_passes_timeout(monkeypatch):
    # Don't touch the filesystem: stub the status writer.
    monkeypatch.setattr(editor, "_set_spec_status", lambda spec_id, status: None)
    coord = _RealishCoordinator()
    handle = MagicMock(run_id="run-xyz")

    editor._finalize_run(coord, handle, "spec-1")

    # Before the fix this raised TypeError (swallowed) and timeout stayed None.
    assert coord.waited_with is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/spec/test_editor_finalizer.py -v`
Expected: FAIL — `coord.waited_with` is `None` (the swallowed `TypeError` means `wait_for_completion` never ran successfully).

- [ ] **Step 3: Apply the minimal fix**

In `pi_harness/spec/editor.py`, change the `_finalize_run` signature and call:

```python
def _finalize_run(coordinator, handle, spec_id: str, timeout: float = 1800.0) -> None:
    """Background-task body: wait for the team to terminate, run the improve
    loop + teardown via on_completion, and flip the spec to its post-run
    status. Errors are logged; they must not crash the FastAPI worker."""
    success = False
    try:
        result = coordinator.wait_for_completion(handle, timeout=timeout)
        success = bool(getattr(result, "success", False))
        coordinator.on_completion(handle)
    except Exception:
        logger.exception("finalizer: background completion failed for run %s", handle.run_id)
    _set_spec_status(spec_id, "complete" if success else "decomposed")
```

(The default keeps the existing `background_tasks.add_task(_finalize_run, coordinator, handle, spec_id)` call site working unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/spec/test_editor_finalizer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/spec/editor.py tests/spec/test_editor_finalizer.py
git commit -m "fix(spec): _finalize_run passes timeout to wait_for_completion"
```

---

## Task 2: Harness git-worktree helper

A tiny module of local `git` operations the harness owns (no ClawTeam involved): detect the repo root, create a run worktree on a fresh branch off HEAD, and remove it (keeping the branch). Pure git → testable with a real temp repo, no clawteam/pi/tmux needed.

**Files:**
- Create: `pi_harness/clawteam/git_workspace.py`
- Test: `tests/clawteam/test_git_workspace.py` (create; add `tests/clawteam/__init__.py` if missing)

- [ ] **Step 1: Write the failing test**

Create `tests/clawteam/test_git_workspace.py`:

```python
"""Local git-worktree helpers for run isolation."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pi_harness.clawteam import git_workspace as gw


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    _git(["init", "-q"], tmp_path)
    _git(["config", "user.email", "t@t.t"], tmp_path)
    _git(["config", "user.name", "t"], tmp_path)
    (tmp_path / "f.txt").write_text("hi\n")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-qm", "init"], tmp_path)
    return tmp_path


def test_repo_root_finds_toplevel(repo):
    sub = repo / "a" / "b"
    sub.mkdir(parents=True)
    assert gw.repo_root(sub) == repo.resolve()


def test_create_run_worktree_makes_branch_off_head(repo):
    wt = repo / ".worktrees" / "run-1"
    gw.create_run_worktree(repo, branch="run/abc123", worktree_path=wt)
    assert wt.is_dir()
    # The new worktree is checked out on the new branch.
    out = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=wt, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert out == "run/abc123"


def test_remove_run_worktree_keeps_branch(repo):
    wt = repo / ".worktrees" / "run-1"
    gw.create_run_worktree(repo, branch="run/abc123", worktree_path=wt)
    gw.remove_run_worktree(repo, wt)
    assert not wt.exists()
    # Branch survives the worktree removal.
    branches = subprocess.run(
        ["git", "branch", "--list", "run/abc123"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout
    assert "run/abc123" in branches


def test_remove_missing_worktree_is_noop(repo):
    gw.remove_run_worktree(repo, repo / ".worktrees" / "nope")  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/clawteam/test_git_workspace.py -v`
Expected: FAIL — `ModuleNotFoundError: pi_harness.clawteam.git_workspace`.

- [ ] **Step 3: Write the implementation**

Create `pi_harness/clawteam/git_workspace.py`:

```python
"""Local git-worktree helpers the harness owns for run isolation.

These are plain `git` operations (NOT clawteam calls): create a dedicated
worktree on a fresh `run/<id>` branch off HEAD so a launched team works in
isolation from the user's checked-out branch, and remove the worktree on
teardown while keeping the branch (the consolidated work lives on it).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

__all__ = ["repo_root", "create_run_worktree", "remove_run_worktree"]


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True,
    )


def repo_root(start: Path | str | None = None) -> Path:
    """Return the git repo top-level containing ``start`` (default: cwd)."""
    cwd = Path(start) if start is not None else Path.cwd()
    out = _git(["rev-parse", "--show-toplevel"], cwd).stdout.strip()
    return Path(out).resolve()


def create_run_worktree(repo: Path, *, branch: str, worktree_path: Path) -> None:
    """Create ``worktree_path`` as a new worktree on a new ``branch`` off HEAD."""
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    _git(["worktree", "add", "-b", branch, str(worktree_path), "HEAD"], repo)


def remove_run_worktree(repo: Path, worktree_path: Path) -> None:
    """Remove the worktree directory (keeps the branch). Missing → no-op."""
    if not Path(worktree_path).exists():
        return
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree_path)],
        cwd=str(repo), capture_output=True, text=True, check=False,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/clawteam/test_git_workspace.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add pi_harness/clawteam/git_workspace.py tests/clawteam/
git commit -m "feat(clawteam): git-worktree helpers for run isolation"
```

---

## Task 3: ClawTeamClient — workspace/repo on launch_team + merge_workspace + snapshot_team

Add the three ClawTeam CLI calls Phase 2 needs. Confirmed signatures:
`clawteam launch TEMPLATE --team Y --goal Z [--workspace] [--repo PATH]`,
`clawteam workspace merge TEAM AGENT [--repo R] [--target T]`,
`clawteam team snapshot TEAM [--tag L]`.

**Files:**
- Modify: `pi_harness/clawteam/client.py:111-129` (launch_team) and add two methods after `cleanup_team`
- Test: `tests/clawteam/test_client.py` (extend; create if absent)

- [ ] **Step 1: Write the failing tests**

Add to `tests/clawteam/test_client.py` (create the file with this content if it doesn't exist):

```python
"""ClawTeamClient subprocess-argv tests for Phase 2 additions."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from pi_harness.clawteam.client import ClawTeamClient


def _client():
    cfg = MagicMock()
    cfg.clawteam_state_dir = "/tmp/ctstate"
    cfg.openai_api_key = "sk-test"
    return ClawTeamClient(config=cfg)


def _argv(mock_run):
    return mock_run.call_args.args[0]


def test_launch_team_passes_workspace_and_repo():
    c = _client()
    with patch("pi_harness.clawteam.client.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        c.launch_team(template="t", team_name="team-1", goal="g",
                      workspace=True, repo="/path/wt")
    argv = _argv(run)
    assert "--workspace" in argv
    assert argv[argv.index("--repo") + 1] == "/path/wt"


def test_launch_team_omits_workspace_by_default():
    c = _client()
    with patch("pi_harness.clawteam.client.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        c.launch_team(template="t", team_name="team-1", goal="g")
    argv = _argv(run)
    assert "--workspace" not in argv
    assert "--repo" not in argv


def test_merge_workspace_argv_and_no_raise_on_conflict():
    c = _client()
    with patch("pi_harness.clawteam.client.subprocess.run") as run:
        run.return_value = MagicMock(returncode=1, stdout="CONFLICT", stderr="")
        result = c.merge_workspace("team-1", "agent-a", repo="/path/wt", target="run/abc")
    argv = _argv(run)
    assert argv[-6:] == ["workspace", "merge", "team-1", "agent-a", "--repo", "/path/wt"] or \
        ("workspace" in argv and "merge" in argv and "team-1" in argv and "agent-a" in argv)
    assert argv[argv.index("--target") + 1] == "run/abc"
    # check=False: a conflict (rc=1) is returned, not raised.
    assert result.returncode == 1


def test_snapshot_team_argv():
    c = _client()
    with patch("pi_harness.clawteam.client.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        c.snapshot_team("team-1", tag="failed-abc")
    argv = _argv(run)
    assert argv[argv.index("team") + 1] == "snapshot"
    assert "team-1" in argv
    assert argv[argv.index("--tag") + 1] == "failed-abc"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/clawteam/test_client.py -v`
Expected: FAIL — `launch_team()` has no `workspace`/`repo` params (TypeError); `merge_workspace`/`snapshot_team` don't exist (AttributeError).

- [ ] **Step 3: Implement**

In `pi_harness/clawteam/client.py`, replace `launch_team` (lines 111-129) with:

```python
    def launch_team(
        self,
        template: str,
        team_name: str,
        goal: str,
        profile: Optional[str] = None,
        *,
        workspace: bool = False,
        repo: Optional[str] = None,
    ) -> subprocess.CompletedProcess:
        """Spawn a new ClawTeam team from a template.

        Real invocation: ``clawteam --data-dir D launch TEMPLATE --team Y --goal Z
        [--profile P] [--workspace] [--repo PATH]``

        When ``workspace`` is True, ClawTeam creates a per-agent git worktree off
        the current branch of ``repo`` (default cwd); the harness uses this for
        run isolation (see topology.coordinator).
        """
        sub: List[str] = [
            "launch", template,
            "--team", team_name,
            "--goal", goal,
        ]
        if profile is not None:
            sub.extend(["--profile", profile])
        if workspace:
            sub.append("--workspace")
        if repo is not None:
            sub.extend(["--repo", repo])
        return self._run(sub)
```

Then add, immediately after `cleanup_team` (after line 136):

```python
    def merge_workspace(
        self,
        team_name: str,
        agent_name: str,
        *,
        repo: Optional[str] = None,
        target: Optional[str] = None,
    ) -> subprocess.CompletedProcess:
        """Merge one agent's workspace branch into ``target`` (default: base branch).

        Real invocation: ``clawteam --data-dir D workspace merge TEAM AGENT
        [--repo R] [--target T]``

        Uses ``check=False`` so a merge conflict (non-zero exit) is *returned* for
        the caller to surface, not raised — consolidation must continue for the
        remaining agents.
        """
        sub: List[str] = ["workspace", "merge", team_name, agent_name]
        if repo is not None:
            sub.extend(["--repo", repo])
        if target is not None:
            sub.extend(["--target", target])
        return self._run(sub, check=False)

    def snapshot_team(
        self, team_name: str, *, tag: Optional[str] = None,
    ) -> subprocess.CompletedProcess:
        """Snapshot full team state (config, tasks, events, sessions, costs).

        Real invocation: ``clawteam --data-dir D team snapshot TEAM [--tag L]``.
        ``check=False`` so a snapshot failure never blocks teardown.
        """
        sub: List[str] = ["team", "snapshot", team_name]
        if tag is not None:
            sub.extend(["--tag", tag])
        return self._run(sub, check=False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/clawteam/test_client.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add pi_harness/clawteam/client.py tests/clawteam/test_client.py
git commit -m "feat(clawteam): launch_team workspace/repo + merge_workspace + snapshot_team"
```

---

## Task 4: Extend RunHandle with isolation state

`on_completion`/`teardown`/`consolidate` receive only a `RunHandle`, so the run's branch, worktree path, agent list, and keep-alive choice must travel on it. All new fields default so existing constructions keep working.

**Files:**
- Modify: `pi_harness/topology/base.py:78-87`
- Test: `tests/topology/test_base.py` (extend)

- [ ] **Step 1: Write the failing test**

Add to `tests/topology/test_base.py`:

```python
def test_run_handle_isolation_fields_default_empty():
    from datetime import datetime, timezone
    from pi_harness.topology.base import RunHandle, TopologyMode

    h = RunHandle(
        run_id="run-1", team_name="team-1",
        started_at=datetime.now(timezone.utc), topology=TopologyMode.SEQUENTIAL,
    )
    assert h.run_branch is None
    assert h.workspace_repo is None
    assert h.agent_names == []
    assert h.keep_alive is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/topology/test_base.py::test_run_handle_isolation_fields_default_empty -v`
Expected: FAIL — `AttributeError: 'RunHandle' object has no attribute 'run_branch'`.

- [ ] **Step 3: Implement**

In `pi_harness/topology/base.py`, replace the `RunHandle` dataclass (lines 78-87) with:

```python
@dataclass
class RunHandle:
    """Returned by Coordinator.launch. Threaded into trajectory capture +
    post-completion improve scheduling. session_id is propagated from RunSpec
    so the improve adapter can stamp corpus entries with the originating session.

    Isolation state (Phase 2): when a run is isolated (the default), ``run_branch``
    is the ``run/<id>`` branch all work lands on, ``workspace_repo`` is the path to
    the dedicated run worktree ClawTeam was pointed at, and ``agent_names`` lists
    leader+workers (consolidation order). ``keep_alive`` suppresses teardown on
    failure so a failed team can be inspected live."""
    run_id: str
    team_name: str
    started_at: datetime
    topology: TopologyMode
    session_id: str | None = None
    run_branch: str | None = None
    workspace_repo: str | None = None
    agent_names: list[str] = field(default_factory=list)
    keep_alive: bool = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/topology/test_base.py::test_run_handle_isolation_fields_default_empty -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pi_harness/topology/base.py tests/topology/test_base.py
git commit -m "feat(topology): RunHandle carries run isolation state"
```

---

## Task 5: Coordinator.launch — isolate on a run branch (default), `in_place` opt-out

Before launching, create a `run/<id>` worktree off HEAD and point ClawTeam at it with `--workspace`, so each agent sub-isolates off `run/<id>`. Record isolation state on the handle. `in_place=True` preserves today's behavior (no worktree, no `--workspace`).

**Files:**
- Modify: `pi_harness/topology/coordinator.py` — `launch` signature + steps 5 and handle construction (lines 89, 167-194)
- Test: `tests/topology/test_coordinator.py` (extend)

- [ ] **Step 1: Write the failing tests**

Add a new class to `tests/topology/test_coordinator.py`:

```python
class TestCoordinatorIsolation:
    def test_launch_isolates_by_default(self, coord, basic_spec, mock_clawteam_client):
        with patch("pi_harness.topology.coordinator.git_workspace") as gw:
            gw.repo_root.return_value = __import__("pathlib").Path("/repo")
            handle = coord.launch(basic_spec)
        # A run worktree was created off HEAD on a run/<id> branch...
        assert gw.create_run_worktree.called
        assert handle.run_branch and handle.run_branch.startswith("run/")
        assert handle.workspace_repo
        # ...and ClawTeam was pointed at it with --workspace.
        kwargs = mock_clawteam_client.launch_team.call_args.kwargs
        assert kwargs["workspace"] is True
        assert kwargs["repo"] == handle.workspace_repo
        # Agent names captured for consolidation (leader + workers).
        assert set(handle.agent_names) == {"a", "b"}

    def test_launch_in_place_skips_isolation(self, coord, basic_spec, mock_clawteam_client):
        with patch("pi_harness.topology.coordinator.git_workspace") as gw:
            handle = coord.launch(basic_spec, in_place=True)
        assert not gw.create_run_worktree.called
        assert handle.run_branch is None
        kwargs = mock_clawteam_client.launch_team.call_args.kwargs
        assert kwargs.get("workspace", False) is False

    def test_launch_propagates_keep_alive_to_handle(self, coord, basic_spec):
        with patch("pi_harness.topology.coordinator.git_workspace") as gw:
            gw.repo_root.return_value = __import__("pathlib").Path("/repo")
            handle = coord.launch(basic_spec, keep_alive=True)
        assert handle.keep_alive is True
```

> Note: the existing `mock_clawteam_client.launch_team` is a MagicMock, so the new keyword args are accepted automatically. The current `test_calls_corpus_prime_before_launch` only asserts `launch_team.called`, so it still passes.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/topology/test_coordinator.py::TestCoordinatorIsolation -v`
Expected: FAIL — `launch()` has no `in_place`/`keep_alive` kwargs (TypeError) and `coordinator.git_workspace` isn't imported.

- [ ] **Step 3: Implement**

In `pi_harness/topology/coordinator.py`, add the import near the top (after line 14):

```python
from pathlib import Path

from pi_harness.clawteam import git_workspace
```

Change the `launch` signature (line 89):

```python
    def launch(self, spec: RunSpec, *, in_place: bool = False, keep_alive: bool = False) -> RunHandle:
```

After the team_name is derived (after line 127) and before the `launch_team` call, insert the worktree setup. Replace the existing step-5 launch block (lines 167-175) with:

```python
        # 4c. Isolation (default): create a run/<id> worktree off HEAD and point
        #     ClawTeam at it so per-agent worktrees fork off run/<id>; the user's
        #     checked-out branch is never touched. --in-place opts out.
        run_branch: str | None = None
        workspace_repo: str | None = None
        if not in_place:
            repo = git_workspace.repo_root()
            run_branch = f"run/{run_id[-8:]}"
            wt_path = Path(self._config.clawteam_state_dir) / "run-worktrees" / run_id
            git_workspace.create_run_worktree(repo, branch=run_branch, worktree_path=wt_path)
            workspace_repo = str(wt_path)

        # Capture agent names (leader + workers) for later consolidation.
        agent_names = [leader_block["name"]] + [
            a["name"] for a in template_dict["template"]["agents"]
        ]

        # 5. Register template + launch team via Plan 1.
        self._clawteam_client.install_template(
            template_name, tomli_w.dumps(template_dict)
        )
        self._clawteam_client.launch_team(
            template=template_name,
            team_name=team_name,
            goal=spec.goal,
            workspace=workspace_repo is not None,
            repo=workspace_repo,
        )
```

Then update the `RunHandle(...)` construction (lines 188-194) to carry the new state:

```python
        handle = RunHandle(
            run_id=run_id,
            team_name=team_name,
            started_at=datetime.now(timezone.utc),
            topology=spec.mode,
            session_id=spec.session_id,
            run_branch=run_branch,
            workspace_repo=workspace_repo,
            agent_names=agent_names,
            keep_alive=keep_alive,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/topology/test_coordinator.py -v`
Expected: PASS (new isolation tests + all existing launch tests).

- [ ] **Step 5: Commit**

```bash
git add pi_harness/topology/coordinator.py tests/topology/test_coordinator.py
git commit -m "feat(topology): launch isolates on run/<id> branch by default (--in-place opts out)"
```

---

## Task 6: Coordinator.consolidate — merge agent branches into the run branch

After a successful run, merge each agent's branch into `run/<id>` via `clawteam workspace merge ... --target run/<id>`, in launch order (leader first). A conflicting merge is recorded and skipped, never force-resolved. No-op for `in_place` runs.

**Files:**
- Modify: `pi_harness/topology/coordinator.py` — add `consolidate` after `teardown`
- Test: `tests/topology/test_coordinator.py` (extend)

- [ ] **Step 1: Write the failing tests**

Add to `tests/topology/test_coordinator.py`:

```python
class TestCoordinatorConsolidate:
    def _isolated_handle(self):
        from datetime import datetime, timezone
        return RunHandle(
            run_id="run-1", team_name="team-1",
            started_at=datetime.now(timezone.utc), topology=TopologyMode.SEQUENTIAL,
            run_branch="run/abc", workspace_repo="/wt", agent_names=["a", "b"],
        )

    def test_consolidate_merges_each_agent_into_run_branch(self, coord, mock_clawteam_client):
        mock_clawteam_client.merge_workspace.return_value = MagicMock(returncode=0)
        handle = self._isolated_handle()
        conflicts = coord.consolidate(handle)
        assert conflicts == []
        calls = mock_clawteam_client.merge_workspace.call_args_list
        assert [c.args[1] for c in calls] == ["a", "b"]  # leader-first order
        for c in calls:
            assert c.kwargs["repo"] == "/wt"
            assert c.kwargs["target"] == "run/abc"

    def test_consolidate_reports_conflicts_without_raising(self, coord, mock_clawteam_client):
        def merge(team, agent, *, repo, target):
            return MagicMock(returncode=1 if agent == "b" else 0)
        mock_clawteam_client.merge_workspace.side_effect = merge
        conflicts = coord.consolidate(self._isolated_handle())
        assert conflicts == ["b"]

    def test_consolidate_noop_for_in_place(self, coord, mock_clawteam_client):
        from datetime import datetime, timezone
        handle = RunHandle(
            run_id="run-1", team_name="team-1",
            started_at=datetime.now(timezone.utc), topology=TopologyMode.SEQUENTIAL,
        )  # run_branch is None
        assert coord.consolidate(handle) == []
        assert not mock_clawteam_client.merge_workspace.called
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/topology/test_coordinator.py::TestCoordinatorConsolidate -v`
Expected: FAIL — `Coordinator` has no `consolidate`.

- [ ] **Step 3: Implement**

In `pi_harness/topology/coordinator.py`, add after `teardown` (after line 347):

```python
    def consolidate(self, handle: RunHandle) -> list[str]:
        """Merge each agent's branch into the run branch (default target).

        Runs in launch order (leader first). A conflicting merge is recorded and
        skipped — never force-resolved. Returns the list of agent names whose
        merge conflicted. No-op (returns []) for in-place runs (no run_branch).
        """
        if handle.run_branch is None:
            return []
        conflicts: list[str] = []
        for agent_name in handle.agent_names:
            result = self._clawteam_client.merge_workspace(
                handle.team_name, agent_name,
                repo=handle.workspace_repo, target=handle.run_branch,
            )
            if getattr(result, "returncode", 0) != 0:
                conflicts.append(agent_name)
        return conflicts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/topology/test_coordinator.py::TestCoordinatorConsolidate -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add pi_harness/topology/coordinator.py tests/topology/test_coordinator.py
git commit -m "feat(topology): consolidate agent branches into the run branch (conflicts surfaced)"
```

---

## Task 7: on_completion / teardown — always tear down, snapshot on failure, consolidate on success

New policy: success → improve, consolidate, teardown; failure/timeout → snapshot then teardown — **unless** `keep_alive`. Teardown also removes the run worktree (keeping the `run/<id>` branch). This **inverts** the existing `test_on_completion_no_teardown_on_failure`, which must be updated.

**Files:**
- Modify: `pi_harness/topology/coordinator.py` — `on_completion` (328-337) and `teardown` (339-347)
- Test: `tests/topology/test_coordinator.py` (update one test, add three)

- [ ] **Step 1: Update the now-inverted test + write the new failing tests**

In `tests/topology/test_coordinator.py`, **replace** `test_on_completion_no_teardown_on_failure` (lines ~281-291) with the new failure-path behavior, and add the rest:

```python
    def test_on_completion_snapshots_and_tears_down_on_failure(self, coord, basic_spec, mock_clawteam_client):
        with patch("pi_harness.topology.coordinator.git_workspace"):
            handle = coord.launch(basic_spec)
        coord._last_result[handle.run_id] = MagicMock(success=False)
        coord.on_completion(handle)
        # snapshot BEFORE teardown, then teardown happens.
        mock_clawteam_client.snapshot_team.assert_called_once()
        mock_clawteam_client.kill_tmux_session.assert_called_once_with(handle.team_name)
        names = [c[0] for c in mock_clawteam_client.mock_calls]
        assert names.index("snapshot_team") < names.index("kill_tmux_session")

    def test_on_completion_keep_alive_skips_teardown_on_failure(self, coord, basic_spec, mock_clawteam_client):
        with patch("pi_harness.topology.coordinator.git_workspace"):
            handle = coord.launch(basic_spec, keep_alive=True)
        coord._last_result[handle.run_id] = MagicMock(success=False)
        coord.on_completion(handle)
        mock_clawteam_client.snapshot_team.assert_called_once()  # still snapshot for debug
        mock_clawteam_client.kill_tmux_session.assert_not_called()  # left live
        mock_clawteam_client.cleanup_team.assert_not_called()

    def test_on_completion_consolidates_then_tears_down_on_success(self, coord, basic_spec, mock_clawteam_client):
        mock_clawteam_client.merge_workspace.return_value = MagicMock(returncode=0)
        with patch("pi_harness.topology.coordinator.git_workspace"):
            handle = coord.launch(basic_spec)
        coord._last_result[handle.run_id] = MagicMock(success=True)
        coord.on_completion(handle)
        assert mock_clawteam_client.merge_workspace.called          # consolidated
        mock_clawteam_client.kill_tmux_session.assert_called_once()  # then torn down
        names = [c[0] for c in mock_clawteam_client.mock_calls]
        assert names.index("merge_workspace") < names.index("kill_tmux_session")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/topology/test_coordinator.py -k "on_completion" -v`
Expected: FAIL — failure path currently does NOT snapshot or tear down; success path does not consolidate.

- [ ] **Step 3: Implement**

In `pi_harness/topology/coordinator.py`, replace `on_completion` and `teardown` (lines 328-347) with:

```python
    def on_completion(self, handle: RunHandle) -> None:
        """Always finalize the run safely.

        Success: run the improve loop, consolidate agent branches into the run
        branch, then tear the team down.
        Failure/timeout: snapshot the team for debugging, then tear it down —
        unless ``handle.keep_alive`` is set, in which case it is left live.
        """
        result = self._last_result.get(handle.run_id)
        success = bool(result is not None and result.success)
        if success:
            self._improve_runner.run_for_completed_run(
                handle.run_id, self._config, session_id=handle.session_id
            )
            self.consolidate(handle)
            self.teardown(handle)
            return
        # Failure / timeout: preserve full state for debugging, then stop the
        # credit burn (snapshot first so it survives teardown).
        self._clawteam_client.snapshot_team(
            handle.team_name, tag=f"failed-{handle.run_id[-8:]}"
        )
        if not handle.keep_alive:
            self.teardown(handle)

    def teardown(self, handle: RunHandle) -> None:
        """Stop the run's agents and delete its team data, then remove the run
        worktree (the run/<id> branch is kept — that's where the work lives).

        Kills the tmux session first (so agents stop immediately and stop burning
        credit), then removes the team record, then the worktree. Safe to call
        repeatedly.
        """
        self._clawteam_client.kill_tmux_session(handle.team_name)
        self._clawteam_client.cleanup_team(handle.team_name)
        if handle.workspace_repo:
            try:
                git_workspace.remove_run_worktree(
                    git_workspace.repo_root(), Path(handle.workspace_repo)
                )
            except Exception:  # noqa: BLE001 — teardown must never raise
                pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/topology/test_coordinator.py -v`
Expected: PASS (updated + new on_completion tests, plus the existing `test_teardown_kills_session_then_cleans_up` and `test_on_completion_tears_down_on_success`, which still hold).

- [ ] **Step 5: Commit**

```bash
git add pi_harness/topology/coordinator.py tests/topology/test_coordinator.py
git commit -m "feat(topology): always teardown; snapshot+keep-alive on failure; consolidate on success"
```

---

## Task 8: CLI `launch` — `--in-place` / `--keep-alive` flags + report the run branch

Expose the new safety knobs and tell the user where the work landed.

**Files:**
- Modify: `pi_harness/cli.py:101-155` (the `launch` command)
- Test: `tests/test_cli_launch_flags.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_launch_flags.py`:

```python
"""CLI launch threads --in-place / --keep-alive into the Coordinator."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from pi_harness.cli import app

runner = CliRunner()


def _patches(coord):
    """Patch the launch pipeline so no real lint/decompose/launch happens."""
    spec = MagicMock(id="spec-1")
    return [
        patch("pi_harness.cli._load_spec_or_die", return_value=spec),
        patch("pi_harness.cli._lint_or_die", return_value=None),
        patch("pi_harness.cli.load_config", return_value=MagicMock()),
        patch("pi_harness.cli._decompose_or_die", return_value=[]),
        patch("pi_harness.cli.spec_to_runspec", return_value=MagicMock()),
        patch("pi_harness.cli._make_coordinator", return_value=coord),
    ]


def test_launch_passes_in_place_and_keep_alive(tmp_path):
    coord = MagicMock()
    coord.launch.return_value = MagicMock(run_id="run-1", run_branch="run/abc")
    import contextlib
    spec_file = tmp_path / "s.md"
    spec_file.write_text("x")
    with contextlib.ExitStack() as stack:
        for p in _patches(coord):
            stack.enter_context(p)
        result = runner.invoke(app, ["launch", str(spec_file), "--detach",
                                     "--in-place", "--keep-alive"])
    assert result.exit_code == 0, result.output
    kwargs = coord.launch.call_args.kwargs
    assert kwargs["in_place"] is True
    assert kwargs["keep_alive"] is True


def test_launch_defaults_isolated(tmp_path):
    coord = MagicMock()
    coord.launch.return_value = MagicMock(run_id="run-1", run_branch="run/abc")
    import contextlib
    spec_file = tmp_path / "s.md"
    spec_file.write_text("x")
    with contextlib.ExitStack() as stack:
        for p in _patches(coord):
            stack.enter_context(p)
        result = runner.invoke(app, ["launch", str(spec_file), "--detach"])
    assert result.exit_code == 0, result.output
    kwargs = coord.launch.call_args.kwargs
    assert kwargs["in_place"] is False
    assert kwargs["keep_alive"] is False
    assert "run/abc" in result.output  # reports where the work landed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_launch_flags.py -v`
Expected: FAIL — `launch` has no `--in-place`/`--keep-alive`; `coord.launch` called without those kwargs.

- [ ] **Step 3: Implement**

In `pi_harness/cli.py`, add two options to the `launch` command signature (after `sync_profile`, before `api_url`, line 117):

```python
    in_place: bool = typer.Option(
        False, "--in-place",
        help="Run in the current checkout instead of an isolated run/<id> branch "
        "(NOT recommended: agents commit to your working branch).",
    ),
    keep_alive: bool = typer.Option(
        False, "--keep-alive",
        help="On failure, leave the team running for inspection instead of "
        "snapshotting and tearing it down.",
    ),
```

Replace the launch + post-launch block (lines 142-155) with:

```python
    coord = _make_coordinator(cfg)
    handle = coord.launch(run_spec, in_place=in_place, keep_alive=keep_alive)
    typer.echo(handle.run_id)
    if handle.run_branch:
        typer.echo(f"  isolated on branch: {handle.run_branch}")

    if detach:
        return

    result = coord.wait_for_completion(handle, timeout=timeout)
    coord.on_completion(handle)
    for task_id, status in sorted(result.terminal_statuses.items()):
        typer.echo(f"  task={task_id} status={status}")
    if result.success and handle.run_branch:
        typer.echo(f"work is on branch {handle.run_branch} — diff and merge when ready")
    if not result.success:
        typer.echo("run did not complete successfully", err=True)
        raise typer.Exit(code=1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_launch_flags.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add pi_harness/cli.py tests/test_cli_launch_flags.py
git commit -m "feat(cli): launch --in-place/--keep-alive + report run branch"
```

---

## Final verification

- [ ] **Run the full non-smoke suite:**

Run: `uv run pytest -m "not smoke" -q`
Expected: all pass. (Pay attention to `tests/topology/test_coordinator.py` — Task 7 changed failure-path behavior; confirm no *other* test still assumed "no teardown on failure".)

- [ ] **Grep for stragglers asserting the old failure-path behavior:**

Run: `grep -rn "no_teardown\|left up\|not torn down" tests/`
Expected: no test still asserts failed runs are left live (except the intentional `--keep-alive` case).

---

## Self-Review (completed during authoring)

- **Spec coverage:** §5.2 isolation → Tasks 5+6; §5.3 teardown/snapshot + finalizer bug → Tasks 7+1; client/handle/git plumbing → Tasks 2–4; CLI surface → Task 8. (§5.1 rename and §5.4–5.8 are later phases, out of this plan.)
- **Placeholder scan:** none — every code/test step has concrete content.
- **Type consistency:** `launch_team(..., workspace=, repo=)`, `merge_workspace(team, agent, *, repo, target)`, `snapshot_team(team, *, tag)`, `RunHandle.{run_branch, workspace_repo, agent_names, keep_alive}`, `Coordinator.launch(spec, *, in_place, keep_alive)`, and `consolidate(handle) -> list[str]` are used identically across tasks.
- **Known residual (verify at execution, not blocking):** the live end-to-end (real `clawteam launch --workspace --repo` → per-agent worktrees off `run/<id>` → `workspace merge --target run/<id>`) is exercised only under the `smoke` marker. Validate it once manually on a throwaway branch before merging Phase 2 to mainline — unit tests cover the wiring/argv but not ClawTeam's live behavior.
