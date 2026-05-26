"""Counter mutations, recency decay, and utility score.

These functions are pure: they return new :class:`CorpusEntry` instances and
never touch disk. Disk writes are gated by :mod:`pi_harness.corpus.writer` and
flow exclusively through :class:`pi_harness.corpus.curator.Curator`.

Formulas (from ``HARNESS_ARCHITECTURE.md`` §2):

- ``recency_decay = 0.5 ** (age_days / half_life_days)``  (default 14d half-life)
- ``utility_score = helpful_count / max(size_tokens, 1) * recency_decay``
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from pi_harness.corpus.format import CorpusEntry

__all__ = [
    "recency_decay",
    "update_contradiction",
    "update_harmful",
    "update_helpful",
    "utility_score",
]


# Default half-life is 14 days; callers may override (the curator stays on
# the default unless explicitly tuned).
DEFAULT_HALF_LIFE_DAYS = 14.0


def update_helpful(entry: CorpusEntry, now: datetime) -> CorpusEntry:
    """Return a copy with ``helpful_count += 1`` and ``last_updated_at = now``."""
    return replace(
        entry,
        helpful_count=entry.helpful_count + 1,
        last_updated_at=now,
    )


def update_harmful(entry: CorpusEntry, now: datetime) -> CorpusEntry:
    """Return a copy with ``harmful_count += 1`` and ``last_updated_at = now``."""
    return replace(
        entry,
        harmful_count=entry.harmful_count + 1,
        last_updated_at=now,
    )


def update_contradiction(entry: CorpusEntry, now: datetime) -> CorpusEntry:
    """Return a copy with ``contradiction_count += 1`` and ``last_updated_at = now``."""
    return replace(
        entry,
        contradiction_count=entry.contradiction_count + 1,
        last_updated_at=now,
    )


def recency_decay(
    entry: CorpusEntry,
    now: datetime,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
) -> float:
    """Exponential decay against ``entry.last_updated_at``.

    Returns 1.0 for a just-updated entry, 0.5 at one half-life, etc.
    Future-dated ``last_updated_at`` returns >1.0 (caller's problem).
    """
    age_seconds = (now - entry.last_updated_at).total_seconds()
    age_days = age_seconds / 86400.0
    return 0.5 ** (age_days / half_life_days)


def utility_score(
    entry: CorpusEntry,
    now: datetime,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
) -> float:
    """``helpful_count / max(size_tokens, 1) * recency_decay``.

    Used by :func:`pi_harness.corpus.prune.prune_by_budget` to rank entries
    for archival when the token soft-cap is breached.
    """
    size = max(entry.size_tokens, 1)
    return (entry.helpful_count / size) * recency_decay(entry, now, half_life_days)
