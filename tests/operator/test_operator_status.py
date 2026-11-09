"""Status logic: pure functions, no cluster."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from rapport_operator import status as st

NOW = datetime(2026, 11, 9, 20, 30, tzinfo=UTC)


def enc(created=NOW, current_status=None, ttl=600):
    body = {
        "metadata": {"name": "enc-1", "uid": "u", "creationTimestamp": created.strftime("%Y-%m-%dT%H:%M:%SZ")},
        "spec": {
            "initiator": {"orgId": "acme", "personaId": "acme.ava"},
            "responder": {"orgId": "bluefin", "personaId": "bluefin.bo"},
            "ttlSeconds": ttl,
        },
    }
    if current_status is not None:
        body["status"] = current_status
    return body


def job(**status):
    return {"status": status}


@pytest.mark.parametrize(
    "j,expected",
    [
        (None, "Pending"),
        (job(), "Pending"),
        (job(active=1, startTime="2026-11-09T20:30:00Z"), "Running"),
        (job(startTime="2026-11-09T20:30:00Z"), "Running"),
        (job(succeeded=1), "Succeeded"),
        (job(conditions=[{"type": "Complete", "status": "True"}]), "Succeeded"),
        (job(failed=1), "Failed"),
        (job(conditions=[{"type": "Failed", "status": "True", "reason": "DeadlineExceeded"}]), "Failed"),
        (job(failed=1, conditions=[{"type": "Failed", "status": "False"}]), "Failed"),
    ],
)
def test_job_phase(j, expected):
    assert st.job_phase(j) == expected


def delegates(i, r):
    return [{"phase": i}, {"phase": r}]


@pytest.mark.parametrize(
    "i,r,expected",
    [
        ("Pending", "Pending", "Running"),
        ("Running", "Pending", "Running"),
        ("Succeeded", "Running", "Running"),
        ("Succeeded", "Succeeded", "Completed"),
        ("Failed", "Succeeded", "Failed"),
        ("Succeeded", "Failed", "Failed"),
        ("Running", "Failed", "Failed"),
    ],
)
def test_encounter_phase(i, r, expected):
    assert st.encounter_phase(delegates(i, r)) == expected


def test_started_status():
    out = st.started_status(enc(), NOW)
    assert out["phase"] == "Running"
    assert out["startedAt"] == "2026-11-09T20:30:00Z"
    assert out["delegates"] == [
        {"orgId": "acme", "side": "initiator", "job": "delegate-enc-1", "phase": "Pending"},
        {"orgId": "bluefin", "side": "responder", "job": "delegate-enc-1", "phase": "Pending"},
    ]


def test_completed_when_both_jobs_succeeded():
    patch = st.status_from_jobs(
        enc(current_status={"phase": "Running"}), {"initiator": job(succeeded=1), "responder": job(succeeded=1)}, NOW
    )
    assert patch["phase"] == "Completed"
    assert patch["completedAt"] == "2026-11-09T20:30:00Z"
    assert [d["phase"] for d in patch["delegates"]] == ["Succeeded", "Succeeded"]
    assert "message" not in patch


def test_failed_when_either_job_failed_and_names_the_side():
    patch = st.status_from_jobs(
        enc(current_status={"phase": "Running"}), {"initiator": job(active=1), "responder": job(failed=1)}, NOW
    )
    assert patch["phase"] == "Failed"
    assert patch["completedAt"] == "2026-11-09T20:30:00Z"
    assert patch["message"] == "delegate job failed: responder"


def test_progress_is_recorded_without_completion():
    patch = st.status_from_jobs(
        enc(current_status={"phase": "Running"}), {"initiator": job(active=1), "responder": job(succeeded=1)}, NOW
    )
    assert patch["phase"] == "Running"
    assert "completedAt" not in patch
    assert [d["phase"] for d in patch["delegates"]] == ["Running", "Succeeded"]


def test_no_patch_when_nothing_changed():
    jobs = {"initiator": job(active=1), "responder": job()}
    first = st.status_from_jobs(enc(current_status={"phase": "Running"}), jobs, NOW)
    again = st.status_from_jobs(
        enc(current_status={"phase": first["phase"], "delegates": first["delegates"]}), jobs, NOW
    )
    assert again is None


@pytest.mark.parametrize("phase", ["Completed", "Failed"])
def test_terminal_phase_is_never_rewritten(phase):
    patch = st.status_from_jobs(
        enc(current_status={"phase": phase}), {"initiator": job(active=1), "responder": job(active=1)}, NOW
    )
    assert "phase" not in patch and "completedAt" not in patch and "message" not in patch


def test_terminal_status_records_the_second_job_and_keeps_collected_jobs():
    initiator = {"orgId": "acme", "side": "initiator", "job": "delegate-enc-1", "phase": "Running"}
    responder = {"orgId": "bluefin", "side": "responder", "job": "delegate-enc-1", "phase": "Failed"}
    failed = enc(current_status={"phase": "Failed", "delegates": [initiator, responder]})
    both_failed = {"initiator": job(failed=1), "responder": job(failed=1)}
    assert st.status_from_jobs(failed, both_failed, NOW) == {"delegates": [{**initiator, "phase": "Failed"}, responder]}
    # the responder Job was garbage-collected: its recorded phase is kept, not reset to Pending
    only_initiator = {"initiator": job(failed=1)}
    assert st.status_from_jobs(failed, only_initiator, NOW) == {
        "delegates": [{**initiator, "phase": "Failed"}, responder]
    }
    # nothing new to record
    assert st.status_from_jobs(failed, {"initiator": job(active=1), "responder": job(failed=1)}, NOW) is None


def test_is_expired_uses_ttl_from_creation():
    created = NOW - timedelta(seconds=599)
    assert not st.is_expired(enc(created=created), NOW)
    assert st.is_expired(enc(created=NOW - timedelta(seconds=600)), NOW)
    assert not st.is_expired(enc(created=NOW - timedelta(seconds=600), ttl=1200), NOW)


def test_timestamps_are_utc():
    local = datetime(2026, 11, 9, 13, 30, tzinfo=ZoneInfo("America/Denver"))
    assert st.iso(local) == "2026-11-09T20:30:00Z"
    assert st.parse_ts("2026-11-09T20:30:00Z") == NOW
