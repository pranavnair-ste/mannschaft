"""Read-side of the corpus: ``prime``, ``expand``, ``find_*`` queries.

The reader is the only path agents take to consume corpus entries. Writes go
through :mod:`pi_harness.corpus.writer` under a curator gate.

Layout assumption (matches what :class:`~pi_harness.corpus.writer` produces)::

    <root>/
      foundational/<id>.md
      tactical/<id>.md
      observational/<id>.md
      archived/<classification>/<id>.md  # not surfaced by ``prime``
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, List, Optional

from dataclasses import replace

from pi_harness.corpus.counters import recency_decay
from pi_harness.corpus.format import (
    Classification,
    CorpusEntry,
    count_tokens,
    parse_entry,
)

__all__ = ["CorpusReader", "prime"]

_LOGGER = logging.getLogger(__name__)


# Classification ordering used by ``prime``: foundational first, then tactical,
# then observational.
_TIER_RANK = {
    Classification.FOUNDATIONAL: 0,
    Classification.TACTICAL: 1,
    Classification.OBSERVATIONAL: 2,
}


def _metadata_summary(body: str, *, max_chars: int = 80) -> str:
    """One-line summary slice for metadata-tier priming.

    Strategy: first non-empty line of the body, with leading markdown ``#``
    decoration stripped, truncated to ``max_chars``.
    """
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Remove leading '# ' / '## ' markdown headings to expose the title text
        while stripped.startswith("#"):
            stripped = stripped[1:].lstrip()
        if not stripped:
            continue
        return stripped[:max_chars]
    # Body is all whitespace — return empty string
    return ""


def _to_metadata(entry: CorpusEntry) -> CorpusEntry:
    """Return a copy of ``entry`` whose ``body`` is the metadata summary slice."""
    summary = _metadata_summary(entry.body)
    return replace(entry, body=summary, size_tokens=count_tokens(summary))


def _iter_active_files(root: Path) -> Iterable[Path]:
    """Yield all ``*.md`` files under non-archived classification subdirs."""
    for classification in Classification:
        subdir = root / classification.value
        if not subdir.is_dir():
            continue
        for path in subdir.glob("*.md"):
            yield path


def _load_active_entries(root: Path) -> List[CorpusEntry]:
    """Parse every active entry under ``root``."""
    out: List[CorpusEntry] = []
    for path in _iter_active_files(root):
        try:
            out.append(parse_entry(path))
        except (ValueError, KeyError) as exc:
            _LOGGER.warning("Skipping malformed entry %s: %s", path, exc)
    return out


class CorpusReader:
    """Read-only view over a corpus directory.

    Constructor injection: ``query_events`` is a callable matching Plan 2's
    ``query_events(run_id=None, since_ts=None, limit=None) -> list[Event]``
    where each event exposes ``corpus_refs: list[str]``. If unspecified we
    lazily import ``pi_harness.trajectory.store.query_events`` only when a
    trajectory-backed query is requested — keeping Plan 3 decoupled from
    Plan 2 at module import time.
    """

    def __init__(
        self,
        root: Path,
        query_events: Optional[Callable[..., List[object]]] = None,
    ) -> None:
        self.root = root
        self._query_events = query_events

    # ------------------------------------------------------------------
    # prime
    # ------------------------------------------------------------------

    def prime(
        self,
        token_budget: int,
        classifications: Optional[List[Classification]] = None,
        now: Optional[datetime] = None,
    ) -> List[CorpusEntry]:
        """Return metadata-tier entries ordered for agent priming.

        Order: foundational → tactical → observational; within each tier,
        more-recently-updated entries appear first. Accumulates entries
        until adding the next one would exceed ``token_budget`` (measured
        in cl100k_base tokens against the metadata-summary body).

        Args:
            token_budget: Max total metadata tokens to return.
            classifications: If provided, only entries in these tiers are
                considered.
            now: Reference timestamp for recency sorting; defaults to UTC now.
        """
        now = now or datetime.now(timezone.utc)
        entries = _load_active_entries(self.root)
        if classifications is not None:
            wanted = set(classifications)
            entries = [e for e in entries if e.classification in wanted]

        # Sort: tier ascending, recency descending. Recency-decay is a strict
        # function of (now - last_updated_at), so a larger decay = more recent.
        entries.sort(
            key=lambda e: (
                _TIER_RANK[e.classification],
                -recency_decay(e, now),
            )
        )

        primed: List[CorpusEntry] = []
        budget_remaining = token_budget
        for entry in entries:
            meta = _to_metadata(entry)
            if meta.size_tokens > budget_remaining:
                break
            primed.append(meta)
            budget_remaining -= meta.size_tokens
        return primed

    # ------------------------------------------------------------------
    # expand
    # ------------------------------------------------------------------

    def expand(self, entry_id: str) -> CorpusEntry:
        """Return the full entry by ``id``. Searches active subdirs only.

        Raises:
            FileNotFoundError: If no active entry has the given id.
        """
        for path in _iter_active_files(self.root):
            if path.stem == entry_id:
                return parse_entry(path)
        raise FileNotFoundError(f"No active corpus entry with id={entry_id!r}")

    # ------------------------------------------------------------------
    # find_by_classification
    # ------------------------------------------------------------------

    def find_by_classification(
        self, classification: Classification
    ) -> List[CorpusEntry]:
        """Return all active entries with ``classification``."""
        subdir = self.root / classification.value
        if not subdir.is_dir():
            return []
        out: List[CorpusEntry] = []
        for path in subdir.glob("*.md"):
            try:
                out.append(parse_entry(path))
            except (ValueError, KeyError) as exc:
                _LOGGER.warning("Skipping malformed entry %s: %s", path, exc)
        return out

    # ------------------------------------------------------------------
    # find_unreferenced
    # ------------------------------------------------------------------

    def find_unreferenced(
        self,
        since_run: Optional[str] = None,
        days: Optional[int] = None,
        now: Optional[datetime] = None,
    ) -> List[CorpusEntry]:
        """Return entries with no recent references.

        - If ``days`` is set: filter to entries whose ``last_referenced_run_id``
          is ``None`` AND ``(now - last_updated_at).days >= days``.
        - If ``since_run`` is set: union of ``corpus_refs`` across trajectory
          events for that run is computed; entries NOT in that set are returned.
        - If both: intersection of the two filters.
        """
        now = now or datetime.now(timezone.utc)
        entries = _load_active_entries(self.root)

        if days is not None:
            entries = [
                e
                for e in entries
                if e.last_referenced_run_id is None
                and (now - e.last_updated_at).days >= days
            ]

        if since_run is not None:
            qe = self._query_events
            if qe is None:
                # Lazy import — see docstring rationale.
                from pi_harness.trajectory.store import query_events as qe  # type: ignore[no-redef]
            events = qe(run_id=since_run)
            referenced: set[str] = set()
            for ev in events:
                referenced.update(getattr(ev, "corpus_refs", []) or [])
            entries = [e for e in entries if e.id not in referenced]

        return entries


# ---------------------------------------------------------------------------
# Convenience module-level entry point exposed for Plan 6/8 cross-plan use.
# ---------------------------------------------------------------------------


def prime(
    root: Path,
    token_budget: int,
    classifications: Optional[List[Classification]] = None,
    now: Optional[datetime] = None,
    query_events: Optional[Callable[..., List[object]]] = None,
) -> List[CorpusEntry]:
    """Module-level convenience: build a :class:`CorpusReader` and call ``prime``."""
    reader = CorpusReader(root, query_events=query_events)
    return reader.prime(token_budget=token_budget, classifications=classifications, now=now)
