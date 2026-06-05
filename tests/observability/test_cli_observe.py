from typer.testing import CliRunner

from pi_harness.cli import app
from pi_harness.observability import bridge


def test_observe_calls_backfill(monkeypatch):
    calls = {}

    def fake_backfill(run_id, **kw):
        calls["run"] = run_id
        calls["kw"] = kw
        return bridge.BackfillResult(sent=42, ingested=40, rejected=2)

    monkeypatch.setattr(bridge, "backfill_run", fake_backfill)
    result = CliRunner().invoke(app, ["observe", "--run", "run-abc"])
    assert result.exit_code == 0
    assert calls["run"] == "run-abc"
    assert "42" in result.stdout      # sent count
    assert "40 ingested" in result.stdout


def test_observe_defaults_db_to_configured_path(monkeypatch):
    """Without --db, observe reads the CONFIGURED trajectory_db_path (honors
    PI_HARNESS_TRAJECTORY_DB_PATH) — not a hardcoded ~/.pi-harness default."""
    from pi_harness.config import load_config

    calls = {}
    monkeypatch.setattr(bridge, "backfill_run",
                        lambda run_id, **kw: calls.update(kw) or bridge.BackfillResult(0, 0, 0))
    result = CliRunner().invoke(app, ["observe", "--run", "r"])
    assert result.exit_code == 0
    assert calls["db_path"] == load_config().trajectory_db_path


def test_observe_forwards_explicit_db(monkeypatch, tmp_path):
    """--db overrides the configured path (replay an archived/throwaway DB)."""
    calls = {}
    monkeypatch.setattr(bridge, "backfill_run",
                        lambda run_id, **kw: calls.update(kw) or bridge.BackfillResult(1, 1, 0))
    db = tmp_path / "archive.db"
    result = CliRunner().invoke(app, ["observe", "--run", "r", "--db", str(db)])
    assert result.exit_code == 0
    assert calls["db_path"] == db
