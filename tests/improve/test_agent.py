"""Tests for pi_harness.improve.agent."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from pi_harness.corpus.format import Classification, CorpusEntry, RecordType
from pi_harness.trajectory.schema import TrajectoryEvent


def _make_event(
    *,
    agent_id: str,
    step_id: str,
    tool: str = "",
    outcome: str = "success",
    duration_ms: int = 10,
    classification: str = "tool_call",
) -> TrajectoryEvent:
    return TrajectoryEvent(
        run_id="run-1",
        agent_id=agent_id,
        step_id=step_id,
        ts=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        model="gpt-5",
        tool=tool,
        input={},
        output={},
        duration_ms=duration_ms,
        tokens_in=10,
        tokens_out=10,
        outcome=outcome,
        classification=classification,
    )


def _make_entry(
    *,
    id_: str,
    body: str,
    record_type: RecordType = RecordType.PATTERN,
    classification: Classification = Classification.TACTICAL,
    helpful: int = 0,
    harmful: int = 0,
) -> CorpusEntry:
    return CorpusEntry(
        id=id_,
        record_type=record_type,
        classification=classification,
        body=body,
        helpful_count=helpful,
        harmful_count=harmful,
        contradiction_count=0,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_referenced_run_id=None,
        size_tokens=len(body) // 4,
    )


# ---------------------------------------------------------------------------
# summarize_trajectory
# ---------------------------------------------------------------------------


def test_summarize_trajectory_shape() -> None:
    """3 agents x 5 steps each → run_shape + per_agent_steps without raw I/O."""
    from pi_harness.improve.agent import summarize_trajectory

    events: list[TrajectoryEvent] = []
    for agent_idx in range(3):
        for step_idx in range(5):
            events.append(
                _make_event(
                    agent_id=f"agent-{agent_idx}",
                    step_id=f"step-{agent_idx}-{step_idx}",
                    tool=f"tool-{step_idx % 2}",  # 2 distinct tools per agent
                    outcome="success" if step_idx < 4 else "error",
                )
            )

    summary = summarize_trajectory(events)

    assert set(summary.keys()) == {"run_shape", "per_agent_steps"}

    run_shape = summary["run_shape"]
    assert set(run_shape.keys()) == {"agents", "tools_used", "outcomes"}
    assert sorted(run_shape["agents"]) == ["agent-0", "agent-1", "agent-2"]
    assert sorted(run_shape["tools_used"]) == ["tool-0", "tool-1"]
    # Each agent's final step outcome was "error".
    assert run_shape["outcomes"] == {
        "agent-0": "error",
        "agent-1": "error",
        "agent-2": "error",
    }

    per_agent = summary["per_agent_steps"]
    assert set(per_agent.keys()) == {"agent-0", "agent-1", "agent-2"}
    for agent_id, steps in per_agent.items():
        assert len(steps) == 5
        for s in steps:
            assert set(s.keys()) == {"step_id", "tool", "outcome", "duration_ms"}
            assert "input" not in s
            assert "output" not in s


# ---------------------------------------------------------------------------
# summarize_corpus_metadata
# ---------------------------------------------------------------------------


def test_summarize_corpus_metadata() -> None:
    """summarize_corpus_metadata returns metadata + body_preview, never full body."""
    from pi_harness.improve.agent import summarize_corpus_metadata

    long_body = "x" * 500
    entries = [
        _make_entry(id_="e1", body=long_body, helpful=3, harmful=0),
        _make_entry(id_="e2", body="short body", helpful=0, harmful=1),
    ]

    out = summarize_corpus_metadata(entries)

    assert len(out) == 2
    for item in out:
        assert set(item.keys()) == {
            "id",
            "classification",
            "record_type",
            "helpful_count",
            "harmful_count",
            "last_referenced_run_id",
            "body_preview",
        }
        assert "body" not in item
        # body_preview is at most 120 chars
        assert len(item["body_preview"]) <= 120

    # First entry's preview is exactly the first 120 chars.
    assert out[0]["body_preview"] == long_body[:120]
    assert out[1]["body_preview"] == "short body"


# ---------------------------------------------------------------------------
# summarize_git_diff
# ---------------------------------------------------------------------------


def _make_diff() -> str:
    """Generate a multi-file git diff with ~200 lines."""
    lines: list[str] = []
    for file_idx in range(3):
        lines.append(f"diff --git a/file{file_idx}.py b/file{file_idx}.py")
        lines.append(f"index 0000000..1111111 100644")
        lines.append(f"--- a/file{file_idx}.py")
        lines.append(f"+++ b/file{file_idx}.py")
        # 8 hunks per file, 8 lines each (mix +/-)
        for hunk_idx in range(8):
            lines.append(f"@@ -{hunk_idx},5 +{hunk_idx},5 @@")
            for line_idx in range(8):
                if line_idx % 2 == 0:
                    lines.append(f"+added line {hunk_idx}.{line_idx}")
                else:
                    lines.append(f"-removed line {hunk_idx}.{line_idx}")
    return "\n".join(lines)


def test_summarize_git_diff() -> None:
    """A 200-line, multi-file diff is summarized to under 2000 chars with +N -M."""
    from pi_harness.improve.agent import summarize_git_diff

    diff = _make_diff()
    summary = summarize_git_diff(diff)

    assert isinstance(summary, str)
    assert len(summary) <= 2000
    # Each file gets a +N -M header.
    for file_idx in range(3):
        assert f"file{file_idx}.py" in summary
    # Some + and - markers survive (first/last 3 hunks).
    assert "+" in summary
    assert "-" in summary


# ---------------------------------------------------------------------------
# build_messages / load_prompt_template
# ---------------------------------------------------------------------------


def test_load_prompt_template_reads_file() -> None:
    """load_prompt_template returns the v1 template content."""
    from pi_harness.improve.agent import load_prompt_template

    text = load_prompt_template()
    assert isinstance(text, str)
    assert len(text) > 0
    # Anchor text from the template — Task 4.
    assert "Improve-Agent System Prompt" in text


def test_build_messages_includes_all_inputs() -> None:
    """The user message contains the run_id, all 4 summaries, and the closing reminder."""
    from pi_harness.improve.agent import build_messages

    msgs = build_messages(
        run_id="run-abc",
        trajectory_summary={"run_shape": {"agents": ["a"]}, "per_agent_steps": {}},
        corpus_summary=[{"id": "e1", "body_preview": "p"}],
        git_diff_summary="file.py: +3 -0",
        prompt_template_text="TEMPLATE_BODY",
    )

    assert isinstance(msgs, list)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == "TEMPLATE_BODY"
    assert msgs[1]["role"] == "user"
    user = msgs[1]["content"]
    assert "run-abc" in user
    assert "run_shape" in user
    assert "e1" in user
    assert "file.py: +3 -0" in user
    assert "Return ONLY a JSON object" in user
