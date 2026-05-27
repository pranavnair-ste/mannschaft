"""Decomposer: turns a linted Spec into a list of DecomposedTask via the LLM.

The LLM call uses ``chat.completions.create`` with JSON mode — the same shape
Plan 4's improve-agent locked onto (reasoning-tier strict json_schema support
varies). The response is validated with pydantic and retried on malformed
output. ``_call_llm`` is the single swap-point if the API shape changes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from pi_harness.spec.format import Spec

PROMPT_PATH = Path(__file__).parent / "prompts" / "decompose_prompt.md"

Role = Literal["orchestrator", "builder", "scout", "reviewer", "synthesizer"]


class DecomposedTask(BaseModel):
    id: str
    name: str
    description: str
    acceptance_criterion: str
    blocked_by: list[str] = Field(default_factory=list)
    assigned_role: Role


class DecompositionResult(BaseModel):
    tasks: list[DecomposedTask]


class DecomposerError(RuntimeError):
    pass


def _spec_to_user_message(spec: Spec) -> str:
    return json.dumps(
        {
            "id": spec.id,
            "title": spec.title,
            "goal": spec.goal,
            "acceptance_criteria": spec.acceptance_criteria,
            "constraints": spec.constraints,
            "non_goals": spec.non_goals,
        },
        indent=2,
    )


def _call_llm(client: Any, *, model: str, messages: list[dict[str, str]]) -> str:
    """Single swap-point for the LLM API shape (JSON mode chat-completions)."""
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content or ""


class Decomposer:
    """Calls the OpenAI reasoning tier and validates the structured response.

    ``client`` is injectable for tests; production callers pass ``None`` and an
    ``OpenAI`` client is built from the config's API key.
    """

    MAX_RETRIES = 2  # in addition to the first attempt

    def __init__(self, config: Any, client: Any | None = None) -> None:
        if not getattr(config, "openai_api_key", None):
            raise DecomposerError("config.openai_api_key is required")
        if not getattr(config, "reasoning_model", None):
            raise DecomposerError("config.reasoning_model is required")
        self.config = config
        self.prompt = PROMPT_PATH.read_text(encoding="utf-8")
        if client is None:
            from openai import OpenAI

            client = OpenAI(api_key=config.openai_api_key)
        self._client = client

    def decompose(self, spec: Spec) -> list[DecomposedTask]:
        attempts = self.MAX_RETRIES + 1
        last_err: Optional[Exception] = None
        messages = [
            {"role": "system", "content": self.prompt},
            {"role": "user", "content": _spec_to_user_message(spec)},
        ]
        for _ in range(attempts):
            try:
                raw = _call_llm(
                    self._client, model=self.config.reasoning_model, messages=messages
                )
                data = json.loads(raw)
                return DecompositionResult.model_validate(data).tasks
            except (json.JSONDecodeError, ValidationError) as e:
                last_err = e
                continue
        raise DecomposerError(
            f"decomposition failed after {attempts} attempts: {last_err}"
        )
