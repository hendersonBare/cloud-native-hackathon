"""Kubernetes pieces with the client faked: Encounter creation, the pod watch, RBAC manifests."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from gateway_support import AVA, BO, eventually

from rapport_common.models import EncounterParty, EncounterSpec, PodStatusData
from rapport_gateway.errors import GatewayError, LauncherUnavailable
from rapport_gateway.k8s import KubernetesLauncher, PodRegistry, PodWatcher, pod_info

ROOT = Path(__file__).resolve().parents[2]
SPEC = EncounterSpec(
    initiator=EncounterParty(orgId="acme", personaId=AVA),
    responder=EncounterParty(orgId="bluefin", personaId=BO, malicious=True),
)


class FakeApi:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = []
        self.error = error

    def create_cluster_custom_object(self, group, version, plural, body):
        self.calls.append((group, version, plural, body))
        if self.error:
            raise self.error
        return body


def pod(name="delegate-enc-1-abc", ns="org-acme", phase="Running", ip="10.0.0.5", **labels):
    base = {
        "rapport.dev/role": "delegate",
        "rapport.dev/encounter": "enc-1",
        "rapport.dev/org": "acme",
        "rapport.dev/side": "initiator",
    }
    base.update(labels)
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, namespace=ns, labels=base),
        status=SimpleNamespace(phase=phase, pod_ip=ip),
    )


async def test_launcher_creates_the_cluster_scoped_encounter_in_a_worker_thread():
    api = FakeApi()
    launcher = KubernetesLauncher(api_factory=lambda: api)
    await launcher.launch("enc-1a2b3c4d", SPEC, "00-abc-def-01")
    [(group, version, plural, body)] = api.calls
    assert (group, version, plural) == ("rapport.dev", "v1alpha1", "encounters")
    assert body["metadata"]["name"] == "enc-1a2b3c4d"
    assert body["metadata"]["annotations"]["rapport.dev/traceparent"] == "00-abc-def-01"
    assert body["spec"]["initiator"]["orgId"] == "acme"


async def test_launcher_maps_api_errors_and_missing_config():
    class ApiError(Exception):
        status = 403

    with pytest.raises(GatewayError) as err:
        await KubernetesLauncher(api_factory=lambda: FakeApi(ApiError("forbidden"))).launch("enc-1", SPEC, None)
    assert err.value.status_code == 502 and "forbidden" not in err.value.detail

    def no_config():
        raise LauncherUnavailable()

    with pytest.raises(LauncherUnavailable) as unavailable:
        await KubernetesLauncher(api_factory=no_config).launch("enc-1", SPEC, None)
    assert unavailable.value.status_code == 503


def test_pod_info_reads_labels_and_ignores_unlabelled_pods():
    info = pod_info(pod())
    assert (info.encounter_id, info.org_id, info.side, info.phase, info.ip) == (
        "enc-1",
        "acme",
        "initiator",
        "Running",
        "10.0.0.5",
    )
    assert pod_info(SimpleNamespace(metadata=SimpleNamespace(name="x", namespace="n", labels={}), status=None)) is None
    assert pod_info(pod(**{"rapport.dev/side": "other"})) is None


def test_registry_matches_encounter_org_side_and_ip():
    registry = PodRegistry()
    registry.update(pod_info(pod()))
    assert registry.matches("10.0.0.5", "enc-1", "acme")
    assert registry.matches("10.0.0.5", "enc-1", "acme", "initiator")
    assert not registry.matches("10.0.0.5", "enc-1", "acme", "responder")
    assert not registry.matches("10.0.0.5", "enc-2", "acme")
    assert not registry.matches("10.0.0.5", "enc-1", "bluefin")
    assert not registry.matches("10.9.9.9", "enc-1", "acme")
    assert not registry.matches(None, "enc-1", "acme")
    registry.remove(pod_info(pod()))
    assert not registry.matches("10.0.0.5", "enc-1", "acme")


async def test_pod_watch_hands_pod_status_to_the_loop_from_a_thread():
    registry = PodRegistry()
    seen: list[tuple[str, PodStatusData]] = []
    events = [
        {"type": "ADDED", "object": pod(phase="Pending", ip=None)},
        {"type": "MODIFIED", "object": pod(phase="Pending")},  # same phase: no second event
        {"type": "MODIFIED", "object": pod(phase="Running")},
        {
            "type": "ADDED",
            "object": pod(
                name="other", ns="org-bluefin", **{"rapport.dev/org": "bluefin", "rapport.dev/side": "responder"}
            ),
        },
        {
            "type": "ADDED",
            "object": SimpleNamespace(metadata=SimpleNamespace(name="x", namespace="n", labels={}), status=None),
        },  # not ours
    ]
    watcher = PodWatcher(
        registry,
        lambda enc, data: seen.append((enc, data)),
        namespaces=("org-acme",),
        stream=lambda ns: iter(events) if not seen else iter(()),
        load_config=None,
        retry_s=0.01,
    )
    watcher.start(asyncio.get_running_loop())
    await eventually(lambda: len(seen) >= 3)
    watcher.stop()
    assert [(e, d.pod, d.phase) for e, d in seen[:3]] == [
        ("enc-1", "delegate-enc-1-abc", "Pending"),
        ("enc-1", "delegate-enc-1-abc", "Running"),
        ("enc-1", "other", "Running"),
    ]
    assert seen[2][1].org_id == "bluefin" and seen[2][1].side == "responder"
    assert registry.matches("10.0.0.5", "enc-1", "acme")


async def test_pod_watch_deleted_pod_leaves_the_registry_and_errors_do_not_kill_the_thread():
    registry = PodRegistry()
    registry.update(pod_info(pod()))
    attempts = []

    def stream(ns):
        attempts.append(ns)
        if len(attempts) == 1:
            raise RuntimeError("api down")
        return iter([{"type": "DELETED", "object": pod()}])

    watcher = PodWatcher(
        registry, lambda *_: None, namespaces=("org-acme",), stream=stream, load_config=None, retry_s=0.01
    )
    watcher.start(asyncio.get_running_loop())
    await eventually(lambda: not registry.matches("10.0.0.5", "enc-1", "acme"))
    watcher.stop()
    assert len(attempts) >= 2


def test_rbac_manifest_is_least_privilege():
    docs = [d for d in yaml.safe_load_all((ROOT / "deploy/gateway/rbac.yaml").read_text()) if d]
    cluster_role = next(d for d in docs if d["kind"] == "ClusterRole")
    assert cluster_role["rules"] == [
        {"apiGroups": ["rapport.dev"], "resources": ["encounters"], "verbs": ["create", "get", "list", "watch"]}
    ]
    roles = {d["metadata"]["namespace"]: d for d in docs if d["kind"] == "Role"}
    assert set(roles) == {"org-acme", "org-bluefin"}
    for role in roles.values():
        assert role["rules"] == [{"apiGroups": [""], "resources": ["pods"], "verbs": ["get", "list", "watch"]}]
    for binding in (d for d in docs if d["kind"] in ("RoleBinding", "ClusterRoleBinding")):
        assert binding["subjects"] == [{"kind": "ServiceAccount", "name": "gateway", "namespace": "team-rapport"}]
    kustomization = yaml.safe_load((ROOT / "deploy/gateway/kustomization.yaml").read_text())
    assert "rbac.yaml" in kustomization["resources"]
