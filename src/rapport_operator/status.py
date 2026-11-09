"""Pure status logic: Job state in, Encounter status out (SPEC 4.4 "Status"). No I/O."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from rapport_common import names

from .builders import SIDES, encounter_name, encounter_spec, party

PHASE_PENDING = "Pending"
PHASE_RUNNING = "Running"
PHASE_COMPLETED = "Completed"
PHASE_FAILED = "Failed"
TERMINAL_PHASES = frozenset({PHASE_COMPLETED, PHASE_FAILED})

JOB_PENDING = "Pending"
JOB_RUNNING = "Running"
JOB_SUCCEEDED = "Succeeded"
JOB_FAILED = "Failed"


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(ts: datetime) -> str:
    """Timezone-aware UTC, the only form stored on the resource."""
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def job_phase(job: Mapping[str, Any] | None) -> str:
    """Pending | Running | Succeeded | Failed for a Job (a dict in the Kubernetes API shape)."""
    if not job:
        return JOB_PENDING
    status = job.get("status") or {}
    for cond in status.get("conditions") or []:
        if cond.get("status") == "True":
            if cond.get("type") == "Complete":
                return JOB_SUCCEEDED
            if cond.get("type") == "Failed":
                return JOB_FAILED
    if (status.get("succeeded") or 0) > 0:
        return JOB_SUCCEEDED
    if (status.get("failed") or 0) > 0:
        return JOB_FAILED
    if (status.get("active") or 0) > 0 or status.get("startTime"):
        return JOB_RUNNING
    return JOB_PENDING


def delegate_entries(enc: Mapping[str, Any], jobs_by_side: Mapping[str, Mapping[str, Any] | None]) -> list[dict]:
    """status.delegates: [{orgId, side, job, phase}], initiator first."""
    spec = encounter_spec(enc)
    job_name = names.delegate_service_name(encounter_name(enc))
    return [
        {"orgId": party(spec, side).orgId, "side": side, "job": job_name, "phase": job_phase(jobs_by_side.get(side))}
        for side in SIDES
    ]


def encounter_phase(delegates: Iterable[Mapping[str, Any]]) -> str:
    """Failed if either Job failed; Completed when both succeeded; otherwise Running."""
    phases = [d["phase"] for d in delegates]
    if JOB_FAILED in phases:
        return PHASE_FAILED
    if phases and all(p == JOB_SUCCEEDED for p in phases):
        return PHASE_COMPLETED
    return PHASE_RUNNING


def started_status(enc: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    """Status written right after the objects exist."""
    return {
        "phase": PHASE_RUNNING,
        "startedAt": iso(now),
        "delegates": delegate_entries(enc, {}),
    }


def status_from_jobs(
    enc: Mapping[str, Any], jobs_by_side: Mapping[str, Mapping[str, Any] | None], now: datetime
) -> dict[str, Any] | None:
    """The status patch for the current Job state, or None when nothing changes.

    A terminal phase is never rewritten (Jobs are garbage-collected after their own TTL, and a late
    event must not move a finished encounter back to Running); only delegates[] keeps following the Jobs.
    """
    current = enc.get("status") or {}
    delegates = delegate_entries(enc, jobs_by_side)
    if current.get("phase") in TERMINAL_PHASES:
        # The phase is final, but delegates[] still follow the Jobs that exist (so the second Job's final
        # phase is recorded). A Job already garbage-collected keeps its last recorded phase.
        recorded = {d.get("side"): d for d in current.get("delegates") or []}
        merged = [d if jobs_by_side.get(d["side"]) else recorded.get(d["side"], d) for d in delegates]
        return None if merged == current.get("delegates") else {"delegates": merged}
    phase = encounter_phase(delegates)
    if phase == current.get("phase") and delegates == current.get("delegates"):
        return None
    patch: dict[str, Any] = {"phase": phase, "delegates": delegates}
    if phase in TERMINAL_PHASES:
        patch["completedAt"] = iso(now)
        if phase == PHASE_FAILED:
            failed = [d["side"] for d in delegates if d["phase"] == JOB_FAILED]
            patch["message"] = f"delegate job failed: {', '.join(failed)}"
    return patch


def is_expired(enc: Mapping[str, Any], now: datetime) -> bool:
    """True once spec.ttlSeconds have passed since the Encounter was created."""
    created = enc["metadata"].get("creationTimestamp")
    if not created:
        return False
    ttl = encounter_spec(enc).ttlSeconds
    return (now - parse_ts(created)).total_seconds() >= ttl
