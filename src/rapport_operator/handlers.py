"""kopf handlers: thin wrappers that hand the real work to controller.py.

Handlers are plain `def`s on purpose: kopf runs them in worker threads, which is where the blocking
Kubernetes client belongs.
"""

from __future__ import annotations

import logging
from typing import Any

import kopf

from rapport_common import names

from . import controller
from .builders import InvalidEncounter
from .config import OperatorConfig, load_config
from .kube import KubeClient, KubeOps, NamespaceNotFound, load_kube_config
from .status import PHASE_FAILED, iso, utc_now

log = logging.getLogger("rapport.operator")

CREATE_RETRIES = 6
CREATE_BACKOFF_SECONDS = 5
TTL_CHECK_INTERVAL_SECONDS = 15.0

_state: dict[str, Any] = {"ops": None, "cfg": None}


def configure(ops: KubeOps, cfg: OperatorConfig) -> None:
    """Set the Kubernetes access and config the handlers use (startup, and tests)."""
    _state["ops"], _state["cfg"] = ops, cfg


def _ops() -> KubeOps:
    return _state["ops"]


def _cfg() -> OperatorConfig:
    return _state["cfg"]


@kopf.on.startup()
def startup(settings: kopf.OperatorSettings, **_: Any) -> None:
    settings.posting.level = logging.INFO
    load_kube_config()
    ops = KubeClient()
    configure(ops, load_config(read_own_pod=ops.read_pod))


def _fail(enc_name: str, message: str) -> None:
    _ops().patch_encounter_status(enc_name, {"phase": PHASE_FAILED, "message": message, "completedAt": iso(utc_now())})


@kopf.on.create(
    names.CRD_GROUP, names.CRD_VERSION, names.CRD_PLURAL, retries=CREATE_RETRIES, backoff=CREATE_BACKOFF_SECONDS
)
def encounter_created(body: kopf.Body, name: str, patch: kopf.Patch, retry: int, **_: Any) -> None:
    try:
        patch.status.update(controller.on_encounter_created(body, _ops(), _cfg(), utc_now()))
    except InvalidEncounter as exc:
        _fail(name, str(exc))
        raise kopf.PermanentError(str(exc)) from exc
    except NamespaceNotFound as exc:
        if retry >= CREATE_RETRIES - 1:
            _fail(name, f"namespace {exc} does not exist")
            raise kopf.PermanentError(f"namespace {exc} does not exist") from exc
        raise kopf.TemporaryError(f"namespace {exc} does not exist yet", delay=CREATE_BACKOFF_SECONDS) from exc


@kopf.on.event("batch", "v1", "jobs", labels={names.LABEL_ROLE: "delegate"})
def delegate_job_changed(body: kopf.Body, event: kopf.RawEvent, **_: Any) -> None:
    if event.get("type") == "DELETED":
        return
    enc_name = (body.get("metadata", {}).get("labels") or {}).get(names.LABEL_ENCOUNTER)
    if enc_name:
        controller.sync_status(enc_name, _ops(), utc_now())


@kopf.timer(names.CRD_GROUP, names.CRD_VERSION, names.CRD_PLURAL, interval=TTL_CHECK_INTERVAL_SECONDS)
def encounter_ttl(body: kopf.Body, **_: Any) -> None:
    controller.delete_if_expired(body, _ops(), utc_now())
