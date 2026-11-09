"""Policy client: OPA over HTTP (SPEC 6), failing closed, plus a fake that implements the SPEC 6 table."""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

import httpx
from pydantic import ValidationError

from rapport_common import names
from rapport_common.models import PolicyDecision, PolicyInput

log = logging.getLogger("rapport.delegate.policy")

OPA_TIMEOUT_S = 2.0
DECISION_PATH = "/v1/data/rapport/decision"
UNAVAILABLE = PolicyDecision(decision="deny", rule_id="opa_unavailable", reason="policy engine unavailable")


class Policy(Protocol):
    async def decide(self, policy_input: PolicyInput) -> PolicyDecision: ...


class OpaPolicy:
    """POST {opa_url(org)}/v1/data/rapport/decision. Any error, timeout or missing result is a deny."""

    def __init__(self, org_id: str, client: httpx.AsyncClient, *, base_url: str | None = None,
                 timeout: float = OPA_TIMEOUT_S) -> None:
        self._url = (base_url or names.opa_url(org_id)).rstrip("/") + DECISION_PATH
        self._client = client
        self._timeout = timeout

    async def decide(self, policy_input: PolicyInput) -> PolicyDecision:
        body = {"input": policy_input.model_dump(mode="json")}
        try:
            async with asyncio.timeout(self._timeout):
                resp = await self._client.post(self._url, json=body, timeout=self._timeout)
            resp.raise_for_status()
            result = resp.json().get("result")
            if result is None:
                log.warning("opa returned no result for item %s", policy_input.item.item_id)
                return UNAVAILABLE
            return PolicyDecision.model_validate(result)
        except (httpx.HTTPError, TimeoutError, ValueError, ValidationError, AttributeError) as exc:
            log.warning("opa call failed (%s) for item %s; denying", type(exc).__name__, policy_input.item.item_id)
            return UNAVAILABLE


DEFAULT_ORG_DATA: dict[str, dict[str, list[str]]] = {
    "acme": {"nda_with": ["bluefin"], "pricing_approved_for": []},
    "bluefin": {"nda_with": ["acme"], "pricing_approved_for": []},
}


class FakePolicy:
    """The SPEC 6 rule table, first match wins. For tests and local runs without OPA."""

    def __init__(self, org_data: dict[str, dict[str, list[str]]] | None = None) -> None:
        self._data = org_data if org_data is not None else DEFAULT_ORG_DATA
        self.calls: list[PolicyInput] = []

    async def decide(self, policy_input: PolicyInput) -> PolicyDecision:
        self.calls.append(policy_input)
        org = self._data.get(policy_input.org_id, {"nda_with": [], "pricing_approved_for": []})
        item = policy_input.item
        who = policy_input.counterparty_org_id
        if item.share_level == "internal":
            return _deny("internal_never_leaves", "internal records never leave the company")
        if item.kind == "profile" and item.owner_persona_id != policy_input.self_persona_id:
            return _deny("profile_owner_only", "only the owner's own profile may be shared")
        if "pricing" in item.tags and who not in org["pricing_approved_for"]:
            return _deny("pricing_needs_approval", "pricing needs explicit approval for this counterparty")
        if item.share_level == "partner" and who not in org["nda_with"]:
            return _deny("partner_needs_nda", "partner material needs an NDA with the counterparty")
        if item.share_level == "public":
            return PolicyDecision(decision="allow", rule_id="public_ok", reason="public material")
        if item.share_level == "partner" and who in org["nda_with"]:
            return PolicyDecision(decision="allow", rule_id="partner_with_nda", reason="partner material under NDA")
        return _deny("default_deny", "no rule allows this")


def _deny(rule_id: str, reason: str) -> PolicyDecision:
    return PolicyDecision(decision="deny", rule_id=rule_id, reason=reason)
