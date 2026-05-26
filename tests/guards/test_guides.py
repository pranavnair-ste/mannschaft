"""Tests for the four built-in Guides in pi_harness.guards.guides."""

from __future__ import annotations

from pathlib import Path

from pi_harness.guards.guides import (
    AllowlistGuide,
    PathScopeGuide,
    RateLimitGuide,
    SchemaValidatorGuide,
)
from pi_harness.guards.types import GuardKind


def _intent(tool="bash", **inp):
    return {
        "run_id": "r",
        "agent_id": "a",
        "step_id": "s",
        "tool": tool,
        "input": dict(inp),
    }


# ---------------------------------------------------------------------------
# AllowlistGuide
# ---------------------------------------------------------------------------


def test_allowlist_guide_kind():
    g = AllowlistGuide(allowed_tools=["bash"])
    assert g.kind == GuardKind.COMPUTATIONAL_GUIDE


def test_allowlist_guide_allows_listed_tool():
    g = AllowlistGuide(allowed_tools=["bash", "read"])
    r = g(_intent(tool="bash"))
    assert r.allow is True
    assert "bash" in r.reason


def test_allowlist_guide_denies_unlisted_tool():
    g = AllowlistGuide(allowed_tools=["bash"])
    r = g(_intent(tool="curl"))
    assert r.allow is False
    assert "curl" in r.reason
    assert "not in allowlist" in r.reason


# ---------------------------------------------------------------------------
# PathScopeGuide
# ---------------------------------------------------------------------------


def test_path_scope_guide_allows_inside_scope(tmp_path):
    scope = tmp_path / "ws"
    scope.mkdir()
    (scope / "f.txt").write_text("x")

    g = PathScopeGuide(allowed_paths=[scope])
    r = g({
        "run_id": "r", "agent_id": "a", "step_id": "s", "tool": "read",
        "input": {"path": str(scope / "f.txt")},
    })
    assert r.allow is True


def test_path_scope_guide_denies_dotdot_escape(tmp_path):
    scope = tmp_path / "ws"
    scope.mkdir()

    g = PathScopeGuide(allowed_paths=[scope])
    r = g({
        "run_id": "r", "agent_id": "a", "step_id": "s", "tool": "read",
        "input": {"path": str(scope / ".." / "secret.txt")},
    })
    assert r.allow is False
    assert "outside scope" in r.reason


def test_path_scope_guide_denies_absolute_outside(tmp_path):
    scope = tmp_path / "ws"
    scope.mkdir()

    g = PathScopeGuide(allowed_paths=[scope])
    r = g({
        "run_id": "r", "agent_id": "a", "step_id": "s", "tool": "write",
        "input": {"path": "/etc/passwd"},
    })
    assert r.allow is False


def test_path_scope_guide_allows_when_no_path_key():
    """Tools without a 'path' input pass through; this guard scopes file ops only."""
    g = PathScopeGuide(allowed_paths=[Path("/tmp")])
    r = g({
        "run_id": "r", "agent_id": "a", "step_id": "s", "tool": "bash",
        "input": {"cmd": "ls"},
    })
    assert r.allow is True
    assert "no path" in r.reason.lower()


# ---------------------------------------------------------------------------
# SchemaValidatorGuide
# ---------------------------------------------------------------------------


def test_schema_validator_allows_valid_input():
    schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    g = SchemaValidatorGuide(tool_name="read", schema=schema)
    r = g({
        "run_id": "r", "agent_id": "a", "step_id": "s", "tool": "read",
        "input": {"path": "/x"},
    })
    assert r.allow is True


def test_schema_validator_denies_invalid_input():
    schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    g = SchemaValidatorGuide(tool_name="read", schema=schema)
    r = g({
        "run_id": "r", "agent_id": "a", "step_id": "s", "tool": "read",
        "input": {},  # missing required 'path'
    })
    assert r.allow is False
    assert "schema" in r.reason.lower()


def test_schema_validator_skips_other_tools():
    """Guard scoped to a tool_name; other tools pass through."""
    g = SchemaValidatorGuide(tool_name="read", schema={"type": "object"})
    r = g({
        "run_id": "r", "agent_id": "a", "step_id": "s", "tool": "bash",
        "input": {"cmd": "ls"},
    })
    assert r.allow is True
    assert "different tool" in r.reason.lower()


# ---------------------------------------------------------------------------
# RateLimitGuide
# ---------------------------------------------------------------------------


def test_rate_limit_guide_allows_under_cap(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("pi_harness.guards.guides.time.monotonic", lambda: now[0])

    g = RateLimitGuide(tool_name="bash", max_per_minute=3)
    for i in range(3):
        now[0] = float(i)
        r = g({
            "run_id": "r", "agent_id": "a", "step_id": f"s{i}",
            "tool": "bash", "input": {},
        })
        assert r.allow is True


def test_rate_limit_guide_denies_over_cap(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("pi_harness.guards.guides.time.monotonic", lambda: now[0])

    g = RateLimitGuide(tool_name="bash", max_per_minute=2)
    g({"run_id": "r", "agent_id": "a", "step_id": "s1", "tool": "bash", "input": {}})
    now[0] = 1.0
    g({"run_id": "r", "agent_id": "a", "step_id": "s2", "tool": "bash", "input": {}})
    now[0] = 2.0
    r = g({"run_id": "r", "agent_id": "a", "step_id": "s3", "tool": "bash", "input": {}})
    assert r.allow is False
    assert "rate" in r.reason.lower()


def test_rate_limit_guide_refills_after_window(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("pi_harness.guards.guides.time.monotonic", lambda: now[0])

    g = RateLimitGuide(tool_name="bash", max_per_minute=2)
    g({"run_id": "r", "agent_id": "a", "step_id": "s1", "tool": "bash", "input": {}})
    g({"run_id": "r", "agent_id": "a", "step_id": "s2", "tool": "bash", "input": {}})
    now[0] = 65.0  # past the 60s window
    r = g({"run_id": "r", "agent_id": "a", "step_id": "s3", "tool": "bash", "input": {}})
    assert r.allow is True


def test_rate_limit_guide_skips_other_tools():
    g = RateLimitGuide(tool_name="bash", max_per_minute=1)
    r = g({
        "run_id": "r", "agent_id": "a", "step_id": "s",
        "tool": "read", "input": {},
    })
    assert r.allow is True


def test_rate_limit_guide_separates_agents(monkeypatch):
    """The bucket key is (agent_id, tool); two agents should not share quota."""
    now = [0.0]
    monkeypatch.setattr("pi_harness.guards.guides.time.monotonic", lambda: now[0])

    g = RateLimitGuide(tool_name="bash", max_per_minute=1)
    r1 = g({"run_id": "r", "agent_id": "agent1", "step_id": "s",
            "tool": "bash", "input": {}})
    r2 = g({"run_id": "r", "agent_id": "agent2", "step_id": "s",
            "tool": "bash", "input": {}})
    assert r1.allow is True
    assert r2.allow is True
