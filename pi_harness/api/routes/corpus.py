from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request

from pi_harness.api.models import CorpusEntryDTO, CorpusHealthDTO
from pi_harness.corpus.curator import Curator
from pi_harness.corpus.format import Classification, CorpusEntry, parse_entry
from pi_harness.corpus.prune import (
    prune_by_budget,
    prune_by_contradiction,
    prune_by_counter,
    prune_by_dedup,
    prune_by_staleness,
)
from pi_harness.corpus.reader import CorpusReader

router = APIRouter(prefix="/corpus", tags=["corpus"])


def _soft_cap() -> int:
    return int(os.environ.get("PI_HARNESS_CORPUS_SOFT_CAP", "50000"))


def _preview(body: str) -> str:
    stripped = body.strip()
    return stripped.splitlines()[0][:80] if stripped else ""


def _entry_to_dto(entry: CorpusEntry, *, archived: bool = False) -> CorpusEntryDTO:
    return CorpusEntryDTO(
        id=entry.id,
        record_type=entry.record_type.value,
        classification=entry.classification.value,
        helpful_count=entry.helpful_count,
        harmful_count=entry.harmful_count,
        contradiction_count=entry.contradiction_count,
        created_at=entry.created_at,
        last_updated_at=entry.last_updated_at,
        last_referenced_run_id=entry.last_referenced_run_id,
        session_id=entry.session_id,
        size_tokens=entry.size_tokens,
        archived=archived,
        body_preview=_preview(entry.body),
    )


def _active_entries(reader: CorpusReader) -> list[CorpusEntry]:
    out: list[CorpusEntry] = []
    for cls in Classification:
        out.extend(reader.find_by_classification(cls))
    return out


def _archived_entries(corpus_root) -> list[CorpusEntry]:
    archive_root = corpus_root / "archived"
    if not archive_root.is_dir():
        return []
    entries: list[CorpusEntry] = []
    for path in archive_root.rglob("*.md"):
        try:
            entries.append(parse_entry(path))
        except (ValueError, KeyError):
            continue
    return entries


@router.get("/health", response_model=CorpusHealthDTO)
def corpus_health(request: Request) -> CorpusHealthDTO:
    cfg = request.app.state.config
    reader = CorpusReader(cfg.corpus_root)
    now = datetime.now(timezone.utc)
    soft_cap = _soft_cap()

    active = _active_entries(reader)
    total_tokens = sum(e.size_tokens for e in active)
    archived = _archived_entries(cfg.corpus_root)
    archived.sort(key=lambda e: e.last_updated_at, reverse=True)

    prune_candidates = {
        "counter": sum(1 for e in active if prune_by_counter(e)),
        "contradiction": sum(1 for e in active if prune_by_contradiction(e)),
        "staleness": sum(1 for e in active if prune_by_staleness(e, now, [])),
        "dedup": len(prune_by_dedup(active, now=now)),
        "budget": len(prune_by_budget(active, soft_cap=soft_cap, now=now)),
    }
    stale = reader.find_unreferenced(days=7, now=now)

    return CorpusHealthDTO(
        total_active_tokens=total_tokens,
        soft_cap_tokens=soft_cap,
        pct_of_cap=(total_tokens / soft_cap) if soft_cap else 0.0,
        foundational_count=sum(1 for e in active if e.classification == Classification.FOUNDATIONAL),
        tactical_count=sum(1 for e in active if e.classification == Classification.TACTICAL),
        observational_count=sum(1 for e in active if e.classification == Classification.OBSERVATIONAL),
        archived_count=len(archived),
        prune_candidates=prune_candidates,
        stale_entries=[_entry_to_dto(e) for e in stale[:50]],
        recently_archived=[_entry_to_dto(e, archived=True) for e in archived[:25]],
    )


@router.get("/entries", response_model=list[CorpusEntryDTO])
def list_entries(
    request: Request,
    classification: str | None = Query(default=None),
    record_type: str | None = Query(default=None),
    archived: bool = Query(default=False),
) -> list[CorpusEntryDTO]:
    cfg = request.app.state.config
    reader = CorpusReader(cfg.corpus_root)
    if archived:
        pairs = [(e, True) for e in _archived_entries(cfg.corpus_root)]
    elif classification:
        pairs = [(e, False) for e in reader.find_by_classification(Classification(classification))]
    else:
        pairs = [(e, False) for e in _active_entries(reader)]

    result: list[CorpusEntryDTO] = []
    for entry, is_archived in pairs:
        if record_type and entry.record_type.value != record_type:
            continue
        if classification and entry.classification.value != classification:
            continue
        result.append(_entry_to_dto(entry, archived=is_archived))
    return result


@router.post("/entries/{entry_id}/restore", response_model=CorpusEntryDTO)
def restore_entry(request: Request, entry_id: str) -> CorpusEntryDTO:
    cfg = request.app.state.config
    try:
        entry = Curator(cfg).restore_archived(entry_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="archived entry not found")
    return _entry_to_dto(entry)
