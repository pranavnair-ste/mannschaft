"""Public API for the Mulch corpus subsystem.

Consumers (Plans 4, 6, 8) should import from this package root rather than
the implementation submodules. See ``HARNESS_ARCHITECTURE.md`` §2 for the
governing design.
"""

from __future__ import annotations

from pi_harness.corpus.counters import (
    recency_decay,
    update_contradiction,
    update_harmful,
    update_helpful,
    utility_score,
)
from pi_harness.corpus.curator import (
    CandidatePrune,
    CandidateUpdate,
    Curator,
    CuratorReport,
)
from pi_harness.corpus.format import (
    Classification,
    CorpusEntry,
    RecordType,
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
from pi_harness.corpus.reader import CorpusReader, prime
from pi_harness.corpus.writer import (
    WriterAccessError,
    archive_entry,
    curator_context,
    write_entry,
)

__all__ = [
    # format
    "Classification",
    "CorpusEntry",
    "RecordType",
    "count_tokens",
    "parse_entry",
    "serialize_entry",
    # reader
    "CorpusReader",
    "prime",
    # writer
    "WriterAccessError",
    "archive_entry",
    "curator_context",
    "write_entry",
    # counters
    "recency_decay",
    "update_contradiction",
    "update_harmful",
    "update_helpful",
    "utility_score",
    # prune
    "PruneAction",
    "PruneActionType",
    "prune_by_budget",
    "prune_by_contradiction",
    "prune_by_counter",
    "prune_by_dedup",
    "prune_by_staleness",
    # curator
    "CandidatePrune",
    "CandidateUpdate",
    "Curator",
    "CuratorReport",
]
