"""python -m rapport_briefer: one briefer for the company in RAPPORT_ORG_ID, on 0.0.0.0:$PORT (default 8080)."""

from __future__ import annotations

import logging
import os

import uvicorn

from rapport_common import names
from rapport_common.interfaces import InMemoryStore, MemoryStore
from rapport_common.telemetry import init_telemetry

from .app import create_app

log = logging.getLogger("rapport.briefer")


def build_store(org_id: str) -> MemoryStore:
    indices = [names.shareable_index(org_id), names.internal_index(org_id), names.CONFERENCE_INDEX]
    try:
        from rapport_memory import store_from_env  # lands in the memory PR; imported late on purpose

        return store_from_env(indices)
    except Exception as exc:  # not merged yet, or misconfigured: still start, with nothing in it
        log.warning(
            "rapport_memory.store_from_env unavailable (%s); starting with an empty in-memory store", type(exc).__name__
        )
        return InMemoryStore()


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    org_id = os.environ.get("RAPPORT_ORG_ID", "")
    if org_id not in names.orgs():
        raise SystemExit(f"RAPPORT_ORG_ID must be one of {sorted(names.orgs())}, got {org_id!r}")
    app = create_app(org_id, build_store(org_id))
    init_telemetry("rapport-briefer", org_id=org_id, fastapi_app=app)
    # A pod must listen on every interface to be reachable by its Service (house rule: 0.0.0.0:8080). Ingress is
    # restricted by deploy/base/network-policies.yaml (only the gateway and the same namespace).
    host = "0.0.0.0"  # NOSONAR
    uvicorn.run(app, host=host, port=int(os.environ.get("PORT", names.HTTP_PORT)), log_level="info")  # NOSONAR


if __name__ == "__main__":
    main()
