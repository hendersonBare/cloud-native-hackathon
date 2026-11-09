"""LocalProcessLauncher through an injected spawn function: argv, env and pod_status; no real delegates run."""

import asyncio
import sys

import httpx
import pytest
import respx
from gateway_support import ACME_BRIEFER, AVA, BLUEFIN_BRIEFER, BO, collect, delegate_event, make_stack, private_brief
from gateway_support import shared_brief as make_shared_brief
from gateway_support import types

from rapport_common.models import EncounterParty, EncounterSpec, PodStatusData
from rapport_gateway.errors import GatewayError
from rapport_gateway.launcher_local import LocalProcessLauncher
from rapport_gateway.settings import Settings

SPEC = EncounterSpec(
    initiator=EncounterParty(orgId="acme", personaId=AVA, malicious=False),
    responder=EncounterParty(orgId="bluefin", personaId=BO, malicious=True),
)


class FakeProc:
    def __init__(self, code: int = 0) -> None:
        self.code, self.terminated, self.release = code, False, asyncio.Event()

    async def wait(self) -> int:
        await self.release.wait()
        return self.code

    def terminate(self) -> None:
        self.terminated = True
        self.release.set()


def make_launcher(procs=None, fail=False, on_pod=None):
    spawned, seen = [], []
    procs = procs or []

    async def spawn(argv, env):
        if fail:
            raise OSError("no python")
        proc = procs.pop(0) if procs else FakeProc()
        spawned.append((argv, env, proc))
        return proc

    ports = iter([40001, 40002])
    environ = {
        "PATH": "/bin",
        "PYTHONPATH": "src",
        "OPA_URL_ACME": "http://127.0.0.1:8181",
        "ES_URL": "http://es",
        "ES_API_KEY": "placeholder",
        "OPENAI_API_KEY": "placeholder",
        "SECRET_THING": "no",
        "RAPPORT_LLM_MODEL": "m",
    }
    launcher = LocalProcessLauncher(
        Settings(internal_port=18081),
        on_pod or (lambda enc, data: seen.append((enc, data))),
        spawn=spawn,
        port_picker=lambda: next(ports),
        environ=environ,
    )
    return launcher, spawned, seen


async def test_spawns_both_delegates_with_the_spec_env():
    launcher, spawned, seen = make_launcher()
    await launcher.launch("enc-1a2b3c4d", SPEC, "00-abc-def-01")
    assert len(spawned) == 2
    (r_argv, r_env, _), (i_argv, i_env, _) = spawned  # the responder starts first
    assert r_argv == i_argv == [sys.executable, "-m", "rapport_delegate"]

    assert r_env["ROLE"] == "responder" and r_env["PORT"] == "40001" and "PEER_URL" not in r_env
    assert r_env["SELF_ORG"] == "bluefin" and r_env["SELF_PERSONA"] == BO
    assert r_env["PEER_ORG"] == "acme" and r_env["PEER_PERSONA"] == AVA and r_env["MALICIOUS"] == "true"

    assert i_env["ROLE"] == "initiator" and i_env["PEER_URL"] == "http://127.0.0.1:40001"  # the responder's port
    assert i_env["PORT"] == "40002" and i_env["MALICIOUS"] == "false"
    assert i_env["SELF_ORG"] == "acme" and i_env["PEER_PERSONA"] == BO

    for env in (r_env, i_env):
        assert env["ENCOUNTER_ID"] == "enc-1a2b3c4d" and env["TRACEPARENT"] == "00-abc-def-01"
        assert env["GATEWAY_URL"] == "http://127.0.0.1:18081"
        assert env["OPA_URL_ACME"] == "http://127.0.0.1:8181" and env["ES_URL"] == "http://es"
        assert env["ES_API_KEY"] == "placeholder" and env["RAPPORT_LLM_MODEL"] == "m"
        assert "SECRET_THING" not in env
    assert r_env["POD_NAMESPACE"] == "org-bluefin" and i_env["POD_NAMESPACE"] == "org-acme"
    assert [(d.side, d.phase) for _, d in seen] == [
        ("responder", "Pending"),
        ("initiator", "Pending"),
        ("responder", "Running"),
        ("initiator", "Running"),
    ]


async def test_pod_status_follows_the_process_lifecycle():
    ok, bad = FakeProc(0), FakeProc(3)
    launcher, _, seen = make_launcher([bad, ok])  # responder fails, initiator succeeds
    await launcher.launch("enc-1", SPEC, None)
    ok.release.set(), bad.release.set()
    for _ in range(50):
        if len(seen) >= 6:
            break
        await asyncio.sleep(0.01)
    final = {d.side: d.phase for _, d in seen[4:]}
    assert final == {"responder": "Failed", "initiator": "Succeeded"}
    assert all(isinstance(d, PodStatusData) for _, d in seen)


async def test_no_traceparent_means_no_env_and_a_spawn_failure_is_a_502():
    launcher, spawned, _ = make_launcher()
    await launcher.launch("enc-1", SPEC, None)
    assert all("TRACEPARENT" not in env for _, env, _ in spawned)
    broken, _, _ = make_launcher(fail=True)
    with pytest.raises(GatewayError) as err:
        await broken.launch("enc-1", SPEC, None)
    assert err.value.status_code == 502


async def test_close_terminates_running_delegates():
    launcher, spawned, _ = make_launcher()
    await launcher.launch("enc-1", SPEC, None)
    await launcher.close()
    assert all(proc.terminated for _, _, proc in spawned)


async def test_local_mode_accepts_events_with_checks_a_and_b_only():
    """RAPPORT_LAUNCHER=local: no pod registry, so the IP check is off; org/persona/encounter checks still apply."""
    with respx.mock(assert_all_called=False) as router:
        router.post(f"{ACME_BRIEFER}/v1/brief").mock(return_value=httpx.Response(200, json=private_brief(AVA, BO)))
        router.post(f"{BLUEFIN_BRIEFER}/v1/brief").mock(return_value=httpx.Response(200, json=private_brief(BO, AVA)))
        router.post(url__regex=r".*/v1/remember").mock(return_value=httpx.Response(200, json={"written": 1}))
        holder = {}
        launcher, spawned, _ = make_launcher(
            on_pod=lambda enc, d: holder["bus"].emit("pod_status", d, encounter_id=enc)
        )
        stack = await make_stack(launcher=launcher, launcher_kind="local")
        holder["bus"] = stack.deps.bus
        try:
            swarm = stack.watch(None)
            rid = (await stack.client.post("/api/connect", json={"from_persona_id": AVA, "to_persona_id": BO})).json()[
                "request_id"
            ]
            eid = (await stack.client.post(f"/api/connect/{rid}/accept", json={"persona_id": BO})).json()[
                "encounter_id"
            ]
            assert len(spawned) == 2
            good = delegate_event(eid, "acme", AVA, "shared_brief", make_shared_brief(eid, AVA).model_dump(mode="json"))
            assert (await stack.internal.post("/internal/events", json=good)).status_code == 202
            forged = delegate_event(
                eid, "bluefin", AVA, "shared_brief", make_shared_brief(eid, AVA).model_dump(mode="json")
            )
            assert (await stack.internal.post("/internal/events", json=forged)).status_code == 403
            events = await collect(swarm, "shared_brief")
            assert "pod_status" in types(events)  # the launcher's lifecycle reports reached the swarm
        finally:
            await stack.close()
