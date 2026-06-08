from __future__ import annotations

import io
import logging
from pathlib import Path

import pytest

from pi_harness.agent_wrapper import _build_argv, consume_stream
from pi_harness.trajectory.store import init_db, query_events


SAMPLE = Path(__file__).resolve().parent.parent / "docs" / "captures" / "pi-stdout-json.ndjson"


def test_resolve_local_bucket_needs_no_key(monkeypatch):
    from pi_harness import agent_wrapper
    from pi_harness.settings import HarnessSettings, BucketConfig

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        agent_wrapper, "load_settings", lambda: HarnessSettings(
            orchestrator=BucketConfig(provider="local", model="mlx-x"),
            builder=BucketConfig(provider="local", model="mlx-y"),
        ),
    )
    assert agent_wrapper._resolve_provider_model("reasoning") == (
        agent_wrapper.LOCAL_PROVIDER_NAME, "mlx-x")


def test_resolve_api_bucket_without_key_raises(monkeypatch):
    from pi_harness import agent_wrapper
    from pi_harness.config import ConfigError
    from pi_harness.settings import HarnessSettings, BucketConfig

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        agent_wrapper, "load_settings", lambda: HarnessSettings(
            orchestrator=BucketConfig(provider="api", model="gpt-5"),
            builder=BucketConfig(provider="local", model="mlx-y"),
        ),
    )
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        agent_wrapper._resolve_provider_model("reasoning")


def test_build_argv_pi_includes_stdin_safe_flags():
    argv = _build_argv("pi", ["my prompt"])
    assert argv[0] == "pi"
    assert "--print" in argv
    assert "--mode" in argv and "json" in argv
    assert "--no-session" in argv
    # the prompt is appended at the end
    assert argv[-1] == "my prompt"


def test_build_argv_codex_passthrough():
    assert _build_argv("codex", ["x"]) == ["codex", "x"]


def test_build_argv_unknown_executor_raises():
    with pytest.raises(ValueError, match="unknown executor"):
        _build_argv("nope", [])


def test_build_argv_pi_passes_provider_and_model_when_set():
    argv = _build_argv("pi", ["my prompt"], provider="openai", model="gpt-5")
    assert "--provider" in argv
    assert argv[argv.index("--provider") + 1] == "openai"
    assert "--model" in argv
    assert argv[argv.index("--model") + 1] == "gpt-5"
    # The prompt is still appended last so ClawTeam-injected `-p <prompt>` lands there.
    assert argv[-1] == "my prompt"


def test_build_argv_pi_omits_provider_when_none():
    argv = _build_argv("pi", ["p"])
    assert "--provider" not in argv
    assert "--model" not in argv


def test_resolve_provider_model_api_bucket_resolves_openai(tmp_path, monkeypatch):
    """An explicitly-selected 'api' bucket resolves to (openai, <model>) when a
    key is present. (Robust to the local-default flip: uses explicit settings,
    not the defaults.)"""
    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    from pi_harness.agent_wrapper import _resolve_provider_model
    from pi_harness.settings import BucketConfig, HarnessSettings, save_settings

    save_settings(HarnessSettings(
        orchestrator=BucketConfig(provider="api", model="gpt-5"),
        builder=BucketConfig(provider="api", model="gpt-5-mini"),
    ))
    assert _resolve_provider_model("reasoning") == ("openai", "gpt-5")
    assert _resolve_provider_model("fast") == ("openai", "gpt-5-mini")


def test_resolve_provider_model_local_uses_harness_local_provider(tmp_path, monkeypatch):
    """When the user picks 'local' for a bucket, the wrapper must hand pi the
    name of the local provider we registered in pi's models.json — currently
    'harness-local'."""
    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")  # builder bucket is api here
    from pi_harness.agent_wrapper import _resolve_provider_model
    from pi_harness.settings import BucketConfig, HarnessSettings, save_settings

    save_settings(HarnessSettings(
        orchestrator=BucketConfig(provider="local", model="qwen2.5-coder:7b"),
        builder=BucketConfig(provider="api", model="gpt-5-mini"),
    ))
    assert _resolve_provider_model("reasoning") == ("harness-local", "qwen2.5-coder:7b")
    assert _resolve_provider_model("fast") == ("openai", "gpt-5-mini")


def test_resolve_provider_model_unknown_bucket_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path))
    from pi_harness.agent_wrapper import _resolve_provider_model

    with pytest.raises(ValueError, match="bucket"):
        _resolve_provider_model("middle")


def test_consume_stream_writes_events_to_db(tmp_path: Path):
    db = tmp_path / "traj.db"
    init_db(db)
    lines = SAMPLE.read_text().splitlines()
    count = consume_stream(lines, run_id="r-wrap", agent_id="agent-wrap", db_path=db, tee_to=None)
    assert count > 0
    events = query_events(run_id="r-wrap", db_path=db)
    classifications = {e.classification for e in events}
    assert {"tool_call", "tool_result", "message"}.issubset(classifications)
    # the captured ls tool call landed
    tc = next(e for e in events if e.classification == "tool_call")
    assert tc.tool == "ls"


def test_consume_stream_tees_lines(tmp_path: Path):
    db = tmp_path / "traj.db"
    init_db(db)
    out = io.StringIO()
    lines = ['{"type":"agent_start"}', '{"type":"turn_start"}']
    consume_stream(lines, run_id="r", agent_id="a", db_path=db, tee_to=out)
    # both lines mirrored to tee_to with trailing newlines
    assert out.getvalue().count("\n") == 2
    assert '"type":"agent_start"' in out.getvalue()


def test_consume_stream_swallows_write_errors(tmp_path: Path, monkeypatch):
    """Capture must never break the run, even if the trajectory write fails."""
    import pi_harness.agent_wrapper as wrap

    def _boom(event, *, db_path=None):
        raise RuntimeError("disk full")

    monkeypatch.setattr(wrap, "write_event", _boom)
    # one tool_execution_start line so feed yields one event the failing write_event will see
    lines = ['{"type":"tool_execution_start","toolCallId":"x","toolName":"ls","args":{}}']
    # must not raise
    count = consume_stream(lines, run_id="r", agent_id="a", db_path=tmp_path / "x.db", tee_to=None)
    assert count == 0  # write failed so nothing counted


def test_consume_stream_logs_dropped_write_errors(tmp_path: Path, monkeypatch, caplog):
    """A dropped write must be visible in logs, not silently swallowed (#9)."""
    import pi_harness.agent_wrapper as wrap

    def _boom(event, *, db_path=None):
        raise RuntimeError("disk full")

    monkeypatch.setattr(wrap, "write_event", _boom)
    lines = ['{"type":"tool_execution_start","toolCallId":"x","toolName":"ls","args":{}}']
    with caplog.at_level(logging.WARNING, logger="pi_harness.agent_wrapper"):
        consume_stream(lines, run_id="r", agent_id="a", db_path=tmp_path / "x.db", tee_to=None)
    assert any("dropped" in r.getMessage().lower() for r in caplog.records)


def test_build_argv_pi_does_not_inject_unsupported_end_of_options():
    """pi 0.73.1 has no `--` end-of-options separator — injecting one crashes it
    with `Unknown option: --` (verified 2026-06-06). So _build_argv must NOT add
    a `--`; the prompt is passed positionally, preserving @file/multi-message
    semantics. (This replaces the audit #27 `--` guard, which never worked.)"""
    argv = _build_argv("pi", ["a prompt"])
    assert "--" not in argv
    assert argv[-1] == "a prompt"

    # Multiple positional messages (and @file includes) pass through verbatim.
    argv = _build_argv("pi", ["@notes.md", "msg one", "msg two"])
    assert "--" not in argv
    assert argv[-3:] == ["@notes.md", "msg one", "msg two"]


def test_run_kills_child_and_propagates_on_capture_error(tmp_path: Path, monkeypatch):
    """If capture raises, run() must kill the child (no orphaned credit burn)
    and let the error surface — not swallow it via `return` in finally (#10/#26/#35)."""
    import pi_harness.agent_wrapper as wrap

    class FakeProc:
        def __init__(self):
            self.stdout = io.StringIO("line\n")
            self.killed = False

        def kill(self):
            self.killed = True

        def wait(self):
            return 137

    fake = FakeProc()
    monkeypatch.setattr(wrap.subprocess, "Popen", lambda *a, **k: fake)

    def _boom(*a, **k):
        raise RuntimeError("capture boom")

    monkeypatch.setattr(wrap, "consume_stream", _boom)
    with pytest.raises(RuntimeError, match="capture boom"):
        wrap.run(
            executor="pi", run_id="r", agent_id="a",
            db_path=tmp_path / "x.db", prompt_args=["hi"], tee_stdout=False,
        )
    assert fake.killed is True
