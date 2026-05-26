"""Tests for pi_harness.improve.agent."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from pi_harness.corpus.format import Classification, CorpusEntry, RecordType
from pi_harness.trajectory.schema import TrajectoryEvent


# A minimal stand-in for pi_harness.config.Config; the agent only reads
# .openai_api_key and .reasoning_model, so we don't need the full dataclass.
@dataclass
class _FakeConfig:
    openai_api_key: str = "fake-key"
    reasoning_model: str = "fake-model"


def _make_fake_client(responses: list[str]) -> MagicMock:
    """A MagicMock OpenAI client whose chat.completions.create returns each
    response in turn (an Exception value is raised instead of returned)."""
    client = MagicMock()
    call_count = {"n": 0}

    def _create(**kwargs: Any) -> Any:
        idx = call_count["n"]
        call_count["n"] += 1
        if idx >= len(responses):
            raise AssertionError(
                f"_create called {idx + 1} times; only {len(responses)} responses queued"
            )
        item = responses[idx]
        if isinstance(item, Exception):
            raise item
        # Shape: response.choices[0].message.content == item
        msg = MagicMock()
        msg.content = item
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        return resp

    client.chat.completions.create.side_effect = _create
    return client


_VALID_JSON_PAYLOAD = json.dumps(
    {
        "updates": [
            {
                "record_type": "pattern",
                "classification": "tactical",
                "body": "Always batch writes.",
                "source_run_id": "run-1",
                "source_step_ids": ["step-1"],
                "confidence": 0.7,
                "rationale": "Observed.",
            }
        ],
        "prunes": [
            {
                "entry_id": "entry-1",
                "trigger": "counter",
                "rationale": "harmful > helpful",
            }
        ],
    }
)


_INVALID_SCHEMA_JSON = json.dumps(
    {
        "updates": [
            {
                "record_type": "pattern",
                "classification": "tactical",
                # missing body, source_run_id, source_step_ids, confidence, rationale
            }
        ],
        "prunes": [],
    }
)


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


# ---------------------------------------------------------------------------
# ImproveAgent.analyze — retry behavior
# ---------------------------------------------------------------------------


def test_analyze_returns_parsed_candidates() -> None:
    """A valid LLM response yields a (updates, prunes) tuple."""
    from pi_harness.improve.agent import ImproveAgent
    from pi_harness.improve.candidates import (
        CandidatePrune,
        CandidateUpdate,
    )

    client = _make_fake_client([_VALID_JSON_PAYLOAD])
    agent = ImproveAgent(_FakeConfig(), client=client)

    updates, prunes = agent.analyze(
        run_id="run-1",
        events=[_make_event(agent_id="a", step_id="step-1")],
        corpus_entries=[_make_entry(id_="entry-1", body="b")],
        git_diff_text="",
    )

    assert len(updates) == 1
    assert isinstance(updates[0], CandidateUpdate)
    assert len(prunes) == 1
    assert isinstance(prunes[0], CandidatePrune)
    assert client.chat.completions.create.call_count == 1


def test_analyze_retries_on_malformed_json() -> None:
    """Non-JSON output triggers one retry, then succeeds."""
    from pi_harness.improve.agent import ImproveAgent

    client = _make_fake_client(["not json at all", _VALID_JSON_PAYLOAD])
    agent = ImproveAgent(_FakeConfig(), client=client)

    updates, prunes = agent.analyze(
        run_id="run-1",
        events=[_make_event(agent_id="a", step_id="step-1")],
        corpus_entries=[],
        git_diff_text="",
    )

    assert len(updates) == 1
    assert len(prunes) == 1
    assert client.chat.completions.create.call_count == 2


def test_analyze_retries_on_schema_violation() -> None:
    """Schema-violating JSON triggers one retry, then succeeds."""
    from pi_harness.improve.agent import ImproveAgent

    client = _make_fake_client([_INVALID_SCHEMA_JSON, _VALID_JSON_PAYLOAD])
    agent = ImproveAgent(_FakeConfig(), client=client)

    updates, prunes = agent.analyze(
        run_id="run-1",
        events=[_make_event(agent_id="a", step_id="step-1")],
        corpus_entries=[],
        git_diff_text="",
    )

    assert len(updates) == 1
    assert len(prunes) == 1
    assert client.chat.completions.create.call_count == 2


def test_analyze_raises_after_max_retries() -> None:
    """3 malformed outputs in a row raises ImproveError."""
    from pi_harness.improve.agent import ImproveAgent, ImproveError

    client = _make_fake_client(["bad1", "bad2", "bad3"])
    agent = ImproveAgent(_FakeConfig(), client=client)

    with pytest.raises(ImproveError):
        agent.analyze(
            run_id="run-1",
            events=[_make_event(agent_id="a", step_id="step-1")],
            corpus_entries=[],
            git_diff_text="",
        )
    assert client.chat.completions.create.call_count == 3


# ---------------------------------------------------------------------------
# Fixture-driven acceptance test (AC2)
# ---------------------------------------------------------------------------


def _event_from_dict(d: dict) -> TrajectoryEvent:
    return TrajectoryEvent(
        run_id=d["run_id"],
        agent_id=d["agent_id"],
        step_id=d["step_id"],
        ts=datetime.fromisoformat(d["ts"]),
        model=d["model"],
        tool=d["tool"],
        input=d["input"],
        output=d["output"],
        duration_ms=d["duration_ms"],
        tokens_in=d["tokens_in"],
        tokens_out=d["tokens_out"],
        outcome=d["outcome"],
        classification=d["classification"],
        corpus_refs=list(d.get("corpus_refs") or []),
        corpus_cited=list(d.get("corpus_cited") or []),
    )


def _entry_from_dict(d: dict) -> CorpusEntry:
    return CorpusEntry(
        id=d["id"],
        record_type=RecordType(d["record_type"]),
        classification=Classification(d["classification"]),
        body=d["body"],
        helpful_count=d["helpful_count"],
        harmful_count=d["harmful_count"],
        contradiction_count=d["contradiction_count"],
        created_at=datetime.fromisoformat(d["created_at"]),
        last_updated_at=datetime.fromisoformat(d["last_updated_at"]),
        last_referenced_run_id=d.get("last_referenced_run_id"),
        size_tokens=d["size_tokens"],
    )


def test_analyze_with_sample_fixtures(
    sample_trajectory: list[dict],
    sample_corpus_index: list[dict],
    sample_git_diff: str,
    sample_agent_response: str,
) -> None:
    """Fixture-driven end-to-end of ImproveAgent.analyze.

    The fixtures cover a realistic small run (2 agents, 6 steps, 3 corpus
    entries, a multi-file diff). The fake client returns the canned valid
    response; we assert the parsed candidates match the expected counts
    (2 updates, 1 prune).
    """
    from pi_harness.improve.agent import ImproveAgent

    events = [_event_from_dict(d) for d in sample_trajectory]
    entries = [_entry_from_dict(d) for d in sample_corpus_index]

    client = _make_fake_client([sample_agent_response])
    agent = ImproveAgent(_FakeConfig(), client=client)

    updates, prunes = agent.analyze(
        run_id="run-sample",
        events=events,
        corpus_entries=entries,
        git_diff_text=sample_git_diff,
    )

    assert len(updates) == 2
    assert len(prunes) == 1
    assert client.chat.completions.create.call_count == 1
    # Spot-check fields preserved correctly.
    assert prunes[0].entry_id == "observation-existing-c"
