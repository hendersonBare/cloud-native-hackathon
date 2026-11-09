"""Profile cards and attendee directory cards, derived from rapport_common/data/personas.json. All fictional.

- profile-<persona>-shareable (public) and profile-<persona>-private (internal) for the four agent personas.
  The delegate builds its Card from the shareable card: headline, interests and up to 3 goals as looking_for.
  Shareable goals are concrete phrases whose topic words are tags in the corpus, so asks land on real documents.
- attendee-<persona> (names.attendee_card_id) for all 12 personas: the opt-in directory the Discover tab searches.
  Headlines for Bo, Priya, Mia and Lena match contracts/demo-research.json.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from rapport_common import names
from rapport_common.models import MemoryRecord, ProfileInfo, SourceRef

from .seed_talks import DENVER, conference_day

# persona_id -> (headline, goals (up to 5; the first 3 become `looking_for`), highlights, extra text)
_SHAREABLE: dict[str, tuple[str, list[str], list[str], str]] = {
    "acme.ava": (
        "Solutions engineer helping platform teams adopt zero-code eBPF tracing",
        [
            "Meet platform-engineering teams evaluating eBPF tracing",
            "Learn from Kubernetes migrations in regulated industries",
            "Compare notes with OpenTelemetry users",
        ],
        ["Rolled out eBPF tracing for hospital and fintech customers", "Speaks about observability on Kubernetes"],
        "Ava works with customers to get tracing on every service without touching application code.",
    ),
    "acme.sam": (
        "Account executive for healthcare platform teams",
        ["Meet healthcare platform-engineering leads", "Find hospital teams modernising on Kubernetes"],
        ["Supports hospital network accounts"],
        "Sam helps healthcare organisations choose observability tooling that passes security review.",
    ),
    "bluefin.bo": (
        "Platform lead moving 300 hospital services to Kubernetes",
        [
            "Tracing with no code changes",
            "Lower observability costs",
            "Security and HIPAA answers for our compliance review",
        ],
        ["Leads the Kubernetes migration of 300 hospital services", "Cares about predictable observability cost"],
        "Bo leads platform engineering at a hospital network and is choosing tracing for hundreds of services.",
    ),
    "bluefin.kai": (
        "Security architect reviewing vendors against HIPAA requirements",
        ["Vendors with clear HIPAA security documentation", "Compliance evidence for observability tooling"],
        ["Signs off on vendor security reviews"],
        "Kai reviews every new vendor against HIPAA safeguards before a pilot can start.",
    ),
    "kestrel.mia": (
        "Tracing Kubernetes clusters on warehouse robots",
        ["Low-overhead tracing for edge clusters"],
        ["Runs small Kubernetes clusters on robots"],
        "Mia debugs fleets of warehouse robots and needs tracing with a tiny overhead budget.",
    ),
    "kestrel.raj": (
        "CTO building warehouse robots; hiring platform engineers",
        ["Hire platform engineers", "Talk to teams running AI agents in production"],
        ["Hiring across platform and robotics"],
        "Raj leads engineering at a robotics maker and is growing the platform team.",
    ),
    "harborline.lena": (
        "SRE manager evaluating observability vendors",
        ["Reduce incident time", "Evaluate observability vendors"],
        ["Rolled out OpenTelemetry under compliance review"],
        "Lena manages SRE at a regional bank and compares observability vendors this quarter.",
    ),
    "harborline.omar": (
        "Security engineer rolling out zero-trust networking",
        ["Roll out zero-trust networking"],
        ["Leads zero-trust adoption"],
        "Omar designs network policy and identity controls for a bank's internal platform.",
    ),
    "tidewater.sofia": (
        "Platform lead cutting the cloud bill by 30%",
        ["Cut the cloud bill by 30%"],
        ["Runs the FinOps programme"],
        "Sofia leads the platform at a freight company and tracks cloud cost per team.",
    ),
    "tidewater.ken": (
        "Data engineer improving search over shipment records",
        ["Improve search over shipment records"],
        ["Builds search over shipment data"],
        "Ken works on search relevance for shipment records.",
    ),
    "lumenly.priya": (
        "Runs a lean platform team; wants cheaper visibility",
        ["Cut cloud spend without losing visibility"],
        ["Speaking on eBPF and cloud cost"],
        "Priya runs infrastructure for an energy start-up and wants cheaper observability without blind spots.",
    ),
    "lumenly.tom": (
        "Developer advocate making community events inclusive",
        ["Make community events more inclusive"],
        ["Speaking on accessible conferences"],
        "Tom organises community events and shares accessibility practices.",
    ),
}

# The four agent personas also have a private view (never visible to a delegate).
_PRIVATE: dict[str, tuple[str, list[str], list[str]]] = {
    "acme.ava": (
        "Wants a healthcare design partner and a reference customer this quarter",
        [
            "Find a healthcare design partner this quarter",
            "Win a reference customer before Q1 planning",
            "Get the Bluefin security questionnaire answered",
        ],
        ["Pilot with Bluefin is the best lead", "Competitor is also in the running at Bluefin"],
    ),
    "acme.sam": (
        "Needs to close the Bluefin pilot before the Q1 budget decision",
        ["Close the Bluefin pilot", "Send Kai the security questionnaire"],
        ["Promised Kai the questionnaire before the pilot starts"],
    ),
    "bluefin.bo": (
        "Needs a vendor decision before the Q1 budget; cost is the main concern",
        ["Cut observability costs", "Find tracing that needs no code changes", "Decide on a vendor before Q1"],
        ["Kai must approve any vendor on HIPAA"],
    ),
    "bluefin.kai": (
        "Will not approve a pilot without HIPAA evidence",
        ["Approve vendors that meet HIPAA requirements", "Get Acme's security questionnaire"],
        ["Waiting on Acme's security questionnaire"],
    ),
}


def shareable_profile(persona_id: str) -> ProfileInfo:
    headline, goals, highlights, _ = _SHAREABLE[persona_id]
    return ProfileInfo(
        visibility="shareable", headline=headline, interests=list(names.persona(persona_id).interests),
        goals=list(goals), highlights=list(highlights),
    )


def private_profile(persona_id: str) -> ProfileInfo:
    headline, goals, highlights = _PRIVATE[persona_id]
    return ProfileInfo(
        visibility="private", headline=headline, interests=list(names.persona(persona_id).interests),
        goals=list(goals), highlights=list(highlights),
    )


def _profile_text(persona_id: str, profile: ProfileInfo, extra: str) -> str:
    p = names.persona(persona_id)
    parts = [f"{p.name}, {p.title}. {profile.headline}."]
    if extra:
        parts.append(extra)
    parts.append("Interests: " + ", ".join(profile.interests) + ".")
    if profile.goals:
        parts.append("Goals: " + "; ".join(profile.goals) + ".")
    if profile.highlights:
        parts.append("Highlights: " + "; ".join(profile.highlights) + ".")
    return " ".join(parts)


def profile_records(now: datetime | None = None) -> list[MemoryRecord]:
    base = datetime.combine(conference_day(now), time(8, 0), tzinfo=DENVER).astimezone(timezone.utc)
    out = []
    for i, persona_id in enumerate(_PRIVATE):
        person = names.persona(persona_id)
        views = (("shareable", shareable_profile(persona_id)), ("private", private_profile(persona_id)))
        for visibility, info in views:
            shareable = visibility == "shareable"
            out.append(
                MemoryRecord(
                    memory_id=f"profile-{persona_id}-{visibility}", org_id=person.org_id,
                    share_level="public" if shareable else "internal", kind="profile",
                    title=f"{person.name}: {visibility} profile",
                    text=_profile_text(persona_id, info, _SHAREABLE[persona_id][3] if shareable else ""),
                    # No tags on purpose: a delegate answers an ask by tag, and a profile must never be a candidate.
                    summary=info.headline, tags=[], owner_persona_id=persona_id,
                    created_at=base + timedelta(minutes=i), source=SourceRef(type="seed"), profile=info,
                )
            )
    return out


def attendee_records(now: datetime | None = None) -> list[MemoryRecord]:
    base = datetime.combine(conference_day(now), time(8, 30), tzinfo=DENVER).astimezone(timezone.utc)
    orgs = names.orgs()
    out = []
    for i, persona_id in enumerate(_SHAREABLE):
        person = names.persona(persona_id)
        info = shareable_profile(persona_id)
        looking = "; ".join(info.goals[:3])
        summary = f"{info.headline}. Interests: {', '.join(info.interests)}. Looking for: {looking}."
        out.append(
            MemoryRecord(
                memory_id=names.attendee_card_id(persona_id), org_id=person.org_id, share_level="public",
                kind="attendee", title=f"{person.name}, {person.title} at {orgs[person.org_id].name}",
                text=_profile_text(persona_id, info, _SHAREABLE[persona_id][3]), summary=summary[:400],
                tags=list(info.interests), owner_persona_id=persona_id, created_at=base + timedelta(minutes=i),
                source=SourceRef(type="seed"), profile=info,
            )
        )
    return out
