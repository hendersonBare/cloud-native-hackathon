"""Connect requests and accept: the path from a click to an Encounter and two private briefs."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass, field

from rapport_common import names
from rapport_common.models import (
    AcceptBody,
    BriefRequest,
    ConnectBody,
    ConnectRequestData,
    EncounterParty,
    EncounterSpec,
    EncounterStartedData,
)
from rapport_common.telemetry import ATTR_ENCOUNTER, ATTR_PERSONA, current_traceparent, tracer

from .briefers import BrieferClient
from .bus import EventBus
from .encounters import EncounterService, EncounterState, Party
from .errors import GatewayError, require_agent_persona
from .k8s import EncounterLauncher
from .observability import Instruments
from .tasks import BackgroundTasks

log = logging.getLogger("rapport.gateway.connect")
MAX_PENDING = 500


@dataclass
class PendingRequest:
    request_id: str
    body: ConnectBody
    created_at: float = field(default_factory=time.monotonic)
    encounter_id: str | None = None  # set once accepted, so a repeated accept is idempotent


def new_request_id() -> str:
    return f"req-{secrets.token_hex(4)}"


class RequestBook:
    """Pending connect requests, in memory. Shared by live mode and mock mode."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._requests: dict[str, PendingRequest] = {}

    def create(self, body: ConnectBody, *, announce: bool = True) -> str:
        """Validate both people, store the request and (unless announce=False) tell the target's phone."""
        sender = require_agent_persona(body.from_persona_id)
        target = require_agent_persona(body.to_persona_id)
        if sender.org_id == target.org_id:
            raise GatewayError(422, "an encounter is between two different companies")
        while len(self._requests) >= MAX_PENDING:
            self._requests.pop(next(iter(self._requests)))
        request_id = new_request_id()
        self._requests[request_id] = PendingRequest(request_id, body)
        if announce:
            self.announce(request_id)
        return request_id

    def announce(self, request_id: str) -> None:
        """Emit connect_request to the target's phone."""
        body = self._requests[request_id].body
        self._bus.emit(
            "connect_request",
            ConnectRequestData(
                request_id=request_id,
                from_persona_id=body.from_persona_id,
                to_persona_id=body.to_persona_id,
                malicious=body.malicious,
                initiated_by=body.initiated_by,
            ),
            persona_id=body.to_persona_id,
        )

    def get_for_accept(self, request_id: str, accept: AcceptBody) -> PendingRequest:
        pending = self._requests.get(request_id)
        if pending is None:
            raise GatewayError(404, f"unknown connect request {request_id!r}")
        if accept.persona_id != pending.body.to_persona_id:
            raise GatewayError(403, "only the person who was asked can accept")
        return pending

    def clear(self) -> None:
        self._requests.clear()


class ConnectService:
    def __init__(
        self,
        *,
        settings_brief_timeout_s: float,
        bus: EventBus,
        book: RequestBook,
        briefers: BrieferClient,
        launcher: EncounterLauncher,
        encounters: EncounterService,
        tasks: BackgroundTasks,
        instruments: Instruments | None = None,
    ) -> None:
        self._brief_timeout_s = settings_brief_timeout_s
        self._bus = bus
        self._book = book
        self._briefers = briefers
        self._launcher = launcher
        self._encounters = encounters
        self._tasks = tasks
        self._instruments = instruments or Instruments()
        self._accept_lock = asyncio.Lock()

    def connect(self, body: ConnectBody, *, announce: bool = True) -> str:
        return self._book.create(body, announce=announce)

    def announce(self, request_id: str) -> None:
        self._book.announce(request_id)

    async def accept(self, request_id: str, body: AcceptBody) -> str:
        async with self._accept_lock:  # a double-click must not create two Encounters
            pending = self._book.get_for_accept(request_id, body)
            if pending.encounter_id is not None:
                return pending.encounter_id
            started = time.monotonic()
            req = pending.body
            from_org, to_org = names.org_of(req.from_persona_id), names.org_of(req.to_persona_id)
            encounter_id = names.new_encounter_id()
            spec = EncounterSpec(
                initiator=EncounterParty(orgId=from_org, personaId=req.from_persona_id, malicious=False),
                responder=EncounterParty(orgId=to_org, personaId=req.to_persona_id, malicious=req.malicious),
            )
            with tracer().start_as_current_span("connect.accept") as span:
                span.set_attribute(ATTR_ENCOUNTER, encounter_id)
                span.set_attribute(ATTR_PERSONA, req.to_persona_id)
                with tracer().start_as_current_span("encounter.create") as create_span:
                    create_span.set_attribute(ATTR_ENCOUNTER, encounter_id)
                    await self._launcher.launch(encounter_id, spec, current_traceparent())
                pending.encounter_id = encounter_id
                state = EncounterState(
                    encounter_id,
                    Party(from_org, req.from_persona_id, "initiator"),
                    Party(to_org, req.to_persona_id, "responder", req.malicious),
                )
                self._encounters.register(state)
                self._instruments.encounter_started()
                self._bus.emit(
                    "encounter_started",
                    EncounterStartedData(
                        initiator_persona_id=req.from_persona_id, responder_persona_id=req.to_persona_id
                    ),
                    encounter_id=encounter_id,
                )
                for party in state.parties:
                    self._tasks.spawn(
                        self._brief(state, party, state.other(party), started),
                        name=f"brief-{encounter_id}-{party.side}",
                    )
            return encounter_id

    async def _brief(self, state: EncounterState, party: Party, other: Party, started: float) -> None:
        """Ask this person's own briefer for their private brief and push it to their phone only."""
        with tracer().start_as_current_span("brief.request") as span:
            span.set_attribute(ATTR_ENCOUNTER, state.encounter_id)
            span.set_attribute(ATTR_PERSONA, party.persona_id)
            try:
                brief = await self._briefers.brief(
                    party.org_id,
                    BriefRequest(
                        encounter_id=state.encounter_id,
                        persona_id=party.persona_id,
                        counterparty_persona_id=other.persona_id,
                    ),
                    timeout_s=self._brief_timeout_s,
                )
            except GatewayError as exc:
                log.warning("brief for %s in %s failed: %s", party.persona_id, state.encounter_id, exc.detail)
                self._bus.emit(
                    "error",
                    {"message": "Your private brief is unavailable right now."},
                    persona_id=party.persona_id,
                    encounter_id=state.encounter_id,
                )
                return
            self._bus.emit("private_brief", brief, persona_id=party.persona_id, encounter_id=state.encounter_id)
            self._instruments.brief_latency((time.monotonic() - started) * 1000, party.org_id)

    def reset(self) -> None:
        self._book.clear()
