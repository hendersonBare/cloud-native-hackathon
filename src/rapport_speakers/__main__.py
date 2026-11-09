"""python -m rapport_speakers: the read-only speaker search API on $HOST:$PORT (local runs).

In the cluster the gateway mounts the same router instead (see api.py), so no new Deployment is needed. This
standalone app defaults to 127.0.0.1 because it is for laptops. Run it as a pod with HOST=0.0.0.0 so its Service
can reach it (house rule: port 8080).
"""

from __future__ import annotations

import logging
import os

import uvicorn

from rapport_common.names import HTTP_PORT

from .api import create_app


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    host = os.environ.get("HOST", "127.0.0.1")
    uvicorn.run(create_app(), host=host, port=int(os.environ.get("PORT", HTTP_PORT)))


if __name__ == "__main__":
    main()
