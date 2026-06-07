"""Observability deep-link endpoint.

GET /observability/link?run_id=<id> returns a runtime-resolved tokenized
deep-link into the fork observability UI. The real token/host/port are resolved
from the Plan 1 ``Config`` on ``app.state.config`` (not build-time NEXT_PUBLIC_*
env), so the frontend always points at the live server.
"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/observability/link")
def observability_link(run_id: str, request: Request) -> dict:
    cfg = request.app.state.config
    base = cfg.obs_server_url.rstrip("/")
    token = cfg.obs_auth_token
    frag = f"#view=race&pool={quote(run_id)}&hide_after=never&show_hidden=1"
    url = f"{base}/?token={quote(token)}{frag}" if token else f"{base}/{frag}"
    return {"enabled": cfg.obs_enabled, "base": base, "url": url}
