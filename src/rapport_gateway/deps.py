"""Dependency container: everything the app needs, injectable so tests and local runs can swap in fakes."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

import httpx

from rapport_common import names
from rapport_common.models import PodStatusData

from .backend import Backend, LiveBackend
from .briefers import BrieferClient
from .bus import EventBus
from .connect import ConnectService, RequestBook
from .discover import HANDSHAKE_WINDOW_S, DiscoverService
from .encounters import EncounterService
from .k8s import EncounterLauncher, KubernetesLauncher, PodRegistry, PodWatcher
from .mock import Fixtures, MockBackend
from .ratelimit import SlidingWindowLimiter
from .settings import Settings
from .tasks import BackgroundTasks

log = logging.getLogger("rapport.gateway.deps")


@dataclass
class Deps:
    settings: Settings
    bus: EventBus
    backend: Backend
    encounters: EncounterService
    tasks: BackgroundTasks
    llm_limiter: SlidingWindowLimiter
    http: httpx.AsyncClient | None = None
    pod_watcher: PodWatcher | None = None
    launcher: EncounterLauncher | None = None
    owns_http: bool = False
    extras: dict[str, object] = field(default_factory=dict)

    async def start(self) -> None:
        if self.pod_watcher is not None:
            self.pod_watcher.start(asyncio.get_running_loop())

    async def stop(self) -> None:
        if self.pod_watcher is not None:
            self.pod_watcher.stop()
        self.tasks.cancel_all()
        close = getattr(self.launcher, "close", None)
        if close is not None:
            await close()
        if self.owns_http and self.http is not None:
            await self.http.aclose()


def build_deps(
    settings: Settings,
    *,
    http: httpx.AsyncClient | None = None,
    launcher: EncounterLauncher | None = None,
    pod_watcher: PodWatcher | None = None,
    registry: PodRegistry | None = None,
    bus: EventBus | None = None,
) -> Deps:
    """Wire the gateway. Pass fakes (http transport, launcher, pod watcher) in tests; leave them out in main()."""
    owns_http = http is None
    http = http or httpx.AsyncClient(timeout=settings.proxy_timeout_s)
    bus = bus or EventBus(queue_size=settings.subscriber_queue_size, buffer_size=settings.replay_buffer_size)
    tasks = BackgroundTasks()
    briefers = BrieferClient(http, timeout_s=settings.proxy_timeout_s)
    llm_limiter = SlidingWindowLimiter(settings.llm_calls_per_minute, 60.0)
    handshakes = SlidingWindowLimiter(names.MAX_AGENT_HANDSHAKES_PER_HOUR, HANDSHAKE_WINDOW_S)
    book = RequestBook(bus)

    def on_pod(encounter_id: str, data: PodStatusData) -> None:
        bus.emit("pod_status", data, encounter_id=encounter_id)

    if launcher is None and settings.launcher == "local" and not settings.mock:
        from .launcher_local import LocalProcessLauncher

        launcher = LocalProcessLauncher(settings, on_pod)
    local = settings.launcher == "local" and not settings.mock
    # pod IPs are only meaningful with the Kubernetes launcher (check (c)); the local launcher uses (a)+(b)
    if registry is None and not settings.mock and not local:
        registry = PodRegistry()
    encounters = EncounterService(
        bus=bus,
        briefers=briefers,
        tasks=tasks,
        registry=registry,
        check_ip=settings.check_delegate_ip and not settings.mock and not local,
        timeout_s=settings.encounter_timeout_s,
        remember_timeout_s=settings.remember_timeout_s,
    )

    if settings.mock:
        backend: Backend = MockBackend(
            fixtures=Fixtures.load(settings.contracts_dir),
            bus=bus,
            book=book,
            tasks=tasks,
            handshakes=handshakes,
            speed=settings.mock_speed,
        )
    else:
        launcher = launcher or KubernetesLauncher()
        connect = ConnectService(
            settings_brief_timeout_s=settings.brief_timeout_s,
            bus=bus,
            book=book,
            briefers=briefers,
            launcher=launcher,
            encounters=encounters,
            tasks=tasks,
        )
        discover = DiscoverService(
            bus=bus,
            briefers=briefers,
            connect=connect,
            tasks=tasks,
            handshakes=handshakes,
            deep_dive_timeout_s=settings.deep_dive_timeout_s,
            remember_timeout_s=settings.remember_timeout_s,
        )
        backend = LiveBackend(
            bus=bus,
            briefers=briefers,
            connect=connect,
            discover=discover,
            encounters=encounters,
            tasks=tasks,
            limiters=[llm_limiter, handshakes],
        )
        if pod_watcher is None and registry is not None:
            pod_watcher = PodWatcher(registry, on_pod)

    return Deps(
        settings=settings,
        bus=bus,
        backend=backend,
        encounters=encounters,
        tasks=tasks,
        llm_limiter=llm_limiter,
        http=http,
        pod_watcher=pod_watcher,
        launcher=None if settings.mock else launcher,
        owns_http=owns_http,
    )
