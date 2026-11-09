"""In-memory event bus: one bounded queue per SSE subscriber, routing per SPEC 7.1, a replay ring buffer.

Routing rules
- A phone stream (persona_id=...) receives events whose persona_id is its persona, plus encounter_started
  and encounter_completed for encounters the persona takes part in.
- The swarm stream receives every event except private_brief, profile_updated, deep_dive_started and
  deep_dive_ready, so private content never leaves the owner's phone. (An `error` addressed to a
  persona is phone-only too; an `error` without a persona goes to everyone.) agent_decision reaches the viewer's
  phone and the swarm and carries no reason.

All methods must run on the event loop thread (the pod watch uses loop.call_soon_threadsafe).
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from pydantic import BaseModel

from rapport_common.models import GatewayEvent, GatewayEventType
from rapport_common.telemetry import current_trace_id

log = logging.getLogger("rapport.gateway.bus")

PRIVATE_FROM_SWARM: frozenset[str] = frozenset(
    {"private_brief", "profile_updated", "deep_dive_started", "deep_dive_ready"}
)
ENCOUNTER_LEVEL: frozenset[str] = frozenset({"encounter_started", "encounter_completed"})


@dataclass(eq=False)  # identity hashing: subscriptions live in a set
class Subscription:
    """persona_id=None is the swarm stream."""

    persona_id: str | None
    queue: asyncio.Queue[GatewayEvent]
    dropped: int = 0

    @property
    def is_swarm(self) -> bool:
        return self.persona_id is None


@dataclass
class EventBus:
    queue_size: int = 256
    buffer_size: int = 200
    _subs: set[Subscription] = field(default_factory=set)
    _buffer: deque[GatewayEvent] = field(default_factory=deque)
    _participants: dict[str, frozenset[str]] = field(default_factory=dict)  # encounter_id -> persona ids
    _seen_keys: set[tuple[str, str, str | None]] = field(default_factory=set)

    # ------------------------------------------------------------------ routing
    def routes_to(self, event: GatewayEvent, persona_id: str | None) -> bool:
        if persona_id is None:  # swarm
            if event.type == "error" and event.persona_id:  # an error for one person's phone stays on that phone
                return False
            return event.type not in PRIVATE_FROM_SWARM
        if event.persona_id == persona_id:
            return True
        if event.type in ENCOUNTER_LEVEL and event.encounter_id:
            return persona_id in self._participants.get(event.encounter_id, frozenset())
        return False

    # ------------------------------------------------------------------ publish / subscribe
    def publish(self, event: GatewayEvent) -> GatewayEvent:
        """Route an event to every matching subscriber. Returns the event actually sent (the ts is nudged
        by microseconds when the web client's dedupe key (type, ts, encounter_id) would collide)."""
        event = self._unique(event)
        if event.type == "encounter_started" and event.encounter_id:
            self._participants[event.encounter_id] = frozenset(
                {str(event.data.get("initiator_persona_id")), str(event.data.get("responder_persona_id"))}
            )
        self._buffer.append(event)
        while len(self._buffer) > self.buffer_size:
            self._buffer.popleft()
        for sub in tuple(self._subs):
            if self.routes_to(event, sub.persona_id):
                self._offer(sub, event)
        return event

    def emit(
        self,
        type: GatewayEventType,
        data: BaseModel | dict[str, Any],
        *,
        persona_id: str | None = None,
        encounter_id: str | None = None,
    ) -> GatewayEvent:
        """Build a validated GatewayEvent (data must match the contract model for its type) and publish it."""
        payload = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
        event = GatewayEvent(
            type=type, encounter_id=encounter_id, persona_id=persona_id, trace_id=current_trace_id(), data=payload
        )
        return self.publish(event)

    def subscribe(self, persona_id: str | None, *, replay: bool = True) -> Subscription:
        sub = Subscription(persona_id=persona_id, queue=asyncio.Queue(maxsize=self.queue_size))
        if replay:
            for event in self._buffer:
                if self.routes_to(event, persona_id):
                    self._offer(sub, event)
        self._subs.add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        self._subs.discard(sub)

    def clear(self) -> None:
        """Demo reset: forget the replay buffer and encounter membership. Open streams stay connected."""
        self._buffer.clear()
        self._participants.clear()
        self._seen_keys.clear()

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    # ------------------------------------------------------------------ internals
    def _offer(self, sub: Subscription, event: GatewayEvent) -> None:
        if sub.queue.full():  # bounded: drop the oldest so a slow reader never blocks the gateway
            try:
                sub.queue.get_nowait()
                sub.dropped += 1
            except asyncio.QueueEmpty:  # pragma: no cover - cannot happen on a single thread
                pass
        sub.queue.put_nowait(event)

    def _unique(self, event: GatewayEvent) -> GatewayEvent:
        key = (event.type, event.ts.isoformat(), event.encounter_id)
        while key in self._seen_keys:
            event = event.model_copy(update={"ts": event.ts + timedelta(microseconds=1)})
            key = (event.type, event.ts.isoformat(), event.encounter_id)
        self._seen_keys.add(key)
        if len(self._seen_keys) > self.buffer_size * 4:  # keep the set small; only recent events can collide
            self._seen_keys = {(e.type, e.ts.isoformat(), e.encounter_id) for e in self._buffer} | {key}
        return event
