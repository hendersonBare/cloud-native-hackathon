"""App wiring: CORS, the static web mount, settings parsing, startup without Kubernetes."""

import httpx
import pytest
from gateway_support import make_stack

from rapport_gateway.app import create_app
from rapport_gateway.deps import build_deps
from rapport_gateway.errors import LauncherUnavailable
from rapport_gateway.k8s import PodRegistry, PodWatcher
from rapport_gateway.settings import Settings, parse_origins


def test_cors_origins_parse_and_never_allow_a_wildcard():
    assert parse_origins("http://localhost:5180, https://x.example/ ,") == (
        "http://localhost:5180",
        "https://x.example",
    )
    assert parse_origins("*") == ()
    assert parse_origins("http://a, *") == ("http://a",)
    assert parse_origins(None) == ()


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("RAPPORT_MOCK", "1")
    monkeypatch.setenv("PORT", "18080")
    monkeypatch.setenv("INTERNAL_PORT", "18081")
    monkeypatch.setenv("RAPPORT_ADMIN_TOKEN", "t")
    monkeypatch.setenv("RAPPORT_VERSION", "abc123")
    monkeypatch.setenv("RAPPORT_LAUNCHER", "local")
    s = Settings.from_env()
    assert (s.mock, s.port, s.internal_port, s.admin_token, s.version, s.launcher) == (
        True,
        18080,
        18081,
        "t",
        "abc123",
        "local",
    )
    monkeypatch.setenv("RAPPORT_LAUNCHER", "bogus")
    assert Settings.from_env().launcher == "kubernetes"
    monkeypatch.delenv("RAPPORT_MOCK")
    monkeypatch.delenv("PORT")
    assert Settings.from_env().mock is False and Settings.from_env().port == 8080


async def test_cors_allows_exactly_the_configured_origins_with_credentials():
    s = await make_stack(mock=True, cors_origins=("http://localhost:5180",))
    try:
        ok = await s.client.options(
            "/api/connect",
            headers={
                "Origin": "http://localhost:5180",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert ok.headers["access-control-allow-origin"] == "http://localhost:5180"
        assert ok.headers["access-control-allow-credentials"] == "true"
        other = await s.client.get("/api/personas", headers={"Origin": "http://evil.example"})
        assert "access-control-allow-origin" not in other.headers
        same = await s.client.get("/api/personas", headers={"Origin": "http://localhost:5180"})
        assert same.headers["access-control-allow-origin"] == "http://localhost:5180"
    finally:
        await s.close()


async def test_no_cors_headers_when_unset():
    s = await make_stack(mock=True)
    try:
        r = await s.client.get("/api/personas", headers={"Origin": "http://localhost:5180"})
        assert "access-control-allow-origin" not in r.headers
    finally:
        await s.close()


async def test_static_web_mount_comes_after_the_api(tmp_path):
    (tmp_path / "index.html").write_text("<h1>Rapport</h1>")
    s = await make_stack(mock=True, web_dir=tmp_path)
    try:
        assert "<h1>Rapport</h1>" in (await s.client.get("/")).text
        assert (await s.client.get("/api/personas")).status_code == 200
        assert (await s.client.get("/healthz")).json()["ok"] is True
        assert (await s.client.get("/missing.js")).status_code == 404
        # POSTs to unknown paths are 404 (not the static files' 405), and /internal is never served
        assert (await s.client.post("/nope")).status_code == 404
        assert (await s.client.post("/internal/events", json={})).status_code == 404
        assert (await s.client.get("/internal/events")).status_code == 404
    finally:
        await s.close()


async def test_live_mode_starts_without_a_kubernetes_config(monkeypatch):
    """Startup must succeed with no cluster; only accept answers 503. (Never touches a real kubeconfig.)"""

    def no_cluster():
        raise LauncherUnavailable()

    monkeypatch.setattr("rapport_gateway.k8s.load_kube_config", no_cluster)
    watcher = PodWatcher(PodRegistry(), lambda *_: None, load_config=no_cluster, retry_s=0.05)
    settings = Settings(mock=False, web_dir=None)
    deps = build_deps(settings, pod_watcher=watcher)  # the default KubernetesLauncher loads its config lazily
    app = create_app(settings, deps)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://g") as client:
            assert (await client.get("/healthz")).status_code == 200
            rid = (
                await client.post("/api/connect", json={"from_persona_id": "acme.ava", "to_persona_id": "bluefin.bo"})
            ).json()["request_id"]
            r = await client.post(f"/api/connect/{rid}/accept", json={"persona_id": "bluefin.bo"})
            assert r.status_code == 503


async def test_mock_mode_needs_the_contract_fixtures(tmp_path):
    with pytest.raises(RuntimeError, match="demo-events.json"):
        build_deps(Settings(mock=True, contracts_dir=tmp_path))
