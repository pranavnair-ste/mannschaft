"""Idempotent upserts into pi's provider registry at ``~/.pi/agent/models.json``.

pi (the executor) only honors ``--provider X --model Y`` if provider X is
declared in its own models.json. When the user picks Local in the harness
Settings UI, we register a provider entry there pointing at their local
OpenAI-compatible server (Ollama, LM Studio, vLLM, ...).

This is a *sidecar* — the harness owns the entry it writes but leaves all
other providers in the file alone. The file is shared with pi's own
package-manager tools, so the upsert is intentionally surgical.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Iterable

# Qwen thinking models (e.g. Qwen3.6) default to thinking ON at the server.
# pi only sends the disabling param (`chat_template_kwargs.enable_thinking`)
# when the model entry declares `reasoning` + the qwen chat-template compat; we
# stamp those on managed Qwen entries so `pi --thinking off` actually works.
_QWEN_RE = re.compile(r"qwen", re.IGNORECASE)


def _thinking_fields(model_id: str) -> dict:
    """Thinking-control fields for a model id, or {} if not a Qwen model."""
    if _QWEN_RE.search(model_id or ""):
        return {"reasoning": True, "compat": {"thinkingFormat": "qwen-chat-template"}}
    return {}

__all__ = [
    "DEFAULT_PI_MODELS_PATH",
    "ensure_pi_provider",
    "ensure_local_provider_from_settings",
]


def DEFAULT_PI_MODELS_PATH() -> Path:  # function so tests can monkeypatch home
    return Path.home() / ".pi" / "agent" / "models.json"


def _load(path: Path) -> dict:
    if not path.exists():
        return {"providers": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not a JSON object")
    except (json.JSONDecodeError, ValueError, OSError):
        # Garbled file: better to overwrite with our entry than refuse to save.
        # Trade-off documented in tests/test_pi_models.py.
        return {"providers": {}}
    data.setdefault("providers", {})
    if not isinstance(data["providers"], dict):
        data["providers"] = {}
    return data


def _new_model_entry(model_id: str) -> dict:
    entry = {
        "id": model_id,
        "name": model_id,
        "contextWindow": 32768,
        "maxTokens": 4096,
        "input": ["text"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
    }
    entry.update(_thinking_fields(model_id))
    return entry


def ensure_pi_provider(
    *,
    name: str,
    base_url: str,
    model_ids: Iterable[str],
    pi_models_path: Path | str | None = None,
) -> None:
    """Idempotently upsert a provider entry into pi's models.json.

    On the entry we manage:
        - ``baseUrl`` is set to ``base_url`` (overwritten if changed).
        - ``api`` is set to ``"openai-completions"`` (the lingua franca for
          Ollama, LM Studio, vLLM).
        - ``apiKey`` is left untouched if present, else set to ``"local"``
          (most local servers don't validate, but pi requires a non-empty
          string).
        - Each id in ``model_ids`` is added to ``models[]`` if not already
          present; existing models keep their existing config.
    Other providers in the file are not touched.
    """
    path = Path(pi_models_path) if pi_models_path is not None else DEFAULT_PI_MODELS_PATH()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = _load(path)
    provider = data["providers"].get(name, {})
    provider["baseUrl"] = base_url
    provider.setdefault("apiKey", "local")
    provider["api"] = "openai-completions"

    existing_models = provider.get("models") or []
    existing_ids = {m.get("id") for m in existing_models if isinstance(m, dict)}
    for model_id in model_ids:
        if model_id not in existing_ids:
            existing_models.append(_new_model_entry(model_id))
            existing_ids.add(model_id)
    # Stamp thinking-control fields on every managed entry (incl. ones written
    # before this existed) so `pi --thinking off` disables Qwen reasoning. This
    # is the harness-owned provider, so setting these is safe.
    for m in existing_models:
        if isinstance(m, dict):
            m.update(_thinking_fields(m.get("id", "")))
    provider["models"] = existing_models

    data["providers"][name] = provider
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def ensure_local_provider_from_settings(
    settings=None, *, pi_models_path: Path | str | None = None
) -> bool:
    """If any bucket selects ``local``, register the harness-local provider in
    pi's models.json so a run works without first opening the Settings UI.

    Returns True iff a registration was performed. This is the launch-path
    counterpart to the Settings-UI side effect in ``api/routes/settings.py``.
    """
    from pi_harness.agent_wrapper import LOCAL_PROVIDER_NAME
    from pi_harness.settings import load_settings

    s = settings if settings is not None else load_settings()
    local_models = [
        b.model for b in (s.orchestrator, s.builder) if b.provider == "local"
    ]
    if not local_models:
        return False
    ensure_pi_provider(
        name=LOCAL_PROVIDER_NAME,
        base_url=s.local_base_url,
        model_ids=local_models,
        pi_models_path=pi_models_path,
    )
    return True
