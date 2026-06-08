"""Build an OpenAI-SDK client for the two *direct* LLM call sites.

The decomposer (`spec/decomposer.py`) and the improve-agent (`improve/agent.py`)
call ``chat.completions.create`` directly (not through pi/ClawTeam), so they
need their own client. Both must honor the **sovereign local default**: when
the reasoning bucket is ``local`` they point at the local OpenAI-compatible
endpoint with no key; only an explicit ``api`` bucket requires ``OPENAI_API_KEY``.

This is the direct-call-site counterpart to ``agent_wrapper._resolve_provider_model``
(which serves the pi/ClawTeam path).
"""
from __future__ import annotations

from typing import Any, Tuple

from pi_harness.config import ConfigError
from pi_harness.settings import HarnessSettings, load_settings

__all__ = ["reasoning_client_and_model"]


def reasoning_client_and_model(
    config: Any, settings: HarnessSettings | None = None
) -> Tuple[Any, str]:
    """Return ``(openai_client, model_id)`` for the reasoning (orchestrator)
    bucket, honoring local-vs-api.

    Raises:
        ConfigError: if the bucket has no model, or selects ``api`` without
            ``OPENAI_API_KEY``.
    """
    s = settings if settings is not None else load_settings()
    bucket = s.orchestrator
    model = bucket.model
    if not model:
        raise ConfigError("reasoning bucket has no model configured")

    from openai import OpenAI

    if bucket.provider == "local":
        # Local OpenAI-compatible servers (mlx_lm.server, vLLM, …) don't
        # validate the key, but the SDK requires a non-empty string.
        return OpenAI(base_url=s.local_base_url, api_key="local"), model

    key = (getattr(config, "openai_api_key", "") or "").strip()
    if not key:
        raise ConfigError(
            "the reasoning bucket uses the 'api' provider but OPENAI_API_KEY is "
            "unset. Set it, or switch the bucket to 'local' (the sovereign default)."
        )
    return OpenAI(api_key=key), model
