"""Standalone dev server: ``RAPPORT_WEB_DIR=web PYTHONPATH=src uv run python -m rapport_calendar``."""

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
    # The container listens on all interfaces. No access log: its request lines carry the agenda search query.
    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT, access_log=False)


if __name__ == "__main__":
    main()
