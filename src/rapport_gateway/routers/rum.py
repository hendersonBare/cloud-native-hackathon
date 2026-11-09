"""GET /api/rum-config: the Dash0 website-monitoring settings the web page reads at load time (web/app/rum.js).

The values come from the optional `dash0-rum` Secret, so no token is committed to git. Everything here is sent to
every browser that opens the page: only a separate, ingest-only website token belongs in that Secret.
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from ..schemas import RumConfig, RumEndpoint
from .guards import DepsDep

router = APIRouter(tags=["telemetry"])

SERVICE_NAME = "rapport-web"


@router.get(
    "/api/rum-config",
    response_model=RumConfig,
    response_model_exclude_none=True,
    summary="Dash0 website monitoring settings for the web page",
)
async def rum_config(deps: DepsDep, response: Response) -> RumConfig:
    response.headers["Cache-Control"] = "no-store"  # a rotated token takes effect on the next page load
    settings = deps.settings
    if not (settings.rum_endpoint and settings.rum_auth_token):
        return RumConfig(enabled=False)
    return RumConfig(
        enabled=True,
        serviceName=SERVICE_NAME,
        serviceVersion=settings.version,
        environment=settings.environment,
        endpoint=RumEndpoint(
            url=settings.rum_endpoint,
            authToken=settings.rum_auth_token,
            dataset=settings.rum_dataset,
        ),
    )
