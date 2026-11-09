"""Reconcile logic, independent of kopf: every function takes a KubeOps, so tests pass a fake."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from rapport_common import names

from .builders import build_job, build_network_policy, build_service, encounter_name
from .config import OperatorConfig
from .kube import KubeOps
from .status import is_expired, started_status, status_from_jobs

log = logging.getLogger("rapport.operator")


def create_objects(enc: Mapping[str, Any], ops: KubeOps, cfg: OperatorConfig) -> list[str]:
    """Create the Service, NetworkPolicy and both Jobs for an Encounter; safe to call again after a retry.

    The responder's Service, NetworkPolicy and Job come first so the initiator never starts before
    its peer can accept traffic. Returns "<Kind>/<namespace>/<name>" for the objects newly created.
    Raises InvalidEncounter (permanent) or NamespaceNotFound (worth retrying).
    """
    objects = [
        build_service(enc),
        build_network_policy(enc),
        build_job(enc, "responder", cfg.image, cfg.passthrough_env),
        build_job(enc, "initiator", cfg.image, cfg.passthrough_env),
    ]
    created = []
    for obj in objects:
        if ops.ensure(obj):
            created.append(f"{obj['kind']}/{obj['metadata']['namespace']}/{obj['metadata']['name']}")
    log.info("encounter %s: created %d of %d objects", encounter_name(enc), len(created), len(objects))
    return created


def on_encounter_created(enc: Mapping[str, Any], ops: KubeOps, cfg: OperatorConfig, now: datetime) -> dict[str, Any]:
    """Create everything and return the Running status to record."""
    create_objects(enc, ops, cfg)
    return started_status(enc, now)


def sync_status(enc_name: str, ops: KubeOps, now: datetime) -> dict[str, Any] | None:
    """Recompute the Encounter status from the current Jobs and patch it if it changed.

    Reading both Jobs each time (rather than merging one event into stored state) keeps this correct
    when the two Jobs' events are handled concurrently.
    """
    enc = ops.get_encounter(enc_name)
    if enc is None:
        return None
    jobs_by_side: dict[str, Mapping[str, Any]] = {}
    for job in ops.list_delegate_jobs(enc_name):
        side = (job["metadata"].get("labels") or {}).get(names.LABEL_SIDE)
        if side:
            jobs_by_side[side] = job
    patch = status_from_jobs(enc, jobs_by_side, now)
    if patch is not None:
        ops.patch_encounter_status(enc_name, patch)
        log.info("encounter %s: status updated, phase %s", enc_name, patch.get("phase", "unchanged"))
    return patch


def delete_if_expired(enc: Mapping[str, Any], ops: KubeOps, now: datetime) -> bool:
    """Delete the Encounter once spec.ttlSeconds have passed; garbage collection removes the rest."""
    if not is_expired(enc, now):
        return False
    ops.delete_encounter(encounter_name(enc))
    log.info("encounter %s: ttl expired, deleted", encounter_name(enc))
    return True
