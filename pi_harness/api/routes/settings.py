"""HTTP surface for the model picker.

GET  /settings/models                 → current HarnessSettings
PUT  /settings/models                 → update + persist; side-effects pi's
                                        models.json when local is selected
GET  /settings/models/local-models    → query the user's local OpenAI-compatible
                                        server's /v1/models for the dropdown
"""
from __future__ import annotations

from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from pi_harness import discovery, keystore
from pi_harness.agent_wrapper import LOCAL_PROVIDER_NAME
from pi_harness.pi_models import ensure_pi_provider
from pi_harness.settings import (
    BucketConfig,
    HarnessSettings,
    load_settings,
    save_settings,
)
from pi_harness.trajectory.runs import query_run_summaries
from pi_harness.url_validation import validate_local_url  # re-exported; tests import it here

# Two routers: the existing model picker (prefix /settings/models) and a sibling
# for account-level settings (PUT /settings/key, GET /settings/run-active) that
# cannot hang off the /settings/models prefix.
router = APIRouter(prefix="/settings/models", tags=["settings"])
root_router = APIRouter(prefix="/settings", tags=["settings"])


def _active_run_id(db_path) -> str | None:
    """The single source of truth for the idle gate (shared with the CLI)."""
    rows = query_run_summaries(status="running", limit=1, db_path=db_path)
    return rows[0].run_id if rows else None


class BucketBody(BaseModel):
    provider: Literal["api", "local"]
    model: str = Field(..., min_length=1)


class SettingsBody(BaseModel):
    orchestrator: BucketBody
    builder: BucketBody
    local_base_url: str = Field(..., min_length=1)

    @field_validator("local_base_url")
    @classmethod
    def _trim(cls, v: str) -> str:
        return v.strip().rstrip("/")


@router.get("", response_model=SettingsBody)
def get_settings() -> SettingsBody:
    s = load_settings()
    return SettingsBody(
        orchestrator=BucketBody(provider=s.orchestrator.provider, model=s.orchestrator.model),
        builder=BucketBody(provider=s.builder.provider, model=s.builder.model),
        local_base_url=s.local_base_url,
    )


@router.put("", response_model=SettingsBody)
def put_settings(body: SettingsBody, request: Request) -> SettingsBody:
    # Idle gate: never switch models while a run is building (agent_wrapper reads
    # settings per agent spawn, so a mid-run change would inconsistently affect
    # later-spawned agents). Backend-authoritative (spec §6).
    active = _active_run_id(request.app.state.config.trajectory_db_path)
    if active:
        raise HTTPException(
            status_code=409,
            detail=f"run {active} is active; stop it before switching models",
        )

    settings = HarnessSettings(
        orchestrator=BucketConfig(provider=body.orchestrator.provider, model=body.orchestrator.model),
        builder=BucketConfig(provider=body.builder.provider, model=body.builder.model),
        local_base_url=body.local_base_url,
    )

    # If any bucket is local, the local_base_url will be persisted AND handed to
    # pi as a provider base_url — so validate it as a safe loopback/LAN target
    # BEFORE saving, never persisting an SSRF-able URL (audit #23). An api-only
    # config may carry a harmless default local_base_url, so only check then.
    local_models = [
        b.model
        for b in (settings.orchestrator, settings.builder)
        if b.provider == "local"
    ]
    if local_models:
        try:
            validate_local_url(settings.local_base_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    save_settings(settings)

    # Side effect: register the provider entry in pi's models.json so
    # `pi --provider <LOCAL_PROVIDER_NAME>` works.
    if local_models:
        ensure_pi_provider(
            name=LOCAL_PROVIDER_NAME,
            base_url=settings.local_base_url,
            model_ids=local_models,
        )

    return body


@router.get("/local-models")
def discover_local_models(base_url: str = Query(...)) -> dict:
    """Query the user's local OpenAI-compatible server at <base_url>/models
    and return the model id list. Returns {models: [], error: ...} on failure
    so the UI can render a hint instead of a generic 500."""
    # SSRF guard: only fetch loopback/private targets, never arbitrary URLs
    # (audit #6). A bad/blocked URL is a 400, not a silent server-side fetch.
    try:
        validate_local_url(base_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    url = base_url.rstrip("/") + "/models"
    try:
        resp = httpx.get(url, timeout=3.0, follow_redirects=False)
        resp.raise_for_status()
        payload = resp.json()
    except (httpx.HTTPError, ValueError):
        # Don't echo the raw exception (could leak internal network detail).
        return {"models": [], "error": f"could not reach {base_url}"}

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return {"models": [], "error": f"unexpected response shape from {url}"}
    ids = [m.get("id") for m in data if isinstance(m, dict) and m.get("id")]
    return {"models": ids}


@router.get("/cloud-models")
def discover_cloud_models(provider: str = Query("openai")) -> dict:
    """List the models the stored key unlocks. Opt-in: requires a stored key
    (no auto-phone-home — preserves the air-gap default)."""
    key = keystore.get_key(provider)
    if not key:
        return {"models": [], "error": "no key stored for this provider"}
    return discovery.list_models(provider, api_key=key)


class KeyBody(BaseModel):
    provider: Literal["openai"]
    api_key: str = Field(..., min_length=1)


@root_router.put("/key")
def put_key(body: KeyBody) -> dict:
    """Validate the key by listing models, store it (chmod-600), return the
    masked form + discovered models. The raw key is NEVER echoed."""
    result = discovery.list_models(body.provider, api_key=body.api_key)
    if result.get("error") or not result.get("models"):
        raise HTTPException(status_code=400, detail="invalid or unauthorized key")
    keystore.set_key(body.provider, body.api_key)
    return {"ok": True, "masked": keystore.mask(body.api_key), "models": result["models"]}


@root_router.get("/run-active")
def get_run_active(request: Request) -> dict:
    active = _active_run_id(request.app.state.config.trajectory_db_path)
    return {"active": bool(active), "run_id": active}
