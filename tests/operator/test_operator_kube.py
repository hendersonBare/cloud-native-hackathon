"""KubeClient's mapping of API errors, with the kubernetes client objects replaced by fakes."""

import pytest
from kubernetes.client.rest import ApiException

from rapport_operator.kube import KubeClient, NamespaceNotFound

JOB = {"kind": "Job", "metadata": {"name": "delegate-enc-1", "namespace": "org-acme"}}


class Recorder:
    """Stands in for one generated API method; raises the given error or records the call."""

    def __init__(self, error=None, result=None):
        self.error, self.result, self.calls = error, result, []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error:
            raise self.error
        return self.result


def client_with(**apis):
    c = KubeClient.__new__(KubeClient)  # skip __init__: it builds real API clients
    for name, api in apis.items():
        setattr(c, f"_{name}", api)
    return c


class Api:
    def __init__(self, **methods):
        for name, method in methods.items():
            setattr(self, name, method)


def test_ensure_true_when_created_and_false_on_409():
    created = Recorder()
    assert client_with(batch=Api(create_namespaced_job=created)).ensure(JOB) is True
    assert created.calls[0][0][0] == "org-acme"
    exists = Recorder(ApiException(status=409))
    assert client_with(batch=Api(create_namespaced_job=exists)).ensure(JOB) is False


def test_ensure_404_means_namespace_missing_and_other_errors_propagate():
    with pytest.raises(NamespaceNotFound):
        client_with(batch=Api(create_namespaced_job=Recorder(ApiException(status=404)))).ensure(JOB)
    with pytest.raises(ApiException):
        client_with(batch=Api(create_namespaced_job=Recorder(ApiException(status=403)))).ensure(JOB)


@pytest.mark.parametrize(
    "obj,api,method",
    [
        ({"kind": "Service", "metadata": {"name": "s", "namespace": "n"}}, "core", "create_namespaced_service"),
        (
            {"kind": "NetworkPolicy", "metadata": {"name": "p", "namespace": "n"}},
            "net",
            "create_namespaced_network_policy",
        ),
    ],
)
def test_ensure_routes_each_kind_to_its_api(obj, api, method):
    rec = Recorder()
    assert client_with(**{api: Api(**{method: rec})}).ensure(obj) is True
    assert rec.calls[0][0][0] == "n"


def test_get_encounter_returns_none_on_404():
    assert (
        client_with(custom=Api(get_cluster_custom_object=Recorder(ApiException(status=404)))).get_encounter("x") is None
    )
    got = client_with(custom=Api(get_cluster_custom_object=Recorder(result={"metadata": {}}))).get_encounter("x")
    assert got == {"metadata": {}}
    with pytest.raises(ApiException):
        client_with(custom=Api(get_cluster_custom_object=Recorder(ApiException(status=500)))).get_encounter("x")


def test_patch_status_and_delete_ignore_404_only():
    patch_404 = Recorder(ApiException(status=404))
    client_with(custom=Api(patch_cluster_custom_object_status=patch_404)).patch_encounter_status(
        "x", {"phase": "Failed"}
    )
    assert patch_404.calls[0][0][-1] == {"status": {"phase": "Failed"}}
    with pytest.raises(ApiException):
        client_with(
            custom=Api(patch_cluster_custom_object_status=Recorder(ApiException(status=500)))
        ).patch_encounter_status("x", {})
    client_with(custom=Api(delete_cluster_custom_object=Recorder(ApiException(status=404)))).delete_encounter("x")
    with pytest.raises(ApiException):
        client_with(custom=Api(delete_cluster_custom_object=Recorder(ApiException(status=403)))).delete_encounter("x")
