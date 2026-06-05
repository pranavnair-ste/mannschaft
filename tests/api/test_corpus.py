from __future__ import annotations

from datetime import datetime, timezone


def _write_entry(
    corpus_root, classification, *, record_type=None, body="some pattern body",
    archived=False, helpful=0, harmful=0, contradiction=0,
):
    from pi_harness.corpus.format import CorpusEntry, RecordType, serialize_entry

    record_type = record_type or RecordType.PATTERN
    now = datetime(2026, 5, 28, tzinfo=timezone.utc)
    e = CorpusEntry.new(record_type=record_type, classification=classification, body=body, now=now)
    e = e.with_counters(helpful_count=helpful, harmful_count=harmful, contradiction_count=contradiction)
    if archived:
        subdir = corpus_root / "archived" / classification.value
    else:
        subdir = corpus_root / classification.value
    subdir.mkdir(parents=True, exist_ok=True)
    (subdir / f"{e.id}.md").write_text(serialize_entry(e), encoding="utf-8")
    return e


def test_corpus_health_returns_token_gauge(client, cfg):
    from pi_harness.corpus.format import Classification

    _write_entry(cfg.corpus_root, Classification.TACTICAL, body="tactical body one")
    _write_entry(cfg.corpus_root, Classification.FOUNDATIONAL, body="foundational body")
    r = client.get("/corpus/health")
    assert r.status_code == 200
    h = r.json()
    assert h["tactical_count"] == 1
    assert h["foundational_count"] == 1
    assert h["soft_cap_tokens"] > 0
    assert h["pct_of_cap"] == h["total_active_tokens"] / h["soft_cap_tokens"]
    assert set(h["prune_candidates"]) == {"counter", "contradiction", "staleness", "dedup", "budget"}


def test_corpus_health_counts_counter_candidate(client, cfg):
    from pi_harness.corpus.format import Classification

    _write_entry(cfg.corpus_root, Classification.TACTICAL, body="bad entry", helpful=1, harmful=10)
    h = client.get("/corpus/health").json()
    assert h["prune_candidates"]["counter"] >= 1


def test_corpus_entries_filter_by_classification(client, cfg):
    from pi_harness.corpus.format import Classification

    _write_entry(cfg.corpus_root, Classification.TACTICAL, body="t")
    _write_entry(cfg.corpus_root, Classification.OBSERVATIONAL, body="o")
    r = client.get("/corpus/entries", params={"classification": "tactical"})
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["classification"] == "tactical"


def test_corpus_entries_bad_classification_is_400(client, cfg):
    """An unknown classification must be a clean 400, not an uncaught
    Classification(...) ValueError -> 500 (audit #22)."""
    r = client.get("/corpus/entries", params={"classification": "bogus"})
    assert r.status_code == 400, r.text


def test_corpus_entries_default_excludes_archived(client, cfg):
    from pi_harness.corpus.format import Classification

    _write_entry(cfg.corpus_root, Classification.OBSERVATIONAL, body="active one")
    _write_entry(cfg.corpus_root, Classification.OBSERVATIONAL, body="archived one", archived=True)
    active = client.get("/corpus/entries").json()
    assert all(not row["archived"] for row in active)
    archived = client.get("/corpus/entries", params={"archived": "true"}).json()
    assert len(archived) == 1
    assert archived[0]["archived"] is True


def test_restore_archived_entry(client, cfg):
    from pi_harness.corpus.format import Classification

    entry = _write_entry(cfg.corpus_root, Classification.OBSERVATIONAL, body="restore me", archived=True)
    r = client.post(f"/corpus/entries/{entry.id}/restore")
    assert r.status_code == 200
    assert r.json()["id"] == entry.id
    # now active, no longer archived
    assert (cfg.corpus_root / "observational" / f"{entry.id}.md").exists()
    assert not (cfg.corpus_root / "archived" / "observational" / f"{entry.id}.md").exists()


def test_restore_404_unknown(client):
    assert client.post("/corpus/entries/bogus-id/restore").status_code == 404
