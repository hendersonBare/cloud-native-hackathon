"""Rapport shared contracts.

This module is the single source of truth for every payload that crosses a
component boundary: HTTP bodies, SSE events, Elasticsearch documents, OPA
input/output and delegate exchange messages. Import from here; never redefine
these shapes locally. Changing this file follows the contract-change process
in AGENTS.md.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROTOCOL = "rapport.exchange/v1"

ShareLevel = Literal["public", "partner", "internal"]
MemoryKind = Literal[
    "talk", "attendee", "note", "document", "account_note", "profile", "encounter_summary", "followup"
]
Visibility = Literal["shareable", "private"]
Language = Literal["en", "es"]
TAG = r"^[a-z0-9][a-z0-9-]{0,40}$"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- directory
class Org(Contract):
    org_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,30}$")
    name: str
    namespace: str
    blurb: str
    color: str
    agents_enabled: bool = False  # True only for companies that run Rapport agents (namespaces exist)


class Persona(Contract):
    persona_id: str = Field(pattern=r"^[a-z][a-z0-9-]*\.[a-z][a-z0-9-]*$")
    org_id: str
    name: str
    title: str
    language: Language = "en"
    interests: list[str] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    demo_phone: Literal["left", "right"] | None = None


# --------------------------------------------------------------------------- memory (Elasticsearch documents)
class SourceRef(Contract):
    type: Literal["seed", "upload", "encounter", "conference"]
    encounter_id: str | None = None
    filename: str | None = None
    url: str | None = None


class TalkInfo(Contract):
    starts_at: datetime
    ends_at: datetime
    room: str
    speakers: list[str] = Field(default_factory=list)
    track: str


class FollowupInfo(Contract):
    status: Literal["proposed", "confirmed", "done"] = "proposed"
    owner_org_id: str
    owner_persona_id: str | None = None
    counterparty_org_id: str
    due: str | None = None


class ProfileInfo(Contract):
    """Structured view of a person's uploaded context (CV, notes). One per visibility."""

    visibility: Visibility
    headline: str = Field(max_length=160)
    interests: list[str] = Field(default_factory=list, max_length=8)
    goals: list[str] = Field(default_factory=list, max_length=5)
    highlights: list[str] = Field(default_factory=list, max_length=5)


class MemoryRecord(Contract):
    """One Elasticsearch document. Index routing: rapport_common.names.index_for()."""

    memory_id: str
    org_id: str  # "conference" for agenda talks
    share_level: ShareLevel
    kind: MemoryKind
    title: str = Field(max_length=200)
    text: str
    summary: str = Field(max_length=400)  # the only text a delegate may send to another company
    tags: list[str] = Field(default_factory=list)
    about_org_ids: list[str] = Field(default_factory=list)
    about_persona_ids: list[str] = Field(default_factory=list)
    owner_persona_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    source: SourceRef
    talk: TalkInfo | None = None
    followup: FollowupInfo | None = None
    profile: ProfileInfo | None = None  # set only on a person's profile "card" record

    @model_validator(mode="after")
    def _check(self) -> MemoryRecord:
        if self.kind == "talk":
            if self.talk is None or self.org_id != "conference" or self.share_level != "public":
                raise ValueError("talk records need talk info, org_id='conference' and share_level='public'")
        elif self.org_id == "conference":
            raise ValueError("only talk records may use org_id='conference'")
        if self.kind == "attendee":  # opt-in public directory card, stored in the conference index
            if self.owner_persona_id is None or self.share_level != "public":
                raise ValueError("attendee cards need owner_persona_id and share_level='public'")
            if self.profile is None or self.profile.visibility != "shareable":
                raise ValueError("attendee cards need a shareable profile")
        if self.kind == "followup" and self.followup is None:
            raise ValueError("followup records need followup info")
        if self.kind == "profile":
            if self.owner_persona_id is None:
                raise ValueError("profile records need owner_persona_id")
            if self.profile is not None and (self.profile.visibility == "private") != (
                self.share_level == "internal"
            ):
                raise ValueError("private profile <=> share_level 'internal'")
        return self


class PersonaProfile(Contract):
    """What a person has told their own agent. `private` is never visible to a delegate."""

    persona_id: str
    shareable: ProfileInfo | None = None
    private: ProfileInfo | None = None
    source_files: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------- search, ask, briefs
class Citation(Contract):
    memory_id: str
    title: str
    kind: MemoryKind
    snippet: str = Field(max_length=240)


class AskRequest(Contract):
    persona_id: str
    question: str = Field(max_length=500)


class AskAnswer(Contract):
    answer: str
    citations: list[Citation] = Field(default_factory=list, max_length=5)


class TalkHit(Contract):
    talk_id: str  # memory_id of the talk record
    title: str
    starts_at: datetime
    room: str
    track: str
    speakers: list[str] = Field(default_factory=list)
    reason: str | None = Field(default=None, max_length=160)


class TalkSearchResult(Contract):
    query: str
    talks: list[TalkHit] = Field(default_factory=list, max_length=10)


class BriefRequest(Contract):
    encounter_id: str
    persona_id: str
    counterparty_persona_id: str


class PrivateBrief(Contract):
    """Only for the owner's phone. May use internal memory and the private profile."""

    encounter_id: str
    persona_id: str
    counterparty_persona_id: str
    language: Language
    headline: str = Field(max_length=200)
    talking_points: list[str] = Field(default_factory=list, max_length=3)
    watch_outs: list[str] = Field(default_factory=list, max_length=2)
    goal_matches: list[str] = Field(default_factory=list, max_length=2)
    conversation_starters: list[str] = Field(default_factory=list, max_length=2)
    history: list[Citation] = Field(default_factory=list, max_length=3)
    suggested_talks: list[TalkHit] = Field(default_factory=list, max_length=2)


class SharedItem(Contract):
    from_org: str
    item_id: str
    title: str
    summary: str = Field(max_length=400)


class DeclinedAsk(Contract):
    from_org: str  # org whose delegate declined
    topic: str
    reason_code: Literal["policy_deny", "not_available"]
    rule_id: str | None = None


class SharedFollowup(Contract):
    followup_id: str
    text: str = Field(max_length=200)
    owner_org_id: str
    status: Literal["proposed", "confirmed"] = "proposed"


class SharedBrief(Contract):
    """Built by each delegate after round 3 for its own human, in that human's language."""

    encounter_id: str
    for_persona_id: str
    language: Language
    summary: str = Field(max_length=400)
    mutual_interests: list[str] = Field(default_factory=list)
    shared_items: list[SharedItem] = Field(default_factory=list)
    declined: list[DeclinedAsk] = Field(default_factory=list)
    followups: list[SharedFollowup] = Field(default_factory=list)
    suggested_talk: TalkHit | None = None


# --------------------------------------------------------------------------- discover: research, swipe, deep dive
class DiscoverFilters(Contract):
    interests: list[str] = Field(default_factory=list)  # any-of, tag slugs
    roles: list[str] = Field(default_factory=list)  # keywords matched against job titles
    org_ids: list[str] = Field(default_factory=list)
    looking_for: str | None = Field(default=None, max_length=200)  # free text, hybrid-searched
    has_agent: bool | None = None  # True: only people whose company runs Rapport agents
    language: Language | None = None


class ResearchRequest(Contract):
    persona_id: str  # the viewer
    filters: DiscoverFilters = Field(default_factory=DiscoverFilters)
    exclude_persona_ids: list[str] = Field(default_factory=list)  # already swiped
    limit: int = Field(default=10, ge=1, le=20)


class PersonCard(Contract):
    """One swipe card. Built by the VIEWER's briefer; only ever shown on the viewer's phone."""

    persona_id: str
    name: str
    title: str
    org_id: str
    org_name: str
    language: Language
    headline: str = Field(max_length=160)
    interests: list[str] = Field(default_factory=list, max_length=8)
    looking_for: list[str] = Field(default_factory=list, max_length=3)
    agent_available: bool
    match_score: int = Field(ge=0, le=100)
    shared_interests: list[str] = Field(default_factory=list)
    why_meet: str = Field(max_length=240)
    their_talks: list[TalkHit] = Field(default_factory=list, max_length=2)
    company_history: list[Citation] = Field(default_factory=list, max_length=2)  # viewer's own notes


class ResearchResult(Contract):
    persona_id: str
    cards: list[PersonCard] = Field(default_factory=list, max_length=20)


class SwipeBody(Contract):
    persona_id: str
    target_persona_id: str
    direction: Literal["left", "right"]
    autonomy: bool = True  # may my agent start an agent-to-agent handshake on its own?
    malicious: bool = False  # demo toggle, same meaning as ConnectBody.malicious


class ConversationPlan(Contract):
    goals: list[str] = Field(default_factory=list, max_length=3)
    offers: list[str] = Field(default_factory=list, max_length=3)  # titles of my shareable items
    questions: list[str] = Field(default_factory=list, max_length=3)
    watch_outs: list[str] = Field(default_factory=list, max_length=2)
    opener: str = Field(max_length=200)


class AgentDecision(Contract):
    action: Literal["agent_handshake", "human_intro", "skip"]
    reason: str = Field(max_length=240)
    confidence: float = Field(ge=0, le=1)
    checks: list[str] = Field(default_factory=list, max_length=6)  # guardrails and their outcomes


class DeepDiveRequest(Contract):
    persona_id: str
    target_persona_id: str


class DeepDive(Contract):
    """Private preparation for one person. Only for the viewer's phone; never sent to the swarm or a delegate."""

    persona_id: str
    target_persona_id: str
    language: Language
    summary: str = Field(max_length=400)
    plan: ConversationPlan
    decision: AgentDecision
    citations: list[Citation] = Field(default_factory=list, max_length=5)


# --------------------------------------------------------------------------- delegate exchange (pod <-> pod)
class Card(Contract):
    persona_id: str
    name: str
    title: str
    org_id: str
    org_name: str
    headline: str = Field(max_length=160)
    interests: list[str] = Field(default_factory=list, max_length=8)
    looking_for: list[str] = Field(default_factory=list, max_length=3)


class OfferItem(Contract):
    item_id: str
    kind: MemoryKind
    title: str
    summary: str = Field(max_length=400)
    tags: list[str] = Field(default_factory=list)
    share_level: Literal["public", "partner"]
    owner_persona_id: str | None = None


class Ask(Contract):
    ask_id: str
    topic: str = Field(pattern=TAG)
    text: str = Field(max_length=280)  # UNTRUSTED on receipt: data, never instructions


class Answer(Contract):
    ask_id: str
    status: Literal["answered", "declined"]
    item: OfferItem | None = None
    reason_code: Literal["policy_deny", "not_available"] | None = None
    rule_id: str | None = None

    @model_validator(mode="after")
    def _check(self) -> Answer:
        if self.status == "answered" and self.item is None:
            raise ValueError("answered requires item")
        if self.status == "declined" and (self.reason_code is None or self.item is not None):
            raise ValueError("declined requires reason_code and no item")
        return self


class FollowupProposal(Contract):
    followup_id: str
    text: str = Field(max_length=200)
    owner_side: Literal["initiator", "responder", "both"]
    talk_id: str | None = None


_ROUND_TYPES = {1: "hello", 2: "offers_asks", 3: "answers_followups"}


class ExchangeMessage(Contract):
    protocol: Literal["rapport.exchange/v1"] = PROTOCOL
    encounter_id: str
    round: Literal[1, 2, 3]
    type: Literal["hello", "offers_asks", "answers_followups"]
    from_org: str
    from_persona: str
    to_org: str
    to_persona: str
    sent_at: datetime = Field(default_factory=utcnow)
    card: Card | None = None  # round 1
    offers: list[OfferItem] = Field(default_factory=list, max_length=3)  # round 2
    asks: list[Ask] = Field(default_factory=list, max_length=2)  # round 2
    answers: list[Answer] = Field(default_factory=list, max_length=4)  # round 3
    followups: list[FollowupProposal] = Field(default_factory=list, max_length=3)  # round 3

    @model_validator(mode="after")
    def _check(self) -> ExchangeMessage:
        if _ROUND_TYPES[self.round] != self.type:
            raise ValueError(f"round {self.round} must have type {_ROUND_TYPES[self.round]}")
        if self.round == 1 and self.card is None:
            raise ValueError("round 1 (hello) requires card")
        if self.round != 1 and self.card is not None:
            raise ValueError("card only in round 1")
        if self.round != 2 and (self.offers or self.asks):
            raise ValueError("offers/asks only in round 2")
        if self.round != 3 and (self.answers or self.followups):
            raise ValueError("answers/followups only in round 3")
        return self


# --------------------------------------------------------------------------- policy (OPA)
class PolicyItem(Contract):
    item_id: str
    kind: MemoryKind
    share_level: ShareLevel
    tags: list[str] = Field(default_factory=list)
    owner_persona_id: str | None = None


class PolicyInput(Contract):
    action: Literal["offer", "answer"]
    org_id: str
    self_persona_id: str
    counterparty_org_id: str
    encounter_id: str
    item: PolicyItem


class PolicyDecision(Contract):
    decision: Literal["allow", "deny"]
    rule_id: str
    reason: str


# --------------------------------------------------------------------------- gateway HTTP bodies
class ConnectBody(Contract):
    from_persona_id: str
    to_persona_id: str
    malicious: bool = False  # demo toggle: the RESPONDER's delegate tries a prompt injection
    initiated_by: Literal["human", "agent"] = "human"


class AcceptBody(Contract):
    persona_id: str


class EncounterParty(Contract):
    orgId: str
    personaId: str
    malicious: bool = False


class EncounterSpec(Contract):
    """spec of the cluster-scoped Encounter custom resource (deploy/crds/encounter-crd.yaml)."""

    initiator: EncounterParty
    responder: EncounterParty
    ttlSeconds: int = Field(default=600, ge=60, le=3600)


# --------------------------------------------------------------------------- events
class ConnectRequestData(Contract):
    request_id: str
    from_persona_id: str
    to_persona_id: str
    malicious: bool = False
    initiated_by: Literal["human", "agent"] = "human"  # "agent": the target's phone says "Ava's agent..."


class DeepDiveStartedData(Contract):
    target_persona_id: str


class AgentDecisionData(Contract):
    """Swarm-safe: no reason or research content, just what the agent decided."""

    target_persona_id: str
    action: Literal["agent_handshake", "human_intro", "skip"]
    request_id: str | None = None  # set when the agent sent a connect request


class EncounterStartedData(Contract):
    initiator_persona_id: str
    responder_persona_id: str


class PodStatusData(Contract):
    org_id: str
    side: Literal["initiator", "responder"]
    pod: str
    phase: str  # Kubernetes pod phase: Pending, Running, Succeeded, Failed


class ExchangeMessageData(Contract):
    round: Literal[1, 2, 3]
    type: Literal["hello", "offers_asks", "answers_followups"]
    from_org: str
    to_org: str
    display: str = Field(max_length=200)  # one human-readable line for the swarm panel


class PolicyDecisionData(Contract):
    org_id: str
    action: Literal["offer", "answer"]
    item_id: str
    item_title: str
    decision: Literal["allow", "deny"]
    rule_id: str


class DelegateStatusData(Contract):
    side: Literal["initiator", "responder"]
    status: Literal["started", "done", "failed"]
    detail: str | None = None


class EncounterCompletedData(Contract):
    status: Literal["completed", "failed"]
    detail: str | None = None


GatewayEventType = Literal[
    "connect_request",
    "encounter_started",
    "pod_status",
    "exchange_message",
    "policy_decision",
    "private_brief",
    "shared_brief",
    "encounter_completed",
    "profile_updated",
    "deep_dive_started",
    "deep_dive_ready",
    "agent_decision",
    "error",
]

EVENT_DATA_MODELS: dict[str, type[Contract] | None] = {
    "deep_dive_started": DeepDiveStartedData,
    "deep_dive_ready": DeepDive,
    "agent_decision": AgentDecisionData,
    "connect_request": ConnectRequestData,
    "encounter_started": EncounterStartedData,
    "pod_status": PodStatusData,
    "exchange_message": ExchangeMessageData,
    "policy_decision": PolicyDecisionData,
    "private_brief": PrivateBrief,
    "shared_brief": SharedBrief,
    "encounter_completed": EncounterCompletedData,
    "profile_updated": PersonaProfile,
    "error": None,  # free-form {"message": str}
}


class GatewayEvent(Contract):
    """One SSE event from the gateway to the web page (SSE `event:` = type, `data:` = this JSON)."""

    type: GatewayEventType
    ts: datetime = Field(default_factory=utcnow)
    encounter_id: str | None = None
    persona_id: str | None = None  # target phone; None means the swarm panel / everyone
    trace_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> GatewayEvent:
        model = EVENT_DATA_MODELS[self.type]
        if model is not None:
            model.model_validate(self.data)
        return self


DelegateEventType = Literal["delegate_status", "exchange_message", "policy_decision", "shared_brief"]
_DELEGATE_DATA = {
    "delegate_status": DelegateStatusData,
    "exchange_message": ExchangeMessageData,
    "policy_decision": PolicyDecisionData,
    "shared_brief": SharedBrief,
}


class DelegateEvent(Contract):
    """POST /internal/events body: what delegates report to the gateway."""

    encounter_id: str
    org_id: str
    persona_id: str
    type: DelegateEventType
    data: dict[str, Any]

    @model_validator(mode="after")
    def _check(self) -> DelegateEvent:
        _DELEGATE_DATA[self.type].model_validate(self.data)
        return self
