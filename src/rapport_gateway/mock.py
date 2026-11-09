"""Mock mode (RAPPORT_MOCK=1): every endpoint works with no Kubernetes, no briefers and no keys.

Events come from contracts/demo-events.json by phase and at_ms:
  upload  after POST /api/context           swipe  after a right swipe on bluefin.bo
  accept  after POST /api/connect/{id}/accept
Each replay is re-stamped to now (ts) and gets fresh request and encounter IDs that are consistent within
the run, so repeating the demo never collides in the web client's dedupe key (type, ts, encounter_id).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rapport_common import names
from rapport_common.models import (
    AcceptBody,
    AgentDecision,
    AskAnswer,
    AskRequest,
    Citation,
    ConnectBody,
    ConversationPlan,
    DeepDive,
    GatewayEvent,
    PersonaProfile,
    PersonCard,
    ResearchRequest,
    ResearchResult,
    SwipeBody,
    TalkHit,
    TalkSearchResult,
    utcnow,
)

from .backend import UploadFile
from .bus import EventBus
from .connect import RequestBook
from .errors import GatewayError, require_agent_persona, require_persona
from .ratelimit import SlidingWindowLimiter
from .tasks import BackgroundTasks
from .timefmt import local_label, utc_at

log = logging.getLogger("rapport.gateway.mock")

FIXTURE_ENCOUNTER_ID = "enc-1a2b3c4d"
FIXTURE_REQUEST_ID = "req-01"
DEMO_VIEWER, DEMO_TARGET = "acme.ava", "bluefin.bo"


@dataclass(frozen=True)
class Fixtures:
    events: list[dict[str, Any]]
    research: ResearchResult

    @classmethod
    def load(cls, contracts_dir: Path) -> Fixtures:
        try:
            events = json.loads((contracts_dir / "demo-events.json").read_text())["events"]
            research = ResearchResult.model_validate_json((contracts_dir / "demo-research.json").read_text())
        except (OSError, ValueError, KeyError) as exc:
            raise RuntimeError(f"mock mode needs demo-events.json and demo-research.json in {contracts_dir}") from exc
        return cls(events=events, research=research)

    def phase(self, name: str, replacements: dict[str, str] | None = None) -> list[tuple[int, dict[str, Any]]]:
        """(at_ms, event dict) for one phase, with IDs replaced. Order follows the file, then at_ms."""
        out = []
        for item in self.events:
            if item["phase"] != name:
                continue
            text = json.dumps(item["event"])
            for old, new in (replacements or {}).items():
                text = text.replace(old, new)
            out.append((int(item["at_ms"]), json.loads(text)))
        return sorted(out, key=lambda pair: pair[0])


# --------------------------------------------------------------------------- canned data
def _talk(talk_id: str, title: str, hour: int, minute: int, room: str, track: str, speaker: str) -> TalkHit:
    starts = utc_at(2026, 11, 9, hour, minute)
    return TalkHit(
        talk_id=talk_id,
        title=title,
        starts_at=starts,
        room=room,
        track=track,
        speakers=[speaker],
        reason=f"{local_label(starts)} in {room}",
    )


def canned_talks() -> list[TalkHit]:
    zero = "Zero-code tracing with eBPF on Kubernetes"
    return [
        _talk("talk-ebpf-zero-code", zero, 15, 30, "Room B", "Observability", "R. Alvarez"),
        _talk("talk-ebpf-cost", "Cutting the cloud bill with eBPF", 14, 30, "Room A", "Cost", "Priya"),
        _talk("talk-ebpf-edge", "eBPF on warehouse robots", 16, 0, "Room C", "Edge", "Mia"),
        _talk("talk-otel-regulated", "OpenTelemetry in regulated industries", 13, 30, "Room B", "OTel", "Lena"),
        _talk("talk-inclusive-confs", "Designing conferences for everyone", 16, 30, "Room A", "Accessibility", "Tom"),
    ]


def _words(text: str) -> set[str]:
    return {w for w in "".join(c if c.isalnum() else " " for c in text.lower()).split() if len(w) > 2}


class MockBackend:
    def __init__(
        self,
        *,
        fixtures: Fixtures,
        bus: EventBus,
        book: RequestBook,
        tasks: BackgroundTasks,
        handshakes: SlidingWindowLimiter,
        speed: float = 1.0,
    ) -> None:
        self._fx = fixtures
        self._bus = bus
        self._book = book
        self._tasks = tasks
        self._handshakes = handshakes
        self._speed = speed
        self._profiles: dict[str, PersonaProfile] = {}
        self._skipped: set[tuple[str, str]] = set()
        self._accepted: dict[str, str] = {}

    # ------------------------------------------------------------------ replay
    def _play(self, steps: list[tuple[int, dict[str, Any]]], name: str) -> None:
        self._tasks.spawn(self._run(steps), name=f"mock-{name}")

    async def _run(self, steps: list[tuple[int, dict[str, Any]]]) -> None:
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        for at_ms, raw in steps:
            delay = at_ms / 1000 / self._speed - (loop.time() - t0)
            if delay > 0:
                await asyncio.sleep(delay)
            self._bus.publish(GatewayEvent.model_validate({**raw, "ts": utcnow()}))

    # ------------------------------------------------------------------ Backend
    def _fixture_profile(self, persona_id: str) -> PersonaProfile:
        raw = next(e["event"]["data"] for e in self._fx.events if e["event"]["type"] == "profile_updated")
        profile = PersonaProfile.model_validate({**raw, "persona_id": persona_id})
        return profile.model_copy(update={"updated_at": utcnow()})

    async def upload_context(
        self, persona_id: str, visibility: str, text: str | None, file: UploadFile | None
    ) -> PersonaProfile:
        require_agent_persona(persona_id)
        profile = self._fixture_profile(persona_id)
        if file is not None:
            profile = profile.model_copy(update={"source_files": [file[0]]})
        self._profiles[persona_id] = profile
        steps = []
        for at_ms, raw in self._fx.phase("upload"):
            raw["persona_id"] = persona_id
            raw["data"] = profile.model_dump(mode="json")
            steps.append((at_ms, raw))
        self._play(steps, "upload")
        return profile

    async def profile(self, persona_id: str) -> PersonaProfile:
        require_agent_persona(persona_id)
        return self._profiles.get(persona_id) or self._fixture_profile(persona_id)

    async def connect(self, body: ConnectBody) -> str:
        return self._book.create(body)

    async def accept(self, request_id: str, body: AcceptBody) -> str:
        pending = self._book.get_for_accept(request_id, body)
        if pending.encounter_id is not None:
            return pending.encounter_id
        encounter_id = names.new_encounter_id()
        pending.encounter_id = encounter_id
        req = pending.body
        steps = []
        for at_ms, raw in self._fx.phase("accept", {FIXTURE_ENCOUNTER_ID: encounter_id}):
            self._retarget(raw, req.from_persona_id, req.to_persona_id)
            steps.append((at_ms, raw))
        self._play(steps, "accept")
        return encounter_id

    @staticmethod
    def _retarget(raw: dict[str, Any], from_id: str, to_id: str) -> None:
        """The fixtures are Ava (initiator) and Bo (responder); map them onto whoever really connected."""
        swap = {DEMO_VIEWER: from_id, DEMO_TARGET: to_id}
        swap_org = {"acme": names.org_of(from_id), "bluefin": names.org_of(to_id)}
        if raw.get("persona_id") in swap:
            raw["persona_id"] = swap[raw["persona_id"]]
        data = raw["data"]
        for key in (
            "initiator_persona_id",
            "for_persona_id",
            "persona_id",
            "counterparty_persona_id",
            "responder_persona_id",
        ):
            if data.get(key) in swap:
                data[key] = swap[data[key]]
        if (from_id, to_id) != (DEMO_VIEWER, DEMO_TARGET):
            for key in ("org_id", "from_org", "to_org"):
                if data.get(key) in swap_org:
                    data[key] = swap_org[data[key]]

    async def ask(self, body: AskRequest) -> AskAnswer:
        require_agent_persona(body.persona_id)
        words = _words(body.question)
        if {"promise", "promised"} & words and "bluefin" in words:
            return AskAnswer(
                answer="Sam promised Kai the security questionnaire before the Bluefin pilot starts. "
                "Bluefin is also evaluating a competitor, and the budget decision is in Q1.",
                citations=[
                    Citation(
                        memory_id="acme-note-0007",
                        title="Call notes: Bluefin pilot (March)",
                        kind="account_note",
                        snippet="Sam promised Kai the security questionnaire before the pilot starts.",
                    )
                ],
            )
        return AskAnswer(answer="I could not find anything about that in the demo notes.", citations=[])

    async def talks(self, persona_id: str, q: str) -> TalkSearchResult:
        require_agent_persona(persona_id)
        wanted = _words(q)
        hits = [
            t
            for t in canned_talks()
            if not wanted or wanted & _words(f"{t.title} {t.track} {' '.join(t.speakers)} {t.talk_id}")
        ]
        return TalkSearchResult(query=q, talks=hits[:10])

    async def research(self, body: ResearchRequest) -> ResearchResult:
        viewer = require_agent_persona(body.persona_id)
        f = body.filters
        cards = []
        for card in self._fx.research.cards:
            if card.persona_id in body.exclude_persona_ids or card.persona_id == body.persona_id:
                continue
            if card.org_id == viewer.org_id:
                continue
            if f.interests and not set(f.interests) & set(card.interests):
                continue
            if f.org_ids and card.org_id not in f.org_ids:
                continue
            if f.has_agent is not None and card.agent_available != f.has_agent:
                continue
            if f.language and card.language != f.language:
                continue
            if f.roles and not any(r.lower() in card.title.lower() for r in f.roles):
                continue
            cards.append(card)
        return ResearchResult(persona_id=body.persona_id, cards=cards[: body.limit])

    async def swipe(self, body: SwipeBody) -> None:
        viewer = require_agent_persona(body.persona_id)
        target = require_persona(body.target_persona_id)
        if target.persona_id == viewer.persona_id:
            raise GatewayError(422, "you cannot swipe on yourself")
        if body.direction == "left":
            self._skipped.add((body.persona_id, body.target_persona_id))
            return
        handshake = (
            body.autonomy
            and names.agents_enabled(target.org_id)
            and target.org_id != viewer.org_id
            and self._handshakes.used(body.persona_id) < self._handshakes.limit
        )
        request_id = None
        if handshake:
            request_id = self._book.create(
                ConnectBody(
                    from_persona_id=body.persona_id,
                    to_persona_id=body.target_persona_id,
                    malicious=body.malicious,
                    initiated_by="agent",
                ),
                announce=False,
            )
            self._handshakes.record(body.persona_id)
        action = "agent_handshake" if handshake else "human_intro"
        if (body.persona_id, body.target_persona_id) == (DEMO_VIEWER, DEMO_TARGET):
            steps = self._demo_swipe(body, action, request_id)
        else:
            steps = self._generic_swipe(body, action, request_id)
        self._play(steps, "swipe")

    # ------------------------------------------------------------------ swipe scripts
    def _demo_swipe(self, body: SwipeBody, action: str, request_id: str | None) -> list[tuple[int, dict[str, Any]]]:
        steps = []
        for at_ms, raw in self._fx.phase("swipe", {FIXTURE_REQUEST_ID: request_id or FIXTURE_REQUEST_ID}):
            kind = raw["type"]
            if kind == "connect_request":
                if request_id is None:
                    continue
                raw["data"]["malicious"] = body.malicious
            elif kind == "agent_decision":
                raw["data"]["action"] = action
                if request_id is None:
                    raw["data"]["request_id"] = None
            elif kind == "deep_dive_ready":
                raw["data"]["decision"]["action"] = action
            steps.append((at_ms, raw))
        return steps

    def _generic_swipe(self, body: SwipeBody, action: str, request_id: str | None) -> list[tuple[int, dict[str, Any]]]:
        viewer, target = names.persona(body.persona_id), names.persona(body.target_persona_id)
        card = next((c for c in self._fx.research.cards if c.persona_id == target.persona_id), None)
        dive = canned_deep_dive(viewer.persona_id, target.persona_id, action, card)
        base = {"encounter_id": None, "trace_id": None}
        steps: list[tuple[int, dict[str, Any]]] = [
            (
                800,
                {
                    **base,
                    "type": "deep_dive_started",
                    "persona_id": viewer.persona_id,
                    "data": {"target_persona_id": target.persona_id},
                },
            ),
            (
                2500,
                {
                    **base,
                    "type": "deep_dive_ready",
                    "persona_id": viewer.persona_id,
                    "data": dive.model_dump(mode="json"),
                },
            ),
            (
                2600,
                {
                    **base,
                    "type": "agent_decision",
                    "persona_id": viewer.persona_id,
                    "data": {"target_persona_id": target.persona_id, "action": action, "request_id": request_id},
                },
            ),
        ]
        if request_id is not None:
            steps.append(
                (
                    2700,
                    {
                        **base,
                        "type": "connect_request",
                        "persona_id": target.persona_id,
                        "data": {
                            "request_id": request_id,
                            "from_persona_id": viewer.persona_id,
                            "to_persona_id": target.persona_id,
                            "malicious": body.malicious,
                            "initiated_by": "agent",
                        },
                    },
                )
            )
        return steps

    async def reset(self) -> None:
        self._tasks.cancel_all()
        self._book.clear()
        self._bus.clear()
        self._profiles.clear()
        self._skipped.clear()
        self._handshakes.clear()


def canned_deep_dive(viewer_id: str, target_id: str, action: str, card: PersonCard | None) -> DeepDive:
    viewer, target = names.persona(viewer_id), names.persona(target_id)
    shared = [i for i in target.interests if i in viewer.interests]
    interests = ", ".join(shared) or "the conference"
    summary = card.why_meet if card else f"{target.name} ({target.title}) shares {interests} with you."
    handshake = action == "agent_handshake"
    reason = (
        f"{target.name} matches your goals and runs an agent, so yours can open the conversation."
        if handshake
        else f"{target.name} has no agent for yours to meet, so catch them in person."
    )
    return DeepDive(
        persona_id=viewer_id,
        target_persona_id=target_id,
        language=viewer.language,
        summary=summary[:400],
        plan=ConversationPlan(
            goals=viewer.goals[:2] or ["Make a useful new contact"],
            offers=["Case study: hospital network"] if viewer.org_id == "acme" else [],
            questions=[f"What is {target.name} working on this quarter?"],
            watch_outs=[],
            opener=f"Hi {target.name}, I saw we both care about {interests}."[:200],
        ),
        decision=AgentDecision(
            action=action,  # type: ignore[arg-type]
            reason=reason[:240],
            confidence=0.8 if handshake else 0.6,
            checks=[
                f"target has an agent: {'yes' if names.agents_enabled(target.org_id) else 'no'}",
                "no do-not-contact note: yes",
            ],
        ),
        citations=list(card.company_history) if card else [],
    )
