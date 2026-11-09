"""Encounter state, /internal/events validation and mapping, completion and the 150 s timeout.

An event from a delegate is accepted only when
  (a) its encounter_id is an active encounter this gateway created,
  (b) its org_id and persona_id are the same party of that encounter (and the payload agrees), and
  (c) in Kubernetes mode, the caller's IP belongs to a delegate pod labelled with that encounter and org.
Anything else raises EventRejected (HTTP 403) and is logged with IDs only.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Literal

from rapport_common.models import (
    DelegateEvent,
    DelegateStatusData,
    EncounterCompletedData,
    ExchangeMessageData,
    PolicyDecisionData,
    SharedBrief,
)

from .briefers import BrieferClient
from .bus import EventBus
from .errors import EventRejected
from .k8s import PodRegistry
from .remember import build_records
from .tasks import BackgroundTasks

log = logging.getLogger("rapport.gateway.encounters")

Side = Literal["initiator", "responder"]
MAX_KEPT = 200


@dataclass(frozen=True)
class Party:
    org_id: str
    persona_id: str
    side: Side
    malicious: bool = False


@dataclass
class EncounterState:
    encounter_id: str
    initiator: Party
    responder: Party
    created_at: float = field(default_factory=time.monotonic)
    status: Literal["running", "completed", "failed"] = "running"
    briefs: dict[str, SharedBrief] = field(default_factory=dict)
    timeout_task: asyncio.Task | None = None

    @property
    def parties(self) -> tuple[Party, Party]:
        return (self.initiator, self.responder)

    def party_for(self, org_id: str, persona_id: str) -> Party | None:
        for party in self.parties:
            if party.org_id == org_id and party.persona_id == persona_id:
                return party
        return None

    def other(self, party: Party) -> Party:
        return self.responder if party is self.initiator else self.initiator


class EncounterService:
    def __init__(
        self,
        *,
        bus: EventBus,
        briefers: BrieferClient,
        tasks: BackgroundTasks,
        registry: PodRegistry | None,
        check_ip: bool,
        timeout_s: float = 150.0,
        remember_timeout_s: float = 10.0,
        ip_grace_s: float = 1.0,
    ) -> None:
        self._bus = bus
        self._briefers = briefers
        self._tasks = tasks
        self._registry = registry
        self._check_ip = check_ip and registry is not None
        self._timeout_s = timeout_s
        self._remember_timeout_s = remember_timeout_s
        self._ip_grace_s = ip_grace_s
        self._encounters: dict[str, EncounterState] = {}

    # ------------------------------------------------------------------ lifecycle
    def register(self, state: EncounterState) -> None:
        while len(self._encounters) >= MAX_KEPT:  # oldest first; insertion order is creation order
            self._encounters.pop(next(iter(self._encounters)))
        self._encounters[state.encounter_id] = state
        state.timeout_task = self._tasks.spawn(self._expire(state), name=f"expire-{state.encounter_id}")

    def get(self, encounter_id: str) -> EncounterState | None:
        return self._encounters.get(encounter_id)

    def reset(self) -> None:
        for state in self._encounters.values():
            if state.timeout_task is not None:
                state.timeout_task.cancel()
        self._encounters.clear()

    async def _expire(self, state: EncounterState) -> None:
        await asyncio.sleep(self._timeout_s)
        self.finish(state, "failed", "timeout")

    def finish(self, state: EncounterState, status: Literal["completed", "failed"], detail: str | None = None) -> None:
        """Emit encounter_completed once; later calls are no-ops."""
        if state.status != "running":
            return
        state.status = status
        current = asyncio.current_task()
        if state.timeout_task is not None and state.timeout_task is not current:
            state.timeout_task.cancel()
        self._bus.emit(
            "encounter_completed",
            EncounterCompletedData(status=status, detail=detail),
            encounter_id=state.encounter_id,
        )
        log.info("encounter %s %s%s", state.encounter_id, status, f" ({detail})" if detail else "")

    # ------------------------------------------------------------------ /internal/events
    async def handle_delegate_event(self, event: DelegateEvent, client_ip: str | None) -> None:
        state = self._encounters.get(event.encounter_id)
        if state is None:
            raise self._reject(event, "unknown encounter")
        # a finished encounter only accepts the delegate's closing status; a failed one accepts nothing
        if state.status == "failed" or (state.status == "completed" and event.type != "delegate_status"):
            raise self._reject(event, f"encounter is {state.status}")
        party = state.party_for(event.org_id, event.persona_id)
        if party is None:
            raise self._reject(event, "org and persona are not the same party of this encounter")
        self._check_payload(event, state, party)
        if self._check_ip and not await self._ip_belongs(client_ip, state, party):
            raise self._reject(event, "caller is not a delegate pod of this encounter")
        self._dispatch(event, state, party)

    def _check_payload(self, event: DelegateEvent, state: EncounterState, party: Party) -> None:
        data = event.data
        if event.type == "shared_brief":
            brief = SharedBrief.model_validate(data)
            if brief.encounter_id != state.encounter_id or brief.for_persona_id != party.persona_id:
                raise self._reject(event, "shared_brief is for another encounter or persona")
        elif event.type == "exchange_message":
            if ExchangeMessageData.model_validate(data).from_org != party.org_id:
                raise self._reject(event, "exchange_message from another org")
        elif event.type == "policy_decision":
            if PolicyDecisionData.model_validate(data).org_id != party.org_id:
                raise self._reject(event, "policy_decision for another org")
        elif DelegateStatusData.model_validate(data).side != party.side:
            raise self._reject(event, "delegate_status for the other side")

    def _reject(self, event: DelegateEvent, why: str) -> EventRejected:
        # IDs only: never the payload
        log.warning(
            "rejected %s for %s (%s/%s): %s", event.type, event.encounter_id, event.org_id, event.persona_id, why
        )
        return EventRejected(why)

    async def _ip_belongs(self, ip: str | None, state: EncounterState, party: Party) -> bool:
        assert self._registry is not None
        deadline = time.monotonic() + self._ip_grace_s  # the pod watch may lag the first report by a moment
        while True:
            if self._registry.matches(ip, state.encounter_id, party.org_id, party.side):
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(0.1)

    def _dispatch(self, event: DelegateEvent, state: EncounterState, party: Party) -> None:
        eid = state.encounter_id
        if event.type == "exchange_message":
            self._bus.emit("exchange_message", event.data, encounter_id=eid)
        elif event.type == "policy_decision":
            self._bus.emit("policy_decision", event.data, encounter_id=eid)
        elif event.type == "delegate_status":
            status = DelegateStatusData.model_validate(event.data)
            if status.status == "failed":
                self.finish(state, "failed", f"{party.side} delegate failed")
        else:
            self._on_shared_brief(SharedBrief.model_validate(event.data), state, party)

    def _on_shared_brief(self, brief: SharedBrief, state: EncounterState, party: Party) -> None:
        if party.persona_id in state.briefs:  # a repeated report: already delivered
            return
        state.briefs[party.persona_id] = brief
        self._bus.emit("shared_brief", brief, persona_id=party.persona_id, encounter_id=state.encounter_id)
        self._tasks.spawn(self._remember(brief, state, party), name=f"remember-{state.encounter_id}-{party.side}")
        if len(state.briefs) == 2:
            self.finish(state, "completed")

    async def _remember(self, brief: SharedBrief, state: EncounterState, party: Party) -> None:
        other = state.other(party)
        records = build_records(
            brief, org_id=party.org_id, counterparty_org_id=other.org_id, counterparty_persona_id=other.persona_id
        )
        try:
            written = await asyncio.wait_for(
                self._briefers.remember(party.org_id, records, timeout_s=self._remember_timeout_s),
                timeout=self._remember_timeout_s,
            )
            log.info("remembered %d records for %s in %s", written, party.persona_id, state.encounter_id)
        except Exception as exc:  # never block or fail the encounter because memory is down
            log.warning("remember failed for %s in %s: %s", party.persona_id, state.encounter_id, type(exc).__name__)
