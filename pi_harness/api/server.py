"""Symphony dashboard FastAPI app.

A single-process app that mounts the spec router (Plan 7) and adds run /
corpus / guard routes plus a WebSocket event tailer. The Plan 1 ``Config`` is
loaded once at startup; dashboard-only knobs live on ``DashboardConfig`` (env).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pi_harness.config import Config, load_config
from pi_harness.spec.editor import router as spec_router


DEFAULT_FRONTEND_ORIGINS: tuple[str, ...] = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)


@dataclass(frozen=True)
class DashboardConfig:
    api_host: str = "127.0.0.1"
    api_port: int = 8800
    frontend_origins: tuple[str, ...] = DEFAULT_FRONTEND_ORIGINS


def load_dashboard_config() -> DashboardConfig:
    raw = os.environ.get("PI_HARNESS_FRONTEND_ORIGIN")
    origins: tuple[str, ...] = (
        tuple(o.strip() for o in raw.split(",") if o.strip())
        if raw
        else DEFAULT_FRONTEND_ORIGINS
    )
    return DashboardConfig(
        api_host=os.environ.get("PI_HARNESS_API_HOST", "127.0.0.1"),
        api_port=int(os.environ.get("PI_HARNESS_API_PORT", "8800")),
        frontend_origins=origins,
    )


def create_app(config: Config, dash: DashboardConfig | None = None) -> FastAPI:
    dash = dash or load_dashboard_config()
    app = FastAPI(title="Pi-Agent Harness API", version="0.1.0")
    app.state.config = config
    app.state.dashboard_config = dash
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(dash.frontend_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(spec_router)  # routes already prefixed with /specs

    from pi_harness.api.routes.runs import router as runs_router
    from pi_harness.spec.runspec import build_coordinator

    # Factory the branch route uses to build a Coordinator; overridable in tests.
    app.state.coordinator_factory = build_coordinator
    app.include_router(runs_router)

    from pi_harness.api.routes.corpus import router as corpus_router
    from pi_harness.api.routes.guards import router as guards_router
    from pi_harness.api.routes.settings import router as settings_router
    from pi_harness.api.routes.ws import router as ws_router

    app.include_router(corpus_router)
    app.include_router(guards_router)
    app.include_router(settings_router)
    app.include_router(ws_router)
    return app


def main() -> None:  # pragma: no cover
    import uvicorn

    cfg = load_config()
    dash = load_dashboard_config()
    uvicorn.run(create_app(cfg, dash), host=dash.api_host, port=dash.api_port, reload=False)


if __name__ == "__main__":  # pragma: no cover
    main()
