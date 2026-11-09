"""RAPPORT_LAUNCHER=local: run the two delegates as subprocesses on a laptop, no Kubernetes (layer L2).

The env follows SPEC 4.4. The responder listens on a free local port; the initiator's PEER_URL points at it;
both report to this gateway's internal port. pod_status comes from the process lifecycle. Events from local
delegates are accepted with checks (a) and (b) only (there are no pods to check an IP against).
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import sys
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from rapport_common import names
from rapport_common.models import EncounterSpec, PodStatusData

from .errors import GatewayError
from .settings import Settings

log = logging.getLogger("rapport.gateway.launcher")

PASS_THROUGH_PREFIXES = ("OPA_URL_", "ES_", "RAPPORT_LLM_", "OTEL_", "OPENAI_")
PASS_THROUGH_NAMES = ("PATH", "PYTHONPATH", "HOME", "VIRTUAL_ENV", "LANG")


class Process(Protocol):
    async def wait(self) -> int: ...

    def terminate(self) -> None: ...


Spawn = Callable[[list[str], dict[str, str]], Awaitable[Process]]
OnPod = Callable[[str, PodStatusData], None]


async def spawn_subprocess(argv: list[str], env: dict[str, str]) -> Process:
    return await asyncio.create_subprocess_exec(*argv, env=env)  # type: ignore[return-value]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class LocalProcessLauncher:
    def __init__(
        self,
        settings: Settings,
        on_pod: OnPod | None = None,
        *,
        spawn: Spawn = spawn_subprocess,
        port_picker: Callable[[], int] = free_port,
        environ: dict[str, str] | None = None,
    ) -> None:
        self._settings = settings
        self._on_pod = on_pod or (lambda *_: None)
        self._spawn = spawn
        self._free_port = port_picker
        self._environ = dict(os.environ) if environ is None else environ
        self._procs: set[Process] = set()
        self._watchers: set[asyncio.Task[Any]] = set()

    # ------------------------------------------------------------------ env and argv
    def delegate_env(
        self, encounter_id: str, spec: EncounterSpec, side: str, traceparent: str | None, responder_port: int, port: int
    ) -> dict[str, str]:
        me, peer = (spec.initiator, spec.responder) if side == "initiator" else (spec.responder, spec.initiator)
        env = {k: v for k, v in self._environ.items() if k in PASS_THROUGH_NAMES or k.startswith(PASS_THROUGH_PREFIXES)}
        env.update(
            {
                "ENCOUNTER_ID": encounter_id,
                "ROLE": side,
                "SELF_ORG": me.orgId,
                "SELF_PERSONA": me.personaId,
                "PEER_ORG": peer.orgId,
                "PEER_PERSONA": peer.personaId,
                "MALICIOUS": "true" if me.malicious else "false",
                "PORT": str(port),
                "GATEWAY_URL": f"http://127.0.0.1:{self._settings.internal_port}",
                "POD_NAME": self.pod_name(encounter_id, side),
                "POD_NAMESPACE": names.org_namespace(me.orgId),
            }
        )
        if side == "initiator":
            env["PEER_URL"] = f"http://127.0.0.1:{responder_port}"
        if traceparent:
            env["TRACEPARENT"] = traceparent
        return env

    @staticmethod
    def pod_name(encounter_id: str, side: str) -> str:
        return f"delegate-{encounter_id}-{side}"

    # ------------------------------------------------------------------ launch
    async def launch(self, encounter_id: str, spec: EncounterSpec, traceparent: str | None) -> None:
        responder_port, initiator_port = self._free_port(), self._free_port()
        argv = [sys.executable, "-m", "rapport_delegate"]
        started: list[tuple[str, str, Process]] = []
        try:
            for side, port in (("responder", responder_port), ("initiator", initiator_port)):
                env = self.delegate_env(encounter_id, spec, side, traceparent, responder_port, port)
                org = (spec.responder if side == "responder" else spec.initiator).orgId
                self._report(encounter_id, org, side, "Pending")
                proc = await self._spawn(argv, env)
                started.append((side, org, proc))
        except Exception as exc:
            for _, _, proc in started:
                proc.terminate()
            log.error("starting delegates for %s failed: %s", encounter_id, type(exc).__name__)
            raise GatewayError(502, "could not start the local delegates") from exc
        for side, org, proc in started:
            self._procs.add(proc)
            self._report(encounter_id, org, side, "Running")
            task = asyncio.get_running_loop().create_task(self._watch(encounter_id, org, side, proc))
            self._watchers.add(task)
            task.add_done_callback(self._watchers.discard)

    async def _watch(self, encounter_id: str, org: str, side: str, proc: Process) -> None:
        code = await proc.wait()
        self._procs.discard(proc)
        self._report(encounter_id, org, side, "Succeeded" if code == 0 else "Failed")

    def _report(self, encounter_id: str, org: str, side: str, phase: str) -> None:
        self._on_pod(
            encounter_id,
            PodStatusData(org_id=org, side=side, pod=self.pod_name(encounter_id, side), phase=phase),  # type: ignore[arg-type]
        )

    async def close(self) -> None:
        for proc in tuple(self._procs):
            proc.terminate()
        for task in tuple(self._watchers):
            task.cancel()
