"""Shared test helpers for the operator tests: an in-memory fake of the Kubernetes API and an Encounter factory.

Not a test module (no `test_` prefix); sibling tests import it by name because pytest puts this folder
on sys.path (there is deliberately no tests/__init__.py).
"""

from datetime import UTC, datetime

from rapport_operator.config import OperatorConfig
from rapport_operator.kube import NamespaceNotFound

NOW = datetime(2026, 11, 9, 20, 30, tzinfo=UTC)
CFG = OperatorConfig(image="ghcr.io/example/rapport:abc", passthrough_env={"RAPPORT_LLM_MODEL": "m"})


class FakeOps:
    def __init__(self, enc=None, missing_namespaces=()):
        self.objects = {}
        self.encounters = {enc["metadata"]["name"]: enc} if enc else {}
        self.missing = set(missing_namespaces)
        self.patches = []
        self.deleted = []
        self.jobs = []
        self.create_order = []

    def ensure(self, obj):
        ns = obj["metadata"]["namespace"]
        if ns in self.missing:
            raise NamespaceNotFound(ns)
        key = (obj["kind"], ns, obj["metadata"]["name"])
        if key in self.objects:
            return False
        self.objects[key] = obj
        self.create_order.append(key)
        return True

    def list_delegate_jobs(self, enc_name):
        return self.jobs

    def get_encounter(self, enc_name):
        return self.encounters.get(enc_name)

    def patch_encounter_status(self, enc_name, status):
        self.patches.append((enc_name, status))

    def delete_encounter(self, enc_name):
        self.deleted.append(enc_name)

    def read_pod(self, name, namespace):
        raise AssertionError("not expected in these tests")


def make_enc(created=NOW, status=None):
    body = {
        "metadata": {
            "name": "enc-1",
            "uid": "uid-1",
            "creationTimestamp": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "annotations": {"rapport.dev/traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"},
        },
        "spec": {
            "initiator": {"orgId": "acme", "personaId": "acme.ava"},
            "responder": {"orgId": "bluefin", "personaId": "bluefin.bo", "malicious": True},
            "ttlSeconds": 600,
        },
    }
    if status:
        body["status"] = status
    return body


def labelled_job(side, **status):
    return {"metadata": {"labels": {"rapport.dev/side": side}}, "status": status}
