"""POST /api/ask and GET /api/talks: proxied to the person's own briefer."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from rapport_common.models import AskAnswer, AskRequest, TalkSearchResult

from .guards import DepsDep, LlmLimited

router = APIRouter(prefix="/api", tags=["memory"])


@router.post(
    "/ask",
    response_model=AskAnswer,
    dependencies=[LlmLimited],
    summary="Ask your agent a question about your company's memory (with citations)",
    responses={404: {"description": "unknown persona"}, 429: {"description": "rate limited"}},
)
async def ask(body: AskRequest, deps: DepsDep) -> AskAnswer:
    return await deps.backend.ask(body)


@router.get(
    "/talks",
    response_model=TalkSearchResult,
    summary="Search the conference agenda for a person",
    responses={404: {"description": "unknown persona"}},
)
async def talks(
    deps: DepsDep,
    persona_id: Annotated[str, Query()],
    q: Annotated[str, Query(max_length=200)] = "",
) -> TalkSearchResult:
    return await deps.backend.talks(persona_id, q)
