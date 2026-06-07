"""Tests for `pi-harness up` + `pi-harness doctor`.

Supervisor.run is patched so no real processes are ever spawned.
"""

from typer.testing import CliRunner

from pi_harness.cli import app
from pi_harness.observability import supervisor as sup

runner = CliRunner()


def test_up_builds_procs_and_runs(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    captured = {}

    def fake_run(self, **k):
        captured["procs"] = [p.name for p in self.procs]
        return 0

    monkeypatch.setattr(sup.Supervisor, "run", fake_run)
    res = runner.invoke(app, ["up", "--no-ui"])
    assert res.exit_code == 0
    assert (
        "fork" in captured["procs"]
        and "bridge" in captured["procs"]
        and "api" in captured["procs"]
    )
    assert "ui" not in captured["procs"]


def test_doctor_reports(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    res = runner.invoke(app, ["doctor"])
    assert res.exit_code in (0, 1)  # depends on local env
    assert "bun" in res.stdout.lower()
