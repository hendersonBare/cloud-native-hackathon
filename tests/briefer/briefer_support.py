"""Shared helpers for the briefer tests: fixture records (the SPEC 11 storyline), a recording fake LLM, an
in-process client and a tiny PDF writer. No network, no Elasticsearch, no OpenAI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx

from rapport_briefer.app import create_app
from rapport_common import names
from rapport_common.interfaces import InMemoryStore
from rapport_common.models import MemoryRecord, ProfileInfo, SourceRef, TalkInfo

SEED = SourceRef(type="seed")
DAY = (2026, 11, 9)  # MST = UTC-7


def at(hour_mst: int, minute: int = 0) -> datetime:
    return datetime(*DAY, tzinfo=timezone.utc) + timedelta(hours=hour_mst + 7, minutes=minute)


def talk(mid: str, title: str, hour: int, minute: int, room: str, track: str, tags: list[str], speakers=(), about=()):
    return MemoryRecord(
        memory_id=mid,
        org_id="conference",
        share_level="public",
        kind="talk",
        title=title,
        text=f"{title}. Track {track}.",
        summary=f"{title} in {room}",
        tags=tags,
        about_persona_ids=list(about),
        source=SourceRef(type="conference"),
        talk=TalkInfo(
            starts_at=at(hour, minute), ends_at=at(hour + 1, minute), room=room, speakers=list(speakers), track=track
        ),
    )


def doc(mid: str, org: str, title: str, level: str, tags: list[str], summary: str = "", text: str = "") -> MemoryRecord:
    return MemoryRecord(
        memory_id=mid,
        org_id=org,
        share_level=level,
        kind="document",
        title=title,
        text=text or f"{title}. Long text of the document.",
        summary=summary or f"Summary of {title}",
        tags=tags,
        source=SEED,
    )


HEADLINES = {
    "bluefin.bo": "Platform lead moving 300 hospital services to Kubernetes",
    "lumenly.priya": "Runs a lean platform team; wants cheaper visibility",
    "kestrel.mia": "Tracing Kubernetes clusters on warehouse robots",
    "harborline.lena": "SRE manager evaluating observability vendors",
}


def attendee_cards() -> list[MemoryRecord]:
    out = []
    for pid, p in names.personas().items():
        headline = HEADLINES.get(pid, f"{p.title} at {names.orgs()[p.org_id].name}")
        out.append(
            MemoryRecord(
                memory_id=names.attendee_card_id(pid),
                org_id=p.org_id,
                share_level="public",
                kind="attendee",
                title=f"{p.name}, {p.title}",
                text=f"{headline}. Looking for: {'; '.join(p.goals)}",
                summary=headline,
                tags=p.interests,
                owner_persona_id=pid,
                source=SEED,
                profile=ProfileInfo(visibility="shareable", headline=headline, interests=p.interests, goals=p.goals),
            )
        )
    return out


def records() -> list[MemoryRecord]:
    agenda = [
        talk(
            "talk-ebpf-zero-code",
            "Zero-code tracing with eBPF on Kubernetes",
            15,
            30,
            "Room B",
            "Observability",
            ["ebpf", "observability", "kubernetes"],
            ["Dana"],
        ),
        talk(
            "talk-ebpf-cost",
            "Cutting the cloud bill with eBPF",
            14,
            30,
            "Room A",
            "Cost",
            ["ebpf", "cost", "kubernetes"],
            ["Priya"],
            ["lumenly.priya"],
        ),
        talk(
            "talk-ebpf-edge",
            "eBPF on warehouse robots",
            16,
            0,
            "Room C",
            "Edge",
            ["ebpf", "edge", "kubernetes"],
            ["Mia"],
            ["kestrel.mia"],
        ),
        talk(
            "talk-otel-regulated",
            "OpenTelemetry in regulated industries",
            13,
            30,
            "Room B",
            "OpenTelemetry",
            ["opentelemetry", "compliance", "observability"],
            ["Lena"],
            ["harborline.lena"],
        ),
        talk(
            "talk-inclusive-confs",
            "Designing conferences for everyone",
            16,
            30,
            "Room A",
            "Accessibility",
            ["accessibility", "community"],
            ["Tom"],
            ["lumenly.tom"],
        ),
        talk("talk-hipaa", "HIPAA for platform teams", 15, 0, "Room C", "Security", ["hipaa", "security"], ["Kim"]),
    ]
    acme_shareable = [
        doc("acme-doc-0001", "acme", "Acme product one-pager", "public", ["ebpf", "observability", "product"]),
        doc(
            "acme-doc-0002",
            "acme",
            "Case study: hospital network (40% faster incidents)",
            "public",
            ["healthcare", "ebpf", "case-study"],
        ),
        doc("acme-doc-0003", "acme", "Security whitepaper", "partner", ["security", "hipaa", "compliance"]),
        doc("acme-doc-0004", "acme", "Pricing overview 2026", "partner", ["pricing"]),
        doc("acme-doc-0005", "acme", "Acme at the conference: booth 12, demo times", "public", ["conference"]),
    ]
    acme_internal = [
        MemoryRecord(
            memory_id="acme-note-0007",
            org_id="acme",
            share_level="internal",
            kind="account_note",
            title="Call notes: Bluefin pilot (March)",
            text="Sam promised Kai the security questionnaire before the pilot starts. Bluefin is also evaluating a "
            "competitor. Budget decision in Q1.",
            summary="Sam promised Kai the security questionnaire before the pilot. Competitor in the mix.",
            tags=["bluefin", "pilot"],
            about_org_ids=["bluefin"],
            about_persona_ids=["bluefin.kai", "bluefin.bo"],
            source=SEED,
        ),
        doc("acme-doc-0008", "acme", "Discount approvals (internal)", "internal", ["pricing"]),
    ]
    bluefin = [
        doc(
            "bluefin-doc-0001",
            "bluefin",
            "Platform requirements (summary)",
            "partner",
            ["platform-engineering", "kubernetes", "requirements"],
        ),
        doc(
            "bluefin-doc-0002",
            "bluefin",
            "Engineering blog: our Kubernetes migration",
            "public",
            ["kubernetes", "platform-engineering"],
        ),
        MemoryRecord(
            memory_id="bluefin-note-0003",
            org_id="bluefin",
            share_level="internal",
            kind="account_note",
            title="Vendor evaluation: Acme",
            text="Likes Acme's zero-code eBPF approach; Kai must sign off on HIPAA; cost is the main concern.",
            summary="Likes zero-code eBPF; Kai signs off on HIPAA; cost is the concern.",
            tags=["acme"],
            about_org_ids=["acme"],
            source=SEED,
        ),
    ]
    return [*agenda, *attendee_cards(), *acme_shareable, *acme_internal, *bluefin]


def fresh_store(extra: list[MemoryRecord] | None = None) -> InMemoryStore:
    return InMemoryStore([*records(), *(extra or [])])


# --------------------------------------------------------------------------------------------- fake LLM
@dataclass
class Call:
    system: str
    user: str
    schema: type
    timeout: float


class FakeLLM:
    """Records every prompt. `responses` maps a schema class name to an instance, or to a function of the user
    message returning one. Anything unmapped returns None, exactly like the real wrapper without a key."""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[Call] = []

    async def parse(self, *, system: str, user: str, schema: type, timeout: float = 8.0):
        self.calls.append(Call(system, user, schema, timeout))
        r = self.responses.get(schema.__name__)
        return r(user) if isinstance(r, Callable) else r

    @property
    def prompts(self) -> str:
        return "\n".join(f"{c.system}\n{c.user}" for c in self.calls)


def client(org: str = "acme", store=None, llm=None) -> httpx.AsyncClient:
    app = create_app(org, store if store is not None else fresh_store(), llm if llm is not None else FakeLLM())
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://briefer")


# --------------------------------------------------------------------------------------------- tiny PDF
def make_pdf(text: str | None) -> bytes:
    """A one-page PDF. `text=None` gives a page with no text at all (like a scan)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode() if text else b""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out
