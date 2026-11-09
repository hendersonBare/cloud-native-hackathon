"""Entrypoint: kopf must get an explicit identity so startup never depends on a /etc/passwd entry."""

import getpass
import socket

import kopf
import pytest

from rapport_common import telemetry
from rapport_operator import __main__ as entry


@pytest.fixture
def captured(monkeypatch):
    calls = []
    monkeypatch.setattr(kopf, "run", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(telemetry, "init_telemetry", lambda *a, **k: None)

    def no_passwd_entry():
        raise KeyError("getpwuid(): uid not found: 10001")

    monkeypatch.setattr(getpass, "getuser", no_passwd_entry)
    return calls


def test_identity_is_pod_name(monkeypatch, captured):
    monkeypatch.setenv("POD_NAME", "operator-abc123")
    entry.main()
    assert captured[0]["identity"] == "operator-abc123"


def test_identity_falls_back_to_hostname(monkeypatch, captured):
    monkeypatch.delenv("POD_NAME", raising=False)
    monkeypatch.setattr(socket, "gethostname", lambda: "operator-host")
    entry.main()
    assert captured[0]["identity"] == "operator-host"


def test_identity_falls_back_to_fixed_string(monkeypatch, captured):
    monkeypatch.delenv("POD_NAME", raising=False)
    monkeypatch.setattr(socket, "gethostname", lambda: "")
    entry.main()
    assert captured[0]["identity"] == "rapport-operator"
