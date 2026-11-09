"""Pure builders for the objects the operator creates for an Encounter (SPEC 4.4).

Each function takes the Encounter as a plain dict (the custom resource body) and returns a plain dict
that can be sent to the Kubernetes API unchanged. No I/O, no clock, no environment reads.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, Literal

from rapport_common import names
from rapport_common.models import EncounterParty, EncounterSpec

Side = Literal["initiator", "responder"]
SIDES: tuple[Side, ...] = ("initiator", "responder")

PART_OF = "rapport"
ROLE_DELEGATE = "delegate"
JOB_BACKOFF_LIMIT = 0
JOB_ACTIVE_DEADLINE_SECONDS = 120
JOB_TTL_AFTER_FINISHED_SECONDS = 600
# Secrets are optional so a missing one degrades the delegate to its fallbacks instead of blocking the pod.
DELEGATE_SECRETS = ("openai", "dash0-otlp", "es-delegate")
PASSTHROUGH_ENV = ("RAPPORT_LLM_MODEL", "RAPPORT_LLM_REASONING_EFFORT")


class InvalidEncounter(ValueError):
    """The Encounter cannot be turned into objects (permanent: retrying will not help)."""


def encounter_spec(enc: Mapping[str, Any]) -> EncounterSpec:
    """Validate the spec with the shared contract model."""
    try:
        spec = EncounterSpec.model_validate(enc.get("spec") or {})
    except ValueError as exc:  # pydantic.ValidationError is a ValueError
        raise InvalidEncounter(f"spec is not a valid EncounterSpec: {exc.__class__.__name__}") from exc
    if spec.initiator.orgId == spec.responder.orgId:
        # Both Jobs are named delegate-<enc>, so the two parties must be in different namespaces.
        raise InvalidEncounter("initiator and responder must be different organizations")
    return spec


def encounter_name(enc: Mapping[str, Any]) -> str:
    return enc["metadata"]["name"]


def party(spec: EncounterSpec, side: Side) -> EncounterParty:
    return spec.initiator if side == "initiator" else spec.responder


def peer(spec: EncounterSpec, side: Side) -> EncounterParty:
    return spec.responder if side == "initiator" else spec.initiator


def passthrough_from_environ(environ: Mapping[str, str]) -> dict[str, str]:
    """The operator's own LLM settings that delegates inherit (only those that are set)."""
    return {key: environ[key] for key in PASSTHROUGH_ENV if environ.get(key)}


def owner_references(enc: Mapping[str, Any]) -> list[dict[str, Any]]:
    meta = enc["metadata"]
    return [
        {
            "apiVersion": f"{names.CRD_GROUP}/{names.CRD_VERSION}",
            "kind": names.CRD_KIND,
            "name": meta["name"],
            "uid": meta["uid"],
            "controller": True,
            "blockOwnerDeletion": True,
        }
    ]


def labels(enc_name: str, org_id: str, side: Side) -> dict[str, str]:
    return {
        names.LABEL_PART_OF: PART_OF,
        names.LABEL_ROLE: ROLE_DELEGATE,
        names.LABEL_ORG: org_id,
        names.LABEL_ENCOUNTER: enc_name,
        names.LABEL_SIDE: side,
    }


def _metadata(enc: Mapping[str, Any], org_id: str, side: Side) -> dict[str, Any]:
    enc_name = encounter_name(enc)
    return {
        "name": names.delegate_service_name(enc_name),
        "namespace": names.org_namespace(org_id),
        "labels": labels(enc_name, org_id, side),
        "ownerReferences": owner_references(enc),
    }


def delegate_env(
    enc: Mapping[str, Any], spec: EncounterSpec, side: Side, passthrough_env: Mapping[str, str]
) -> list[dict[str, Any]]:
    me, other = party(spec, side), peer(spec, side)
    env: list[dict[str, Any]] = [
        {"name": "ENCOUNTER_ID", "value": encounter_name(enc)},
        {"name": "ROLE", "value": side},
        {"name": "SELF_ORG", "value": me.orgId},
        {"name": "SELF_PERSONA", "value": me.personaId},
        {"name": "PEER_ORG", "value": other.orgId},
        {"name": "PEER_PERSONA", "value": other.personaId},
    ]
    if side == "initiator":
        env.append({"name": "PEER_URL", "value": names.delegate_url(encounter_name(enc), spec.responder.orgId)})
    env.append({"name": "MALICIOUS", "value": "true" if me.malicious else "false"})
    traceparent = ((enc["metadata"].get("annotations")) or {}).get(names.TRACEPARENT_ANNOTATION)
    if traceparent:
        env.append({"name": "TRACEPARENT", "value": traceparent})
    for key in PASSTHROUGH_ENV:
        if passthrough_env.get(key):
            env.append({"name": key, "value": passthrough_env[key]})
    env.append({"name": "POD_NAME", "valueFrom": {"fieldRef": {"fieldPath": "metadata.name"}}})
    env.append({"name": "POD_NAMESPACE", "valueFrom": {"fieldRef": {"fieldPath": "metadata.namespace"}}})
    return env


def build_job(
    enc: Mapping[str, Any], side: Side, image: str, passthrough_env: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Job `delegate-<enc>` in the namespace of the party on `side`."""
    spec = encounter_spec(enc)
    org_id = party(spec, side).orgId
    meta = _metadata(enc, org_id, side)
    pod_labels = labels(encounter_name(enc), org_id, side)
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": meta,
        "spec": {
            "backoffLimit": JOB_BACKOFF_LIMIT,
            "activeDeadlineSeconds": JOB_ACTIVE_DEADLINE_SECONDS,
            "ttlSecondsAfterFinished": JOB_TTL_AFTER_FINISHED_SECONDS,
            "template": {
                "metadata": {"labels": pod_labels},
                "spec": {
                    "restartPolicy": "Never",
                    "automountServiceAccountToken": False,
                    "containers": [
                        {
                            "name": "delegate",
                            "image": image,
                            "imagePullPolicy": "IfNotPresent",
                            "command": ["python", "-m", "rapport_delegate"],
                            "ports": [{"name": "http", "containerPort": names.HTTP_PORT}],
                            "env": delegate_env(enc, spec, side, passthrough_env or {}),
                            "envFrom": [{"secretRef": {"name": s, "optional": True}} for s in DELEGATE_SECRETS],
                            "resources": deepcopy(names.RESOURCES_DELEGATE),
                            "securityContext": deepcopy(names.SECURITY_CONTEXT),
                        }
                    ],
                },
            },
        },
    }


def build_service(enc: Mapping[str, Any]) -> dict[str, Any]:
    """Service `delegate-<enc>` in the responder namespace; the initiator reaches the responder through it."""
    spec = encounter_spec(enc)
    enc_name = encounter_name(enc)
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": _metadata(enc, spec.responder.orgId, "responder"),
        "spec": {
            "selector": {names.LABEL_ENCOUNTER: enc_name, names.LABEL_SIDE: "responder"},
            "ports": [{"name": "http", "protocol": "TCP", "port": names.HTTP_PORT, "targetPort": names.HTTP_PORT}],
        },
    }


def build_network_policy(enc: Mapping[str, Any]) -> dict[str, Any]:
    """Only this encounter's initiator pod may reach this encounter's responder pod.

    The namespaceSelector and the podSelector sit in ONE `from` entry, so they are ANDed. Two entries
    would be ORed and would let every pod in the initiator namespace in.
    """
    spec = encounter_spec(enc)
    enc_name = encounter_name(enc)
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": _metadata(enc, spec.responder.orgId, "responder"),
        "spec": {
            "podSelector": {"matchLabels": {names.LABEL_ENCOUNTER: enc_name, names.LABEL_SIDE: "responder"}},
            "policyTypes": ["Ingress"],
            "ingress": [
                {
                    "from": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {
                                    "kubernetes.io/metadata.name": names.org_namespace(spec.initiator.orgId)
                                }
                            },
                            "podSelector": {
                                "matchLabels": {names.LABEL_ENCOUNTER: enc_name, names.LABEL_SIDE: "initiator"}
                            },
                        }
                    ],
                    "ports": [{"protocol": "TCP", "port": names.HTTP_PORT}],
                }
            ],
        },
    }
