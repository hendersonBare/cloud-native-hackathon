"""Names, URLs and labels shared by every component. Never hard-code these elsewhere."""

from __future__ import annotations

import json
import os
import secrets
from functools import lru_cache
from pathlib import Path

from .models import MemoryRecord, Org, Persona

# The Radar team vcluster: gateway and operator live in the team namespace Argo CD deploys to.
SYSTEM_NAMESPACE = "team-rapport"
PUBLIC_URL = "https://rapport.cnh.radarhq.io"  # the platform routes it to Service `app`, port 80
GATEWAY_SERVICE = "app"  # public: web page and /api/* only (Service port 80 -> pod 8080)
GATEWAY_INTERNAL_SERVICE = "gateway-internal"  # cluster-only: POST /internal/events (port 8081)
CONFERENCE_INDEX = "rapport-conference"
CONFERENCE_ORG = "conference"

CRD_GROUP = "rapport.dev"
CRD_VERSION = "v1alpha1"
CRD_PLURAL = "encounters"
CRD_KIND = "Encounter"
TRACEPARENT_ANNOTATION = "rapport.dev/traceparent"

HTTP_PORT = 8080
GATEWAY_INTERNAL_PORT = 8081  # /internal/* is served ONLY here, never on the public port
OPA_PORT = 8181

# The image every pod runs. Manifests in deploy/ say `image: app` and kustomize swaps in the GHCR
# tag. The operator creates delegate Jobs outside kustomize, so it uses $RAPPORT_IMAGE, or else
# the image of its own pod (read via POD_NAME/POD_NAMESPACE).
IMAGE_ENV = "RAPPORT_IMAGE"
KUSTOMIZE_IMAGE_PLACEHOLDER = "app"

# Team budget across the whole vcluster: 2 CPU / 4 GiB requests, 4 CPU / 8 GiB limits.
# Every container sets both; unset limits default to 500m, which caps the cluster at 8 pods.
RESOURCES_SMALL = {"requests": {"cpu": "25m", "memory": "64Mi"}, "limits": {"cpu": "100m", "memory": "128Mi"}}  # opa
RESOURCES_SERVICE = {"requests": {"cpu": "50m", "memory": "128Mi"}, "limits": {"cpu": "300m", "memory": "512Mi"}}
RESOURCES_DELEGATE = {"requests": {"cpu": "50m", "memory": "128Mi"}, "limits": {"cpu": "500m", "memory": "512Mi"}}
RESOURCES_OPERATOR = {"requests": {"cpu": "50m", "memory": "128Mi"}, "limits": {"cpu": "200m", "memory": "256Mi"}}
# Container securityContext for every Rapport pod (the image runs as UID 10001).
SECURITY_CONTEXT = {
    "runAsNonRoot": True,
    "allowPrivilegeEscalation": False,
    "seccompProfile": {"type": "RuntimeDefault"},
    "capabilities": {"drop": ["ALL"]},
}

LABEL_PART_OF = "app.kubernetes.io/part-of"  # = "rapport"
LABEL_ROLE = "rapport.dev/role"  # gateway | briefer | delegate | opa | operator
LABEL_ORG = "rapport.dev/org"
LABEL_ENCOUNTER = "rapport.dev/encounter"
LABEL_SIDE = "rapport.dev/side"  # initiator | responder

# OpenAI's "most efficient model for focused, high-volume tasks" ($0.10 in / $0.50 out per 1M tokens,
# structured outputs supported). gpt-5-mini is marked deprecated. Override with RAPPORT_LLM_MODEL.
DEFAULT_LLM_MODEL = "gpt-6-luna"
DEFAULT_REASONING_EFFORT = "low"  # override with RAPPORT_LLM_REASONING_EFFORT; keeps latency and cost down

MAX_AGENT_HANDSHAKES_PER_HOUR = 5  # per persona; gateway enforces for agent-initiated connect requests


def org_namespace(org_id: str) -> str:
    return f"org-{org_id}"


def shareable_index(org_id: str) -> str:
    return f"rapport-{org_id}-shareable"


def internal_index(org_id: str) -> str:
    return f"rapport-{org_id}-internal"


def index_for(record: MemoryRecord) -> str:
    """The ONLY routing rule: talks and attendee cards -> conference; public/partner -> shareable;
    internal -> internal."""
    if record.kind in ("talk", "attendee"):
        return CONFERENCE_INDEX
    if record.share_level in ("public", "partner"):
        return shareable_index(record.org_id)
    return internal_index(record.org_id)


def _override(var: str, default: str) -> str:
    return os.environ.get(var, default)


def gateway_url() -> str:
    """Where delegates POST /internal/events: the cluster-only Service, never the public one."""
    return _override(
        "GATEWAY_URL",
        f"http://{GATEWAY_INTERNAL_SERVICE}.{SYSTEM_NAMESPACE}.svc.cluster.local:{GATEWAY_INTERNAL_PORT}",
    )


def briefer_url(org_id: str) -> str:
    # Local dev without Kubernetes: BRIEFER_URL_ACME=http://localhost:8101 etc.
    return _override(
        f"BRIEFER_URL_{org_id.upper()}", f"http://briefer.{org_namespace(org_id)}.svc.cluster.local:{HTTP_PORT}"
    )


def opa_url(org_id: str) -> str:
    return _override(
        f"OPA_URL_{org_id.upper()}", f"http://opa.{org_namespace(org_id)}.svc.cluster.local:{OPA_PORT}"
    )


def delegate_service_name(encounter_id: str) -> str:
    return f"delegate-{encounter_id}"


def delegate_url(encounter_id: str, org_id: str) -> str:
    return f"http://{delegate_service_name(encounter_id)}.{org_namespace(org_id)}.svc.cluster.local:{HTTP_PORT}"


def new_encounter_id() -> str:
    return f"enc-{secrets.token_hex(4)}"


@lru_cache
def _directory() -> dict:
    return json.loads((Path(__file__).parent / "data" / "personas.json").read_text())


def orgs() -> dict[str, Org]:
    return {o["org_id"]: Org.model_validate(o) for o in _directory()["orgs"]}


def personas() -> dict[str, Persona]:
    return {p["persona_id"]: Persona.model_validate(p) for p in _directory()["personas"]}


def persona(persona_id: str) -> Persona:
    return personas()[persona_id]


def org_of(persona_id: str) -> str:
    return persona(persona_id).org_id


def agents_enabled(org_id: str) -> bool:
    """True if this company runs Rapport agents (has a namespace, briefer and OPA)."""
    org = orgs().get(org_id)
    return bool(org and org.agents_enabled)


def attendee_card_id(persona_id: str) -> str:
    return f"attendee-{persona_id}"


def llm_model() -> str:
    return os.environ.get("RAPPORT_LLM_MODEL", DEFAULT_LLM_MODEL)


def llm_reasoning_effort() -> str:
    return os.environ.get("RAPPORT_LLM_REASONING_EFFORT", DEFAULT_REASONING_EFFORT)
