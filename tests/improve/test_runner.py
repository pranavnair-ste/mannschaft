"""Tests for pi_harness.improve.runner."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from pi_harness.corpus.format import Classification, CorpusEntry, RecordType
from pi_harness.improve.agent import ImproveError
from pi_harness.improve.candidates import (
    ProposedPrune,
    ProposedUpdate,
    PruneTrigger,
    parse_agent_response,
)
from pi_harness.trajectory.schema import TrajectoryEvent
from pi_harness.trajectory.store import init_db, write_event


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _StubConfig:
    """Stand-in for pi_harness.config.Config for tests.

    Frozen so Curator's ``self.config = config`` doesn't barf, and exposes
    only the fields the runner reads.
    """

    openai_api_key: str
    reasoning_model: str
    fast_model: str
    clawteam_state_dir: Path
    corpus_root: Path
    trajectory_db_path: Path


def _make_config(tmp_path: Path) -> _StubConfig:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    db = tmp_path / "trajectory.db"
    init_db(db)
    return _StubConfig(
        openai_api_key="fake-key",
        reasoning_model="fake-model",
        fast_model="fake-fast-model",
        clawteam_state_dir=tmp_path / "clawteam",
        corpus_root=corpus,
        trajectory_db_path=db,
    )


def _seed_events(db_path: Path, run_id: str, start_ts: datetime, n: int = 4) -> None:
    for i in range(n):
        ev = TrajectoryEvent(
            run_id=run_id,
            agent_id=f"agent-{i % 2}",
            step_id=f"step-{i:03d}",
            ts=start_ts + timedelta(seconds=i),
            model="gpt-5",
            tool="tool-x" if i % 2 == 0 else "tool-y",
            input={},
            output={},
            duration_ms=10,
            tokens_in=5,
            tokens_out=5,
            outcome="success",
            classification="tool_call",
        )
        write_event(ev, db_path=db_path)


def _seed_corpus_entry(curator: Any, now: datetime) -> CorpusEntry:
    """Use the curator to seed one observational entry (and the initial git commit)."""
    from pi_harness.corpus.curator import CandidateUpdate as CuratorUpdate

    seed = CorpusEntry.new(
        record_type=RecordType.PATTERN,
        classification=Classification.OBSERVATIONAL,
        body="seed entry body",
        now=now,
    )
    curator.apply_candidates(
        "run-seed",
        [CuratorUpdate(entry=seed, kind="new", reason="seed")],
        [],
        now=now,
    )
    return seed


def _commit_count(repo_path: Path) -> int:
    if not (repo_path / ".git").exists():
        return 0
    res = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=False,
    )
    return int(res.stdout.strip() or 0)


def _make_fake_agent(updates: list[ProposedUpdate], prunes: list[ProposedPrune]) -> MagicMock:
    """A MagicMock ImproveAgent whose analyze() returns the canned (updates, prunes)."""
    agent = MagicMock()
    agent.analyze.return_value = (updates, prunes)
    return agent


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_run_for_completed_run_end_to_end(
    tmp_path: Path,
    sample_agent_response: str,
) -> None:
    """The full pipeline: seed → call runner → corpus git advances."""
    from pi_harness.corpus.curator import Curator
    from pi_harness.improve.runner import (
        ImproveReport,
        run_for_completed_run,
    )

    config = _make_config(tmp_path)

    # Init the curator/git repo + seed one corpus entry so the prune target
    # exists. The sample fixture's prune is for entry "observation-existing-c"
    # — we mint that exact entry below by overriding the seed id.
    now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    curator = Curator(config)
    _seed_corpus_entry(curator, now)

    # Seed trajectory events.
    _seed_events(config.trajectory_db_path, "run-test-1", now, n=4)

    # Snapshot the commit count BEFORE the improve pass.
    pre_count = _commit_count(config.corpus_root)
    assert pre_count >= 1, "Curator should have produced an initial seed commit"

    # Build candidates from the sample fixture, then mock the agent.
    updates, prunes = parse_agent_response(sample_agent_response)
    fake_agent = _make_fake_agent(updates, prunes)

    report = run_for_completed_run("run-test-1", config=config, agent=fake_agent)

    assert isinstance(report, ImproveReport)
    assert report.run_id == "run-test-1"
    assert report.candidates_emitted == 2
    assert report.prunes_emitted == 1
    # 2 updates applied by the curator (foundational/tactical writes).
    assert report.curator_report.updates_applied == 2
    # At least one curator action was executed.
    assert report.curator_actions >= 2

    # Corpus git advanced.
    post_count = _commit_count(config.corpus_root)
    assert post_count > pre_count


def test_run_for_completed_run_propagates_improve_error(
    tmp_path: Path,
) -> None:
    """The runner re-raises ImproveError; Plan 5 must see it."""
    from pi_harness.corpus.curator import Curator
    from pi_harness.improve.runner import run_for_completed_run

    config = _make_config(tmp_path)
    now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    curator = Curator(config)
    _seed_corpus_entry(curator, now)
    _seed_events(config.trajectory_db_path, "run-fail", now, n=2)

    failing_agent = MagicMock()
    failing_agent.analyze.side_effect = ImproveError("agent borked")

    with pytest.raises(ImproveError):
        run_for_completed_run("run-fail", config=config, agent=failing_agent)


def test_run_for_completed_run_raises_when_no_events(
    tmp_path: Path,
) -> None:
    """A run with no trajectory events raises ImproveError immediately."""
    from pi_harness.corpus.curator import Curator
    from pi_harness.improve.runner import run_for_completed_run

    config = _make_config(tmp_path)
    # Seed the curator git repo but no events.
    now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    Curator(config)._ensure_git()  # type: ignore[attr-defined]

    with pytest.raises(ImproveError):
        run_for_completed_run("run-empty", config=config, agent=MagicMock())


def _head_sha(repo_path: Path) -> str:
    res = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()


def test_no_writes_during_run(
    tmp_path: Path,
    sample_agent_response: str,
) -> None:
    """Execution-Learning Separation: no path mutates corpus outside the runner.

    Simulate a "live run":
      1. query_events.
      2. construct ImproveAgent.
      3. invoke summarization helpers manually.
    None of these should advance the corpus git. Only when
    run_for_completed_run is invoked should the git head move.
    """
    from pi_harness.corpus.curator import Curator
    from pi_harness.corpus.reader import CorpusReader
    from pi_harness.improve.agent import (
        ImproveAgent,
        summarize_corpus_metadata,
        summarize_git_diff,
        summarize_trajectory,
    )
    from pi_harness.improve.runner import run_for_completed_run
    from pi_harness.trajectory.store import query_events

    config = _make_config(tmp_path)
    now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

    # Seed git + one corpus entry + trajectory events.
    curator = Curator(config)
    _seed_corpus_entry(curator, now)
    _seed_events(config.trajectory_db_path, "run-sep-1", now, n=3)

    pre_count = _commit_count(config.corpus_root)
    pre_sha = _head_sha(config.corpus_root)
    assert pre_count >= 1

    # Simulated "live" path — read-only.
    events = query_events(
        run_id="run-sep-1", db_path=config.trajectory_db_path
    )
    assert len(events) == 3

    reader = CorpusReader(config.corpus_root)
    entries: list[CorpusEntry] = []
    for c in Classification:
        entries.extend(reader.find_by_classification(c))
    assert entries  # we seeded at least one

    # Construct an ImproveAgent (no LLM call).
    fake_client = MagicMock()
    agent = ImproveAgent(config, client=fake_client)
    _ = agent  # constructed, not called

    # Run the read-only summarizers.
    _ = summarize_trajectory(events)
    _ = summarize_corpus_metadata(entries)
    _ = summarize_git_diff("")

    # Corpus git MUST be unchanged.
    assert _commit_count(config.corpus_root) == pre_count
    assert _head_sha(config.corpus_root) == pre_sha

    # Now invoke the runner with a mocked agent.
    updates, prunes = parse_agent_response(sample_agent_response)
    runner_agent = _make_fake_agent(updates, prunes)
    report = run_for_completed_run(
        "run-sep-1", config=config, agent=runner_agent
    )

    # Corpus git MUST have advanced.
    post_count = _commit_count(config.corpus_root)
    post_sha = _head_sha(config.corpus_root)
    assert post_count > pre_count
    assert post_sha != pre_sha
    assert report.candidates_emitted == 2
