"""Standalone dev server on 127.0.0.1:8080: ``RAPPORT_WEB_DIR=web PYTHONPATH=src uv run python -m rapport_calendar``.

In the cluster the calendar is not a separate service: the gateway mounts ``rapport_calendar.api.router``.
"""

from __future__ import annotations

import logging
import os

from rapport_common.names import HTTP_PORT
from rapport_common.telemetry import init_telemetry

from .app import create_app


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its INFO lines carry full URLs, including search queries
    app = create_app(web_dir=os.environ.get("RAPPORT_WEB_DIR"))
    init_telemetry("rapport-calendar", fastapi_app=app)
    # Local development only: in the cluster the gateway mounts the router, so this server stays on loopback
    # unless RAPPORT_CALENDAR_HOST says otherwise. No access log: its request lines carry the agenda search query.
    host = os.environ.get("RAPPORT_CALENDAR_HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=HTTP_PORT, access_log=False)


if __name__ == "__main__":
    main()
