"""python -m rapport_speakers: the read-only speaker search API on 0.0.0.0:8080 (local runs).

In the cluster the gateway mounts the same router instead (see api.py), so no new Deployment is needed.
"""

from __future__ import annotations

import logging
import os

import uvicorn

from rapport_common.names import HTTP_PORT

from .api import create_app


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", HTTP_PORT)))


if __name__ == "__main__":
    main()
