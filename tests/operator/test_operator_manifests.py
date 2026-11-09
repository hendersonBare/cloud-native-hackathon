"""deploy/operator/ is wired up the way the brief and SPEC 4.5 say."""

from pathlib import Path

import yaml

from rapport_common import names
from rapport_common.models import EncounterSpec

OPERATOR = Path(__file__).resolve().parents[2] / "deploy" / "operator"


def load(name):
    return list(yaml.safe_load_all((OPERATOR / name).read_text()))


def test_kustomization_lists_everything_except_the_sample():
    resources = load("kustomization.yaml")[0]["resources"]
    assert set(resources) == {"serviceaccount.yaml", "rbac.yaml", "deployment.yaml"}
    assert "sample-encounter.yaml" not in resources
    assert all((OPERATOR / r).exists() for r in resources)


def test_deployment():
    (dep,) = load("deployment.yaml")
    assert dep["metadata"]["namespace"] == "team-rapport"
    assert dep["spec"]["replicas"] == 1
    labels = dep["spec"]["template"]["metadata"]["labels"]
    assert labels["app.kubernetes.io/part-of"] == "rapport" and labels["rapport.dev/role"] == "operator"
    pod = dep["spec"]["template"]["spec"]
    assert pod["serviceAccountName"] == "operator"
    (c,) = pod["containers"]
    assert c["image"] == names.KUSTOMIZE_IMAGE_PLACEHOLDER
    assert c["imagePullPolicy"] == "IfNotPresent"
    assert c["command"] == ["python", "-m", "rapport_operator"]
    assert c["resources"] == names.RESOURCES_OPERATOR
    assert c["securityContext"] == names.SECURITY_CONTEXT
    env = {e["name"]: e for e in c["env"]}
    assert env["POD_NAME"]["valueFrom"]["fieldRef"]["fieldPath"] == "metadata.name"
    assert env["POD_NAMESPACE"]["valueFrom"]["fieldRef"]["fieldPath"] == "metadata.namespace"
    assert c["envFrom"] == [{"secretRef": {"name": "dash0-otlp", "optional": True}}]


def test_rbac_covers_spec_4_5_and_kopf_and_nothing_wide():
    role, binding = load("rbac.yaml")
    assert role["kind"] == "ClusterRole" and binding["kind"] == "ClusterRoleBinding"
    assert binding["roleRef"]["name"] == role["metadata"]["name"]
    assert binding["subjects"] == [{"kind": "ServiceAccount", "name": "operator", "namespace": "team-rapport"}]
    granted = {
        (g, r): set(rule["verbs"]) for rule in role["rules"] for g in rule["apiGroups"] for r in rule["resources"]
    }
    assert granted[("rapport.dev", "encounters")] == {"get", "list", "watch", "patch", "update", "delete"}
    assert {"patch", "update"} <= granted[("rapport.dev", "encounters/status")]
    assert granted[("rapport.dev", "encounters/finalizers")] == {"update"}
    for key in [("batch", "jobs"), ("", "services"), ("networking.k8s.io", "networkpolicies")]:
        assert granted[key] == {"create", "get", "list", "watch", "delete"}
    assert granted[("", "pods")] == {"get", "list", "watch"}
    assert "create" in granted[("", "events")]
    assert {"list", "watch"} <= granted[("apiextensions.k8s.io", "customresourcedefinitions")]
    assert {"list", "watch"} <= granted[("", "namespaces")]
    for rule in role["rules"]:
        assert "*" not in rule["verbs"] + rule["resources"] + rule["apiGroups"]
    assert ("", "secrets") not in granted


def test_sample_encounter_is_a_valid_encounter():
    (enc,) = load("sample-encounter.yaml")
    assert enc["apiVersion"] == f"{names.CRD_GROUP}/{names.CRD_VERSION}" and enc["kind"] == names.CRD_KIND
    spec = EncounterSpec.model_validate(enc["spec"])
    assert spec.initiator.orgId != spec.responder.orgId
    assert names.TRACEPARENT_ANNOTATION in enc["metadata"]["annotations"]
