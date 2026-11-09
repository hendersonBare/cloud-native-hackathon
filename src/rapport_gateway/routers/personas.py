"""GET /api/personas."""

from __future__ import annotations

from fastapi import APIRouter

from rapport_common import names

from ..schemas import PersonaDirectory

router = APIRouter(prefix="/api", tags=["personas"])


@router.get("/personas", response_model=PersonaDirectory, summary="The conference directory: companies and people")
async def list_personas() -> PersonaDirectory:
    return PersonaDirectory(orgs=list(names.orgs().values()), personas=list(names.personas().values()))
