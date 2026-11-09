"""Gateway configuration: environment variables only (AGENTS.md section 3)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from rapport_common import names

log = logging.getLogger("rapport.gateway.settings")

REPO_ROOT = Path(__file__).resolve().parents[2]  # /app in the image, the repo root in a checkout
CONTRACTS_DIR = REPO_ROOT / "contracts"
WEB_DIR = REPO_ROOT / "web"

_TRUE = {"1", "true", "yes", "on"}


def _flag(var: str, default: bool = False) -> bool:
    raw = os.environ.get(var)
    return default if raw is None else raw.strip().lower() in _TRUE


def _float(var: str, default: float) -> float:
    try:
        return float(os.environ.get(var, default))
    except ValueError:
        log.warning("%s is not a number; using %s", var, default)
        return default


def parse_origins(raw: str | None) -> tuple[str, ...]:
    """Comma-separated origins. A wildcard is dropped: credentials and '*' must never be combined."""
    origins: list[str] = []
    for item in (raw or "").split(","):
        origin = item.strip().rstrip("/")
        if not origin:
            continue
        if origin == "*":
            log.warning("RAPPORT_CORS_ORIGINS: ignoring '*' (credentials are allowed, so origins must be explicit)")
            continue
        origins.append(origin)
    return tuple(origins)


@dataclass(frozen=True)
class Settings:
    mock: bool = False
    version: str = "dev"
    port: int = names.HTTP_PORT
    internal_port: int = names.GATEWAY_INTERNAL_PORT
    cors_origins: tuple[str, ...] = ()
    admin_token: str | None = None
    launcher: Literal["kubernetes", "local"] = "kubernetes"
    web_dir: Path | None = WEB_DIR
    contracts_dir: Path = CONTRACTS_DIR
    # abuse limits
    llm_calls_per_minute: int = 30
    # timeouts (seconds)
    brief_timeout_s: float = 15.0
    deep_dive_timeout_s: float = 20.0
    proxy_timeout_s: float = 30.0
    remember_timeout_s: float = 10.0
    encounter_timeout_s: float = 150.0
    # uploads (SPEC 4.3)
    max_upload_bytes: int = 2 * 1024 * 1024
    # event bus / SSE
    keepalive_s: float = 15.0
    # Close each SSE stream from the server after this long (0 = never) so clients reconnect (with Last-Event-ID)
    # before the platform's edge proxy cuts the stream at its ~15 s route timeout.
    sse_max_seconds: float = 12.0
    subscriber_queue_size: int = 256
    replay_buffer_size: int = 200
    # delegate source check (c): the reporting client IP must be a delegate pod of the encounter
    check_delegate_ip: bool = True
    # mock mode: 1.0 replays the fixtures in real time, 100 plays them 100x faster (tests)
    mock_speed: float = 1.0
    extra: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> Settings:
        launcher = os.environ.get("RAPPORT_LAUNCHER", "kubernetes").strip().lower()
        if launcher not in ("kubernetes", "local"):
            log.warning("RAPPORT_LAUNCHER=%s is unknown; using kubernetes", launcher)
            launcher = "kubernetes"
        return cls(
            mock=_flag("RAPPORT_MOCK"),
            version=os.environ.get("RAPPORT_VERSION", "dev"),
            port=int(os.environ.get("PORT", names.HTTP_PORT)),
            internal_port=int(os.environ.get("INTERNAL_PORT", names.GATEWAY_INTERNAL_PORT)),
            cors_origins=parse_origins(os.environ.get("RAPPORT_CORS_ORIGINS")),
            admin_token=os.environ.get("RAPPORT_ADMIN_TOKEN") or None,
            launcher=launcher,  # type: ignore[arg-type]
            llm_calls_per_minute=int(_float("RAPPORT_LLM_CALLS_PER_MINUTE", 30)),
            check_delegate_ip=_flag("RAPPORT_CHECK_DELEGATE_IP", True),
            sse_max_seconds=max(_float("RAPPORT_SSE_MAX_SECONDS", 12.0), 0.0),
            mock_speed=max(_float("RAPPORT_MOCK_SPEED", 1.0), 0.01),
        )
