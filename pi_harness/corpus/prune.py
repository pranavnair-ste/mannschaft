"""Pure-code corpus pruning triggers.

Implements every trigger listed in ``HARNESS_ARCHITECTURE.md`` §2:

1. **Counter** — ``harmful_count > helpful_count`` → demote one tier (or archive
   if already observational).
2. **Contradiction** — ``contradiction_count >= 3`` → archive.
3. **Staleness** — per-classification:

   - Foundational: never auto-prune.
   - Tactical: archive if 0 references in the last K runs (default 50).
   - Observational: archive after 7 days unreferenced, delete after 30 days
     archived (unless ``restored=True``).

4. **Token budget** — soft cap (default 50k tokens) across foundational +
   tactical + observational; foundational is preserved, lowest-utility
   entries are archived first until total tokens ≤ cap.
5. **Semantic dedup** — Jaccard similarity over 5-shingles ≥ ``similarity_threshold``
   (default 0.85) triggers MERGE: lower-utility loser archived, counters summed.

All functions return ``list[PruneAction]`` — *the curator* executes them. No
LLM calls, no embeddings.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pi_harness.corpus.counters import utility_score
from pi_harness.corpus.format import Classification, CorpusEntry

__all__ = [
    "PruneAction",
    "PruneActionType",
    "prune_by_budget",
    "prune_by_contradiction",
    "prune_by_counter",
    "prune_by_dedup",
    "prune_by_staleness",
]

_LOGGER = logging.getLogger(__name__)


# Defaults — exposed as kwarg defaults; the curator may override per pass.
DEFAULT_TACTICAL_RECENT_K = 50
DEFAULT_OBSERVATIONAL_ARCHIVE_DAYS = 7
DEFAULT_OBSERVATIONAL_DELETE_DAYS = 30
DEFAULT_BUDGET_SOFT_CAP = 50_000
DEFAULT_DEDUP_SIMILARITY_THRESHOLD = 0.85
DEFAULT_DEDUP_SHINGLE_K = 5
DEFAULT_ARCHIVE_GRACE_DAYS = 90


# Demote target per classification.
_DEMOTE_TARGET = {
    Classification.FOUNDATIONAL: Classification.TACTICAL,
    Classification.TACTICAL: Classification.OBSERVATIONAL,
    # Observational has no lower tier — handled inline as ARCHIVE.
}


class PruneActionType(str, Enum):
    """The four graduated prune actions."""

    ARCHIVE = "archive"
    DEMOTE = "demote"
    MERGE = "merge"
    DELETE = "delete"


@dataclass(frozen=True)
class PruneAction:
    """A single curator action to apply to one entry.

    Attributes:
        action: Kind of action.
        entry_id: Target entry id.
        reason: Human-readable trigger (logged in commit message).
        target_classification: For DEMOTE — the new classification.
        merge_with: For MERGE — id of the surviving entry the loser merges into.
        merged_counters: For MERGE — summed counters to apply to the survivor.
    """

    action: PruneActionType
    entry_id: str
    reason: str
    target_classification: Optional[Classification] = None
    merge_with: Optional[str] = None
    merged_counters: Optional[Dict[str, int]] = None


# ---------------------------------------------------------------------------
# 1. Counter trigger
# ---------------------------------------------------------------------------


def prune_by_counter(entry: CorpusEntry) -> List[PruneAction]:
    """Emit DEMOTE / ARCHIVE when ``harmful_count > helpful_count``."""
    if entry.harmful_count <= entry.helpful_count:
        return []
    reason = (
        f"harmful_count={entry.harmful_count} > helpful_count={entry.helpful_count}"
    )
    if entry.classification == Classification.OBSERVATIONAL:
        return [
            PruneAction(
                action=PruneActionType.ARCHIVE,
                entry_id=entry.id,
                reason=reason,
            )
        ]
    return [
        PruneAction(
            action=PruneActionType.DEMOTE,
            entry_id=entry.id,
            reason=reason,
            target_classification=_DEMOTE_TARGET[entry.classification],
        )
    ]


# ---------------------------------------------------------------------------
# 2. Contradiction trigger
# ---------------------------------------------------------------------------


def prune_by_contradiction(entry: CorpusEntry) -> List[PruneAction]:
    """Emit ARCHIVE when ``contradiction_count >= 3``."""
    if entry.contradiction_count < 3:
        return []
    return [
        PruneAction(
            action=PruneActionType.ARCHIVE,
            entry_id=entry.id,
            reason=f"contradiction_count={entry.contradiction_count} >= 3",
        )
    ]


# ---------------------------------------------------------------------------
# 3. Staleness trigger
# ---------------------------------------------------------------------------


def prune_by_staleness(
    entry: CorpusEntry,
    now: datetime,
    recent_run_ids: List[str],
    tactical_recent_k: int = DEFAULT_TACTICAL_RECENT_K,
    observational_archive_days: int = DEFAULT_OBSERVATIONAL_ARCHIVE_DAYS,
    observational_delete_days: int = DEFAULT_OBSERVATIONAL_DELETE_DAYS,
    archive_age_days: Optional[int] = None,
    restored: bool = False,
) -> List[PruneAction]:
    """Per-classification staleness rules.

    Args:
        entry: Active or archived entry.
        now: Reference timestamp.
        recent_run_ids: The most recent ``K`` run ids (for the tactical check).
        tactical_recent_k: Window size for the tactical check (default 50).
        observational_archive_days: Days after which an unreferenced observational
            entry is archived (default 7).
        observational_delete_days: Days after which an archived observational
            entry is hard-deleted (default 30).
        archive_age_days: If set, ``entry`` is currently archived and this is
            how long it has been archived. Triggers the DELETE check.
        restored: If ``True``, the archived entry has been restored at least
            once — DELETE is suppressed.
    """
    classification = entry.classification

    # --- Foundational: never auto-prune ----------------------------------
    if classification == Classification.FOUNDATIONAL:
        return []

    # --- Archived-observational hard-delete path -------------------------
    if archive_age_days is not None and classification == Classification.OBSERVATIONAL:
        if archive_age_days >= observational_delete_days and not restored:
            return [
                PruneAction(
                    action=PruneActionType.DELETE,
                    entry_id=entry.id,
                    reason=(
                        f"observational archived {archive_age_days}d unreferenced"
                    ),
                )
            ]
        return []

    # --- Tactical: 0 references in last K runs ---------------------------
    if classification == Classification.TACTICAL:
        recent_set = set(recent_run_ids[-tactical_recent_k:])
        if entry.last_referenced_run_id is None or entry.last_referenced_run_id not in recent_set:
            return [
                PruneAction(
                    action=PruneActionType.ARCHIVE,
                    entry_id=entry.id,
                    reason=(
                        f"tactical unreferenced in last {tactical_recent_k} runs"
                    ),
                )
            ]
        return []

    # --- Observational active: archive after N days unreferenced ---------
    if classification == Classification.OBSERVATIONAL:
        if entry.last_referenced_run_id is not None:
            return []
        age_days = (now - entry.last_updated_at).days
        if age_days >= observational_archive_days:
            return [
                PruneAction(
                    action=PruneActionType.ARCHIVE,
                    entry_id=entry.id,
                    reason=(
                        f"observational unreferenced {observational_archive_days}d"
                    ),
                )
            ]
        return []

    return []  # Defensive — unreachable given enum exhaustiveness


# ---------------------------------------------------------------------------
# 4. Token-budget trigger
# ---------------------------------------------------------------------------


def prune_by_budget(
    entries: List[CorpusEntry],
    soft_cap: int = DEFAULT_BUDGET_SOFT_CAP,
    now: Optional[datetime] = None,
) -> List[PruneAction]:
    """Archive lowest-utility tactical/observational entries until under cap.

    Foundational entries are preserved (never archived by this trigger). If
    foundational alone exceeds ``soft_cap``, ``[]`` is returned and a warning
    is logged.
    """
    if now is None:
        now = datetime.now(tz=entries[0].last_updated_at.tzinfo) if entries else datetime.utcnow()

    total = sum(e.size_tokens for e in entries)
    if total <= soft_cap:
        return []

    foundational_total = sum(
        e.size_tokens for e in entries if e.classification == Classification.FOUNDATIONAL
    )
    if foundational_total > soft_cap:
        _LOGGER.warning(
            "Token budget %s exceeded by foundational entries alone (%s); "
            "no archive candidates emitted.",
            soft_cap,
            foundational_total,
        )
        return []

    candidates = [e for e in entries if e.classification != Classification.FOUNDATIONAL]
    candidates.sort(key=lambda e: utility_score(e, now))

    actions: List[PruneAction] = []
    running_total = total
    for entry in candidates:
        if running_total <= soft_cap:
            break
        actions.append(
            PruneAction(
                action=PruneActionType.ARCHIVE,
                entry_id=entry.id,
                reason=(
                    f"token-budget archive ({running_total} > soft_cap={soft_cap}; "
                    f"utility={utility_score(entry, now):.6f})"
                ),
            )
        )
        running_total -= entry.size_tokens
    return actions


# ---------------------------------------------------------------------------
# 5. Semantic-dedup trigger
# ---------------------------------------------------------------------------


def _shingles(text: str, k: int = DEFAULT_DEDUP_SHINGLE_K) -> set[int]:
    """k-shingled hash set over whitespace-separated tokens.

    Hash uses BLAKE2b (deterministic across runs); each shingle is a tuple of
    ``k`` lowercased tokens joined by a single space.
    """
    tokens = text.lower().split()
    if len(tokens) < k:
        # Treat the whole text as one shingle when shorter than k.
        joined = " ".join(tokens)
        return {int.from_bytes(hashlib.blake2b(joined.encode(), digest_size=8).digest(), "big")} if tokens else set()
    out: set[int] = set()
    for i in range(len(tokens) - k + 1):
        shingle = " ".join(tokens[i : i + k])
        digest = hashlib.blake2b(shingle.encode(), digest_size=8).digest()
        out.add(int.from_bytes(digest, "big"))
    return out


def _jaccard(a: set[int], b: set[int]) -> float:
    if not a and not b:
        return 1.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def prune_by_dedup(
    entries: List[CorpusEntry],
    similarity_threshold: float = DEFAULT_DEDUP_SIMILARITY_THRESHOLD,
    now: Optional[datetime] = None,
) -> List[PruneAction]:
    """Emit MERGE actions for near-duplicate pairs.

    Each pair ``(a, b)`` with ``jaccard(shingles(a), shingles(b)) >= threshold``
    yields one MERGE: the lower-utility entry merges INTO the higher-utility
    entry. Counters are summed and reported via ``merged_counters``.

    Each entry participates in at most one MERGE per pass (the highest-similarity
    pair wins; subsequent pairs that reference an already-claimed entry are
    skipped).
    """
    if now is None:
        now = datetime.now(tz=entries[0].last_updated_at.tzinfo) if entries else datetime.utcnow()

    if len(entries) < 2:
        return []

    # Precompute shingles once
    shingles = {e.id: _shingles(e.body) for e in entries}
    utilities = {e.id: utility_score(e, now) for e in entries}
    by_id = {e.id: e for e in entries}

    # Score every pair and sort by similarity descending so the strongest
    # candidate merges first.
    pairs: List[tuple[float, str, str]] = []
    ids = list(by_id.keys())
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            sim = _jaccard(shingles[ids[i]], shingles[ids[j]])
            if sim >= similarity_threshold:
                pairs.append((sim, ids[i], ids[j]))
    pairs.sort(reverse=True)

    actions: List[PruneAction] = []
    claimed: set[str] = set()
    for sim, ida, idb in pairs:
        if ida in claimed or idb in claimed:
            continue
        a = by_id[ida]
        b = by_id[idb]
        if utilities[ida] >= utilities[idb]:
            winner, loser = a, b
        else:
            winner, loser = b, a
        merged_counters = {
            "helpful_count": winner.helpful_count + loser.helpful_count,
            "harmful_count": winner.harmful_count + loser.harmful_count,
            "contradiction_count": winner.contradiction_count + loser.contradiction_count,
        }
        actions.append(
            PruneAction(
                action=PruneActionType.MERGE,
                entry_id=loser.id,
                reason=f"dedup merge (jaccard={sim:.3f} >= {similarity_threshold})",
                merge_with=winner.id,
                merged_counters=merged_counters,
            )
        )
        claimed.add(ida)
        claimed.add(idb)
    return actions
