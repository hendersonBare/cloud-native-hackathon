"""The briefer's HTTP surface (SPEC 7.2). Routes only: each handler validates, delegates to a feature module and
returns a contract model. Dependencies (store, LLM) are injected into `create_app` so tests and local runs can swap
in fakes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from rapport_common import names
from rapport_common.interfaces import MemoryStore
from rapport_common.models import (
    AskAnswer,
    AskRequest,
    BriefRequest,
    DeepDive,
    DeepDiveRequest,
    PersonaProfile,
    PrivateBrief,
    ResearchRequest,
    ResearchResult,
    TalkSearchResult,
    Visibility,
)

from . import ask, brief, context, deep_dive, research, talks
from .core import Briefer
from .llm import LLM, OpenAILLM
from .schemas import Health, RememberRequest, Written

log = logging.getLogger("rapport.briefer")


def create_app(org_id: str, store: MemoryStore, llm: LLM | None = None) -> FastAPI:
    if org_id not in names.orgs():
        raise ValueError(f"unknown org {org_id!r}")
    b = Briefer(org_id=org_id, store=store, llm=llm or OpenAILLM())
    app = FastAPI(title=f"Rapport briefer ({org_id})", version="1")
    app.state.briefer = b

    @app.exception_handler(Exception)
    async def _unexpected(_request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled error (%s)", type(exc).__name__)
        return JSONResponse(status_code=500, content={"detail": "internal error"})

    health = APIRouter(tags=["health"])
    memory = APIRouter(prefix="/v1", tags=["memory"])
    assistant = APIRouter(prefix="/v1", tags=["assistant"])
    profile = APIRouter(prefix="/v1", tags=["profile"])
    discover = APIRouter(prefix="/v1", tags=["discover"])

    @health.get("/healthz", response_model=Health)
    async def healthz() -> Health:
        return Health()

    # ------------------------------------------------------------------ memory
    @memory.post("/remember", response_model=Written)
    async def remember(body: RememberRequest) -> Written:
        # Never write for another company, and never into the shared conference index: talks and attendee cards
        # route there (names.index_for) and every company's Discover deck trusts them, so a briefer must not forge them.
        mine = [r for r in body.records if r.org_id == b.org_id and names.index_for(r) != names.CONFERENCE_INDEX]
        skipped = len(body.records) - len(mine)
        if skipped:
            log.warning("remember skipped %d record(s) of another org or for the conference index", skipped)
        return Written(written=await b.write(mine) if mine else 0)

    # ------------------------------------------------------------------ assistant
    @assistant.get("/talks", response_model=TalkSearchResult)
    async def get_talks(persona_id: str, q: str = "") -> TalkSearchResult:
        return await talks.search_talks(b, persona_id, q)

    @assistant.post("/ask", response_model=AskAnswer)
    async def post_ask(body: AskRequest) -> AskAnswer:
        return await ask.answer(b, body)

    @assistant.post("/brief", response_model=PrivateBrief)
    async def post_brief(body: BriefRequest) -> PrivateBrief:
        return await brief.make_brief(b, body)

    # ------------------------------------------------------------------ profile / personal context
    @profile.post("/context", response_model=PersonaProfile)
    async def post_context(
        persona_id: str = Form(...),
        visibility: Visibility = Form(...),
        file: UploadFile | None = File(default=None),
        text: str | None = Form(default=None),
    ) -> PersonaProfile:
        b.own(persona_id)  # 404/403 before reading the upload
        data: bytes | None = None
        filename = None
        if file is not None and (file.filename or file.size):
            data = await file.read(context.MAX_UPLOAD_BYTES + 1)
            filename = file.filename
            if len(data) > context.MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="file is larger than 2 MB")
        if text is not None and len(text.encode("utf-8")) > context.MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="text is larger than 2 MB")
        return await context.ingest(b, persona_id, visibility, filename=filename, data=data, text=text)

    @profile.get("/profile", response_model=PersonaProfile)
    async def get_profile(persona_id: str) -> PersonaProfile:
        return await context.get_profile(b, persona_id)

    # ------------------------------------------------------------------ discover
    @discover.post("/research", response_model=ResearchResult)
    async def post_research(body: ResearchRequest) -> ResearchResult:
        return await research.research(b, body)

    @discover.post("/deep-dive", response_model=DeepDive)
    async def post_deep_dive(body: DeepDiveRequest) -> DeepDive:
        return await deep_dive.deep_dive(b, body)

    for router in (health, memory, assistant, profile, discover):
        app.include_router(router)
    return app
