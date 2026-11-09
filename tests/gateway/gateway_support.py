"""Helpers shared by the gateway tests: an app stack with fakes, SSE reading, event builders."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from rapport_common.models import (
    DelegateStatusData,
    EncounterSpec,
    ExchangeMessageData,
    GatewayEvent,
    PolicyDecisionData,
    PrivateBrief,
    SharedBrief,
    SharedFollowup,
    SharedItem,
)
from rapport_gateway.app import create_app, create_internal_app
from rapport_gateway.bus import Subscription
from rapport_gateway.deps import Deps, build_deps
from rapport_gateway.errors import LauncherUnavailable
from rapport_gateway.k8s import PodRegistry
from rapport_gateway.settings import Settings

ACME_BRIEFER = "http://briefer.org-acme.svc.cluster.local:8080"
BLUEFIN_BRIEFER = "http://briefer.org-bluefin.svc.cluster.local:8080"
AVA, BO, SAM, KAI = "acme.ava", "bluefin.bo", "acme.sam", "bluefin.kai"


class FakeLauncher:
    """Stands in for the Kubernetes API: records what would have been created."""

    def __init__(self, unavailable: bool = False) -> None:
        self.launched: list[tuple[str, EncounterSpec, str | None]] = []
        self.unavailable = unavailable

    async def launch(self, encounter_id: str, spec: EncounterSpec, traceparent: str | None) -> None:
        if self.unavailable:
            raise LauncherUnavailable()
        self.launched.append((encounter_id, spec, traceparent))


def settings_for(**overrides: Any) -> Settings:
    base: dict[str, Any] = dict(
        mock=False,
        version="test",
        web_dir=None,
        mock_speed=1000.0,
        keepalive_s=0.05,
        check_delegate_ip=False,
        brief_timeout_s=2.0,
        deep_dive_timeout_s=2.0,
        remember_timeout_s=2.0,
        proxy_timeout_s=2.0,
    )
    base.update(overrides)
    return Settings(**base)


@dataclass
class Stack:
    deps: Deps
    client: httpx.AsyncClient
    internal: httpx.AsyncClient
    launcher: FakeLauncher
    registry: PodRegistry
    app: Any = None
    internal_app: Any = None
    subs: list[Subscription] = field(default_factory=list)

    def watch(self, persona_id: str | None) -> Subscription:
        """Subscribe like an SSE client would (swarm when persona_id is None)."""
        sub = self.deps.bus.subscribe(persona_id)
        self.subs.append(sub)
        return sub

    async def close(self) -> None:
        await self.client.aclose()
        await self.internal.aclose()
        await self.deps.stop()


async def make_stack(
    *, launcher: FakeLauncher | None = None, registry: PodRegistry | None = None, **settings: Any
) -> Stack:
    cfg = settings_for(**settings)
    launcher = launcher or FakeLauncher()
    registry = registry or PodRegistry()
    deps = build_deps(
        cfg,
        http=httpx.AsyncClient(timeout=cfg.proxy_timeout_s),
        launcher=launcher,
        registry=registry,
        pod_watcher=None,
    )
    deps.owns_http = True
    app = create_app(cfg, deps)
    internal_app = create_internal_app(deps)
    return Stack(
        deps=deps,
        client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway"),
        internal=httpx.AsyncClient(transport=httpx.ASGITransport(app=internal_app), base_url="http://internal"),
        launcher=launcher,
        registry=registry,
        app=app,
        internal_app=internal_app,
    )


def drain(sub: Subscription) -> list[GatewayEvent]:
    out = []
    while not sub.queue.empty():
        out.append(sub.queue.get_nowait())
    return out


def types(events: list[GatewayEvent]) -> list[str]:
    return [e.type for e in events]


async def eventually(check: Callable[[], Any], timeout: float = 3.0) -> Any:
    """Poll until `check()` is truthy; return its value."""
    deadline = time.monotonic() + timeout
    while True:
        value = check()
        if value:
            return value
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


async def collect(sub: Subscription, wanted: str, timeout: float = 3.0) -> list[GatewayEvent]:
    """Wait until an event of type `wanted` has arrived and return everything seen so far."""
    seen: list[GatewayEvent] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        seen.extend(drain(sub))
        if wanted in types(seen):
            return seen
        await asyncio.sleep(0.01)
    raise AssertionError(f"no {wanted} event; saw {types(seen)}")


# ----------------------------------------------------------------------------- SSE over raw ASGI
async def read_sse(app: Any, query: str, *, min_chunks: int = 1, wait: float = 3.0) -> bytes:
    """Open GET /api/stream?<query> on the ASGI app, read until `min_chunks` bodies arrived, then disconnect."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/stream",
        "raw_path": b"/api/stream",
        "query_string": query.encode(),
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 5000),
        "server": ("gateway", 80),
    }
    sent: asyncio.Queue = asyncio.Queue()
    gone = asyncio.Event()

    async def receive() -> dict:
        await gone.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        await sent.put(message)

    task = asyncio.create_task(app(scope, receive, send))
    body, status, headers = b"", None, {}
    chunks = 0
    try:
        deadline = time.monotonic() + wait
        while chunks < min_chunks and time.monotonic() < deadline:
            try:
                message = await asyncio.wait_for(sent.get(), timeout=0.2)
            except asyncio.TimeoutError:
                continue
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = {k.decode(): v.decode() for k, v in message["headers"]}
            elif message["type"] == "http.response.body" and message.get("body"):
                body += message["body"]
                chunks += 1
    finally:
        gone.set()
        try:
            await asyncio.wait_for(task, timeout=2)
        except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
            task.cancel()
    read_sse.last_status = status  # type: ignore[attr-defined]
    read_sse.last_headers = headers  # type: ignore[attr-defined]
    return body


# ----------------------------------------------------------------------------- payload builders
def private_brief(persona_id: str, counterparty: str, encounter_id: str = "enc-x") -> dict:
    return PrivateBrief(
        encounter_id=encounter_id,
        persona_id=persona_id,
        counterparty_persona_id=counterparty,
        language="en",
        headline="Brief headline",
        talking_points=["a"],
    ).model_dump(mode="json")


def shared_brief(encounter_id: str, persona_id: str, *, followups: int = 1) -> SharedBrief:
    org = persona_id.split(".")[0]
    return SharedBrief(
        encounter_id=encounter_id,
        for_persona_id=persona_id,
        language="en",
        summary="They share eBPF interest.",
        mutual_interests=["ebpf", "Not A Tag"],
        shared_items=[SharedItem(from_org=org, item_id="acme-doc-0002", title="Case study", summary="S")],
        followups=[
            SharedFollowup(followup_id=f"fu-{i}", text=f"Follow up {i}", owner_org_id=org) for i in range(followups)
        ],
    )


def delegate_event(encounter_id: str, org_id: str, persona_id: str, type_: str, data: dict) -> dict:
    return {"encounter_id": encounter_id, "org_id": org_id, "persona_id": persona_id, "type": type_, "data": data}


def exchange_data(from_org: str, to_org: str) -> dict:
    return ExchangeMessageData(
        round=1, type="hello", from_org=from_org, to_org=to_org, display="Ava's agent introduces Ava"
    ).model_dump(mode="json")


def policy_data(org_id: str) -> dict:
    return PolicyDecisionData(
        org_id=org_id,
        action="answer",
        item_id="acme-doc-0004",
        item_title="Pricing",
        decision="deny",
        rule_id="pricing_needs_approval",
    ).model_dump(mode="json")


def status_data(side: str, status: str = "started") -> dict:
    return DelegateStatusData(side=side, status=status).model_dump(mode="json")  # type: ignore[arg-type]
