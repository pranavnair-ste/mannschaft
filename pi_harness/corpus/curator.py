"""Curator — the only entry point allowed to mutate the corpus.

The improve-agent (Plan 4) produces ``CandidateUpdate`` / ``CandidatePrune``
records from each run's trajectories. The Curator:

1. Opens a writer gate.
2. Applies updates in order (``new`` / ``append`` / ``date``).
3. Runs every prune trigger over the resulting corpus + merges in the
   caller-supplied prune candidates.
4. Executes the resolved actions (ARCHIVE / DEMOTE / MERGE / DELETE).
5. Closes the gate.
6. Commits the whole pass as a single git commit on the corpus repo —
   the audit trail.

Everything is pure-code; no LLM calls.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Literal, Optional

import git

from pi_harness.corpus import writer
from pi_harness.corpus.format import (
    Classification,
    CorpusEntry,
    count_tokens,
    parse_entry,
    serialize_entry,
)
from pi_harness.corpus.prune import (
    PruneAction,
    PruneActionType,
    prune_by_budget,
    prune_by_contradiction,
    prune_by_counter,
    prune_by_dedup,
    prune_by_staleness,
)

if TYPE_CHECKING:  # pragma: no cover
    from pi_harness.config import Config

__all__ = [
    "CandidatePrune",
    "CandidateUpdate",
    "CuratorReport",
    "Curator",
]

_LOGGER = logging.getLogger(__name__)


# 90-day archive grace before hard delete.
DEFAULT_ARCHIVE_GRACE_DAYS = 90


# ---------------------------------------------------------------------------
# Candidate / report types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CandidateUpdate:
    """A single update emitted by the improve-agent.

    Attributes:
        entry: For ``new`` and ``date``: the full entry (body included).
            For ``append``: the entry whose body field carries the text to
            append; ``id`` must match an existing on-disk entry.
        kind: ``new`` = create entry; ``append`` = append body to existing;
            ``date`` = stamp ``last_updated_at`` (no body change).
        reason: Audit string included in the commit body.
    """

    entry: CorpusEntry
    kind: Literal["new", "append", "date"]
    reason: str


@dataclass(frozen=True)
class CandidatePrune:
    """A caller-supplied prune candidate (improve-agent's recommendation)."""

    entry_id: str
    actions: List[PruneAction]
    reason: str


@dataclass
class CuratorReport:
    """Summary of a single ``apply_candidates`` invocation."""

    run_id: str
    updates_applied: int
    archives: int
    demotes: int
    merges: int
    deletes: int
    actions: List[PruneAction] = field(default_factory=list)
    git_sha: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classification_dir(root: Path, classification: Classification) -> Path:
    return root / classification.value


def _archive_dir(root: Path, classification: Classification) -> Path:
    return root / "archived" / classification.value


def _find_entry_path(root: Path, entry_id: str) -> Optional[Path]:
    """Walk the corpus root (active dirs only) for an entry with this id."""
    for c in Classification:
        path = _classification_dir(root, c) / f"{entry_id}.md"
        if path.exists():
            return path
    return None


def _find_archived_entry_path(root: Path, entry_id: str) -> Optional[Path]:
    """Walk the archived/ subtree for an entry with this id."""
    archive_root = root / "archived"
    if not archive_root.is_dir():
        return None
    for c in Classification:
        path = archive_root / c.value / f"{entry_id}.md"
        if path.exists():
            return path
    return None


def _archive_age_days(path: Path, now: datetime) -> int:
    """Return how many days ago the archived entry was last touched.

    Source of truth is the entry's own ``last_updated_at`` (stamped by
    :func:`pi_harness.corpus.writer.archive_entry` on archive). This is more
    reliable than ``st_mtime`` because frozen-time tests fix wall clock but
    can backdate the entry payload.
    """
    try:
        entry = parse_entry(path)
    except (ValueError, KeyError, FileNotFoundError):
        # Fall back to filesystem mtime.
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return (now - mtime).days
    return (now - entry.last_updated_at).days


# ---------------------------------------------------------------------------
# Curator
# ---------------------------------------------------------------------------


class Curator:
    """The sole gateway authorized to modify the corpus."""

    def __init__(self, config: "Config", archive_grace_days: int = DEFAULT_ARCHIVE_GRACE_DAYS) -> None:
        self.config = config
        self.root: Path = Path(config.corpus_root)
        self.archive_grace_days = archive_grace_days

    # ------------------------------------------------------------------
    # Git bootstrap
    # ------------------------------------------------------------------

    def _ensure_git(self) -> git.Repo:
        """Init or open the corpus git repo. Creates one initial commit."""
        self.root.mkdir(parents=True, exist_ok=True)
        git_dir = self.root / ".git"
        if git_dir.exists():
            return git.Repo(self.root)

        repo = git.Repo.init(self.root)
        # Use a deterministic local committer identity so tests pass without
        # the user's git config.
        with repo.config_writer() as cw:
            cw.set_value("user", "name", "pi-harness curator")
            cw.set_value("user", "email", "curator@pi-harness.local")

        gitignore = self.root / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(
                "*.tmp\n.*.lock\n",
                encoding="utf-8",
            )
        repo.index.add([".gitignore"])
        repo.index.commit("chore: initialize corpus repo")
        return repo

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def apply_candidates(
        self,
        run_id: str,
        updates: List[CandidateUpdate],
        prunes: List[CandidatePrune],
        now: Optional[datetime] = None,
        budget_soft_cap: Optional[int] = None,
        recent_run_ids: Optional[List[str]] = None,
    ) -> CuratorReport:
        """Apply ``updates`` and ``prunes``, run all prune rules, commit one SHA."""
        now = now or datetime.now(timezone.utc)
        recent_run_ids = recent_run_ids or [run_id]

        repo = self._ensure_git()

        report = CuratorReport(
            run_id=run_id,
            updates_applied=0,
            archives=0,
            demotes=0,
            merges=0,
            deletes=0,
            actions=[],
        )
        applied_updates: List[CandidateUpdate] = []

        with writer.curator_context():
            # 1. Apply updates
            for u in updates:
                self._apply_update(u, now)
                report.updates_applied += 1
                applied_updates.append(u)

            # 2. Gather actions: caller-supplied + internally-derived
            current_entries = self._scan_active_entries()

            internal_actions: List[PruneAction] = []
            # Per-entry rules
            for entry in current_entries:
                internal_actions.extend(prune_by_counter(entry))
                internal_actions.extend(prune_by_contradiction(entry))
                internal_actions.extend(
                    prune_by_staleness(entry, now, recent_run_ids=recent_run_ids)
                )
            # Corpus-wide rules
            soft_cap = budget_soft_cap if budget_soft_cap is not None else 50_000
            internal_actions.extend(
                prune_by_budget(current_entries, soft_cap=soft_cap, now=now)
            )
            internal_actions.extend(prune_by_dedup(current_entries, now=now))

            # 3. Merge caller-supplied prune candidates (caller may force
            #    specific actions, e.g. DELETE for entries the improve-agent
            #    deems irrelevant).
            caller_actions: List[PruneAction] = []
            for cp in prunes:
                caller_actions.extend(cp.actions)

            # Filter foundational entries out of any ARCHIVE actions
            # (acceptance criterion 6 — foundational never auto-archived).
            all_actions = self._filter_foundational_archives(
                internal_actions + caller_actions
            )

            # Dedup actions by (entry_id, action_type) keeping first occurrence
            seen: set[tuple[str, PruneActionType]] = set()
            deduped: List[PruneAction] = []
            for a in all_actions:
                key = (a.entry_id, a.action)
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(a)

            # 4. Resolve actions
            for action in deduped:
                executed = self._execute_action(action, now)
                if executed is None:
                    continue
                report.actions.append(executed)
                if executed.action == PruneActionType.ARCHIVE:
                    report.archives += 1
                elif executed.action == PruneActionType.DEMOTE:
                    report.demotes += 1
                elif executed.action == PruneActionType.MERGE:
                    report.merges += 1
                elif executed.action == PruneActionType.DELETE:
                    report.deletes += 1

        # 5. Commit
        commit_sha = self._commit_pass(repo, run_id, report, applied_updates)
        report.git_sha = commit_sha
        return report

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _scan_active_entries(self) -> List[CorpusEntry]:
        out: List[CorpusEntry] = []
        for c in Classification:
            d = _classification_dir(self.root, c)
            if not d.is_dir():
                continue
            for p in d.glob("*.md"):
                try:
                    out.append(parse_entry(p))
                except (ValueError, KeyError) as exc:
                    _LOGGER.warning("Skipping malformed entry %s: %s", p, exc)
        return out

    def _apply_update(self, update: CandidateUpdate, now: datetime) -> None:
        entry = update.entry
        if update.kind == "new":
            writer.write_entry(entry, self.root, now)
        elif update.kind == "append":
            path = _find_entry_path(self.root, entry.id)
            if path is None:
                # Fall back to creating it.
                writer.write_entry(entry, self.root, now)
                return
            existing = parse_entry(path)
            new_body = existing.body + "\n\n" + entry.body
            new_entry = replace(
                existing,
                body=new_body,
                size_tokens=count_tokens(new_body),
                last_updated_at=now,
            )
            writer.write_entry(new_entry, self.root, now)
        elif update.kind == "date":
            path = _find_entry_path(self.root, entry.id)
            if path is None:
                _LOGGER.warning("date update for unknown entry %s; skipping", entry.id)
                return
            existing = parse_entry(path)
            writer.write_entry(existing, self.root, now)
        else:  # pragma: no cover
            raise ValueError(f"Unknown CandidateUpdate.kind={update.kind!r}")

    def restore_archived(self, entry_id: str, now: Optional[datetime] = None) -> CorpusEntry:
        """Un-archive an entry: move it from ``archived/`` back to its active
        classification dir and commit. Mirrors the archive path in reverse.

        Raises:
            FileNotFoundError: If no archived entry with ``entry_id`` exists.
        """
        now = now or datetime.now(timezone.utc)
        archive_path = _find_archived_entry_path(self.root, entry_id)
        if archive_path is None:
            raise FileNotFoundError(f"no archived corpus entry {entry_id!r}")

        entry = parse_entry(archive_path)
        repo = self._ensure_git()
        with writer.curator_context():
            writer.write_entry(entry, self.root, now)
            archive_path.unlink()
        repo.git.add(A=True)
        repo.index.commit(f"restore: un-archive {entry_id}")
        return entry

    def _filter_foundational_archives(
        self, actions: List[PruneAction]
    ) -> List[PruneAction]:
        """Drop any ARCHIVE action targeting an active foundational entry."""
        filtered: List[PruneAction] = []
        for a in actions:
            if a.action != PruneActionType.ARCHIVE:
                filtered.append(a)
                continue
            path = _find_entry_path(self.root, a.entry_id)
            if path is None:
                # Already gone / archived — keep, will be no-op in execute
                filtered.append(a)
                continue
            try:
                e = parse_entry(path)
            except (ValueError, KeyError):
                filtered.append(a)
                continue
            if e.classification == Classification.FOUNDATIONAL:
                _LOGGER.info(
                    "Suppressing ARCHIVE on foundational entry %s (reason=%r)",
                    a.entry_id,
                    a.reason,
                )
                continue
            filtered.append(a)
        return filtered

    def _execute_action(
        self, action: PruneAction, now: datetime
    ) -> Optional[PruneAction]:
        """Apply a single action to disk. Returns ``action`` if it ran, else None."""
        if action.action == PruneActionType.ARCHIVE:
            path = _find_entry_path(self.root, action.entry_id)
            if path is None:
                return None
            entry = parse_entry(path)
            writer.archive_entry(entry, self.root, now)
            return action

        if action.action == PruneActionType.DEMOTE:
            target = action.target_classification
            if target is None:
                _LOGGER.warning(
                    "DEMOTE action for %s missing target_classification", action.entry_id
                )
                return None
            path = _find_entry_path(self.root, action.entry_id)
            if path is None:
                return None
            entry = parse_entry(path)
            if entry.classification == target:
                return None
            new_entry = replace(entry, classification=target)
            writer.write_entry(new_entry, self.root, now)
            # Remove the old file at the previous classification
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            return action

        if action.action == PruneActionType.MERGE:
            survivor_id = action.merge_with
            if survivor_id is None:
                return None
            loser_path = _find_entry_path(self.root, action.entry_id)
            survivor_path = _find_entry_path(self.root, survivor_id)
            if loser_path is None or survivor_path is None:
                return None
            loser = parse_entry(loser_path)
            survivor = parse_entry(survivor_path)
            merged_counters = action.merged_counters or {
                "helpful_count": survivor.helpful_count + loser.helpful_count,
                "harmful_count": survivor.harmful_count + loser.harmful_count,
                "contradiction_count": (
                    survivor.contradiction_count + loser.contradiction_count
                ),
            }
            merged = replace(
                survivor,
                helpful_count=merged_counters["helpful_count"],
                harmful_count=merged_counters["harmful_count"],
                contradiction_count=merged_counters["contradiction_count"],
            )
            writer.write_entry(merged, self.root, now)
            writer.archive_entry(loser, self.root, now)
            return action

        if action.action == PruneActionType.DELETE:
            # Only honor DELETE for archived observational entries past grace.
            archive_path = _find_archived_entry_path(self.root, action.entry_id)
            if archive_path is None:
                # Not currently archived — refuse to hard-delete.
                _LOGGER.info(
                    "Skipping DELETE for non-archived entry %s", action.entry_id
                )
                return None
            archive_age = _archive_age_days(archive_path, now)
            if archive_age < self.archive_grace_days:
                _LOGGER.info(
                    "Skipping DELETE for entry %s (archived only %dd, "
                    "grace=%dd)",
                    action.entry_id,
                    archive_age,
                    self.archive_grace_days,
                )
                return None
            try:
                archive_path.unlink()
            except FileNotFoundError:
                return None
            return action

        return None

    # ------------------------------------------------------------------
    # Commit helper
    # ------------------------------------------------------------------

    def _commit_pass(
        self,
        repo: git.Repo,
        run_id: str,
        report: CuratorReport,
        applied_updates: List[CandidateUpdate],
    ) -> Optional[str]:
        """Stage everything and commit as one. Returns SHA or None if no diff."""
        repo.git.add(A=True)
        # If nothing changed, skip the commit (avoid empty commits).
        try:
            diff = repo.index.diff("HEAD") if repo.head.is_valid() else None
        except Exception:
            diff = None
        if not repo.is_dirty(untracked_files=True) and not diff:
            return repo.head.commit.hexsha if repo.head.is_valid() else None

        title = (
            f"curator: {run_id} applied {report.updates_applied} updates, "
            f"{report.archives} archives, {report.deletes} deletes"
        )
        body_lines: List[str] = []
        if applied_updates:
            body_lines.append("")
            body_lines.append("Updates:")
            for u in applied_updates:
                body_lines.append(f"- {u.kind} {u.entry.id}: {u.reason}")
        if report.actions:
            body_lines.append("")
            body_lines.append("Actions:")
            for a in report.actions:
                body_lines.append(f"- {a.action.value} {a.entry_id}: {a.reason}")
        message = title + ("\n" + "\n".join(body_lines) if body_lines else "")

        # ``commit`` may raise if there is nothing to commit; protect ourselves.
        try:
            commit = repo.index.commit(message)
            return commit.hexsha
        except Exception as exc:  # pragma: no cover - defensive
            _LOGGER.warning("Empty commit suppressed: %s", exc)
            return repo.head.commit.hexsha if repo.head.is_valid() else None
