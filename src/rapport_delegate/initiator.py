"""Initiator: waits for the peer, runs the three rounds, reports the SharedBrief, returns the exit code.

Budget (SPEC 5): poll the peer's /healthz every 0.5 s for up to 30 s, 20 s per HTTP call, 90 s for everything.
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx
from pydantic import ValidationError

from rapport_common import telemetry
from rapport_common.interfaces import MemoryStore
from rapport_common.models import ExchangeMessage

from .agent import DelegateAgent, ProtocolError
from .config import CALL_TIMEOUT_S, EXCHANGE_TIMEOUT_S, PEER_POLL_S, PEER_WAIT_S, DelegateConfig
from .instruments import DelegateMetrics
from .llm import LLM
from .memory import SelfMemory
from .policy import Policy
from .reporter import Reporter

log = logging.getLogger("rapport.delegate.initiator")


class PeerError(Exception):
    """The peer is unreachable or answered badly. `code` is safe to report (no content)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def wait_for_peer(client: httpx.AsyncClient, *, wait_s: float = PEER_WAIT_S, poll_s: float = PEER_POLL_S,
                        call_timeout_s: float = 2.0) -> None:
    """Poll GET /healthz until the responder is up."""
    deadline = time.monotonic() + wait_s
    while True:
        try:
            resp = await client.get("/healthz", timeout=call_timeout_s)
            if resp.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        if time.monotonic() + poll_s > deadline:
            raise PeerError("peer_not_ready")
        await asyncio.sleep(poll_s)


async def _send(client: httpx.AsyncClient, msg: ExchangeMessage, timeout_s: float) -> ExchangeMessage:
    try:
        async with asyncio.timeout(timeout_s):
            resp = await client.post("/v1/exchange", content=msg.model_dump_json(),
                                     headers={"content-type": "application/json"}, timeout=timeout_s)
    except (httpx.HTTPError, TimeoutError):
        raise PeerError(f"round_{msg.round}_unreachable") from None
    if resp.status_code != 200:
        raise PeerError(f"round_{msg.round}_http_{resp.status_code}")
    try:
        return ExchangeMessage.model_validate_json(resp.content)
    except ValidationError:
        raise PeerError(f"round_{msg.round}_invalid_reply") from None


async def _rounds(agent: DelegateAgent, client: httpx.AsyncClient, call_timeout_s: float) -> None:
    reply = await _send(client, await agent.make_hello(), call_timeout_s)
    agent.receive_hello(reply)
    reply = await _send(client, await agent.make_offers_asks(), call_timeout_s)
    agent.receive_offers_asks(reply)
    reply = await _send(client, await agent.make_answers_followups(), call_timeout_s)
    agent.receive_answers_followups(reply)


def failure_code(exc: BaseException) -> str:
    if isinstance(exc, PeerError):
        return exc.code
    if isinstance(exc, TimeoutError):
        return "exchange_timeout"
    if isinstance(exc, ProtocolError):
        return "protocol_error"
    return type(exc).__name__


async def run_initiator(
    cfg: DelegateConfig, *, store: MemoryStore, policy: Policy, llm: LLM, reporter: Reporter,
    client: httpx.AsyncClient | None = None, wait_s: float = PEER_WAIT_S, poll_s: float = PEER_POLL_S,
    call_timeout_s: float = CALL_TIMEOUT_S, overall_s: float = EXCHANGE_TIMEOUT_S,
) -> int:
    """Run the whole exchange. Returns the process exit code: 0 done, 1 failed (after reporting `failed`)."""
    if cfg.peer_url is None and client is None:
        raise ValueError("an initiator needs PEER_URL")
    own_client = client is None
    client = client or httpx.AsyncClient(base_url=cfg.peer_url or "", timeout=call_timeout_s)
    metrics = DelegateMetrics()
    agent = DelegateAgent(cfg, memory=SelfMemory(store, cfg.self_org), policy=policy, llm=llm, reporter=reporter,
                          metrics=metrics)
    started = time.monotonic()
    attrs = {telemetry.ATTR_ENCOUNTER: cfg.encounter_id, telemetry.ATTR_SIDE: "initiator",
             telemetry.ATTR_ORG: cfg.self_org}
    code = 1
    try:
        tracer = telemetry.tracer("rapport.delegate")
        context = telemetry.context_from_traceparent(cfg.traceparent)
        with tracer.start_as_current_span("exchange.run", context=context, attributes=attrs) as span:
            agent.report_status("started")
            try:
                async with asyncio.timeout(overall_s):
                    await wait_for_peer(client, wait_s=wait_s, poll_s=poll_s)
                    await _rounds(agent, client, call_timeout_s)
                    brief = await agent.build_shared_brief()
                reporter.send("shared_brief", brief.model_dump(mode="json"))
                agent.report_status("done")
                code = 0
            except Exception as exc:
                reason = failure_code(exc)
                log.error("exchange failed (%s)", reason)
                span.set_attribute("rapport.failure", reason)
                agent.report_status("failed", reason)
            metrics.exchange_duration.record((time.monotonic() - started) * 1000.0)
    finally:
        await reporter.aclose()
        if own_client:
            await client.aclose()
    return code
