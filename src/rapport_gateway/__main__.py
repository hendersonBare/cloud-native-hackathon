"""python -m rapport_gateway: the public app on PORT (8080) and the internal app on INTERNAL_PORT (8081)."""

from __future__ import annotations

import asyncio
import contextlib
import logging

import uvicorn

from rapport_common.telemetry import init_telemetry

from .app import create_app, create_internal_app
from .deps import build_deps
from .settings import Settings

log = logging.getLogger("rapport.gateway")


async def serve(settings: Settings) -> None:
    deps = build_deps(settings)
    public_app = create_app(settings, deps)
    internal_app = create_internal_app(deps)
    init_telemetry("rapport-gateway", fastapi_app=public_app)
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(internal_app)
    except Exception:  # telemetry is a bonus; never block startup
        log.exception("could not instrument the internal app")

    public = uvicorn.Server(uvicorn.Config(public_app, host="0.0.0.0", port=settings.port, server_header=False))
    internal = uvicorn.Server(
        uvicorn.Config(internal_app, host="0.0.0.0", port=settings.internal_port, server_header=False)
    )
    # Only the public server installs signal handlers; stopping it stops the internal one too.
    internal.capture_signals = contextlib.nullcontext  # type: ignore[method-assign]
    internal_task = asyncio.create_task(internal.serve())
    log.info(
        "gateway %s: public :%s, internal :%s, %s mode",
        settings.version, settings.port, settings.internal_port, "MOCK" if settings.mock else "live",
    )
    try:
        await public.serve()
    finally:
        internal.should_exit = True
        await internal_task


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(serve(Settings.from_env()))


if __name__ == "__main__":
    main()
