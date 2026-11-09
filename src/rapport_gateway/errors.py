"""Domain errors and the helpers that turn directory lookups into clear HTTP errors."""

from __future__ import annotations

from rapport_common import names
from rapport_common.models import Persona


class GatewayError(Exception):
    """An error with an HTTP status, rendered as {"detail": ...} by the app's exception handler."""

    def __init__(self, status_code: int, detail: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.headers = headers


class UpstreamError(GatewayError):
    """A briefer (or other backend) call failed."""


class LauncherUnavailable(GatewayError):
    """Kubernetes (or the local launcher) cannot create encounters right now."""

    def __init__(self, detail: str = "encounters cannot be created: Kubernetes is not available") -> None:
        super().__init__(503, detail)


class EventRejected(Exception):
    """/internal/events refused an event (source or party checks)."""


def require_persona(persona_id: str) -> Persona:
    persona = names.personas().get(persona_id)
    if persona is None:
        raise GatewayError(404, f"unknown persona {persona_id!r}")
    return persona


def require_agent_persona(persona_id: str) -> Persona:
    """The persona must exist and belong to a company that runs a briefer (agents_enabled)."""
    persona = require_persona(persona_id)
    if not names.agents_enabled(persona.org_id):
        raise GatewayError(422, f"{persona_id} has no Rapport agent")
    return persona
