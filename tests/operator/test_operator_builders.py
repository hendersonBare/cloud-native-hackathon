"""The objects the operator builds must match SPEC 4.4 exactly."""

import pytest

from rapport_common import names
from rapport_operator.builders import (
    InvalidEncounter,
    build_job,
    build_network_policy,
    build_service,
    passthrough_from_environ,
)

IMAGE = "ghcr.io/example/rapport:abc123"
TRACEPARENT = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
FIVE_LABELS = {
    "app.kubernetes.io/part-of",
    "rapport.dev/role",
    "rapport.dev/org",
    "rapport.dev/encounter",
    "rapport.dev/side",
}


def make_enc(name="enc-1a2b3c4d", initiator_bad=False, responder_bad=True, traceparent=TRACEPARENT, **spec_extra):
    meta = {"name": name, "uid": "11111111-2222-3333-4444-555555555555"}
    if traceparent:
        meta["annotations"] = {"rapport.dev/traceparent": traceparent}
    return {
        "apiVersion": "rapport.dev/v1alpha1",
        "kind": "Encounter",
        "metadata": meta,
        "spec": {
            "initiator": {"orgId": "acme", "personaId": "acme.ava", "malicious": initiator_bad},
            "responder": {"orgId": "bluefin", "personaId": "bluefin.bo", "malicious": responder_bad},
            "ttlSeconds": 600,
            **spec_extra,
        },
    }


def env_of(job):
    return {e["name"]: e for e in job["spec"]["template"]["spec"]["containers"][0]["env"]}


OWNER = [
    {
        "apiVersion": "rapport.dev/v1alpha1",
        "kind": "Encounter",
        "name": "enc-1a2b3c4d",
        "uid": "11111111-2222-3333-4444-555555555555",
        "controller": True,
        "blockOwnerDeletion": True,
    }
]


@pytest.mark.parametrize("side,org", [("initiator", "acme"), ("responder", "bluefin")])
def test_job_identity_labels_and_owner(side, org):
    job = build_job(make_enc(), side, IMAGE)
    assert job["apiVersion"] == "batch/v1" and job["kind"] == "Job"
    meta = job["metadata"]
    assert meta["name"] == "delegate-enc-1a2b3c4d"
    assert meta["namespace"] == f"org-{org}"
    expected = {
        "app.kubernetes.io/part-of": "rapport",
        "rapport.dev/role": "delegate",
        "rapport.dev/org": org,
        "rapport.dev/encounter": "enc-1a2b3c4d",
        "rapport.dev/side": side,
    }
    assert meta["labels"] == expected
    assert job["spec"]["template"]["metadata"]["labels"] == expected
    assert set(expected) == FIVE_LABELS
    assert meta["ownerReferences"] == OWNER


def test_job_spec_and_container():
    job = build_job(make_enc(), "initiator", IMAGE)
    spec = job["spec"]
    assert (spec["backoffLimit"], spec["activeDeadlineSeconds"], spec["ttlSecondsAfterFinished"]) == (0, 120, 600)
    pod = spec["template"]["spec"]
    assert pod["restartPolicy"] == "Never"
    assert pod["automountServiceAccountToken"] is False
    (c,) = pod["containers"]
    assert c["name"] == "delegate"
    assert c["image"] == IMAGE
    assert c["imagePullPolicy"] == "IfNotPresent"
    assert c["command"] == ["python", "-m", "rapport_delegate"]
    assert c["ports"] == [{"name": "http", "containerPort": 8080}]
    assert c["resources"] == names.RESOURCES_DELEGATE
    assert c["securityContext"] == names.SECURITY_CONTEXT
    assert c["envFrom"] == [
        {"secretRef": {"name": "openai", "optional": True}},
        {"secretRef": {"name": "dash0-otlp", "optional": True}},
        {"secretRef": {"name": "es-delegate", "optional": True}},
    ]


def test_builders_do_not_share_mutable_contract_dicts():
    job = build_job(make_enc(), "initiator", IMAGE)
    job["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"]["cpu"] = "9"
    job["spec"]["template"]["spec"]["containers"][0]["securityContext"]["capabilities"]["drop"].append("x")
    assert names.RESOURCES_DELEGATE["limits"]["cpu"] == "500m"
    assert names.SECURITY_CONTEXT["capabilities"]["drop"] == ["ALL"]


def test_initiator_env():
    env = env_of(build_job(make_enc(initiator_bad=False, responder_bad=True), "initiator", IMAGE))
    assert env["ENCOUNTER_ID"]["value"] == "enc-1a2b3c4d"
    assert env["ROLE"]["value"] == "initiator"
    assert (env["SELF_ORG"]["value"], env["SELF_PERSONA"]["value"]) == ("acme", "acme.ava")
    assert (env["PEER_ORG"]["value"], env["PEER_PERSONA"]["value"]) == ("bluefin", "bluefin.bo")
    assert env["PEER_URL"]["value"] == "http://delegate-enc-1a2b3c4d.org-bluefin.svc.cluster.local:8080"
    assert env["PEER_URL"]["value"] == names.delegate_url("enc-1a2b3c4d", "bluefin")
    assert env["MALICIOUS"]["value"] == "false"
    assert env["TRACEPARENT"]["value"] == TRACEPARENT
    assert env["POD_NAME"]["valueFrom"]["fieldRef"]["fieldPath"] == "metadata.name"
    assert env["POD_NAMESPACE"]["valueFrom"]["fieldRef"]["fieldPath"] == "metadata.namespace"


def test_responder_env_has_no_peer_url_and_own_malicious_flag():
    env = env_of(build_job(make_enc(initiator_bad=False, responder_bad=True), "responder", IMAGE))
    assert "PEER_URL" not in env
    assert env["ROLE"]["value"] == "responder"
    assert (env["SELF_ORG"]["value"], env["SELF_PERSONA"]["value"]) == ("bluefin", "bluefin.bo")
    assert (env["PEER_ORG"]["value"], env["PEER_PERSONA"]["value"]) == ("acme", "acme.ava")
    assert env["MALICIOUS"]["value"] == "true"
    assert env["TRACEPARENT"]["value"] == TRACEPARENT


def test_malicious_is_per_party():
    enc = make_enc(initiator_bad=True, responder_bad=False)
    assert env_of(build_job(enc, "initiator", IMAGE))["MALICIOUS"]["value"] == "true"
    assert env_of(build_job(enc, "responder", IMAGE))["MALICIOUS"]["value"] == "false"


def test_traceparent_omitted_without_annotation():
    assert "TRACEPARENT" not in env_of(build_job(make_enc(traceparent=None), "initiator", IMAGE))


def test_llm_env_passed_through_only_when_set():
    base = env_of(build_job(make_enc(), "initiator", IMAGE, {}))
    assert "RAPPORT_LLM_MODEL" not in base and "RAPPORT_LLM_REASONING_EFFORT" not in base
    env = env_of(
        build_job(make_enc(), "initiator", IMAGE, {"RAPPORT_LLM_MODEL": "m1", "RAPPORT_LLM_REASONING_EFFORT": "high"})
    )
    assert env["RAPPORT_LLM_MODEL"]["value"] == "m1"
    assert env["RAPPORT_LLM_REASONING_EFFORT"]["value"] == "high"


def test_passthrough_from_environ():
    assert passthrough_from_environ({}) == {}
    assert passthrough_from_environ({"RAPPORT_LLM_MODEL": "m", "OPENAI_API_KEY": "secret", "X": ""}) == {
        "RAPPORT_LLM_MODEL": "m"
    }


def test_service_in_responder_namespace():
    svc = build_service(make_enc())
    meta = svc["metadata"]
    assert (svc["apiVersion"], svc["kind"]) == ("v1", "Service")
    assert meta["name"] == "delegate-enc-1a2b3c4d"
    assert meta["namespace"] == "org-bluefin"
    assert meta["labels"] == {
        "app.kubernetes.io/part-of": "rapport",
        "rapport.dev/role": "delegate",
        "rapport.dev/org": "bluefin",
        "rapport.dev/encounter": "enc-1a2b3c4d",
        "rapport.dev/side": "responder",
    }
    assert meta["ownerReferences"] == OWNER
    assert svc["spec"]["selector"] == {"rapport.dev/encounter": "enc-1a2b3c4d", "rapport.dev/side": "responder"}
    (port,) = svc["spec"]["ports"]
    assert (port["port"], port["targetPort"], port["protocol"]) == (8080, 8080, "TCP")


def test_network_policy_selectors_exactly():
    np = build_network_policy(make_enc())
    meta = np["metadata"]
    assert (np["apiVersion"], np["kind"]) == ("networking.k8s.io/v1", "NetworkPolicy")
    assert meta["name"] == "delegate-enc-1a2b3c4d"
    assert meta["namespace"] == "org-bluefin"
    assert set(meta["labels"]) == FIVE_LABELS
    assert meta["ownerReferences"] == OWNER
    spec = np["spec"]
    assert spec["podSelector"] == {
        "matchLabels": {"rapport.dev/encounter": "enc-1a2b3c4d", "rapport.dev/side": "responder"}
    }
    assert spec["policyTypes"] == ["Ingress"]
    (rule,) = spec["ingress"]
    # ONE `from` entry holding both selectors: AND, not OR.
    (source,) = rule["from"]
    assert source == {
        "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "org-acme"}},
        "podSelector": {"matchLabels": {"rapport.dev/encounter": "enc-1a2b3c4d", "rapport.dev/side": "initiator"}},
    }
    assert rule["ports"] == [{"protocol": "TCP", "port": 8080}]


def test_invalid_encounters_are_rejected():
    same_org = make_enc()
    same_org["spec"]["responder"]["orgId"] = "acme"
    with pytest.raises(InvalidEncounter):
        build_job(same_org, "initiator", IMAGE)
    with pytest.raises(InvalidEncounter):
        build_service(make_enc(ttlSeconds=5))
    broken = make_enc()
    del broken["spec"]["responder"]
    with pytest.raises(InvalidEncounter):
        build_network_policy(broken)
