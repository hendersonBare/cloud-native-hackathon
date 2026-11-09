"""HTTP client for the briefer API (SPEC 7.2). One briefer per company, found with names.briefer_url(org)."""

from __future__ import annotations

import logging
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from rapport_common import names
from rapport_common.models import (
    AskAnswer,
    AskRequest,
    BriefRequest,
    DeepDive,
    DeepDiveRequest,
    MemoryRecord,
    PersonaProfile,
    PrivateBrief,
    ResearchRequest,
    ResearchResult,
    TalkSearchResult,
)

from .errors import UpstreamError

log = logging.getLogger("rapport.gateway.briefers")

M = TypeVar("M", bound=BaseModel)
_PASS_THROUGH = {
    403: "the briefer refused this persona",
    404: "not found",
    413: "upload too large",
    415: "unsupported file type",
    422: "the briefer rejected the request",
}


class BrieferClient:
    """Thin typed wrapper; every method returns a contract model or raises UpstreamError."""

    def __init__(self, http: httpx.AsyncClient, *, timeout_s: float = 30.0) -> None:
        self._http = http
        self._timeout_s = timeout_s

    async def _call(
        self, org_id: str, method: str, path: str, model: type[M], *, timeout_s: float | None = None, **kwargs: Any
    ) -> M:
        url = f"{names.briefer_url(org_id)}{path}"
        try:
            response = await self._http.request(method, url, timeout=timeout_s or self._timeout_s, **kwargs)
        except httpx.TimeoutException as exc:
            log.warning("briefer %s %s timed out", org_id, path)
            raise UpstreamError(504, f"the {org_id} briefer timed out") from exc
        except httpx.HTTPError as exc:
            log.warning("briefer %s %s unreachable: %s", org_id, path, type(exc).__name__)
            raise UpstreamError(503, f"the {org_id} briefer is unavailable") from exc
        if response.status_code >= 400:
            log.warning("briefer %s %s answered %s", org_id, path, response.status_code)
            status = response.status_code if response.status_code in _PASS_THROUGH else 502
            raise UpstreamError(status, _PASS_THROUGH.get(status, f"the {org_id} briefer failed"))
        try:
            return model.model_validate_json(response.content)
        except ValidationError as exc:
            log.error("briefer %s %s returned an invalid body (%d errors)", org_id, path, exc.error_count())
            raise UpstreamError(502, f"the {org_id} briefer returned an invalid response") from exc

    # ---------------------------------------------------------------- SPEC 7.2
    async def brief(self, org_id: str, body: BriefRequest, *, timeout_s: float) -> PrivateBrief:
        return await self._call(
            org_id, "POST", "/v1/brief", PrivateBrief, timeout_s=timeout_s, json=body.model_dump(mode="json")
        )

    async def ask(self, org_id: str, body: AskRequest) -> AskAnswer:
        return await self._call(org_id, "POST", "/v1/ask", AskAnswer, json=body.model_dump(mode="json"))

    async def talks(self, org_id: str, persona_id: str, q: str) -> TalkSearchResult:
        return await self._call(org_id, "GET", "/v1/talks", TalkSearchResult, params={"persona_id": persona_id, "q": q})

    async def profile(self, org_id: str, persona_id: str) -> PersonaProfile:
        return await self._call(org_id, "GET", "/v1/profile", PersonaProfile, params={"persona_id": persona_id})

    async def context(
        self,
        org_id: str,
        *,
        persona_id: str,
        visibility: str,
        text: str | None,
        file: tuple[str, bytes, str] | None,
    ) -> PersonaProfile:
        """Forward the multipart upload unchanged (same field names and file bytes)."""
        data = {"persona_id": persona_id, "visibility": visibility}
        if text is not None:
            data["text"] = text
        files = {"file": file} if file is not None else None
        return await self._call(org_id, "POST", "/v1/context", PersonaProfile, data=data, files=files)

    async def remember(self, org_id: str, records: list[MemoryRecord], *, timeout_s: float) -> int:
        """POST /v1/remember. The briefer writes with names.index_for(); returns the written count."""
        url = f"{names.briefer_url(org_id)}/v1/remember"
        payload = {"records": [r.model_dump(mode="json") for r in records]}
        try:
            response = await self._http.post(url, json=payload, timeout=timeout_s)
        except httpx.HTTPError as exc:
            raise UpstreamError(503, f"the {org_id} briefer is unavailable") from exc
        if response.status_code >= 400:
            raise UpstreamError(502, f"the {org_id} briefer rejected the records")
        try:
            return int(response.json().get("written", 0))
        except (ValueError, AttributeError) as exc:
            raise UpstreamError(502, f"the {org_id} briefer returned an invalid response") from exc

    async def research(self, org_id: str, body: ResearchRequest) -> ResearchResult:
        return await self._call(org_id, "POST", "/v1/research", ResearchResult, json=body.model_dump(mode="json"))

    async def deep_dive(self, org_id: str, body: DeepDiveRequest, *, timeout_s: float) -> DeepDive:
        return await self._call(
            org_id, "POST", "/v1/deep-dive", DeepDive, timeout_s=timeout_s, json=body.model_dump(mode="json")
        )
