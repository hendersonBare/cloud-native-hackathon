"""Process wiring for `python -m rapport_delegate`: real dependencies from the environment, then run the role.

Everything testable lives in agent.py, initiator.py and responder.py; this module only builds the real thing.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
import uvicorn

from rapport_common import telemetry

from .config import EXCHANGE_TIMEOUT_S, ConfigError, DelegateConfig
from .initiator import run_initiator
from .llm import llm_from_env
from .memory import open_store
from .policy import OpaPolicy
from .reporter import HttpEventSink, Reporter
from .responder import ResponderService, create_app

log = logging.getLogger("rapport.delegate")

WATCHDOG_GRACE_S = 10.0  # the responder gives up this long after the initiator's own budget


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        cfg = DelegateConfig.from_env()
    except ConfigError as exc:
        log.error("bad configuration: %s", exc)
        return 2
    log.info("delegate %s starting as %s for %s", cfg.encounter_id, cfg.role, cfg.self_org)
    try:
        if cfg.role == "initiator":
            return _run_initiator(cfg)
        return _run_responder(cfg)
    finally:
        telemetry.shutdown_telemetry()  # short-lived pod: without this the spans are lost


def _reporter(cfg: DelegateConfig) -> Reporter:
    sink = HttpEventSink(httpx.AsyncClient(timeout=2.0))
    return Reporter(sink, encounter_id=cfg.encounter_id, org_id=cfg.self_org, persona_id=cfg.self_persona)


def _run_initiator(cfg: DelegateConfig) -> int:
    telemetry.init_telemetry("rapport-delegate", org_id=cfg.self_org)
    policy = OpaPolicy(cfg.self_org, httpx.AsyncClient())
    return asyncio.run(run_initiator(cfg, store=open_store(cfg.self_org), policy=policy, llm=llm_from_env(),
                                     reporter=_reporter(cfg)))


def _run_responder(cfg: DelegateConfig) -> int:
    servers: list[uvicorn.Server] = []

    def stop(_ok: bool) -> None:
        for server in servers:
            server.should_exit = True

    policy = OpaPolicy(cfg.self_org, httpx.AsyncClient())
    app = create_app(cfg, store=open_store(cfg.self_org), policy=policy, llm=llm_from_env(),
                     reporter=_reporter(cfg), on_finished=stop)
    telemetry.init_telemetry("rapport-delegate", org_id=cfg.self_org, fastapi_app=app)
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=cfg.port, log_config=None,
                                           timeout_graceful_shutdown=5))
    servers.append(server)
    service: ResponderService = app.state.service
    asyncio.run(_serve(server, service))
    return 0 if service.succeeded else 1


async def _serve(server: uvicorn.Server, service: ResponderService) -> None:
    watchdog = asyncio.create_task(_watchdog(service))
    try:
        await server.serve()
    finally:
        watchdog.cancel()
        if service.succeeded is None:  # stopped by a signal before the exchange ended
            await service.fail("interrupted")


async def _watchdog(service: ResponderService) -> None:
    """The initiator never came, or died: report failed and stop instead of waiting for the Job deadline."""
    await asyncio.sleep(EXCHANGE_TIMEOUT_S + WATCHDOG_GRACE_S)
    if service.succeeded is None:
        log.error("exchange did not finish in time")
        await service.fail("exchange_timeout")

