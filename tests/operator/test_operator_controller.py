"""Controller logic against an in-memory fake of the Kubernetes API."""

from datetime import timedelta

import pytest

from rapport_operator import controller
from rapport_operator.builders import InvalidEncounter
from operator_fakes import CFG, NOW, FakeOps, labelled_job, make_enc
from rapport_operator.config import load_config, pick_container_image
from rapport_operator.kube import NamespaceNotFound


def test_create_makes_all_four_objects_and_returns_running_status():
    ops = FakeOps()
    status = controller.on_encounter_created(make_enc(), ops, CFG, NOW)
    assert set(ops.objects) == {
        ("Service", "org-bluefin", "delegate-enc-1"),
        ("NetworkPolicy", "org-bluefin", "delegate-enc-1"),
        ("Job", "org-bluefin", "delegate-enc-1"),
        ("Job", "org-acme", "delegate-enc-1"),
    }
    assert status["phase"] == "Running" and status["startedAt"] == "2026-11-09T20:30:00Z"
    assert [(d["orgId"], d["side"]) for d in status["delegates"]] == [("acme", "initiator"), ("bluefin", "responder")]


def test_responder_side_is_created_before_the_initiator():
    ops = FakeOps()
    controller.create_objects(make_enc(), ops, CFG)
    assert ops.create_order[-1] == ("Job", "org-acme", "delegate-enc-1")
    assert ops.create_order.index(("Job", "org-bluefin", "delegate-enc-1")) < len(ops.create_order) - 1


def test_create_is_idempotent_on_retry():
    ops = FakeOps()
    assert len(controller.create_objects(make_enc(), ops, CFG)) == 4
    assert controller.create_objects(make_enc(), ops, CFG) == []  # 409 AlreadyExists counts as success
    assert len(ops.objects) == 4


def test_job_uses_resolved_image_and_passthrough():
    ops = FakeOps()
    controller.create_objects(make_enc(), ops, CFG)
    container = ops.objects[("Job", "org-acme", "delegate-enc-1")]["spec"]["template"]["spec"]["containers"][0]
    assert container["image"] == CFG.image
    assert {"name": "RAPPORT_LLM_MODEL", "value": "m"} in container["env"]


def test_missing_namespace_is_surfaced_for_retry():
    with pytest.raises(NamespaceNotFound):
        controller.create_objects(make_enc(), FakeOps(missing_namespaces={"org-acme"}), CFG)


def test_invalid_encounter_creates_nothing():
    enc = make_enc()
    enc["spec"]["responder"]["orgId"] = "acme"
    ops = FakeOps()
    with pytest.raises(InvalidEncounter):
        controller.create_objects(enc, ops, CFG)
    assert ops.objects == {}


def test_sync_status_completes_when_both_jobs_succeed():
    ops = FakeOps(make_enc(status={"phase": "Running"}))
    ops.jobs = [labelled_job("initiator", succeeded=1), labelled_job("responder", succeeded=1)]
    patch = controller.sync_status("enc-1", ops, NOW)
    assert patch["phase"] == "Completed"
    assert ops.patches == [("enc-1", patch)]


def test_sync_status_fails_when_a_job_fails():
    ops = FakeOps(make_enc(status={"phase": "Running"}))
    ops.jobs = [labelled_job("initiator", active=1), labelled_job("responder", failed=1)]
    assert controller.sync_status("enc-1", ops, NOW)["phase"] == "Failed"


def test_sync_status_ignores_unknown_encounter_and_terminal_state():
    assert controller.sync_status("gone", FakeOps(), NOW) is None
    ops = FakeOps(make_enc(status={"phase": "Completed"}))
    ops.jobs = [labelled_job("initiator", failed=1)]
    assert controller.sync_status("enc-1", ops, NOW) is None
    assert ops.patches == []


def test_ttl_deletes_only_after_expiry():
    ops = FakeOps()
    assert not controller.delete_if_expired(make_enc(created=NOW - timedelta(seconds=599)), ops, NOW)
    assert controller.delete_if_expired(make_enc(created=NOW - timedelta(seconds=601)), ops, NOW)
    assert ops.deleted == ["enc-1"]


# ----------------------------------------------------------------- image resolution
def test_image_from_env_wins_and_skips_pod_read():
    def boom(*_):
        raise AssertionError("must not read the pod")

    cfg = load_config({"RAPPORT_IMAGE": "img:1", "RAPPORT_LLM_MODEL": "m"}, read_own_pod=boom)
    assert cfg.image == "img:1" and cfg.passthrough_env == {"RAPPORT_LLM_MODEL": "m"}


def test_image_from_own_pod():
    pod = {
        "spec": {"containers": [{"name": "sidecar", "image": "x"}, {"name": "operator", "image": "ghcr.io/o/r:sha"}]}
    }
    seen = []

    def read_pod(name, ns):
        seen.append((name, ns))
        return pod

    cfg = load_config({"POD_NAME": "operator-abc", "POD_NAMESPACE": "team-rapport"}, read_own_pod=read_pod)
    assert cfg.image == "ghcr.io/o/r:sha"
    assert seen == [("operator-abc", "team-rapport")]


def test_image_unresolvable_raises():
    with pytest.raises(RuntimeError):
        load_config({}, read_own_pod=lambda *_: {})
    with pytest.raises(RuntimeError):
        load_config({"POD_NAME": "p", "POD_NAMESPACE": "n"}, read_own_pod=lambda *_: {"spec": {"containers": []}})


def test_pick_container_image_falls_back_to_first_container():
    assert pick_container_image({"spec": {"containers": [{"name": "app", "image": "i"}]}}) == "i"
