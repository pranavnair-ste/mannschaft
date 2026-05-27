"""Tests for spec format: parse/serialize round-trip and storage location."""
from __future__ import annotations

from pathlib import Path

import pytest

from pi_harness.spec.format import (
    Spec,
    parse_spec,
    parse_spec_file,
    serialize_spec,
    spec_storage_dir,
    spec_path,
)


@pytest.fixture
def tmp_specs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path))
    d = tmp_path / "specs"
    d.mkdir()
    return d


def _spec(**overrides) -> Spec:
    defaults = dict(
        id="spec-001",
        title="Add cancel button",
        goal="Users can cancel an in-flight upload.",
        acceptance_criteria=[
            "Clicking Cancel during upload aborts the request within 200ms",
            "Cancelled upload leaves no partial file on the server",
        ],
        constraints=["Must not break resumable uploads"],
        non_goals=["Resuming after cancel is out of scope"],
        created_at="2026-05-25T10:00:00Z",
        updated_at="2026-05-25T10:00:00Z",
        linter_score=None,
        status="draft",
    )
    defaults.update(overrides)
    return Spec(**defaults)


def test_storage_dir_uses_env(tmp_specs_dir: Path) -> None:
    assert spec_storage_dir() == tmp_specs_dir


def test_round_trip_preserves_all_fields(tmp_specs_dir: Path) -> None:
    spec = _spec()
    path = spec_path(spec.id)
    serialize_spec(spec, path)
    parsed = parse_spec(path)
    assert parsed == spec


def test_round_trip_preserves_run_shape(tmp_specs_dir: Path) -> None:
    spec = _spec(
        id="spec-run",
        topology="parallel",
        sync_mode="sync_all",
        executor="codex",
        sync_profile="pi-openai-fast",
        session_id="sess-42",
        corpus_classifications=["foundational", "tactical"],
    )
    serialize_spec(spec, spec_path(spec.id))
    parsed = parse_spec(spec_path(spec.id))
    assert parsed == spec
    assert parsed.topology == "parallel"
    assert parsed.session_id == "sess-42"
    assert parsed.corpus_classifications == ["foundational", "tactical"]


def test_run_shape_defaults_when_absent(tmp_specs_dir: Path) -> None:
    """A hand-edited file without the run-shape keys parses with defaults."""
    raw = (
        "---\n"
        "id: spec-min\n"
        "title: Minimal\n"
        "goal: do a thing that is measurable in 200ms\n"
        "acceptance_criteria:\n"
        "  - one two three four\n"
        "constraints: []\n"
        "non_goals:\n"
        "  - not this\n"
        "created_at: '2026-05-25T10:00:00Z'\n"
        "updated_at: '2026-05-25T10:00:00Z'\n"
        "linter_score: null\n"
        "status: draft\n"
        "---\n\n# Minimal\n"
    )
    p = tmp_specs_dir / "spec-min.md"
    p.write_text(raw, encoding="utf-8")
    spec = parse_spec(p)
    assert spec.topology == "sequential"
    assert spec.sync_mode == "per_agent"
    assert spec.executor == "pi"
    assert spec.sync_profile is None
    assert spec.session_id is None
    assert spec.corpus_classifications == []


def test_parse_spec_file_is_alias() -> None:
    assert parse_spec_file is parse_spec


def test_parse_rejects_missing_frontmatter(tmp_specs_dir: Path) -> None:
    bad = tmp_specs_dir / "bad.md"
    bad.write_text("# no frontmatter here\n", encoding="utf-8")
    with pytest.raises(ValueError, match="frontmatter"):
        parse_spec(bad)


def test_serialize_creates_parent_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path))
    spec = _spec(id="spec-002")
    # `specs/` directory does not exist yet — serialize must create it.
    serialize_spec(spec, spec_path(spec.id))
    assert (tmp_path / "specs" / "spec-002.md").exists()


def test_public_exports() -> None:
    from pi_harness.spec import (
        DecomposedTask,
        Decomposer,
        LintResult,
        LintViolation,
        Linter,
        Spec,
        build_coordinator,
        spec_to_runspec,
    )

    assert all(
        x is not None
        for x in (
            DecomposedTask, Decomposer, LintResult, LintViolation, Linter, Spec,
            build_coordinator, spec_to_runspec,
        )
    )
