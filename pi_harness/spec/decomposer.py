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
    """Calls the reasoning tier (local-first) and validates the structured
    response.

    Provider/model come from the reasoning (orchestrator) bucket in
    HarnessSettings — ``local`` by default (no key), or ``api`` (requires
    ``OPENAI_API_KEY``). ``client``/``settings`` are injectable for tests;
    production callers pass ``None`` and a client is built from the bucket.
    """

    MAX_RETRIES = 2  # in addition to the first attempt

    def __init__(self, config: Any, client: Any | None = None, settings: Any | None = None) -> None:
        from pi_harness.llm_direct import reasoning_client_and_model

        self.config = config
        self.prompt = PROMPT_PATH.read_text(encoding="utf-8")
        if client is not None:
            # Injected client (tests): resolve the model from settings only.
            from pi_harness.settings import load_settings

            s = settings if settings is not None else load_settings()
            self.model = s.orchestrator.model
            self._client = client
        else:
            self._client, self.model = reasoning_client_and_model(config, settings)

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
                    self._client, model=self.model, messages=messages
                )
                data = json.loads(raw)
                return DecompositionResult.model_validate(data).tasks
            except (json.JSONDecodeError, ValidationError) as e:
                last_err = e
                continue
        raise DecomposerError(
            f"decomposition failed after {attempts} attempts: {last_err}"
        )
