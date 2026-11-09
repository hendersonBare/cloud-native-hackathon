"""Shared route dependencies: the deps container, the LLM rate limit and the admin token."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Header, Request

from ..deps import Deps
from ..errors import GatewayError
from ..ratelimit import client_ip, too_many


def get_deps(request: Request) -> Deps:
    return request.app.state.deps


DepsDep = Annotated[Deps, Depends(get_deps)]


def check_llm_limit(request: Request, deps: Deps) -> None:
    """At most settings.llm_calls_per_minute LLM-backed calls per client IP per minute (429 + Retry-After)."""
    wait = deps.llm_limiter.hit(client_ip(request))
    if wait > 0:
        raise too_many(wait, "too many requests; slow down")


def llm_limited(request: Request, deps: DepsDep) -> None:
    check_llm_limit(request, deps)


LlmLimited = Depends(llm_limited)


def require_admin(deps: DepsDep, authorization: Annotated[str | None, Header()] = None) -> None:
    """When RAPPORT_ADMIN_TOKEN is set, Authorization: Bearer <token> is required (401 missing, 403 wrong)."""
    token = deps.settings.admin_token
    if not token:
        return
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not supplied:
        raise GatewayError(401, "admin token required", headers={"WWW-Authenticate": "Bearer"})
    if not secrets.compare_digest(supplied.strip().encode(), token.encode()):
        raise GatewayError(403, "invalid admin token")
