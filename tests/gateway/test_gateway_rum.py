"""GET /api/rum-config: Dash0 website monitoring settings for the web page (web/app/rum.js)."""

import pytest
from gateway_support import make_stack

from rapport_gateway.settings import Settings, parse_rum_endpoint

ENDPOINT = "https://ingress.example.aws.dash0.com"
TOKEN = "auth_website_test_placeholder"


async def test_disabled_by_default():
    s = await make_stack(mock=True)
    try:
        r = await s.client.get("/api/rum-config")
        assert r.status_code == 200
        assert r.json() == {"enabled": False}
        assert r.headers["cache-control"] == "no-store"
    finally:
        await s.close()


@pytest.mark.parametrize(
    "overrides",
    [{"rum_endpoint": ENDPOINT}, {"rum_auth_token": TOKEN}],
)
async def test_needs_both_endpoint_and_token(overrides):
    s = await make_stack(mock=True, **overrides)
    try:
        assert (await s.client.get("/api/rum-config")).json() == {"enabled": False}
    finally:
        await s.close()


async def test_enabled_config_follows_the_sdk_option_names():
    s = await make_stack(
        mock=True, rum_endpoint=ENDPOINT, rum_auth_token=TOKEN, rum_dataset="rapport", environment="hackathon"
    )
    try:
        assert (await s.client.get("/api/rum-config")).json() == {
            "enabled": True,
            "serviceName": "rapport-web",
            "serviceVersion": "test",
            "environment": "hackathon",
            "endpoint": {"url": ENDPOINT, "authToken": TOKEN, "dataset": "rapport"},
        }
    finally:
        await s.close()


async def test_dataset_is_left_out_when_unset():
    s = await make_stack(mock=True, rum_endpoint=ENDPOINT, rum_auth_token=TOKEN)
    try:
        assert (await s.client.get("/api/rum-config")).json()["endpoint"] == {"url": ENDPOINT, "authToken": TOKEN}
    finally:
        await s.close()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (ENDPOINT + "/", ENDPOINT),
        ("  " + ENDPOINT + "  ", ENDPOINT),
        ("http://localhost:4318", "http://localhost:4318"),
        ("http://127.0.0.1:4318", "http://127.0.0.1:4318"),
        ("http://ingress.example.aws.dash0.com", None),  # the browser must not post over plain http
        ("ftp://ingress.example.aws.dash0.com", None),
        ("https://", None),
        ("not a url", None),
        ("", None),
        (None, None),
    ],
)
def test_endpoint_must_be_https_or_localhost(raw, expected):
    assert parse_rum_endpoint(raw) == expected


def test_settings_read_only_the_rum_variables(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://backend.example")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "Authorization=Bearer backend_token_placeholder")
    for var in ("DASH0_RUM_ENDPOINT", "DASH0_RUM_AUTH_TOKEN", "DASH0_RUM_DATASET", "RAPPORT_ENV"):
        monkeypatch.delenv(var, raising=False)
    s = Settings.from_env()
    assert (s.rum_endpoint, s.rum_auth_token, s.rum_dataset, s.environment) == (None, None, None, "dev")

    monkeypatch.setenv("DASH0_RUM_ENDPOINT", ENDPOINT)
    monkeypatch.setenv("DASH0_RUM_AUTH_TOKEN", f" {TOKEN} ")
    monkeypatch.setenv("DASH0_RUM_DATASET", "")
    monkeypatch.setenv("RAPPORT_ENV", "hackathon")
    s = Settings.from_env()
    assert (s.rum_endpoint, s.rum_auth_token, s.rum_dataset, s.environment) == (ENDPOINT, TOKEN, None, "hackathon")


def test_the_token_stays_out_of_the_settings_repr():
    assert TOKEN not in repr(Settings(rum_endpoint=ENDPOINT, rum_auth_token=TOKEN))


async def test_never_serves_the_backend_otlp_token(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "Authorization=Bearer backend_token_placeholder")
    s = await make_stack(mock=True, rum_endpoint=ENDPOINT, rum_auth_token=TOKEN)
    try:
        body = (await s.client.get("/api/rum-config")).text
        assert "backend_token_placeholder" not in body
    finally:
        await s.close()
