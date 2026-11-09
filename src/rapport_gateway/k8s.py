"""Kubernetes side of the gateway: Encounter creation and the delegate pod watch.

Everything blocking (the kubernetes client is synchronous) runs in a worker thread so the event loop
is never held up. Tests inject fakes through the constructor arguments.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from rapport_common import names
from rapport_common.models import EncounterSpec, PodStatusData

from .errors import GatewayError, LauncherUnavailable

log = logging.getLogger("rapport.gateway.k8s")

DELEGATE_SELECTOR = f"{names.LABEL_ROLE}=delegate"
WATCHED_NAMESPACES = (names.org_namespace("acme"), names.org_namespace("bluefin"))


class EncounterLauncher(Protocol):
    """Creates the delegates for one encounter. KubernetesLauncher creates the Encounter resource;
    LocalProcessLauncher (launcher_local.py) starts delegate subprocesses on a laptop."""

    async def launch(self, encounter_id: str, spec: EncounterSpec, traceparent: str | None) -> None: ...


def encounter_manifest(encounter_id: str, spec: EncounterSpec, traceparent: str | None) -> dict[str, Any]:
    """The cluster-scoped Encounter (SPEC 4.4)."""
    annotations = {names.TRACEPARENT_ANNOTATION: traceparent} if traceparent else {}
    return {
        "apiVersion": f"{names.CRD_GROUP}/{names.CRD_VERSION}",
        "kind": names.CRD_KIND,
        "metadata": {
            "name": encounter_id,
            "labels": {names.LABEL_PART_OF: "rapport"},
            "annotations": annotations,
        },
        "spec": spec.model_dump(mode="json"),
    }


def load_kube_config() -> None:
    """In-cluster config first, then the local kubeconfig. Raises LauncherUnavailable if neither loads."""
    from kubernetes import config

    try:
        config.load_incluster_config()
        return
    except config.ConfigException:
        pass
    try:
        config.load_kube_config()
    except Exception as exc:  # ConfigException, FileNotFoundError, YAML errors...
        raise LauncherUnavailable() from exc


class KubernetesLauncher:
    def __init__(self, api_factory: Callable[[], Any] | None = None) -> None:
        self._api_factory = api_factory or self._default_api
        self._api: Any | None = None
        self._lock = threading.Lock()

    @staticmethod
    def _default_api() -> Any:
        from kubernetes import client

        load_kube_config()
        return client.CustomObjectsApi()

    def _get_api(self) -> Any:
        with self._lock:
            if self._api is None:
                self._api = self._api_factory()
            return self._api

    async def launch(self, encounter_id: str, spec: EncounterSpec, traceparent: str | None) -> None:
        body = encounter_manifest(encounter_id, spec, traceparent)

        def create() -> None:
            api = self._get_api()
            api.create_cluster_custom_object(names.CRD_GROUP, names.CRD_VERSION, names.CRD_PLURAL, body)

        try:
            await asyncio.to_thread(create)
        except GatewayError:
            raise
        except Exception as exc:
            status = getattr(exc, "status", None)
            log.error("creating Encounter %s failed (%s, status %s)", encounter_id, type(exc).__name__, status)
            raise GatewayError(502, "the cluster refused to create the encounter") from exc


# --------------------------------------------------------------------------- pod watch
@dataclass(frozen=True)
class PodInfo:
    name: str
    namespace: str
    encounter_id: str
    org_id: str
    side: str
    phase: str
    ip: str | None


def pod_info(pod: Any) -> PodInfo | None:
    """Read the fields we need from a V1Pod (or any object with the same attributes)."""
    meta = getattr(pod, "metadata", None)
    labels = getattr(meta, "labels", None) or {}
    encounter, org, side = labels.get(names.LABEL_ENCOUNTER), labels.get(names.LABEL_ORG), labels.get(names.LABEL_SIDE)
    if not (meta and encounter and org and side in ("initiator", "responder")):
        return None
    status = getattr(pod, "status", None)
    return PodInfo(
        name=meta.name,
        namespace=getattr(meta, "namespace", "") or "",
        encounter_id=encounter,
        org_id=org,
        side=side,
        phase=getattr(status, "phase", None) or "Pending",
        ip=getattr(status, "pod_ip", None),
    )


class PodRegistry:
    """Live delegate pods by name, so /internal/events can check the caller is a pod of that encounter."""

    def __init__(self) -> None:
        self._pods: dict[tuple[str, str], PodInfo] = {}
        self._lock = threading.Lock()

    def update(self, info: PodInfo) -> None:
        with self._lock:
            self._pods[(info.namespace, info.name)] = info

    def remove(self, info: PodInfo) -> None:
        with self._lock:
            self._pods.pop((info.namespace, info.name), None)

    def matches(self, ip: str | None, encounter_id: str, org_id: str, side: str | None = None) -> bool:
        if not ip:
            return False
        with self._lock:
            return any(
                p.ip == ip and p.encounter_id == encounter_id and p.org_id == org_id and (side in (None, p.side))
                for p in self._pods.values()
            )


PodEventCallback = Callable[[str, PodStatusData], None]
PodStream = Callable[[str], Iterable[dict[str, Any]]]


def default_pod_stream(namespace: str) -> Iterable[dict[str, Any]]:
    """Blocking kubernetes.watch over delegate pods in one namespace (ends after ~5 minutes; the caller loops)."""
    from kubernetes import client, watch

    api = client.CoreV1Api()
    return watch.Watch().stream(
        api.list_namespaced_pod, namespace, label_selector=DELEGATE_SELECTOR, timeout_seconds=300
    )


class PodWatcher:
    """One daemon thread per namespace. Pod changes are handed to the asyncio loop with call_soon_threadsafe."""

    def __init__(
        self,
        registry: PodRegistry,
        on_pod: PodEventCallback,
        *,
        namespaces: tuple[str, ...] = WATCHED_NAMESPACES,
        stream: PodStream = default_pod_stream,
        load_config: Callable[[], None] | None = load_kube_config,
        retry_s: float = 10.0,
    ) -> None:
        self._registry = registry
        self._on_pod = on_pod
        self._namespaces = namespaces
        self._stream = stream
        self._load_config = load_config
        self._retry_s = retry_s
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._last_phase: dict[tuple[str, str], str] = {}

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        for namespace in self._namespaces:
            thread = threading.Thread(target=self._run, args=(namespace,), name=f"pod-watch-{namespace}", daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        self._stop.set()

    def _run(self, namespace: str) -> None:
        load_config = self._load_config
        configured = load_config is None
        while not self._stop.is_set():
            try:
                if not configured and load_config is not None:
                    load_config()
                    configured = True
                for event in self._stream(namespace):
                    if self._stop.is_set():
                        return
                    self.handle(event)
            except Exception as exc:  # keep the thread alive: the cluster may be unreachable for a while
                log.warning("pod watch %s: %s; retrying in %ss", namespace, type(exc).__name__, self._retry_s)
                self._stop.wait(self._retry_s)

    def handle(self, event: dict[str, Any]) -> None:
        info = pod_info(event.get("object"))
        if info is None:
            return
        if event.get("type") == "DELETED":
            self._registry.remove(info)
            self._last_phase.pop((info.namespace, info.name), None)
            return
        self._registry.update(info)
        key = (info.namespace, info.name)
        if self._last_phase.get(key) == info.phase:
            return
        self._last_phase[key] = info.phase
        data = PodStatusData(org_id=info.org_id, side=info.side, pod=info.name, phase=info.phase)  # type: ignore[arg-type]
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._on_pod, info.encounter_id, data)
