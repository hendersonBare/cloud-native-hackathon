"""Standalone dev server: ``RAPPORT_WEB_DIR=web PYTHONPATH=src uv run python -m rapport_venue``."""

from __future__ import annotations

import logging
import os

from rapport_common.names import HTTP_PORT
from rapport_common.telemetry import init_telemetry

from .app import create_app


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    app = create_app(web_dir=os.environ.get("RAPPORT_WEB_DIR"))
    init_telemetry("rapport-venue", fastapi_app=app)
    # Only a local dev server: in the cluster the venue runs inside the gateway, so this listens on localhost unless
    # RAPPORT_VENUE_HOST says otherwise. Access log lines carry only paths and persona ids (GPS is in PUT bodies,
    # which are never logged).
    uvicorn.run(app, host=os.environ.get("RAPPORT_VENUE_HOST", "127.0.0.1"), port=HTTP_PORT)


if __name__ == "__main__":
    main()
