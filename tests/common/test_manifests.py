"""Every manifest Argo CD deploys must fit the team vcluster: GHCR image via kustomize, explicit
requests AND limits (the team budget), and a non-root securityContext. See AGENTS.md "Limits"."""

from pathlib import Path

import pytest
import yaml

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
SKIP = {"kind", "elastic"}  # local-cluster config and Elastic Cloud files, not cluster manifests


def _docs():
    for path in sorted(DEPLOY.rglob("*.yaml")):
        if SKIP & set(path.relative_to(DEPLOY).parts) or path.name == "kustomization.yaml":
            continue
        for doc in yaml.safe_load_all(path.read_text()):
            if doc:
                yield path.relative_to(DEPLOY), doc


def _pod_specs():
    for path, doc in _docs():
        spec = doc.get("spec") or {}
        if doc.get("kind") in ("Deployment", "StatefulSet", "DaemonSet", "Job"):
            yield path, spec["template"]["spec"]
        elif doc.get("kind") == "Pod":
            yield path, spec


PODS = list(_pod_specs())


def test_no_kind_era_settings():
    for path, doc in _docs():
        text = yaml.safe_dump(doc)
        assert "rapport:dev" not in text, f"{path}: use `image: app`; kustomize sets the GHCR image"
        assert "NodePort" not in text, f"{path}: NodePort isn't available; use Service `app` port 80"
        assert "rapport-system" not in text, f"{path}: the system namespace is team-rapport"


@pytest.mark.parametrize("path,pod", PODS, ids=[str(p) for p, _ in PODS] or None)
def test_pods_fit_the_team_budget(path, pod):
    for c in pod.get("containers", []) + pod.get("initContainers", []):
        res = c.get("resources") or {}
        for kind in ("requests", "limits"):
            assert {"cpu", "memory"} <= set(res.get(kind) or {}), f"{path}:{c['name']} needs {kind} cpu+memory"
        sc = c.get("securityContext") or {}
        assert sc.get("allowPrivilegeEscalation") is False, f"{path}:{c['name']} securityContext"
        assert not sc.get("privileged"), f"{path}:{c['name']} privileged pods are refused by the host"
    assert not pod.get("hostNetwork") and not pod.get("hostPID"), f"{path}: refused by the host"
