"""POST /api/context (CV or notes upload) and GET /api/profile."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile

from rapport_common.models import PersonaProfile, Visibility

from ..errors import GatewayError, require_agent_persona
from .guards import DepsDep, LlmLimited

router = APIRouter(prefix="/api", tags=["profile"])
ALLOWED_SUFFIXES = {".pdf", ".md", ".txt"}
MAX_TEXT_CHARS = 200_000


@router.post(
    "/context",
    response_model=PersonaProfile,
    dependencies=[LlmLimited],
    summary="Upload a CV or notes (multipart); returns the person's structured profile",
    responses={
        404: {"description": "unknown persona"},
        413: {"description": "file over 2 MB"},
        415: {"description": "file is not .pdf, .md or .txt"},
        422: {"description": "neither file nor text, or the persona has no agent"},
        429: {"description": "rate limited (Retry-After header)"},
    },
)
async def upload_context(
    deps: DepsDep,
    persona_id: Annotated[str, Form()],
    visibility: Annotated[Visibility, Form()],
    file: Annotated[UploadFile | None, File()] = None,
    text: Annotated[str | None, Form()] = None,
) -> PersonaProfile:
    require_agent_persona(persona_id)
    content: tuple[str, bytes, str] | None = None
    if file is not None and file.filename:
        suffix = PurePosixPath(file.filename).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise GatewayError(415, "only .pdf, .md and .txt files are accepted")
        data = await file.read(deps.settings.max_upload_bytes + 1)
        if len(data) > deps.settings.max_upload_bytes:
            raise GatewayError(413, f"file is larger than {deps.settings.max_upload_bytes // (1024 * 1024)} MB")
        content = (file.filename, data, file.content_type or "application/octet-stream")
    if text is not None and len(text) > MAX_TEXT_CHARS:
        raise GatewayError(413, "text is too long")
    if content is None and not (text and text.strip()):
        raise GatewayError(422, "send a file and/or text")
    return await deps.backend.upload_context(persona_id, visibility, text or None, content)


@router.get(
    "/profile",
    response_model=PersonaProfile,
    summary="A person's shareable and private profile",
    responses={404: {"description": "unknown persona"}, 422: {"description": "the persona has no agent"}},
)
async def get_profile(deps: DepsDep, persona_id: Annotated[str, Query()]) -> PersonaProfile:
    return await deps.backend.profile(persona_id)
