"""Fixture copies of the SPEC 11 records (synthetic). Every `text` carries a marker so a leak is detectable."""

from __future__ import annotations

from datetime import datetime, timezone

from rapport_common.interfaces import InMemoryStore
from rapport_common.models import MemoryRecord, ProfileInfo, TalkInfo
from rapport_delegate.config import DelegateConfig
from rapport_delegate.llm import NullLLM
from rapport_delegate.policy import FakePolicy
from rapport_delegate.reporter import RecordingSink, Reporter

TEXT_MARK = "FULLTEXT-DO-NOT-SEND"
ENC = "enc-test0001"


def doc(memory_id, org, level, title, tags, kind="document", summary=None, owner=None, **extra):
    return MemoryRecord(
        memory_id=memory_id, org_id=org, share_level=level, kind=kind, title=title,
        text=f"{TEXT_MARK} {memory_id} full body of {title}",
        summary=summary or f"Summary of {title}.", tags=tags, owner_persona_id=owner,
        source={"type": "seed"}, **extra,
    )


def talk(memory_id, title, tags, hour_utc, room="Room B", track="Observability"):
    start = datetime(2026, 11, 9, hour_utc, 30, tzinfo=timezone.utc)
    return MemoryRecord(
        memory_id=memory_id, org_id="conference", share_level="public", kind="talk", title=title,
        text=f"{TEXT_MARK} {memory_id}", summary=f"Talk: {title}", tags=tags, source={"type": "conference"},
        talk=TalkInfo(starts_at=start, ends_at=start.replace(hour=hour_utc + 1), room=room, speakers=["R. Alvarez"],
                      track=track),
    )


def profile(persona_id, org, headline, interests, goals, visibility="shareable"):
    return MemoryRecord(
        memory_id=f"profile-{persona_id}-{visibility}", org_id=org,
        share_level="public" if visibility == "shareable" else "internal", kind="profile",
        title=f"Profile {persona_id}", text=f"{TEXT_MARK} profile {persona_id}", summary=headline,
        owner_persona_id=persona_id, source={"type": "seed"},
        profile=ProfileInfo(visibility=visibility, headline=headline, interests=interests, goals=goals),
    )


def seed_records() -> list[MemoryRecord]:
    return [
        talk("talk-ebpf-zero-code", "Zero-code tracing with eBPF on Kubernetes",
             ["ebpf", "observability", "kubernetes"], 22),
        talk("talk-finops", "Cutting the cloud bill", ["cost", "finops"], 20, room="Room A", track="Cost"),
        doc("acme-doc-0001", "acme", "public", "Acme product one-pager", ["ebpf", "observability", "product"]),
        doc("acme-doc-0002", "acme", "public", "Case study: hospital network (40% faster incidents)",
            ["healthcare", "ebpf", "case-study"]),
        doc("acme-doc-0003", "acme", "partner", "Security whitepaper", ["security", "hipaa", "compliance"]),
        doc("acme-doc-0004", "acme", "partner", "Pricing overview 2026", ["pricing"]),
        doc("acme-doc-0005", "acme", "public", "Acme at the conference: booth 12, demo times", ["conference"]),
        doc("acme-doc-0008", "acme", "internal", "Discount approvals (internal)", ["pricing"]),
        doc("acme-note-0007", "acme", "internal", "Call notes: Bluefin pilot (March)", ["bluefin"],
            kind="account_note", about_org_ids=["bluefin"]),
        doc("bluefin-doc-0001", "bluefin", "partner", "Platform requirements (summary)",
            ["platform-engineering", "kubernetes", "requirements"]),
        doc("bluefin-doc-0002", "bluefin", "public", "Engineering blog: our Kubernetes migration",
            ["kubernetes", "platform-engineering"]),
        doc("bluefin-note-0003", "bluefin", "internal", "Vendor evaluation: Acme", ["acme"], kind="account_note",
            about_org_ids=["acme"]),
        profile("acme.ava", "acme", "Solutions engineer helping platform teams adopt eBPF tracing",
                ["ebpf", "observability", "opentelemetry", "kubernetes"],
                ["Meet platform teams evaluating eBPF tracing", "Find a design partner in healthcare"]),
        profile("acme.ava", "acme", "PRIVATE headline", ["secret"], ["find a healthcare design partner"],
                visibility="private"),
        profile("bluefin.bo", "bluefin", "Plataforma en Bluefin: Kubernetes y costos",
                ["kubernetes", "ebpf", "cost", "platform-engineering"],
                ["Cut observability costs", "Find tracing that needs no code changes"]),
    ]


def make_config(role, *, malicious=False, peer_url="http://peer.test") -> DelegateConfig:
    initiator = role == "initiator"
    return DelegateConfig(
        role=role, encounter_id=ENC,
        self_org="acme" if initiator else "bluefin", self_persona="acme.ava" if initiator else "bluefin.bo",
        peer_org="bluefin" if initiator else "acme", peer_persona="bluefin.bo" if initiator else "acme.ava",
        peer_url=peer_url if initiator else None, malicious=malicious, traceparent=None, port=8080,
    )


class Side:
    """One delegate's injected dependencies, with a recorder for the gateway."""

    def __init__(self, cfg: DelegateConfig, *, llm=None, policy=None, records=None) -> None:
        self.cfg = cfg
        self.store = InMemoryStore(records if records is not None else seed_records())
        self.policy = policy or FakePolicy()
        self.llm = llm or NullLLM()
        self.sink = RecordingSink()
        self.reporter = Reporter(self.sink, encounter_id=cfg.encounter_id, org_id=cfg.self_org,
                                 persona_id=cfg.self_persona)

    def kwargs(self):
        return dict(store=self.store, policy=self.policy, llm=self.llm, reporter=self.reporter)
