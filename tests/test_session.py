from __future__ import annotations

from pathlib import Path

import pytest


def test_build_chat_argv_is_interactive_and_ungagged():
    from pi_harness.session import build_chat_argv

    argv = build_chat_argv(
        provider="harness-local",
        model="qwen",
        session_dir=Path("/h/sessions"),
        skills_dir=Path("/repo/skills"),
        disable_thinking=True,
    )
    # interactive: NONE of the batch gag-flags are present
    for gag in ("--print", "-p", "--no-session", "--no-skills",
                "--no-context-files", "--no-extensions", "--mode"):
        assert gag not in argv, f"{gag} must not be in an interactive chat argv"
    # the pieces we DO want
    assert argv[0] == "pi"
    assert argv[argv.index("--provider") + 1] == "harness-local"
    assert argv[argv.index("--model") + 1] == "qwen"
    assert argv[argv.index("--session-dir") + 1] == "/h/sessions"
    assert argv[argv.index("--skill") + 1] == "/repo/skills"
    assert "--thinking" in argv and argv[argv.index("--thinking") + 1] == "off"
    assert "--append-system-prompt" in argv


def test_build_chat_argv_no_thinking_flag_when_not_disabled():
    from pi_harness.session import build_chat_argv

    argv = build_chat_argv(
        provider="openai", model="gpt-5.4",
        session_dir=Path("/h/s"), skills_dir=Path("/r/skills"),
        disable_thinking=False,
    )
    assert "--thinking" not in argv


def test_resolve_session_model_defaults_to_orchestrator_bucket(monkeypatch):
    from pi_harness import session
    monkeypatch.setattr(
        "pi_harness.session._resolve_provider_model",
        lambda bucket: ("harness-local", "qwen") if bucket == "reasoning" else ("x", "y"),
    )
    assert session.resolve_session_model() == ("harness-local", "qwen")


def test_resolve_session_model_honors_overrides():
    from pi_harness import session
    assert session.resolve_session_model(
        provider_override="openai", model_override="gpt-5.4"
    ) == ("openai", "gpt-5.4")


def test_local_server_reachable_true_on_response(monkeypatch):
    from pi_harness import session

    class _Resp:  # any response means the socket answered
        status_code = 200

    monkeypatch.setattr(session.httpx, "get", lambda *a, **k: _Resp())
    assert session.local_server_reachable("http://localhost:8080/v1") is True


def test_local_server_reachable_false_on_connect_error(monkeypatch):
    from pi_harness import session

    def _boom(*a, **k):
        raise session.httpx.RequestError("nope")

    monkeypatch.setattr(session.httpx, "get", _boom)
    assert session.local_server_reachable("http://localhost:8080/v1") is False


def test_launch_chat_local_unreachable_exits_nonzero(monkeypatch, capsys):
    from pi_harness import session

    monkeypatch.setattr(session, "resolve_session_model", lambda **k: ("harness-local", "qwen"))
    monkeypatch.setattr(session, "ensure_local_provider_from_settings", lambda *a, **k: None)
    monkeypatch.setattr(session, "local_server_reachable", lambda *a, **k: False)
    spawned = []
    rc = session.launch_chat(spawn=lambda argv, **k: spawned.append(argv))
    assert rc != 0
    assert spawned == []  # never spawned pi
    assert "mlx_lm.server" in capsys.readouterr().out


def test_launch_chat_local_reachable_spawns_pi(monkeypatch, tmp_path):
    from pi_harness import session

    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path))
    monkeypatch.setattr(session, "resolve_session_model", lambda **k: ("harness-local", "qwen"))
    monkeypatch.setattr(session, "ensure_local_provider_from_settings", lambda *a, **k: None)
    monkeypatch.setattr(session, "local_server_reachable", lambda *a, **k: True)
    monkeypatch.setattr(session, "retire_raw_clawteam_skill", lambda **k: None)

    captured = {}

    class _Done:
        returncode = 0

    def _spawn(argv, **k):
        captured["argv"] = argv
        return _Done()

    rc = session.launch_chat(spawn=_spawn)
    assert rc == 0
    assert captured["argv"][0] == "pi"
    assert "--provider" in captured["argv"]
