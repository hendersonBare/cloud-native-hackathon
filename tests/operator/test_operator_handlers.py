"""The kopf wrappers: call the handler functions directly with a fake Kubernetes API."""

import kopf
import pytest
from operator_fakes import CFG, FakeOps, make_enc

from rapport_operator import handlers


@pytest.fixture
def ops():
    fake = FakeOps(make_enc(status={"phase": "Running"}))
    handlers.configure(fake, CFG)
    yield fake
    handlers.configure(None, None)


def test_create_handler_patches_running_status(ops):
    patch = kopf.Patch()
    handlers.encounter_created(body=make_enc(), name="enc-1", patch=patch, retry=0)
    assert patch["status"]["phase"] == "Running"
    assert len(ops.objects) == 4


def test_create_handler_fails_permanently_on_invalid_spec(ops):
    enc = make_enc()
    enc["spec"]["responder"]["orgId"] = "acme"
    with pytest.raises(kopf.PermanentError):
        handlers.encounter_created(body=enc, name="enc-1", patch=kopf.Patch(), retry=0)
    assert ops.patches[-1][1]["phase"] == "Failed"
    assert ops.objects == {}


def test_create_handler_retries_a_missing_namespace_then_gives_up():
    fake = FakeOps(missing_namespaces={"org-bluefin"})
    handlers.configure(fake, CFG)
    with pytest.raises(kopf.TemporaryError):
        handlers.encounter_created(body=make_enc(), name="enc-1", patch=kopf.Patch(), retry=0)
    with pytest.raises(kopf.PermanentError):
        handlers.encounter_created(body=make_enc(), name="enc-1", patch=kopf.Patch(), retry=handlers.CREATE_RETRIES - 1)
    assert fake.patches[-1][1]["phase"] == "Failed"
    assert "org-bluefin" in fake.patches[-1][1]["message"]


def job_body(side="initiator", enc="enc-1"):
    return {"metadata": {"labels": {"rapport.dev/encounter": enc, "rapport.dev/side": side}}}


def test_job_event_syncs_status(ops):
    ops.jobs = [
        {"metadata": {"labels": {"rapport.dev/side": "initiator"}}, "status": {"succeeded": 1}},
        {"metadata": {"labels": {"rapport.dev/side": "responder"}}, "status": {"succeeded": 1}},
    ]
    handlers.delegate_job_changed(body=job_body(), event={"type": "MODIFIED"})
    assert ops.patches[-1][1]["phase"] == "Completed"


def test_job_deleted_event_is_ignored(ops):
    handlers.delegate_job_changed(body=job_body(), event={"type": "DELETED"})
    assert ops.patches == []


def test_job_without_encounter_label_is_ignored(ops):
    handlers.delegate_job_changed(body={"metadata": {"labels": {}}}, event={"type": "ADDED"})
    assert ops.patches == []


def test_ttl_timer_deletes_expired_encounter(ops):
    enc = make_enc()
    enc["metadata"]["creationTimestamp"] = "2020-01-01T00:00:00Z"
    handlers.encounter_ttl(body=enc)
    assert ops.deleted == ["enc-1"]
