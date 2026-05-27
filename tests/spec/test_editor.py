"""HTTP tests for the spec editor FastAPI app."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from pi_harness.spec.decomposer import DecomposedTask
from pi_harness.spec.editor import app, get_coordinator, get_decomposer
from pi_harness.topology.base import RunSpec


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


# ---------- /launch ----------


def test_launch_requires_decomposed(client: TestClient) -> None:
    created = client.post("/specs", json=_payload()).json()
    assert client.post(f"/specs/{created['id']}/launch").status_code == 409


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
    assert [a.name for a in run_spec.agents] == ["t-lead", "t-cancel"]
    assert run_spec.tasks is not None
    by = {t.task_id: t for t in run_spec.tasks}
    assert by["t-cancel"].blocked_by == ["t-lead"]

    assert client.get(f"/specs/{created['id']}").json()["status"] == "running"
