"""Conference agenda seed (SPEC section 11 and docs/FEATURE-DISCOVER.md). All talks and speakers are fictional.

Times are wall-clock America/Denver on the day seed_records() runs; they are stored as aware UTC.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from rapport_common.models import MemoryRecord, SourceRef, TalkInfo
from rapport_common.names import CONFERENCE_ORG

DENVER = ZoneInfo("America/Denver")
DAY_START = time(13, 0)  # 1:00 PM
DAY_END = time(17, 30)  # 5:30 PM
HEADLINE_TALK = "talk-ebpf-zero-code"
TALK_MINUTES = 30

# (memory_id, title, "H:MM" 24h start, room, track, speakers, about_persona_ids, tags, summary, text)
_TALKS: list[tuple[str, str, str, str, str, list[str], list[str], list[str], str, str]] = [
    (
        "talk-platform-golden-paths", "Golden paths: platform engineering developers actually use", "13:00", "Room A",
        "Platform Engineering", ["Imani"], [], ["platform-engineering", "kubernetes", "developer-experience"],
        "How a small platform team shipped paved roads for deployment and what made developers adopt them.",
        "Imani walks through three golden paths for service creation, deployment and rollback, and the "
        "adoption metrics that told the platform team which paths were working.",
    ),
    (
        "talk-hipaa-k8s", "HIPAA-ready Kubernetes: what auditors ask for", "13:00", "Room B",
        "Security and HIPAA", ["Jonas"], [], ["hipaa", "security", "compliance", "healthcare"],
        "A checklist of the evidence auditors request for clusters that handle protected health information.",
        "Jonas covers audit logging, encryption, access reviews and vendor documentation, with the questions "
        "hospital security teams ask when they evaluate a new tool.",
    ),
    (
        "talk-otel-regulated", "OpenTelemetry in regulated industries", "13:30", "Room B",
        "OpenTelemetry", ["Lena"], ["harborline.lena"], ["opentelemetry", "compliance", "observability"],
        "Lessons from rolling out OpenTelemetry at a bank: data residency, redaction and getting sign-off.",
        "Lena shares how her SRE team introduced OpenTelemetry under strict compliance review, which signals "
        "they kept, and how they cut incident time.",
    ),
    (
        "talk-finops-rightsizing", "Rightsizing pods without paging anyone", "13:30", "Room A",
        "Cost and FinOps", ["Nadia"], [], ["finops", "cost", "kubernetes"],
        "A safe workflow for lowering pod requests and limits and proving the savings.",
        "Nadia shows request and limit tuning driven by usage data, with guardrails that avoid out-of-memory "
        "kills, and a monthly review that finance trusts.",
    ),
    (
        "talk-ai-agents-guardrails", "Guardrails for autonomous AI agents", "13:30", "Room C",
        "AI Agents", ["Theo"], [], ["ai-agents", "security", "policy"],
        "Practical limits for agents that act on a person's behalf: scoped data, policy checks and audit trails.",
        "Theo describes least-privilege data access for agents, policy engines that fail closed and how to "
        "treat text from other agents as untrusted input.",
    ),
    (
        "talk-zero-trust-mesh", "Zero-trust networking for clusters", "14:00", "Room A",
        "Security and HIPAA", ["Beatriz"], [], ["zero-trust", "security", "kubernetes", "networking"],
        "Network policy and workload identity patterns that make lateral movement hard.",
        "Beatriz compares network policy, mutual TLS and workload identity, and shows an incremental rollout "
        "plan for an existing cluster.",
    ),
    (
        "talk-otel-collector-scale", "Scaling the OpenTelemetry Collector", "14:00", "Room B",
        "OpenTelemetry", ["Arjun"], [], ["opentelemetry", "observability", "collector"],
        "Sizing, sampling and routing for collectors that handle a large volume of telemetry.",
        "Arjun explains agent versus gateway collectors, tail sampling trade-offs and the dashboards he uses "
        "to watch the pipeline itself.",
    ),
    (
        "talk-ebpf-cost", "Cutting the cloud bill with eBPF", "14:30", "Room A",
        "Cost", ["Priya"], ["lumenly.priya"], ["ebpf", "cost", "kubernetes", "finops"],
        "How a lean platform team used eBPF to find waste and cut cloud spend without losing visibility.",
        "Priya shows how kernel-level telemetry exposed idle capacity and chatty services, what it saved, and "
        "how the team kept the overhead of measurement low.",
    ),
    (
        "talk-search-ops-data", "Hybrid search over operational data", "14:30", "Room C",
        "Search and Data", ["Ken"], [], ["elasticsearch", "search", "data"],
        "Combining keyword and semantic search to find the right runbook or shipment record fast.",
        "Ken demonstrates relevance tuning, filters and reciprocal rank fusion on a shipment-records index.",
    ),
    (
        "talk-platform-teams-scale", "Running a platform team of five", "15:00", "Room A",
        "Platform Engineering", ["Camille"], [], ["platform-engineering", "community", "kubernetes"],
        "Staffing, on-call and roadmap habits that let a small platform team support hundreds of services.",
        "Camille covers intake, saying no, and measuring developer satisfaction when the team is small.",
    ),
    (
        "talk-agent-protocols", "Agent-to-agent protocols in practice", "15:00", "Room C",
        "AI Agents", ["Wei"], [], ["ai-agents", "protocols", "policy"],
        "What worked and what broke when companies let their agents exchange information.",
        "Wei reviews message formats, consent steps and how to keep each side's private data out of the "
        "exchange.",
    ),
    (
        "talk-ebpf-zero-code", "Zero-code tracing with eBPF on Kubernetes", "15:30", "Room B",
        "Observability", ["Dev"], [], ["ebpf", "observability", "kubernetes"],
        "Trace every service on a Kubernetes cluster with eBPF and no code changes: how it works and its limits.",
        "Dev explains how eBPF captures requests at the kernel without instrumentation, what eBPF tracing "
        "sees on Kubernetes workloads, how it fits with OpenTelemetry, and where eBPF cannot help. Includes "
        "a live demo of zero-code eBPF tracing across a sample microservice app.",
    ),
    (
        "talk-finops-showback", "Showback that engineers actually read", "15:30", "Room A",
        "Cost and FinOps", ["Rosa"], [], ["finops", "cost", "reporting"],
        "Cost reports teams act on: ownership tags, weekly digests and budgets with context.",
        "Rosa shows how to attribute shared cluster cost to teams and present it where engineers already work.",
    ),
    (
        "talk-ebpf-edge", "eBPF on warehouse robots", "16:00", "Room C",
        "Observability", ["Mia"], ["kestrel.mia"], ["ebpf", "kubernetes", "edge", "robotics"],
        "Low-overhead tracing for small Kubernetes clusters running on warehouse robots.",
        "Mia describes running eBPF on constrained edge hardware, the overhead budget her team set and what "
        "they learned debugging fleets with flaky networks.",
    ),
    (
        "talk-supply-chain", "Supply-chain security for container images", "16:00", "Room A",
        "Security and HIPAA", ["Hana"], [], ["security", "supply-chain", "kubernetes"],
        "Signing, scanning and admission checks that keep untrusted images out of the cluster.",
        "Hana demonstrates image signing and an admission policy, and what to do when a base image is "
        "compromised.",
    ),
    (
        "talk-inclusive-confs", "Designing conferences for everyone", "16:30", "Room A",
        "Accessibility", ["Tom"], ["lumenly.tom"], ["accessibility", "community"],
        "Practical choices that make technical events welcoming: captions, quiet rooms and schedule design.",
        "Tom shares what his community learned running accessible events, with a checklist organisers can "
        "adopt for their next conference.",
    ),
    (
        "talk-slo-burn-rate", "SLOs that survive on-call", "16:30", "Room B",
        "Observability", ["Lucia"], [], ["observability", "slo", "reliability"],
        "Burn-rate alerts and error budgets that reduce noise instead of adding to it.",
        "Lucia covers choosing indicators, multi-window burn-rate alerts and reviewing budgets with product "
        "teams.",
    ),
    (
        "talk-closing-keynote", "Closing keynote: the next five years of cloud native", "17:00", "Room A",
        "Platform Engineering", ["Marcus"], [], ["kubernetes", "community", "platform-engineering"],
        "A look ahead at where platforms, agents and open source are going.",
        "Marcus closes the day with trends in platform engineering, AI-assisted operations and the community "
        "projects worth watching.",
    ),
]


def conference_day(now: datetime | None = None) -> date:
    """Today's date in America/Denver."""
    return (now or datetime.now(timezone.utc)).astimezone(DENVER).date()


def _utc(day: date, hhmm: str) -> datetime:
    hour, minute = (int(p) for p in hhmm.split(":"))
    return datetime.combine(day, time(hour, minute), tzinfo=DENVER).astimezone(timezone.utc)


def talk_records(now: datetime | None = None) -> list[MemoryRecord]:
    day = conference_day(now)
    created = datetime.combine(day, time(6, 0), tzinfo=DENVER).astimezone(timezone.utc)
    records = []
    for i, (mid, title, start, room, track, speakers, about, tags, summary, text) in enumerate(_TALKS):
        starts = _utc(day, start)
        records.append(
            MemoryRecord(
                memory_id=mid, org_id=CONFERENCE_ORG, share_level="public", kind="talk", title=title,
                text=text, summary=summary, tags=tags, about_persona_ids=about,
                # InMemoryStore breaks keyword ties by newest created_at. Make the headline demo talk the
                # newest so a plain "ebpf" query ranks it first there too (Elasticsearch ranks it by BM25).
                created_at=created + timedelta(seconds=1000 if mid == HEADLINE_TALK else i),
                source=SourceRef(type="conference"),
                talk=TalkInfo(
                    starts_at=starts, ends_at=starts + timedelta(minutes=TALK_MINUTES), room=room,
                    speakers=speakers, track=track,
                ),
            )
        )
    return records
