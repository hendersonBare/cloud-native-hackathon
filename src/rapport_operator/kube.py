"""The only module that talks to the Kubernetes API. Everything else uses the KubeOps protocol,
so tests and local runs can pass a fake."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any, Protocol

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from rapport_common import names

log = logging.getLogger("rapport.operator")


class NamespaceNotFound(Exception):
    """The target namespace does not exist (yet); creating an object there returned 404."""


class KubeOps(Protocol):
    def ensure(self, obj: Mapping[str, Any]) -> bool:
        """Create the object; return True if created, False if it already existed (409 is success)."""

    def list_delegate_jobs(self, enc_name: str) -> list[dict[str, Any]]:
        """Delegate Jobs of one Encounter across all namespaces."""

    def get_encounter(self, enc_name: str) -> dict[str, Any] | None: ...

    def patch_encounter_status(self, enc_name: str, status: Mapping[str, Any]) -> None: ...

    def delete_encounter(self, enc_name: str) -> None: ...

    def read_pod(self, name: str, namespace: str) -> dict[str, Any]: ...


def load_kube_config() -> None:
    """In-cluster when running as a pod; otherwise the kubeconfig (KUBE_CONTEXT selects the context)."""
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config(context=os.environ.get("KUBE_CONTEXT") or None)


class KubeClient:
    """KubeOps backed by the official Python client (blocking calls: kopf runs sync handlers in threads)."""

    def __init__(self) -> None:
        self._api = client.ApiClient()
        self._core = client.CoreV1Api(self._api)
        self._batch = client.BatchV1Api(self._api)
        self._net = client.NetworkingV1Api(self._api)
        self._custom = client.CustomObjectsApi(self._api)

    def _dict(self, obj: Any) -> dict[str, Any]:
        return self._api.sanitize_for_serialization(obj)

    def ensure(self, obj: Mapping[str, Any]) -> bool:
        kind, namespace = obj["kind"], obj["metadata"]["namespace"]
        api, method = {
            "Job": ("_batch", "create_namespaced_job"),
            "Service": ("_core", "create_namespaced_service"),
            "NetworkPolicy": ("_net", "create_namespaced_network_policy"),
        }[kind]
        create = getattr(getattr(self, api), method)
        try:
            create(namespace, dict(obj))
        except ApiException as exc:
            if exc.status == 409:
                return False
            if exc.status == 404:
                raise NamespaceNotFound(namespace) from exc
            raise
        return True

    def list_delegate_jobs(self, enc_name: str) -> list[dict[str, Any]]:
        selector = f"{names.LABEL_ROLE}=delegate,{names.LABEL_ENCOUNTER}={enc_name}"
        return [self._dict(j) for j in self._batch.list_job_for_all_namespaces(label_selector=selector).items]

    def get_encounter(self, enc_name: str) -> dict[str, Any] | None:
        try:
            return self._custom.get_cluster_custom_object(
                names.CRD_GROUP, names.CRD_VERSION, names.CRD_PLURAL, enc_name
            )
        except ApiException as exc:
            if exc.status == 404:
                return None
            raise

    def patch_encounter_status(self, enc_name: str, status: Mapping[str, Any]) -> None:
        try:
            self._custom.patch_cluster_custom_object_status(
                names.CRD_GROUP, names.CRD_VERSION, names.CRD_PLURAL, enc_name, {"status": dict(status)}
            )
        except ApiException as exc:
            if exc.status != 404:  # the Encounter was deleted meanwhile: nothing to update
                raise

    def delete_encounter(self, enc_name: str) -> None:
        try:
            self._custom.delete_cluster_custom_object(names.CRD_GROUP, names.CRD_VERSION, names.CRD_PLURAL, enc_name)
        except ApiException as exc:
            if exc.status != 404:
                raise

    def read_pod(self, name: str, namespace: str) -> dict[str, Any]:
        return self._dict(self._core.read_namespaced_pod(name, namespace))
