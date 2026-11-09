"""Delegate configuration: environment variables only (SPEC 4.4)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from rapport_common import names

Role = Literal["initiator", "responder"]

EXCHANGE_TIMEOUT_S = 90.0  # whole exchange (activeDeadlineSeconds is 120)
CALL_TIMEOUT_S = 20.0  # one HTTP call to the peer
PEER_WAIT_S = 30.0  # how long the initiator waits for the peer's /healthz
PEER_POLL_S = 0.5


class ConfigError(ValueError):
    """The pod environment is wrong. Fail fast, with the variable name (never a value)."""


@dataclass(frozen=True)
class DelegateConfig:
    role: Role
    encounter_id: str
    self_org: str
    self_persona: str
    peer_org: str
    peer_persona: str
    peer_url: str | None
    malicious: bool
    traceparent: str | None
    port: int = names.HTTP_PORT

    @property
    def initiator_org(self) -> str:
        return self.self_org if self.role == "initiator" else self.peer_org

    @property
    def responder_org(self) -> str:
        return self.peer_org if self.role == "initiator" else self.self_org

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> DelegateConfig:
        env = os.environ if env is None else env

        def need(var: str) -> str:
            value = env.get(var, "").strip()
            if not value:
                raise ConfigError(f"missing environment variable {var}")
            return value

        role = need("ROLE")
        if role not in ("initiator", "responder"):
            raise ConfigError("ROLE must be 'initiator' or 'responder'")
        cfg = cls(
            role=role,
            encounter_id=need("ENCOUNTER_ID"),
            self_org=need("SELF_ORG"),
            self_persona=need("SELF_PERSONA"),
            peer_org=need("PEER_ORG"),
            peer_persona=need("PEER_PERSONA"),
            peer_url=need("PEER_URL").rstrip("/") if role == "initiator" else None,
            malicious=env.get("MALICIOUS", "false").strip().lower() == "true",
            traceparent=env.get("TRACEPARENT") or None,
            port=_port(env.get("PORT")),
        )
        cfg.validate_directory()
        return cfg

    def validate_directory(self) -> None:
        """Both people must exist in the directory and belong to the org the env says."""
        for org, persona_id in ((self.self_org, self.self_persona), (self.peer_org, self.peer_persona)):
            try:
                actual = names.org_of(persona_id)
            except KeyError as exc:
                raise ConfigError("persona is not in the directory") from exc
            if actual != org:
                raise ConfigError("persona does not belong to the org given")


def _port(raw: str | None) -> int:
    if not raw:
        return names.HTTP_PORT
    try:
        port = int(raw)
    except ValueError as exc:
        raise ConfigError("PORT must be an integer") from exc
    if not 0 < port < 65536:
        raise ConfigError("PORT out of range")
    return port
