"""Tests for the Decomposer: model shape, prompt loading, LLM call + retry.

The OpenAI client is injected (Decomposer(config, client=...)) so no network
or monkeypatching is needed — mirrors how Plan 4's ImproveAgent is tested.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from pi_harness.config import ConfigError
from pi_harness.settings import BucketConfig, HarnessSettings
from pi_harness.spec.decomposer import (
    DecomposedTask,
    Decomposer,
    DecomposerError,
    DecompositionResult,
    PROMPT_PATH,
)
from pi_harness.spec.format import Spec


def _api_settings(model: str = "o-test") -> HarnessSettings:
    return HarnessSettings(
        orchestrator=BucketConfig(provider="api", model=model),
        builder=BucketConfig(provider="api", model=model),
    )


def _spec() -> Spec:
    return Spec(
        id="spec-cancel",
        title="Cancel button",
        goal="Users can cancel an in-flight upload",
        acceptance_criteria=[
            "Clicking Cancel during upload aborts the request within 200ms",
            "Cancelled upload leaves no partial file on the server",
        ],
        constraints=[],
        non_goals=["Resuming after cancel"],
        created_at="2026-05-25T10:00:00Z",
        updated_at="2026-05-25T10:00:00Z",
        linter_score=1.0,
        status="linted",
    )


def _fake_config():
    cfg = MagicMock()
    cfg.openai_api_key = "sk-test"
    cfg.reasoning_model = "o-test"
    return cfg


def _chat_response(payload: dict | str) -> MagicMock:
    """Build a fake chat.completions result with choices[0].message.content."""
    content = payload if isinstance(payload, str) else json.dumps(payload)
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


# ---------- model + prompt ----------


def test_prompt_file_exists_and_versioned() -> None:
    assert PROMPT_PATH.exists()
    assert "prompt-version" in PROMPT_PATH.read_text(encoding="utf-8")


def test_decomposed_task_validates_role() -> None:
    with pytest.raises(ValidationError):
        DecomposedTask(
            id="t-1",
            name="bad",
            description="d",
            acceptance_criterion="x",
            blocked_by=[],
            assigned_role="wizard",
        )


def test_decomposed_task_round_trip() -> None:
    t = DecomposedTask(
        id="t-cancel",
        name="Add cancel button",
        description="Wire the button to abort the upload",
        acceptance_criterion="Clicking Cancel during upload aborts the request within 200ms",
        blocked_by=[],
        assigned_role="builder",
    )
    assert DecomposedTask.model_validate(t.model_dump()) == t


def test_decomposition_result_holds_tasks() -> None:
    res = DecompositionResult(
        tasks=[
            DecomposedTask(
                id="t-1", name="n", description="d",
                acceptance_criterion="abc", blocked_by=[], assigned_role="builder",
            )
        ]
    )
    assert len(res.tasks) == 1


def test_decomposer_init_loads_prompt() -> None:
    d = Decomposer(_fake_config(), client=MagicMock(), settings=_api_settings())
    assert "decomposition assistant" in d.prompt.lower()


def test_decomposer_api_bucket_requires_key() -> None:
    """No injected client + api reasoning bucket + no key → ConfigError."""
    cfg = MagicMock()
    cfg.openai_api_key = ""
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        Decomposer(cfg, settings=_api_settings())


def test_decomposer_requires_model() -> None:
    """A reasoning bucket with no model is a configuration error."""
    cfg = MagicMock()
    cfg.openai_api_key = "sk-test"
    settings = HarnessSettings(
        orchestrator=BucketConfig(provider="local", model=""),
        builder=BucketConfig(provider="local", model=""),
    )
    with pytest.raises(ConfigError, match="model"):
        Decomposer(cfg, settings=settings)


def test_decomposer_local_bucket_needs_no_key() -> None:
    """A local reasoning bucket builds a client with no OPENAI_API_KEY."""
    cfg = MagicMock()
    cfg.openai_api_key = ""
    settings = HarnessSettings(
        orchestrator=BucketConfig(provider="local", model="mlx-x"),
        builder=BucketConfig(provider="local", model="mlx-x"),
        local_base_url="http://localhost:8080/v1",
    )
    d = Decomposer(cfg, settings=settings)  # must not raise
    assert d.model == "mlx-x"


# ---------- LLM call + retry ----------


def test_decomposer_returns_tasks_on_valid_response() -> None:
    payload = {
        "tasks": [
            {
                "id": "t-cancel", "name": "Wire cancel button",
                "description": "Hook the cancel button up to abort the upload",
                "acceptance_criterion": "Clicking Cancel during upload aborts the request within 200ms",
                "blocked_by": [], "assigned_role": "builder",
            },
            {
                "id": "t-cleanup", "name": "Server cleanup",
                "description": "Delete partial file on cancel",
                "acceptance_criterion": "Cancelled upload leaves no partial file on the server",
                "blocked_by": ["t-cancel"], "assigned_role": "builder",
            },
        ]
    }
    client = MagicMock()
    client.chat.completions.create.return_value = _chat_response(payload)

    tasks = Decomposer(_fake_config(), client=client, settings=_api_settings()).decompose(_spec())

    assert [t.id for t in tasks] == ["t-cancel", "t-cleanup"]
    assert tasks[1].blocked_by == ["t-cancel"]
    client.chat.completions.create.assert_called_once()
    # JSON mode + the spec content reached the model.
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["model"] == "o-test"


def test_decomposer_retries_on_malformed_then_succeeds() -> None:
    good = {
        "tasks": [
            {
                "id": "t-only", "name": "n", "description": "d",
                "acceptance_criterion": "Clicking Cancel during upload aborts the request within 200ms",
                "blocked_by": [], "assigned_role": "builder",
            }
        ]
    }
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _chat_response("not json"),        # attempt 1 -> json parse error
        _chat_response({"tasks": [{}]}),   # attempt 2 -> pydantic error
        _chat_response(good),              # attempt 3 -> success
    ]
    tasks = Decomposer(_fake_config(), client=client, settings=_api_settings()).decompose(_spec())
    assert len(tasks) == 1
    assert client.chat.completions.create.call_count == 3


def test_decomposer_feeds_error_back_into_retry() -> None:
    """A schema failure must be fed back to the model on retry, not re-prompted
    identically. Small local models (e.g. Qwen3-Coder under json_object mode)
    drop required fields like `acceptance_criterion`; an identical re-prompt
    repeats the same omission, so the retry must carry the prior output + a
    corrective instruction naming what was missing."""
    missing = {  # valid JSON, but every task drops name + acceptance_criterion
        "tasks": [{"id": "t-1", "description": "d", "assigned_role": "builder"}]
    }
    good = {
        "tasks": [
            {
                "id": "t-1", "name": "n", "description": "d",
                "acceptance_criterion": "Clicking Cancel during upload aborts the request within 200ms",
                "blocked_by": [], "assigned_role": "builder",
            }
        ]
    }
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _chat_response(missing),  # attempt 1 -> pydantic error (missing fields)
        _chat_response(good),     # attempt 2 -> success, given the feedback
    ]

    tasks = Decomposer(_fake_config(), client=client, settings=_api_settings()).decompose(_spec())

    assert len(tasks) == 1
    assert client.chat.completions.create.call_count == 2
    # The 2nd call must carry the failure context: the model's own prior output
    # (assistant turn) followed by a corrective user turn naming the missing field.
    second_messages = client.chat.completions.create.call_args_list[1].kwargs["messages"]
    assert [m["role"] for m in second_messages] == ["system", "user", "assistant", "user"]
    assert second_messages[-2]["content"] == json.dumps(missing)
    assert "acceptance_criterion" in second_messages[-1]["content"]


def test_decomposer_raises_after_max_retries() -> None:
    client = MagicMock()
    client.chat.completions.create.return_value = _chat_response("still broken")
    with pytest.raises(DecomposerError, match="failed after"):
        Decomposer(_fake_config(), client=client, settings=_api_settings()).decompose(_spec())
    assert client.chat.completions.create.call_count == 3  # 1 initial + 2 retries
