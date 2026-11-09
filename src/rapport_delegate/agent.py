"""DelegateAgent: builds and receives the three rounds of rapport.exchange/v1 for one side of one encounter.

Same class for initiator and responder; the transport (initiator.py, responder.py) decides who speaks first.
Every dependency is injected: memory, policy, LLM, reporter. Nothing here touches the network itself.

Safety properties (each has a test):
- only `OfferItem`s built from a record's summary leave; `MemoryRecord.text` is never read here;
- every offer and answer passes the policy first; a denial is reported and the item dropped;
- peer strings (ask text, headline, item titles) are data: used as a search string or inside the LLM data block;
- LLM output may only reference candidate IDs.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Literal

from opentelemetry.context import Context

from rapport_common import names, telemetry
from rapport_common.models import (
    Answer,
    Ask,
    Card,
    DeclinedAsk,
    DelegateStatusData,
    ExchangeMessage,
    ExchangeMessageData,
    FollowupProposal,
    Language,
    MemoryRecord,
    OfferItem,
    PolicyDecision,
    PolicyDecisionData,
    PolicyInput,
    PolicyItem,
    SharedBrief,
    SharedFollowup,
)

from . import protocol as proto
from .config import DelegateConfig
from .instruments import DelegateMetrics
from .llm import BRIEF_SYSTEM, FOLLOWUP_SYSTEM, LLM, BriefText, FollowupPlan
from .memory import SelfMemory
from .policy import Policy
from .reporter import Reporter

log = logging.getLogger("rapport.delegate.agent")


class ProtocolError(Exception):
    """The peer broke the protocol. `status` is the HTTP status the responder answers with."""

    def __init__(self, detail: str, status: int = 422) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status = status


@dataclass
class ExchangeState:
    my_card: Card | None = None
    peer_card: Card | None = None
    my_offers: list[OfferItem] = field(default_factory=list)
    my_asks: list[Ask] = field(default_factory=list)
    peer_offers: list[OfferItem] = field(default_factory=list)
    peer_asks: list[Ask] = field(default_factory=list)
    my_answers: list[Answer] = field(default_factory=list)
    my_declined: list[DeclinedAsk] = field(default_factory=list)
    peer_answers: list[Answer] = field(default_factory=list)
    my_followups: list[FollowupProposal] = field(default_factory=list)
    peer_followups: list[FollowupProposal] = field(default_factory=list)
    chosen_talk: MemoryRecord | None = None
    review_items: dict[str, OfferItem] = field(default_factory=dict)  # followup_id -> item (rule-made follow-ups)


class DelegateAgent:
    def __init__(self, cfg: DelegateConfig, *, memory: SelfMemory, policy: Policy, llm: LLM, reporter: Reporter,
                 metrics: DelegateMetrics | None = None, root_context: Context | None = None) -> None:
        self.cfg = cfg
        self.memory = memory
        self.policy = policy
        self.llm = llm
        self.reporter = reporter
        self.metrics = metrics or DelegateMetrics()
        self.root_context = root_context  # parent for round spans when the root span is not the current one
        self.state = ExchangeState()
        self._persona = names.persona(cfg.self_persona)
        orgs = names.orgs()
        self._org_name = orgs[cfg.self_org].name
        self._peer_org_name = orgs[cfg.peer_org].name
        self._tracer = telemetry.tracer("rapport.delegate")

    # ------------------------------------------------------------------ plumbing
    @property
    def side(self) -> Literal["initiator", "responder"]:
        return self.cfg.role

    @contextmanager
    def round_span(self, number: int) -> Iterator[None]:
        attrs = {telemetry.ATTR_ROUND: number, telemetry.ATTR_SIDE: self.side,
                 telemetry.ATTR_ENCOUNTER: self.cfg.encounter_id}
        with self._tracer.start_as_current_span("exchange.round", context=self.root_context, attributes=attrs):
            yield

    def report_status(self, status: Literal["started", "done", "failed"], detail: str | None = None) -> None:
        data = DelegateStatusData(side=self.side, status=status, detail=detail)
        self.reporter.send("delegate_status", data.model_dump(mode="json"))

    def _envelope(self, round_: Literal[1, 2, 3], type_: Literal["hello", "offers_asks", "answers_followups"],
                  display: str, **body: Any) -> ExchangeMessage:
        msg = ExchangeMessage(
            encounter_id=self.cfg.encounter_id, round=round_, type=type_, from_org=self.cfg.self_org,
            from_persona=self.cfg.self_persona, to_org=self.cfg.peer_org, to_persona=self.cfg.peer_persona, **body,
        )
        data = ExchangeMessageData(round=round_, type=type_, from_org=msg.from_org, to_org=msg.to_org, display=display)
        self.reporter.send("exchange_message", data.model_dump(mode="json"))
        return msg

    def check_sender(self, msg: ExchangeMessage) -> None:
        """Encounter, sender and recipient must be exactly the configured peer pair. Runs before anything else,
        including a replay of a cached reply."""
        cfg = self.cfg
        if msg.encounter_id != cfg.encounter_id:
            raise ProtocolError("message is for another encounter", 403)
        if (msg.from_org, msg.from_persona, msg.to_org, msg.to_persona) != (
            cfg.peer_org, cfg.peer_persona, cfg.self_org, cfg.self_persona,
        ):
            raise ProtocolError("unexpected sender or recipient", 403)

    def _check_envelope(self, msg: ExchangeMessage, round_: int) -> None:
        self.check_sender(msg)
        if msg.round != round_:
            raise ProtocolError(f"expected round {round_}", 409)

    async def check(self, action: Literal["offer", "answer"], record: MemoryRecord) -> PolicyDecision:
        """Ask OPA (fail closed), count it, trace it, report it. IDs and decisions only."""
        policy_input = PolicyInput(
            action=action, org_id=self.cfg.self_org, self_persona_id=self.cfg.self_persona,
            counterparty_org_id=self.cfg.peer_org, encounter_id=self.cfg.encounter_id,
            item=PolicyItem(item_id=record.memory_id, kind=record.kind, share_level=record.share_level,
                            tags=list(record.tags), owner_persona_id=record.owner_persona_id),
        )
        attrs = {telemetry.ATTR_POLICY_ACTION: action, telemetry.ATTR_ITEM: record.memory_id}
        with self._tracer.start_as_current_span("policy.check", attributes=attrs) as span:
            decision = await self.policy.decide(policy_input)
            span.set_attribute(telemetry.ATTR_POLICY_DECISION, decision.decision)
            span.set_attribute(telemetry.ATTR_POLICY_RULE, decision.rule_id)
        self.metrics.record_decision(decision=decision.decision, rule_id=decision.rule_id, org_id=self.cfg.self_org)
        event = PolicyDecisionData(
            org_id=self.cfg.self_org, action=action, item_id=record.memory_id, item_title=record.title,
            decision=decision.decision, rule_id=decision.rule_id,
        )
        self.reporter.send("policy_decision", event.model_dump(mode="json"))
        return decision

    # ------------------------------------------------------------------ round 1: hello
    def receive_hello(self, msg: ExchangeMessage) -> None:
        self._check_envelope(msg, 1)
        card = msg.card
        if card is None or card.persona_id != self.cfg.peer_persona or card.org_id != self.cfg.peer_org:
            raise ProtocolError("card does not match the peer", 403)
        self.state.peer_card = card

    async def make_hello(self) -> ExchangeMessage:
        with self.round_span(1):
            profile = await self.memory.profile_card(self.cfg.self_persona)
            card = proto.build_card(self._persona, self._org_name, profile)
            self.state.my_card = card
            return self._envelope(1, "hello", proto.display_hello(self._org_name, card), card=card)

    # ------------------------------------------------------------------ round 2: offers and asks
    def receive_offers_asks(self, msg: ExchangeMessage) -> None:
        self._check_envelope(msg, 2)
        self.state.peer_offers = list(msg.offers)
        self.state.peer_asks = list(msg.asks)

    async def make_offers_asks(self) -> ExchangeMessage:
        st = self.state
        if st.my_card is None or st.peer_card is None:
            raise ProtocolError("round 1 has not happened", 409)
        with self.round_span(2):
            interests = list(st.peer_card.interests)
            offers: list[OfferItem] = []
            for record in await self.memory.search_offers(interests, " ".join(interests)):
                if len(offers) >= proto.MAX_OFFERS:
                    break
                if (await self.check("offer", record)).decision == "allow":
                    offers.append(proto.offer_from_record(record))
            vocab_query = " ".join(st.my_card.looking_for + st.my_card.interests)
            vocabulary = await self.memory.vocabulary(vocab_query)
            topics = proto.choose_ask_topics(st.my_card.looking_for, st.my_card.interests, vocabulary)
            asks = proto.build_asks(topics, self.side, self.cfg.malicious)
            st.my_offers, st.my_asks = offers, asks
            display = proto.display_offers_asks(self._org_name, len(offers), len(asks))
            return self._envelope(2, "offers_asks", display, offers=offers, asks=asks)

    # ------------------------------------------------------------------ round 3: answers and follow-ups
    def receive_answers_followups(self, msg: ExchangeMessage) -> None:
        self._check_envelope(msg, 3)
        known = {a.ask_id for a in self.state.my_asks}
        seen: set[str] = set()
        answers: list[Answer] = []
        for answer in msg.answers:
            if answer.ask_id in known and answer.ask_id not in seen:  # answers to asks we never made are dropped
                seen.add(answer.ask_id)
                answers.append(answer)
        self.state.peer_answers = answers
        self.state.peer_followups = list(msg.followups)

    async def make_answers_followups(self) -> ExchangeMessage:
        st = self.state
        if st.my_card is None or st.peer_card is None:
            raise ProtocolError("round 1 has not happened", 409)
        with self.round_span(3):
            answers, declined = [], []
            for ask in st.peer_asks[: proto.MAX_ASKS]:
                answer, miss = await self._answer(ask)
                answers.append(answer)
                if miss is not None:
                    declined.append(miss)
            st.my_answers, st.my_declined = answers, declined
            followups = await self._propose_followups()
            st.my_followups = followups
            answered = sum(1 for a in answers if a.status == "answered")
            display = proto.display_answers(self._org_name, answered, len(answers), len(followups))
            return self._envelope(3, "answers_followups", display, answers=answers, followups=followups)

    async def _answer(self, ask: Ask) -> tuple[Answer, DeclinedAsk | None]:
        # Tag match first; the ask text is only ever a search string, and only when no tag matches.
        candidates = await self.memory.ask_candidates(ask.topic, ask.text)
        if not candidates:
            miss = DeclinedAsk(from_org=self.cfg.self_org, topic=ask.topic, reason_code="not_available")
            return Answer(ask_id=ask.ask_id, status="declined", reason_code="not_available"), miss
        best = candidates[0]
        decision = await self.check("answer", best)
        if decision.decision == "allow":
            return Answer(ask_id=ask.ask_id, status="answered", item=proto.offer_from_record(best)), None
        miss = DeclinedAsk(from_org=self.cfg.self_org, topic=ask.topic, reason_code="policy_deny",
                           rule_id=decision.rule_id)
        answer = Answer(ask_id=ask.ask_id, status="declined", reason_code="policy_deny", rule_id=decision.rule_id)
        return answer, miss

    def _received_items(self) -> list[OfferItem]:
        items = list(self.state.peer_offers) + [a.item for a in self.state.peer_answers if a.item is not None]
        return list({i.item_id: i for i in items}.values())

    def _sent_items(self) -> list[OfferItem]:
        items = list(self.state.my_offers) + [a.item for a in self.state.my_answers if a.item is not None]
        return list({i.item_id: i for i in items}.values())

    def mutual(self) -> list[str]:
        st = self.state
        if st.my_card is None or st.peer_card is None:
            return []
        return proto.mutual_interests(st.my_card.interests, st.peer_card.interests)

    async def _propose_followups(self) -> list[FollowupProposal]:
        """Up to 3. One is always "attend <talk> together" (rapport-conference, mutual interests). The model may
        pick among candidates and word the others; the rules fill in when it cannot."""
        st = self.state
        enc = self.cfg.encounter_id
        talks = {t.memory_id: t for t in await self.memory.find_talks(self.mutual())}
        received, sent = self._received_items(), self._sent_items()
        candidate_items = {i.item_id: i for i in received + sent}
        data = {
            "language": "en",
            "mutual_interests": self.mutual(),
            "peer_headline": st.peer_card.headline if st.peer_card else "",
            "candidate_items": [{"item_id": i.item_id, "title": i.title, "summary": i.summary}
                                for i in candidate_items.values()],
            "candidate_talks": [{"talk_id": t.memory_id, "title": t.title} for t in talks.values()],
        }
        plan = await self.llm.parse(system=FOLLOWUP_SYSTEM, instruction="Propose the follow-ups.", data=data,
                                    schema=FollowupPlan) if candidate_items or talks else None

        talk = talks.get(plan.talk_id) if plan and plan.talk_id else None  # unknown talk ids are dropped
        talk = talk or next(iter(talks.values()), None)
        st.chosen_talk = talk
        proposals: list[FollowupProposal] = [proto.talk_proposal(enc, talk)] if talk else []

        drafts = [d for d in (plan.followups if plan else []) if d.text.strip()
                  and (d.item_id is None or d.item_id in candidate_items)]
        n = 1
        for draft in drafts[: proto.MAX_FOLLOWUPS - len(proposals)]:
            owner = {"me": self.side, "both": "both"}.get(draft.owner, "responder" if self.side == "initiator"
                                                                      else "initiator")
            fid = proto.followup_id(enc, self.side, n)
            proposals.append(FollowupProposal(followup_id=fid, text=proto.truncate(draft.text, 200), owner_side=owner))
            n += 1
        if len(proposals) < proto.MAX_FOLLOWUPS and not drafts:
            rules = proto.fallback_review_proposals(enc, self.side, self._peer_org_name, received,
                                                    limit=min(2, proto.MAX_FOLLOWUPS - len(proposals)))
            for proposal, item in zip(rules, received):
                st.review_items[proposal.followup_id] = item
            proposals.extend(rules)
        return proposals[: proto.MAX_FOLLOWUPS]

    # ------------------------------------------------------------------ after round 3: the SharedBrief
    async def build_shared_brief(self) -> SharedBrief:
        st = self.state
        enc, lang = self.cfg.encounter_id, self._persona.language
        mutual = self.mutual()
        items = proto.shared_items(self.cfg.self_org, self.cfg.peer_org, self._sent_items(), self._received_items())

        my_asks = {a.ask_id: a for a in st.my_asks}
        declined = list(st.my_declined)
        for answer in st.peer_answers:
            if answer.status == "declined" and answer.reason_code is not None:
                declined.append(DeclinedAsk(from_org=self.cfg.peer_org, topic=my_asks[answer.ask_id].topic,
                                            reason_code=answer.reason_code, rule_id=answer.rule_id))

        followups, talk = await self._brief_followups(lang)
        text = await self._brief_text(lang, items_count=len(items), declined_count=len(declined), mutual=mutual,
                                      item_titles=[i.title for i in items], followups=followups)
        followups = [f.model_copy(update={"text": text.translations.get(f.followup_id, f.text)}) for f in followups]
        suggested = proto.talk_hit(talk, f"Shared interests: {', '.join(mutual)}" if mutual else None) if talk else None
        return proto.build_shared_brief(
            encounter_id=enc, persona=self._persona, items=items, declined=declined, followups=followups,
            mutual=mutual, suggested_talk=suggested, summary=text.summary,
        )

    async def _brief_followups(self, lang: Language) -> tuple[list[SharedFollowup], MemoryRecord | None]:
        """Own and peer follow-ups, deduplicated. Talk follow-ups are rebuilt from our own agenda record."""
        st, cfg = self.state, self.cfg
        talk = st.chosen_talk
        out: dict[str, SharedFollowup] = {}
        peer_side = "responder" if cfg.role == "initiator" else "initiator"

        def owner_org(side: str) -> str:
            if side == "initiator":
                return cfg.initiator_org
            if side == "responder":
                return cfg.responder_org
            return cfg.self_org

        for proposal in st.my_followups:
            if proposal.talk_id and talk is not None:
                text = proto.talk_text(talk, lang)
            elif proposal.followup_id in st.review_items:
                text = proto.review_text(lang, st.review_items[proposal.followup_id].title,
                                         self._peer_org_name)
            else:
                text = proposal.text
            out[proposal.followup_id] = SharedFollowup(
                followup_id=proposal.followup_id, text=text, owner_org_id=owner_org(proposal.owner_side))

        for n, proposal in enumerate(st.peer_followups[: proto.MAX_FOLLOWUPS], start=1):
            if proposal.talk_id:  # the ID must exist in OUR agenda; otherwise the proposal is dropped
                record = await self.memory.get_talk(proposal.talk_id)
                if record is None:
                    continue
                fid = proto.talk_followup_id(cfg.encounter_id)
                if fid not in out:
                    talk = talk or record
                    st.chosen_talk = talk
                    out[fid] = SharedFollowup(followup_id=fid, text=proto.talk_text(talk, lang),
                                              owner_org_id=cfg.self_org)
                continue
            fid = proto.followup_id(cfg.encounter_id, peer_side, n)
            out.setdefault(fid, SharedFollowup(followup_id=fid, text=proto.truncate(proposal.text, 200),
                                               owner_org_id=owner_org(proposal.owner_side)))
        return list(out.values()), talk

    async def _brief_text(self, lang: Language, *, items_count: int, declined_count: int, mutual: list[str],
                          item_titles: list[str], followups: list[SharedFollowup]) -> _BriefParts:
        fallback = proto.fallback_summary(lang, self._peer_org_name, items_count, declined_count,
                                          len(followups), mutual)
        translatable = [f for f in followups if f.followup_id != proto.talk_followup_id(self.cfg.encounter_id)
                        and f.followup_id not in self.state.review_items]
        data = {
            "language": lang, "counts": {"items": items_count, "declined": declined_count,
                                         "followups": len(followups)},
            "peer_company": self._peer_org_name, "mutual_interests": mutual, "item_titles": item_titles,
            "followups": [{"followup_id": f.followup_id, "text": f.text} for f in translatable] if lang != "en" else [],
        }
        result = await self.llm.parse(system=BRIEF_SYSTEM, instruction=f"Write the summary in language '{lang}'.",
                                      data=data, schema=BriefText)
        if result is None or not result.summary.strip():
            return _BriefParts(fallback, {})
        allowed = {f.followup_id for f in translatable} if lang != "en" else set()
        translations = {t.followup_id: proto.truncate(t.text, 200) for t in result.translations
                        if t.followup_id in allowed and t.text.strip()}
        return _BriefParts(proto.truncate(result.summary, 400), translations)


@dataclass
class _BriefParts:
    summary: str
    translations: dict[str, str]
