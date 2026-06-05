from typer.testing import CliRunner

from pi_harness.cli import app
from pi_harness.observability import bridge


def test_observe_calls_backfill(monkeypatch):
    calls = {}

    def fake_backfill(run_id, **kw):
        calls["run"] = run_id
        calls["kw"] = kw
        return 42

    monkeypatch.setattr(bridge, "backfill_run", fake_backfill)
    result = CliRunner().invoke(app, ["observe", "--run", "run-abc"])
    assert result.exit_code == 0
    assert calls["run"] == "run-abc"
    assert "42" in result.stdout
