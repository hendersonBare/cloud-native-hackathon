"""Responder: FastAPI app with GET /healthz and POST /v1/exchange.

`create_app` takes every dependency, so tests and local runs can inject fakes. After the round-3 reply has been
sent, a background task posts shared_brief and delegate_status done, flushes events and calls `on_finished`, which
the runtime uses to stop the server (so the Job pod exits 0 only after the response was flushed).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException
from opentelemetry import trace
from opentelemetry.trace import Span

from rapport_common import telemetry
from rapport_common.interfaces import MemoryStore
from rapport_common.models import ExchangeMessage

from .agent import DelegateAgent, ProtocolError
from .config import DelegateConfig
from .llm import LLM
from .memory import SelfMemory
from .policy import Policy
from .reporter import Reporter

log = logging.getLogger("rapport.delegate.responder")


class ResponderService:
    """State of one encounter on the responder side. Replays a cached reply when a round is repeated."""

    def __init__(self, agent: DelegateAgent, on_finished: Callable[[bool], None] | None = None) -> None:
        self.agent = agent
        self._on_finished = on_finished
        self._lock = asyncio.Lock()
        self._replies: dict[int, ExchangeMessage] = {}
        self._finish_scheduled = False
        self._root: Span | None = None
        self.succeeded: bool | None = None

    def start(self) -> None:
        cfg = self.agent.cfg
        attrs = {telemetry.ATTR_ENCOUNTER: cfg.encounter_id, telemetry.ATTR_SIDE: "responder",
                 telemetry.ATTR_ORG: cfg.self_org}
        context = telemetry.context_from_traceparent(cfg.traceparent)
        self._root = telemetry.tracer("rapport.delegate").start_span("exchange.run", context=context, attributes=attrs)
        self.agent.root_context = trace.set_span_in_context(self._root)
        self.agent.report_status("started")

    async def handle(self, msg: ExchangeMessage) -> ExchangeMessage:
        agent = self.agent
        async with self._lock:
            if msg.round in self._replies:
                return self._replies[msg.round]
            if msg.round != len(self._replies) + 1:
                raise HTTPException(status_code=409, detail=f"expected round {len(self._replies) + 1}")
            try:
                if msg.round == 1:
                    agent.receive_hello(msg)
                    reply = await agent.make_hello()
                elif msg.round == 2:
                    agent.receive_offers_asks(msg)
                    reply = await agent.make_offers_asks()
                else:
                    agent.receive_answers_followups(msg)
                    reply = await agent.make_answers_followups()
            except ProtocolError as exc:
                raise HTTPException(status_code=exc.status, detail=exc.detail) from None
            except Exception as exc:  # our bug: say so clearly, report it, stop; never leak details to the peer
                log.error("round %s failed (%s)", msg.round, type(exc).__name__)
                await self.fail(type(exc).__name__)
                raise HTTPException(status_code=500, detail="delegate failed") from None
            self._replies[msg.round] = reply
            return reply

    def should_finish(self, msg: ExchangeMessage) -> bool:
        if msg.round == 3 and not self._finish_scheduled and 3 in self._replies:
            self._finish_scheduled = True
            return True
        return False

    async def finish(self) -> None:
        """Runs after the round-3 response was sent."""
        agent = self.agent
        ok = True
        try:
            brief = await agent.build_shared_brief()
            agent.reporter.send("shared_brief", brief.model_dump(mode="json"))
            agent.report_status("done")
        except Exception as exc:
            ok = False
            log.error("building the shared brief failed (%s)", type(exc).__name__)
            agent.report_status("failed", type(exc).__name__)
        await self._close(ok)

    async def fail(self, detail: str) -> None:
        self.agent.report_status("failed", detail)
        await self._close(False)

    async def _close(self, ok: bool) -> None:
        if self.succeeded is not None:
            return
        self.succeeded = ok
        await self.agent.reporter.flush()
        if self._root is not None:
            self._root.end()
        if self._on_finished is not None:
            self._on_finished(ok)


def create_app(cfg: DelegateConfig, *, store: MemoryStore, policy: Policy, llm: LLM, reporter: Reporter,
               on_finished: Callable[[bool], None] | None = None) -> FastAPI:
    """Build the responder. Nothing here reads the environment or opens a connection."""
    agent = DelegateAgent(cfg, memory=SelfMemory(store, cfg.self_org), policy=policy, llm=llm, reporter=reporter)
    service = ResponderService(agent, on_finished)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        service.start()
        yield
        await reporter.aclose()

    app = FastAPI(title="Rapport delegate (responder)", version="1", lifespan=lifespan)
    app.state.service = service

    health = APIRouter(tags=["health"])
    exchange = APIRouter(prefix="/v1", tags=["exchange"])

    @health.get("/healthz", response_model=dict[str, bool])
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @exchange.post(
        "/exchange",
        response_model=ExchangeMessage,
        summary="One round of rapport.exchange/v1: receive the initiator's message, reply with ours",
        responses={
            403: {"description": "Sender, recipient or encounter does not match this delegate"},
            409: {"description": "Round out of order"},
            422: {"description": "Not a valid ExchangeMessage"},
            500: {"description": "The delegate failed"},
        },
    )
    async def post_exchange(msg: ExchangeMessage, background: BackgroundTasks) -> ExchangeMessage:
        reply = await service.handle(msg)
        if service.should_finish(msg):
            background.add_task(service.finish)
        return reply

    app.include_router(health)
    app.include_router(exchange)
    return app
