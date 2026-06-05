"""HTTP surface for the model picker.

GET  /settings/models                 → current HarnessSettings
PUT  /settings/models                 → update + persist; side-effects pi's
                                        models.json when local is selected
GET  /settings/models/local-models    → query the user's local OpenAI-compatible
                                        server's /v1/models for the dropdown
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Literal
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from pi_harness.agent_wrapper import LOCAL_PROVIDER_NAME
from pi_harness.pi_models import ensure_pi_provider
from pi_harness.settings import (
    BucketConfig,
    HarnessSettings,
    load_settings,
    save_settings,
)

router = APIRouter(prefix="/settings/models", tags=["settings"])


def validate_local_url(url: str) -> str:
    """Return ``url`` if it safely points at a loopback/private model server,
    else raise ValueError.

    'Local model server' means localhost or a LAN host. Accepting an arbitrary
    URL here is SSRF: an attacker could make the dashboard fetch internal
    services or cloud metadata (169.254.169.254). We require http(s) and that
    EVERY resolved address is loopback or RFC1918-private — never link-local
    (which would include the metadata endpoint), multicast, or global (audit
    #6/#23)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("local model URL must use http or https")
    host = parsed.hostname
    if not host:
        raise ValueError("local model URL has no host")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValueError(f"cannot resolve host {host!r}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_unspecified:
            raise ValueError("local model URL resolves to an unspecified address")
        if ip.is_loopback:
            continue  # 127.0.0.0/8 and ::1 are always fine
        # Block link-local explicitly — it covers the cloud metadata endpoint
        # (169.254.169.254) and is otherwise treated as 'private' by ipaddress.
        if ip.is_link_local:
            raise ValueError("local model URL resolves to a link-local address (blocked)")
        if not ip.is_private:
            raise ValueError(
                "local model URL must point at a loopback or private (LAN) address"
            )
    return url


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
def put_settings(body: SettingsBody) -> SettingsBody:
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
