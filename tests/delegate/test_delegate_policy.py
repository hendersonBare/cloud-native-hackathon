import asyncio

import httpx
import pytest
import respx
from delegate_fixtures import ENC

from rapport_common import names
from rapport_common.models import PolicyInput, PolicyItem
from rapport_delegate.policy import FakePolicy, OpaPolicy

OPA = "http://opa.test:8181"
URL = f"{OPA}/v1/data/rapport/decision"


def pin(*, level, tags=(), kind="document", owner=None, counterparty="bluefin", action="offer"):
    return PolicyInput(
        action=action, org_id="acme", self_persona_id="acme.ava", counterparty_org_id=counterparty, encounter_id=ENC,
        item=PolicyItem(item_id="x", kind=kind, share_level=level, tags=list(tags), owner_persona_id=owner),
    )


# SPEC 6 test vectors
@pytest.mark.parametrize(
    ("kwargs", "decision", "rule"),
    [
        (dict(level="partner", tags=["pricing"]), "deny", "pricing_needs_approval"),
        (dict(level="partner", tags=["security"]), "allow", "partner_with_nda"),
        (dict(level="public", tags=["healthcare"]), "allow", "public_ok"),
        (dict(level="internal", tags=["anything"]), "deny", "internal_never_leaves"),
        (dict(level="public", kind="profile", owner="acme.sam"), "deny", "profile_owner_only"),
        (dict(level="public", kind="profile", owner="acme.ava"), "allow", "public_ok"),
        (dict(level="partner", tags=["security"], counterparty="globex"), "deny", "partner_needs_nda"),
    ],
)
async def test_fake_policy_follows_the_spec_table(kwargs, decision, rule):
    result = await FakePolicy().decide(pin(**kwargs))
    assert (result.decision, result.rule_id) == (decision, rule)


@respx.mock
async def test_opa_allow_posts_input_to_the_decision_path():
    route = respx.post(URL).respond(json={"result": {"decision": "allow", "rule_id": "public_ok", "reason": "ok"}})
    async with httpx.AsyncClient() as client:
        result = await OpaPolicy("acme", client, base_url=OPA).decide(pin(level="public"))
    assert result.decision == "allow"
    body = route.calls.last.request.read()
    assert b'"input"' in body and b'"counterparty_org_id":"bluefin"' in body.replace(b" ", b"")


def test_default_opa_url_comes_from_names(monkeypatch):
    monkeypatch.delenv("OPA_URL_ACME", raising=False)
    assert OpaPolicy("acme", httpx.AsyncClient())._url == names.opa_url("acme") + "/v1/data/rapport/decision"


@respx.mock
@pytest.mark.parametrize(
    "setup",
    [
        lambda: respx.post(URL).mock(side_effect=httpx.ReadTimeout("slow")),
        lambda: respx.post(URL).mock(side_effect=httpx.ConnectError("down")),
        lambda: respx.post(URL).respond(status_code=500),
        lambda: respx.post(URL).respond(json={}),  # rule undefined: no result
        lambda: respx.post(URL).respond(json={"result": {"decision": "maybe"}}),  # malformed
        lambda: respx.post(URL).respond(content=b"not json"),
        lambda: respx.post(URL).respond(json=["unexpected"]),
    ],
)
async def test_opa_fails_closed(setup):
    setup()
    async with httpx.AsyncClient() as client:
        result = await OpaPolicy("acme", client, base_url=OPA).decide(pin(level="public"))
    assert (result.decision, result.rule_id) == ("deny", "opa_unavailable")


@respx.mock
async def test_slow_opa_is_cut_off_at_the_timeout():
    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json={"result": {"decision": "allow", "rule_id": "public_ok", "reason": "ok"}})

    respx.post(URL).mock(side_effect=slow)
    async with httpx.AsyncClient() as client:
        result = await OpaPolicy("acme", client, base_url=OPA, timeout=0.05).decide(pin(level="public"))
    assert (result.decision, result.rule_id) == ("deny", "opa_unavailable")
