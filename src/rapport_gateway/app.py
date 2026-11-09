"""App factories: the public app (port 8080) and the cluster-only internal app (port 8081)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send

from rapport_calendar.api import get_service as calendar_service
from rapport_calendar.api import router as calendar_router
from rapport_speakers.api import make_public_router as make_speakers_router
from rapport_venue import api as venue

from .deps import Deps, build_deps
from .errors import GatewayError
from .routers import connect, demo, discover, health, memory, personas, profile, rum, stream
from .settings import Settings

log = logging.getLogger("rapport.gateway.app")

DESCRIPTION = (
    "Rapport gateway: the only API the web page talks to. REST for actions, Server-Sent Events "
    "(/api/stream) for everything that happens. Frontend reference: docs/API.md."
)
TAGS = [
    {"name": "health", "description": "Liveness and deployed version."},
    {"name": "personas", "description": "The conference directory."},
    {"name": "stream", "description": "Server-Sent Events for a phone or the swarm panel."},
    {"name": "profile", "description": "CV / notes upload and the structured profile."},
    {"name": "connect", "description": "Connect requests and accept (creates the Encounter)."},
    {"name": "memory", "description": "Ask your agent; search the agenda."},
    {"name": "discover", "description": "Research cards, swipe, deep dive, the agent's decision."},
    {"name": "demo", "description": "Reset in-memory demo state."},
    {"name": "calendar", "description": "Conference-week calendar and meeting scheduling (src/rapport_calendar)."},
    {"name": "speakers", "description": "Who said what in conference talks, read-only (src/rapport_speakers)."},
    {"name": "venue", "description": "Find a person at the venue: floor plan, location sharing, directions."},
    {"name": "telemetry", "description": "Dash0 website monitoring settings for the web page."},
]


class _WebFiles(StaticFiles):
    """StaticFiles that answers 404 (not 405) to anything but GET/HEAD, so unknown POSTs look like unknown paths."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] not in ("GET", "HEAD"):
            await JSONResponse({"detail": "Not Found"}, status_code=404)(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(GatewayError)
    async def gateway_error(_: Request, exc: GatewayError) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)


def create_app(settings: Settings | None = None, deps: Deps | None = None) -> FastAPI:
    """The public app. Pass `deps` (fakes for the store/HTTP/Kubernetes pieces) in tests."""
    settings = settings or Settings.from_env()
    deps = deps or build_deps(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await deps.start()
        try:
            yield
        finally:
            await deps.stop()

    app = FastAPI(
        title="Rapport gateway",
        version=settings.version,
        description=DESCRIPTION,
        openapi_tags=TAGS,
        lifespan=lifespan,
    )
    app.state.deps = deps
    _register_error_handlers(app)

    if settings.cors_origins:  # same-origin only when unset; never a wildcard with credentials
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],  # the calendar edits and deletes
            allow_headers=["Content-Type", "Authorization", "X-Venue-Token"],  # X-Venue-Token: venue reads
        )

    for module in (health, personas, stream, profile, connect, memory, discover, demo, venue, rum):
        app.include_router(module.router)
    app.include_router(calendar_router)
    if deps.calendar is not None:  # this app's own instance, so tests and reset never share module state
        calendar = deps.calendar
        app.dependency_overrides[calendar_service] = lambda: calendar
    # Read-only search only. Erasure (make_admin_router) is not mounted on either port: the internal port admits
    # delegate pods, so voice data is erased with the CLI (python -m rapport_speakers.cli).
    if deps.speakers is not None:
        app.include_router(make_speakers_router(deps.speakers.search), prefix="/api/speakers")

    @app.api_route("/internal/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    async def no_internal(path: str) -> JSONResponse:
        """/internal/* exists only on the cluster-only port; the public port never serves it."""
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    if settings.web_dir is not None and settings.web_dir.is_dir():  # mounted last, after every API route
        app.mount("/", _WebFiles(directory=settings.web_dir, html=True), name="web")
    else:
        log.warning("web directory not found; serving the API only")
    return app


def create_internal_app(deps: Deps) -> FastAPI:
    """Served only on the internal port (names.GATEWAY_INTERNAL_PORT): POST /internal/events."""
    from . import internal

    app = FastAPI(title="Rapport gateway (internal)", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.deps = deps
    _register_error_handlers(app)
    app.include_router(internal.router)
    return app
