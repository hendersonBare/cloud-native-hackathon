"""Cold-start safety: bounded uvicorn graceful shutdown, and a startupProbe on every probed Deployment."""

from pathlib import Path

import pytest
import yaml

from rapport_gateway.__main__ import GRACEFUL_SHUTDOWN_SECONDS, make_servers
from rapport_gateway.settings import Settings

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
MANIFESTS = [
    DEPLOY / "gateway" / "deployment.yaml",
    DEPLOY / "briefer" / "briefer-acme.yaml",
    DEPLOY / "briefer" / "briefer-bluefin.yaml",
    DEPLOY / "operator" / "deployment.yaml",
]


def test_both_uvicorn_servers_bound_graceful_shutdown() -> None:
    public, internal = make_servers(object(), object(), Settings(mock=True, web_dir=None))
    assert GRACEFUL_SHUTDOWN_SECONDS == 5
    assert public.config.timeout_graceful_shutdown == GRACEFUL_SHUTDOWN_SECONDS
    assert internal.config.timeout_graceful_shutdown == GRACEFUL_SHUTDOWN_SECONDS


@pytest.mark.parametrize("path", MANIFESTS, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_deployment_has_startup_probe_matching_liveness(path: Path) -> None:
    docs = [d for d in yaml.safe_load_all(path.read_text()) if d and d.get("kind") == "Deployment"]
    assert len(docs) == 1
    for container in docs[0]["spec"]["template"]["spec"]["containers"]:
        if "livenessProbe" not in container:
            continue
        startup = container.get("startupProbe")
        assert startup, f"{path}: container {container['name']} has liveness but no startupProbe"
        assert startup["httpGet"] == container["livenessProbe"]["httpGet"]
        assert startup["periodSeconds"] == 3
        assert startup["timeoutSeconds"] == 2
        assert startup["failureThreshold"] >= 40  # up to 120 s to start
