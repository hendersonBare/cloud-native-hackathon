"""Gateway-local response shapes for bodies that have no contract model.

These are NOT redefinitions of rapport_common.models: SPEC 7.1 returns bare JSON objects such as
{"request_id": ...} and {"accepted": true}, so each gets a tiny model to give the route a response_model
(and the frontend an OpenAPI schema).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from rapport_common.models import Org, Persona


class _Local(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Health(_Local):
    ok: bool = True
    version: str


class PersonaDirectory(_Local):
    orgs: list[Org]
    personas: list[Persona]


class RequestCreated(_Local):
    request_id: str


class EncounterCreated(_Local):
    encounter_id: str


class Accepted(_Local):
    accepted: bool = True


class ResetResult(_Local):
    ok: bool = True


class ErrorBody(_Local):
    """Shape of every error response: FastAPI's {"detail": ...}."""

    detail: str


class RumEndpoint(_Local):
    """Where the browser sends its telemetry. Field names follow the Dash0 Web SDK's `endpoint` option."""

    url: str
    authToken: str  # a public, ingest-only website token (never the backend OTLP token)
    dataset: str | None = None


class RumConfig(_Local):
    """Dash0 website monitoring settings for web/app/rum.js. `enabled: false` alone when the gateway has none."""

    enabled: bool
    serviceName: str | None = None
    serviceVersion: str | None = None
    environment: str | None = None
    endpoint: RumEndpoint | None = None
