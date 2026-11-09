"""Company documents and notes for the demo storyline (SPEC section 11). All content is fictional.

Summaries are what a delegate may send to another company, so each one is safe to share. Internal records
(acme-note-0007, acme-doc-0008, bluefin-note-0003) are never shareable; the policy and the index routing keep them
private, and their summaries are written as if they could leak anyway.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from rapport_common.models import MemoryRecord, SourceRef

from .seed_talks import DENVER, conference_day


def doc_records(now: datetime | None = None) -> list[MemoryRecord]:
    day = conference_day(now)
    base = datetime.combine(day, time(7, 0), tzinfo=DENVER).astimezone(timezone.utc)
    seed = SourceRef(type="seed")

    def rec(memory_id, org, level, kind, title, text, summary, tags, about_orgs=(), about_people=(), minute=0):
        return MemoryRecord(
            memory_id=memory_id, org_id=org, share_level=level, kind=kind, title=title, text=text,
            summary=summary, tags=list(tags), about_org_ids=list(about_orgs), about_persona_ids=list(about_people),
            created_at=base + timedelta(minutes=minute), source=seed,
        )

    return [
        # ---- Acme, shareable ------------------------------------------------------------------------------
        rec(
            "acme-doc-0001", "acme", "public", "document", "Acme product one-pager",
            "Acme Observability sells an eBPF-based agent that traces every service on a Kubernetes cluster with "
            "no code changes. It exports OpenTelemetry data, runs at low overhead and installs with one Helm "
            "chart. Teams use it to get observability coverage for legacy and third-party services in a day.",
            "Acme's eBPF agent gives zero-code observability for Kubernetes services and exports OpenTelemetry "
            "data at low overhead.",
            ["ebpf", "observability", "product"], minute=1,
        ),
        rec(
            "acme-doc-0002", "acme", "public", "document", "Case study: hospital network (40% faster incidents)",
            "A regional hospital network deployed Acme across 300 services on Kubernetes. Incident resolution "
            "became 40% faster because engineers could see every request path without waiting for code "
            "changes. The security team approved the rollout after reviewing Acme's HIPAA documentation.",
            "A hospital network cut incident time by 40% using Acme's zero-code eBPF tracing across 300 "
            "Kubernetes services.",
            ["healthcare", "ebpf", "case-study"], minute=2,
        ),
        rec(
            "acme-doc-0003", "acme", "partner", "document", "Security whitepaper",
            "Acme's security whitepaper describes how the agent handles data: telemetry stays in the customer's "
            "cloud, payloads are never captured, access is role based and all actions are audit logged. It maps "
            "controls to HIPAA safeguards and lists the compliance reports available under NDA.",
            "How Acme secures telemetry and maps its controls to HIPAA; compliance reports available under NDA.",
            ["security", "hipaa", "compliance"], minute=3,
        ),
        rec(
            "acme-doc-0004", "acme", "partner", "document", "Pricing overview 2026",
            "Acme 2026 pricing: Team plan is billed per monitored host with a monthly minimum, Enterprise adds "
            "single sign-on, audit export and premium support. Volume tiers start at 100 hosts. List prices "
            "are fictional placeholders for the demo. Discounts require internal approval.",
            "Overview of Acme's 2026 plan tiers and how usage-based pricing works; contact sales for a quote.",
            ["pricing"], minute=4,
        ),
        rec(
            "acme-doc-0005", "acme", "public", "document", "Acme at the conference: booth 12, demo times",
            "Visit Acme at booth 12. Live demos run at 2:00 PM, 3:00 PM and 4:00 PM Mountain Time. Ask for a "
            "walkthrough of zero-code tracing on a sample Kubernetes app, or book a follow-up conversation.",
            "Acme is at booth 12 with live demos at 2:00, 3:00 and 4:00 PM Mountain Time.",
            ["conference"], minute=5,
        ),
        # ---- Acme, internal -------------------------------------------------------------------------------
        rec(
            "acme-note-0007", "acme", "internal", "account_note", "Call notes: Bluefin pilot (March)",
            "Sam promised Kai the security questionnaire before the pilot starts. Bluefin is also evaluating a "
            "competitor. Budget decision in Q1.",
            "What we promise Bluefin: Sam owes Kai the security questionnaire before the pilot starts.",
            ["bluefin", "pilot", "account"], ["bluefin"], ["bluefin.kai", "bluefin.bo"], minute=7,
        ),
        rec(
            "acme-doc-0008", "acme", "internal", "document", "Discount approvals (internal)",
            "Internal discount approval matrix (fictional): up to 10% by an account executive, up to 20% by the "
            "sales director, anything above needs the CFO. Pilot discounts are approved case by case.",
            "Internal discount approval levels. Not for sharing.",
            ["pricing"], minute=8,
        ),
        # ---- Bluefin, shareable ---------------------------------------------------------------------------
        rec(
            "bluefin-doc-0001", "bluefin", "partner", "document", "Platform requirements (summary)",
            "Bluefin's platform team needs observability for about 300 services moving to Kubernetes: no "
            "application code changes, data stays in Bluefin's cloud account, HIPAA-aligned access control and "
            "predictable cost. Candidates must document their security controls.",
            "Bluefin's requirements for platform tooling on Kubernetes: no code changes, data residency, HIPAA "
            "controls and predictable cost.",
            ["platform-engineering", "kubernetes", "requirements"], minute=10,
        ),
        rec(
            "bluefin-doc-0002", "bluefin", "public", "document", "Engineering blog: our Kubernetes migration",
            "How Bluefin's platform team is moving hospital services from virtual machines to Kubernetes: the "
            "golden-path templates, the staged migration order and what they would do differently.",
            "Bluefin's engineering blog on its staged Kubernetes migration and platform-engineering lessons.",
            ["kubernetes", "platform-engineering"], minute=11,
        ),
        # ---- Bluefin, internal ----------------------------------------------------------------------------
        rec(
            "bluefin-note-0003", "bluefin", "internal", "account_note", "Vendor evaluation: Acme",
            "Likes Acme's zero-code eBPF approach; Kai must sign off on HIPAA; cost is the main concern.",
            "Internal vendor evaluation of Acme. Not for sharing.",
            ["vendor-evaluation", "acme"], ["acme"], minute=12,
        ),
    ]
