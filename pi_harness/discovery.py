"""Model discovery for local (OpenAI-compatible) servers and OpenAI cloud.

``list_models`` never raises and never leaks the key or raw upstream errors:
it returns ``{"models": [...], "error"?: str}``. For OpenAI it doubles as key
validation (a populated list means the key works).
"""
from __future__ import annotations

from typing import Optional

import httpx

from pi_harness.url_validation import validate_local_url

__all__ = ["list_models"]

OPENAI_MODELS_URL = "https://api.openai.com/v1/models"

# Substrings that mark a non-chat model id (embeddings, audio, image, etc.).
_BANNED = ("embedding", "whisper", "tts", "dall-e", "-audio", "-image", "moderation", "-realtime")


def _is_chat_model(model_id: str) -> bool:
    if not model_id.startswith(("gpt-", "o")):
        return False
    return not any(b in model_id for b in _BANNED)


def _ids_from_payload(payload) -> Optional[list[str]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return None
    return [m.get("id") for m in data if isinstance(m, dict) and m.get("id")]


def list_models(
    provider: str, *, base_url: Optional[str] = None, api_key: Optional[str] = None
) -> dict:
    if provider == "local":
        if not base_url:
            return {"models": [], "error": "no base_url for local discovery"}
        try:
            validate_local_url(base_url)
        except ValueError as exc:
            return {"models": [], "error": str(exc)}
        try:
            resp = httpx.get(base_url.rstrip("/") + "/models", timeout=3.0, follow_redirects=False)
            resp.raise_for_status()
            ids = _ids_from_payload(resp.json())
        except (httpx.HTTPError, ValueError):
            return {"models": [], "error": f"could not reach {base_url}"}
        if ids is None:
            return {"models": [], "error": "unexpected response shape"}
        return {"models": ids}

    if provider == "openai":
        if not api_key:
            return {"models": [], "error": "no api key provided"}
        try:
            resp = httpx.get(
                OPENAI_MODELS_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=5.0,
            )
            resp.raise_for_status()
            ids = _ids_from_payload(resp.json())
        except (httpx.HTTPError, ValueError):
            # Never echo the upstream body or the key.
            return {"models": [], "error": "invalid or unauthorized key"}
        if ids is None:
            return {"models": [], "error": "unexpected response shape"}
        return {"models": sorted(i for i in ids if _is_chat_model(i))}

    return {"models": [], "error": f"unknown provider {provider!r}"}
