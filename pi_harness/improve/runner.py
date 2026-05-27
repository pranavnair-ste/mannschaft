"""End-to-end runner: trajectory -> agent -> curator -> commit.

The orchestrator (Plan 5) calls :func:`run_for_completed_run` exactly once
at the end of every run. There is no public API surface for in-run
mutation — the Execution-Learning Separation principle from
``HARNESS_ARCHITECTURE.md`` is enforced architecturally: this is the only
module that writes to the corpus, and it can only be invoked post-hoc.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from pi_harness.corpus.curator import (
    CandidatePrune as CuratorPrune,
)
from pi_harness.corpus.curator import (
    CandidateUpdate as CuratorUpdate,
)
from pi_harness.corpus.curator import Curator, CuratorReport
from pi_harness.corpus.format import CorpusEntry
from pi_harness.corpus.prune import PruneAction, PruneActionType
from pi_harness.corpus.reader import CorpusReader
from pi_harness.improve.agent import ImproveAgent, ImproveError
from pi_harness.improve.candidates import (
    ProposedPrune,
    ProposedUpdate,
    PruneTrigger,
)
from pi_harness.trajectory.store import query_events, query_runs

__all__ = ["ImproveReport", "run_for_completed_run"]

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImproveReport:
    """Summary of one improve-agent pass.

    Attributes:
        run_id: The run that triggered the improve pass.
        candidates_emitted: Total updates returned by the agent.
        prunes_emitted: Total prune candidates returned by the agent.
        curator_actions: Total actions executed by the curator
            (``updates_applied + archives + demotes + merges + deletes``).
        curator_report: The full :class:`CuratorReport` for downstream
            display (dashboard, audit log).
    """

    run_id: str
    candidates_emitted: int
    prunes_emitted: int
    curator_actions: int
    curator_report: CuratorReport


# ---------------------------------------------------------------------------
# Helpers — git diff capture and candidate conversion
# ---------------------------------------------------------------------------


def _git_diff_since(repo_path: Path, since_ts: datetime) -> str:
    """Return the patch text of every commit in ``repo_path`` after ``since_ts``.

    Uses ``git log --since=<iso> -p --no-color``. If the repo has no commits
    after ``since_ts`` or git fails, returns an empty string (the agent is
    expected to handle the no-diff case gracefully).
    """
    if not (repo_path / ".git").exists():
        return ""
    iso = since_ts.isoformat()
    try:
        completed = subprocess.run(
            ["git", "log", f"--since={iso}", "-p", "--no-color"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        _LOGGER.warning("git diff failed for %s: %s", repo_path, exc)
        return ""
    return completed.stdout or ""


def _trigger_to_action(trigger: PruneTrigger) -> PruneAction:
    """Map an improve-agent trigger to a default curator :class:`PruneAction`.

    Plan 3's :class:`Curator` runs its own deterministic triggers in
    ``apply_candidates``; the agent's flags are advisory. We translate them
    to a conservative default action per trigger:

    - ``counter``, ``contradiction``, ``staleness``, ``budget`` → ``ARCHIVE``
    - ``dedup`` → ``ARCHIVE`` (no ``merge_with`` is known here; the curator's
      own ``prune_by_dedup`` finds pairs and emits proper ``MERGE`` actions)

    The curator filters foundational entries out of any ``ARCHIVE`` action
    before execution, so this default is safe.
    """
    return PruneAction(
        action=PruneActionType.ARCHIVE,
        entry_id="",  # filled in by caller
        reason=f"improve-agent trigger={trigger.value}",
    )


def _to_curator_updates(
    updates: Sequence[ProposedUpdate],
    now: datetime,
    session_id: Optional[str] = None,
) -> list[CuratorUpdate]:
    """Convert improve-agent candidates to Plan-3 curator-input updates.

    Each :class:`ProposedUpdate` becomes a ``kind='new'`` curator update
    with a freshly-minted :class:`CorpusEntry` (id derived from
    ``record_type + body``, counters zeroed, timestamps = ``now``,
    ``last_referenced_run_id = source_run_id``,
    ``session_id = session_id``).

    Args:
        updates: Agent-emitted update proposals.
        now: Timestamp to use for ``created_at`` / ``last_updated_at``.
        session_id: The session that owns this run; stamped onto any new
            corpus entries so they can be primed session-scoped later.
    """
    curator_updates: list[CuratorUpdate] = []
    for u in updates:
        entry = CorpusEntry.new(
            record_type=u.record_type,
            classification=u.classification,
            body=u.body,
            now=now,
            session_id=session_id,
        )
        entry = replace(entry, last_referenced_run_id=u.source_run_id)
        curator_updates.append(
            CuratorUpdate(
                entry=entry,
                kind="new",
                reason=u.rationale,
            )
        )
    return curator_updates


def _to_curator_prunes(prunes: Sequence[ProposedPrune]) -> list[CuratorPrune]:
    """Convert improve-agent prunes to Plan-3 curator-input prunes."""
    curator_prunes: list[CuratorPrune] = []
    for p in prunes:
        action = replace(_trigger_to_action(p.trigger), entry_id=p.entry_id)
        curator_prunes.append(
            CuratorPrune(
                entry_id=p.entry_id,
                actions=[action],
                reason=p.rationale,
            )
        )
    return curator_prunes


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_for_completed_run(
    run_id: str,
    config=None,  # type: ignore[no-untyped-def]
    *,
    agent: Optional[ImproveAgent] = None,
    curator: Optional[Curator] = None,
    project_diff_text: Optional[str] = None,
    session_id: Optional[str] = None,
) -> ImproveReport:
    """Analyze one completed run and forward candidates to the curator.

    Args:
        run_id: The run that just terminated.
        config: A :class:`pi_harness.config.Config`. If ``None``, loaded via
            :func:`pi_harness.config.load_config`.
        agent: Optional pre-built :class:`ImproveAgent` (injected by tests).
        curator: Optional pre-built :class:`Curator` (injected by tests).
        project_diff_text: Optional project-code diff. If provided, this is
            passed to :meth:`ImproveAgent.analyze` instead of the
            corpus-only diff (v2 hook per Plan 4 unresolved decision #3).
        session_id: The session that owns this run; stamped onto any new
            corpus entries so they can be primed session-scoped later.
            ``None`` (default) preserves existing caller behavior.

    Returns:
        :class:`ImproveReport`.

    Raises:
        ImproveError: If no events exist for ``run_id`` or the agent fails
            after the retry budget. Plan 5 must handle this — we never
            swallow it.
    """
    if config is None:
        # Local import: avoid a hard config dep when callers inject everything.
        from pi_harness.config import load_config

        config = load_config(env_file=None)

    events = query_events(run_id=run_id, db_path=config.trajectory_db_path)
    if not events:
        raise ImproveError(f"No events for run {run_id}")

    # Determine run start: earliest event ts. (Plan 2's query_runs gives
    # only the latest ts, not the start.)
    run_start_ts = min(ev.ts for ev in events)

    corpus_root = Path(config.corpus_root)
    reader = CorpusReader(corpus_root)
    # CorpusReader doesn't expose an "all entries" method, so we walk
    # active dirs directly through find_by_classification.
    from pi_harness.corpus.format import Classification

    corpus_entries: list[CorpusEntry] = []
    for c in Classification:
        corpus_entries.extend(reader.find_by_classification(c))

    if project_diff_text is not None:
        diff_text = project_diff_text
    else:
        diff_text = _git_diff_since(corpus_root, run_start_ts)

    if agent is None:
        agent = ImproveAgent(config)

    updates, prunes = agent.analyze(
        run_id=run_id,
        events=events,
        corpus_entries=corpus_entries,
        git_diff_text=diff_text,
    )

    if curator is None:
        curator = Curator(config)

    now = datetime.now(timezone.utc)
    curator_updates = _to_curator_updates(updates, now, session_id=session_id)
    curator_prunes = _to_curator_prunes(prunes)

    # Provide the current run as the only "recent" run id so the curator's
    # tactical-staleness check doesn't fire on every existing tactical entry
    # just because we don't know the global history at this layer.
    recent_runs = [r["run_id"] for r in query_runs(db_path=config.trajectory_db_path)]
    if not recent_runs:
        recent_runs = [run_id]

    curator_report = curator.apply_candidates(
        run_id,
        curator_updates,
        curator_prunes,
        now=now,
        recent_run_ids=recent_runs,
    )

    actions = (
        curator_report.updates_applied
        + curator_report.archives
        + curator_report.demotes
        + curator_report.merges
        + curator_report.deletes
    )
    return ImproveReport(
        run_id=run_id,
        candidates_emitted=len(updates),
        prunes_emitted=len(prunes),
        curator_actions=actions,
        curator_report=curator_report,
    )
