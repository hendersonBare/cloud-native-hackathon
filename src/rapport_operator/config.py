"""Operator settings resolved once at startup: which image delegates run and which env they inherit."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from rapport_common import names

from .builders import passthrough_from_environ

log = logging.getLogger("rapport.operator")

OPERATOR_CONTAINER = "operator"


@dataclass(frozen=True)
class OperatorConfig:
    image: str
    passthrough_env: Mapping[str, str] = field(default_factory=dict)


def pick_container_image(pod: Mapping[str, Any]) -> str | None:
    """The operator container's image from a Pod (dict in API shape); falls back to the first container."""
    containers = (pod.get("spec") or {}).get("containers") or []
    for container in containers:
        if container.get("name") == OPERATOR_CONTAINER and container.get("image"):
            return container["image"]
    return containers[0].get("image") if containers else None


def resolve_image(environ: Mapping[str, str], read_own_pod) -> str:
    """$RAPPORT_IMAGE if set, else the image of the operator's own pod (POD_NAME, POD_NAMESPACE).

    `read_own_pod(name, namespace)` returns the Pod as a dict; it is only called when the env var is unset.
    """
    if environ.get(names.IMAGE_ENV):
        return environ[names.IMAGE_ENV]
    pod_name, pod_namespace = environ.get("POD_NAME"), environ.get("POD_NAMESPACE")
    if not (pod_name and pod_namespace):
        raise RuntimeError(f"set {names.IMAGE_ENV}, or run in a pod with POD_NAME and POD_NAMESPACE")
    image = pick_container_image(read_own_pod(pod_name, pod_namespace))
    if not image:
        raise RuntimeError("the operator pod has no container image to reuse for delegates")
    return image


def load_config(environ: Mapping[str, str] | None = None, read_own_pod=None) -> OperatorConfig:
    environ = os.environ if environ is None else environ
    image = resolve_image(environ, read_own_pod or _unavailable)
    log.info("delegate image resolved")
    return OperatorConfig(image=image, passthrough_env=passthrough_from_environ(environ))


def _unavailable(name: str, namespace: str):
    raise RuntimeError("no Kubernetes client available to read the operator pod")
