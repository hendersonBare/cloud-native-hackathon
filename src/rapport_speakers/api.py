"""FastAPI routers for speaker search (spec §6) and a standalone app for local runs.

How the gateway mounts it (the gateway workstream owns that change):

    from rapport_speakers.api import make_admin_router, make_public_router
    from rapport_speakers.runtime import build_runtime

    rt = build_runtime()                                   # ES when ES_URL + a key are set, else fixtures
    public_app.include_router(make_public_router(rt.search), prefix="/api/speakers")    # port 8080
    internal_app.include_router(make_admin_router(rt.pipeline), prefix="/internal/speakers")  # port 8081 only

The public router is read-only and returns transcript text, names of consenting speakers and timestamps.
It never returns vectors. Erasure is on the admin router, which must only be mounted on the cluster-only port.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, FastAPI, Path as PathParam, Query
from fastapi.responses import FileResponse

from rapport_common import telemetry

from .models import EraseResult, SearchResult, SpeakerUtterances, TopSpeakersResult
from .pipeline import Pipeline
from .search import MAX_SIZE, SpeakerSearch

UI_PATH = Path(__file__).parent / "ui.html"
ID_PATTERN = r"^[A-Za-z0-9._-]{1,80}$"
Q = Annotated[str, Query(max_length=200)]
Size = Annotated[int, Query(ge=1, le=MAX_SIZE)]


def make_public_router(search: SpeakerSearch) -> APIRouter:
    router = APIRouter(tags=["speakers"])

    @router.get("/search", response_model=SearchResult, summary="Who said what: hybrid search over talk transcripts")
    async def search_endpoint(
        q: Q = "",
        speaker: Annotated[str | None, Query(max_length=80, description="person ID or name")] = None,
        session: Annotated[str | None, Query(pattern=ID_PATTERN)] = None,
        size: Size = 5,
    ) -> SearchResult:
        return await asyncio.to_thread(search.search, q, speaker=speaker, session=session, size=size)

    @router.get("/speakers/{speaker}/utterances", response_model=SpeakerUtterances,
                summary="Everything one speaker said, by time")
    async def speaker_utterances(
        speaker: Annotated[str, PathParam(max_length=80)], size: Size = MAX_SIZE,
    ) -> SpeakerUtterances:
        return await asyncio.to_thread(search.speaker_utterances, speaker, size=size)

    @router.get("/top-speakers", response_model=TopSpeakersResult, summary="Who talked most about a topic")
    async def top_speakers(q: Q = "", size: Annotated[int, Query(ge=1, le=MAX_SIZE)] = 10) -> TopSpeakersResult:
        return await asyncio.to_thread(search.top_speakers, q, size=size)

    @router.get("/ui", include_in_schema=False)
    async def ui() -> FileResponse:
        # A fixed file shipped with the package; no request data reaches it.
        return FileResponse(UI_PATH, media_type="text/html; charset=utf-8")

    return router


def make_admin_router(pipeline: Pipeline) -> APIRouter:
    """Mount on the cluster-only internal app (port 8081), never on the public port."""
    router = APIRouter(tags=["speakers-admin"])

    @router.delete("/people/{person_id}", response_model=EraseResult, summary="Erase a person's voice data (§8)")
    async def erase(person_id: Annotated[str, PathParam(pattern=ID_PATTERN)]) -> EraseResult:
        return await asyncio.to_thread(pipeline.erase_person, person_id)

    return router


def create_app(search: SpeakerSearch | None = None) -> FastAPI:
    """Standalone public app for local runs: /healthz plus the read-only router under /api/speakers."""
    if search is None:
        from .runtime import build_runtime

        search = build_runtime().search
    app = FastAPI(title="Rapport speakers", description="Who said what at the conference (speaker identification).")
    telemetry.init_telemetry("rapport-speakers", fastapi_app=app)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True}

    app.include_router(make_public_router(search), prefix="/api/speakers")
    return app
