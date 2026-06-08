"""HTTP tests for the spec editor FastAPI app."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from pi_harness.spec.decomposer import DecomposedTask
from pi_harness.spec.editor import app, get_coordinator, get_decomposer
from pi_harness.topology.base import RunSpec


def test_patch_spec_applies_on_latest_disk_state(tmp_path, monkeypatch):
    """_patch_spec re-reads fresh under the lock, so a mutator only overwrites
    the fields it changes — a concurrent writer's status flip (e.g. the launch
    finalizer) survives instead of being clobbered by a stale snapshot (#33)."""
    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path))
    from pi_harness.spec import editor
    from pi_harness.spec.format import Spec, parse_spec, serialize_spec, spec_path

    spec = Spec(
        id="s1", title="orig", goal="g", acceptance_criteria=[], constraints=[],
        non_goals=[], created_at="t", updated_at="t", linter_score=None, status="draft",
    )
    serialize_spec(spec, spec_path("s1"))
    # Simulate a concurrent writer (the finalizer) flipping status on disk.
    serialize_spec(replace(spec, status="running"), spec_path("s1"))

    # A mutator that changes ONLY the title must NOT revert status to draft.
    result = editor._patch_spec("s1", lambda d: {**d, "title": "patched"})
    assert result.title == "patched"
    assert result.status == "running"  # the concurrent flip survived
    assert parse_spec(spec_path("s1")).status == "running"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path))
    yield TestClient(app)
    app.dependency_overrides.clear()


def _payload(**overrides) -> dict:
    base = dict(
        title="Cancel button",
        goal="Let users cancel an in-flight upload",
        acceptance_criteria=[
            "The endpoint returns 200 within 200ms",
            "The worker writes a marker file to disk",
        ],
        constraints=[],
        non_goals=["Resuming after cancel"],
    )
    base.update(overrides)
    return base


def _decomposed():
    return [
        DecomposedTask(
            id="t-lead", name="Coordinate", description="lead",
            acceptance_criterion="", blocked_by=[], assigned_role="orchestrator",
        ),
        DecomposedTask(
            id="t-cancel", name="Cancel", description="wire cancel",
            acceptance_criterion="The endpoint returns 200 within 200ms",
            blocked_by=["t-lead"], assigned_role="builder",
        ),
    ]


# ---------- CRUD ----------


def test_list_empty(client: TestClient) -> None:
    r = client.get("/specs")
    assert r.status_code == 200
    assert r.json() == {"specs": []}


def test_create_spec(client: TestClient) -> None:
    r = client.post("/specs", json=_payload())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["title"] == "Cancel button"
    assert body["status"] == "draft"
    assert body["id"].startswith("spec-")
    assert body["updated_at"] == body["created_at"]
    # run-shape defaults present
    assert body["topology"] == "sequential"
    assert body["session_id"] is None


def test_get_spec(client: TestClient) -> None:
    created = client.post("/specs", json=_payload()).json()
    r = client.get(f"/specs/{created['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == created["id"]


def test_get_spec_missing(client: TestClient) -> None:
    assert client.get("/specs/spec-does-not-exist").status_code == 404


def test_update_spec(client: TestClient) -> None:
    created = client.post("/specs", json=_payload()).json()
    r = client.put(
        f"/specs/{created['id']}",
        json={"title": "Renamed", "session_id": "sess-1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Renamed"
    assert body["session_id"] == "sess-1"
    assert body["updated_at"] >= created["updated_at"]


def test_update_spec_missing(client: TestClient) -> None:
    assert client.put("/specs/spec-nope", json={"title": "x"}).status_code == 404


def test_put_clears_decomposed_state_when_content_changes(client: TestClient) -> None:
    """A content edit invalidates the persisted decomposition: status drops
    back to 'draft', linter_score and decomposed_tasks are cleared. Without
    this, the dashboard would show a 'decomposed' spec whose tasks no longer
    reflect the goal/criteria the user just changed."""
    fake = MagicMock()
    fake.decompose.return_value = _decomposed()
    app.dependency_overrides[get_decomposer] = lambda: fake

    created = client.post("/specs", json=_payload()).json()
    client.post(f"/specs/{created['id']}/lint")
    client.post(f"/specs/{created['id']}/decompose")

    client.put(f"/specs/{created['id']}", json={"goal": "An entirely new goal"})

    fetched = client.get(f"/specs/{created['id']}").json()
    assert fetched["status"] == "draft"
    assert fetched["linter_score"] is None
    assert fetched["decomposed_tasks"] is None


def test_put_preserves_decomposed_state_when_only_run_shape_changes(client: TestClient) -> None:
    """Editing run-shape knobs (session_id, sync_profile, etc.) doesn't change
    what the decomposer would produce, so the persisted tasks must survive."""
    fake = MagicMock()
    fake.decompose.return_value = _decomposed()
    app.dependency_overrides[get_decomposer] = lambda: fake

    created = client.post("/specs", json=_payload()).json()
    client.post(f"/specs/{created['id']}/lint")
    client.post(f"/specs/{created['id']}/decompose")

    client.put(f"/specs/{created['id']}", json={"session_id": "sess-1"})

    fetched = client.get(f"/specs/{created['id']}").json()
    assert fetched["status"] == "decomposed"
    assert fetched["decomposed_tasks"] is not None
    assert fetched["session_id"] == "sess-1"


def test_list_after_create(client: TestClient) -> None:
    a = client.post("/specs", json=_payload(title="A")).json()
    b = client.post("/specs", json=_payload(title="B")).json()
    ids = {s["id"] for s in client.get("/specs").json()["specs"]}
    assert {a["id"], b["id"]} <= ids


# ---------- /lint + /decompose ----------


def test_lint_route_returns_result(client: TestClient) -> None:
    created = client.post("/specs", json=_payload()).json()
    r = client.post(f"/specs/{created['id']}/lint")
    assert r.status_code == 200
    body = r.json()
    assert "errors" in body and "warnings" in body and "score" in body


def test_lint_persists_status_when_no_errors(client: TestClient) -> None:
    created = client.post("/specs", json=_payload()).json()
    client.post(f"/specs/{created['id']}/lint")
    fetched = client.get(f"/specs/{created['id']}").json()
    assert fetched["status"] == "linted"
    assert fetched["linter_score"] is not None


def test_lint_does_not_demote_a_decomposed_spec(client: TestClient) -> None:
    """Lint is a passive check; clicking it on an already-decomposed spec
    (without editing first) must not undo the decomposition. Editing is the
    only thing that invalidates decomposed_tasks, and the PUT handler is what
    enforces that."""
    fake = MagicMock()
    fake.decompose.return_value = _decomposed()
    app.dependency_overrides[get_decomposer] = lambda: fake

    created = client.post("/specs", json=_payload()).json()
    client.post(f"/specs/{created['id']}/lint")
    client.post(f"/specs/{created['id']}/decompose")

    client.post(f"/specs/{created['id']}/lint")

    fetched = client.get(f"/specs/{created['id']}").json()
    assert fetched["status"] == "decomposed"
    assert fetched["decomposed_tasks"] is not None


def test_lint_does_not_promote_on_errors(client: TestClient) -> None:
    created = client.post("/specs", json=_payload(acceptance_criteria=[])).json()
    client.post(f"/specs/{created['id']}/lint")
    fetched = client.get(f"/specs/{created['id']}").json()
    assert fetched["status"] == "draft"


def test_decompose_requires_perfect_score(client: TestClient) -> None:
    # Clean of errors but warning-only (vague terms) -> score < 1.0.
    created = client.post("/specs", json=_payload(goal="Make it simple and fast")).json()
    client.post(f"/specs/{created['id']}/lint")
    r = client.post(f"/specs/{created['id']}/decompose")
    assert r.status_code == 409
    assert "score" in r.text.lower() or "1.0" in r.text


def test_decompose_invokes_decomposer_on_clean(client: TestClient) -> None:
    fake = MagicMock()
    fake.decompose.return_value = _decomposed()
    app.dependency_overrides[get_decomposer] = lambda: fake

    created = client.post("/specs", json=_payload()).json()
    client.post(f"/specs/{created['id']}/lint")
    r = client.post(f"/specs/{created['id']}/decompose")
    assert r.status_code == 200, r.text
    assert [t["id"] for t in r.json()["tasks"]] == ["t-lead", "t-cancel"]
    assert client.get(f"/specs/{created['id']}").json()["status"] == "decomposed"


def test_decompose_404_on_unknown_spec(client: TestClient) -> None:
    assert client.post("/specs/nope/decompose").status_code == 404


def test_decompose_persists_tasks_on_spec(client: TestClient) -> None:
    """The decomposer's output is expensive (LLM call); persist it on the spec
    so subsequent /launch reads from the spec instead of paying again."""
    fake = MagicMock()
    fake.decompose.return_value = _decomposed()
    app.dependency_overrides[get_decomposer] = lambda: fake

    created = client.post("/specs", json=_payload()).json()
    client.post(f"/specs/{created['id']}/lint")
    client.post(f"/specs/{created['id']}/decompose")

    fetched = client.get(f"/specs/{created['id']}").json()
    assert fetched["decomposed_tasks"] is not None
    assert [t["id"] for t in fetched["decomposed_tasks"]] == ["t-lead", "t-cancel"]
    assert fetched["decomposed_tasks"][1]["blocked_by"] == ["t-lead"]


# ---------- /launch ----------


def test_launch_requires_decomposed(client: TestClient) -> None:
    created = client.post("/specs", json=_payload()).json()
    assert client.post(f"/specs/{created['id']}/launch").status_code == 409


def test_launch_reuses_persisted_tasks_without_redecomposing(client: TestClient) -> None:
    """Decomposition is a slow LLM call. After /decompose has run, /launch
    must read the persisted tasks off the spec rather than re-deriving them."""
    fake_dec = MagicMock()
    fake_dec.decompose.return_value = _decomposed()
    fake_coord = MagicMock()
    fake_coord.launch.return_value = MagicMock(run_id="run-reuse")
    app.dependency_overrides[get_decomposer] = lambda: fake_dec
    app.dependency_overrides[get_coordinator] = lambda: fake_coord

    created = client.post("/specs", json=_payload()).json()
    client.post(f"/specs/{created['id']}/lint")
    client.post(f"/specs/{created['id']}/decompose")
    assert fake_dec.decompose.call_count == 1
    fake_dec.decompose.reset_mock()

    r = client.post(f"/specs/{created['id']}/launch")
    assert r.status_code == 200, r.text
    assert r.json() == {"run_id": "run-reuse"}
    fake_dec.decompose.assert_not_called()


def test_launch_schedules_background_finalization(client: TestClient) -> None:
    """/launch must hand off to a background task that calls wait_for_completion
    + on_completion. Without this, the dashboard's run registry stays stuck on
    'running' forever — the launch endpoint is fire-and-forget today."""
    fake_dec = MagicMock()
    fake_dec.decompose.return_value = _decomposed()
    fake_coord = MagicMock()
    fake_coord.launch.return_value = MagicMock(run_id="run-bg")
    fake_coord.wait_for_completion.return_value = MagicMock(success=True)
    app.dependency_overrides[get_decomposer] = lambda: fake_dec
    app.dependency_overrides[get_coordinator] = lambda: fake_coord

    created = client.post("/specs", json=_payload()).json()
    client.post(f"/specs/{created['id']}/lint")
    client.post(f"/specs/{created['id']}/decompose")

    r = client.post(f"/specs/{created['id']}/launch")
    assert r.status_code == 200, r.text

    # TestClient runs background tasks before .post() returns, so by now the
    # finalizer should have driven the run to completion.
    fake_coord.wait_for_completion.assert_called_once()
    fake_coord.on_completion.assert_called_once()


def test_launch_finalizer_marks_spec_complete_on_success(client: TestClient) -> None:
    """After a successful run, the spec moves draft→linted→decomposed→running
    →complete. The 'complete' transition is what makes the editor stop
    blocking a re-launch and lets the user see closure."""
    fake_dec = MagicMock()
    fake_dec.decompose.return_value = _decomposed()
    fake_coord = MagicMock()
    fake_coord.launch.return_value = MagicMock(run_id="run-ok")
    fake_coord.wait_for_completion.return_value = MagicMock(success=True)
    app.dependency_overrides[get_decomposer] = lambda: fake_dec
    app.dependency_overrides[get_coordinator] = lambda: fake_coord

    created = client.post("/specs", json=_payload()).json()
    client.post(f"/specs/{created['id']}/lint")
    client.post(f"/specs/{created['id']}/decompose")
    client.post(f"/specs/{created['id']}/launch")

    fetched = client.get(f"/specs/{created['id']}").json()
    assert fetched["status"] == "complete"


def test_launch_finalizer_rolls_spec_back_to_decomposed_on_failure(client: TestClient) -> None:
    """If the run fails or times out, drop the spec back to 'decomposed' so
    the user can retry without re-running the LLM decomposer. The persisted
    decomposed_tasks are still valid (the spec content didn't change)."""
    fake_dec = MagicMock()
    fake_dec.decompose.return_value = _decomposed()
    fake_coord = MagicMock()
    fake_coord.launch.return_value = MagicMock(run_id="run-fail")
    fake_coord.wait_for_completion.return_value = MagicMock(success=False)
    app.dependency_overrides[get_decomposer] = lambda: fake_dec
    app.dependency_overrides[get_coordinator] = lambda: fake_coord

    created = client.post("/specs", json=_payload()).json()
    client.post(f"/specs/{created['id']}/lint")
    client.post(f"/specs/{created['id']}/decompose")
    client.post(f"/specs/{created['id']}/launch")

    fetched = client.get(f"/specs/{created['id']}").json()
    assert fetched["status"] == "decomposed"
    assert fetched["decomposed_tasks"] is not None


def test_launch_builds_real_runspec_and_returns_run_id(client: TestClient) -> None:
    fake_dec = MagicMock()
    fake_dec.decompose.return_value = _decomposed()
    fake_coord = MagicMock()
    fake_coord.launch.return_value = MagicMock(run_id="run-xyz")

    app.dependency_overrides[get_decomposer] = lambda: fake_dec
    app.dependency_overrides[get_coordinator] = lambda: fake_coord

    created = client.post("/specs", json=_payload()).json()
    client.post(f"/specs/{created['id']}/lint")
    client.post(f"/specs/{created['id']}/decompose")
    r = client.post(f"/specs/{created['id']}/launch")
    assert r.status_code == 200, r.text
    assert r.json() == {"run_id": "run-xyz"}

    # The route built a REAL RunSpec from the decomposed tasks (bridge not mocked).
    run_spec = fake_coord.launch.call_args.args[0]
    assert isinstance(run_spec, RunSpec)
    # One agent per role (orchestrator + builder), not one per task.
    assert [a.name for a in run_spec.agents] == ["orchestrator", "builder"]
    assert run_spec.tasks is not None
    by = {t.task_id: t for t in run_spec.tasks}
    assert by["t-cancel"].blocked_by == ["t-lead"]
    assert by["t-cancel"].agent_name == "builder"
    # Status transitions through 'running' → 'complete' once the background
    # finalizer drives wait_for_completion to a success result; the running
    # state itself is asserted in test_launch_schedules_background_finalization.
