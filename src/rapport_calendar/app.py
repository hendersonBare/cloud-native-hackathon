"""The standalone calendar app: the router, ``/healthz`` and, optionally, the static web app."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api import get_service, router
from .service import CalendarService


def create_app(service: CalendarService | None = None, web_dir: str | Path | None = None) -> FastAPI:
    """Build the app. ``service`` replaces the process-wide singleton; ``web_dir`` is served at ``/``."""
    app = FastAPI(title="Rapport calendar")
    if service is not None:
        app.dependency_overrides[get_service] = lambda: service
    app.include_router(router)

    @app.get("/healthz")
    async def healthz() -> dict[str, object]:
        return {"ok": True, "version": os.environ.get("RAPPORT_VERSION", "dev")}

    if web_dir is not None and Path(web_dir).is_dir():
        # Mounted last so it never shadows the API routes.
        app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
    return app
