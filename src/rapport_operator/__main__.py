"""python -m rapport_operator: run kopf cluster-wide and standalone (no peering).

Env: PORT (kopf liveness endpoint GET /healthz, default 8080), RAPPORT_IMAGE (delegate image; else the
operator pod's own image via POD_NAME and POD_NAMESPACE), KUBE_CONTEXT (local runs only),
RAPPORT_LLM_MODEL and RAPPORT_LLM_REASONING_EFFORT (passed on to delegates).
"""

from __future__ import annotations

import logging
import os

import kopf

from rapport_common import telemetry


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    telemetry.init_telemetry("rapport-operator")
    from . import handlers  # noqa: F401  (importing registers the kopf handlers)

    port = int(os.environ.get("PORT", "8080"))
    kopf.run(
        clusterwide=True,
        standalone=True,
        liveness_endpoint=f"http://0.0.0.0:{port}/healthz",
    )


if __name__ == "__main__":
    main()
