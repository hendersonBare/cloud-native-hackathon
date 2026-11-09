"""POST /api/research and POST /api/swipe (Discover, docs/FEATURE-DISCOVER.md)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from rapport_common.models import ResearchRequest, ResearchResult, SwipeBody

from ..schemas import Accepted
from .guards import DepsDep, LlmLimited, check_llm_limit

router = APIRouter(prefix="/api", tags=["discover"])


@router.post(
    "/research",
    response_model=ResearchResult,
    dependencies=[LlmLimited],
    summary="Swipe cards for the viewer, ranked by the viewer's own agent",
    responses={404: {"description": "unknown persona"}, 429: {"description": "rate limited"}},
)
async def research(body: ResearchRequest, deps: DepsDep) -> ResearchResult:
    return await deps.backend.research(body)


@router.post(
    "/swipe",
    status_code=202,
    response_model=Accepted,
    summary="Left: remember the skip. Right: deep dive, then the agent decides (results arrive on the stream)",
    responses={404: {"description": "unknown persona"}, 429: {"description": "rate limited (right swipes)"}},
)
async def swipe(body: SwipeBody, request: Request, deps: DepsDep) -> Accepted:
    if body.direction == "right":  # a right swipe spends LLM credits (deep dive)
        check_llm_limit(request, deps)
    await deps.backend.swipe(body)
    return Accepted()
