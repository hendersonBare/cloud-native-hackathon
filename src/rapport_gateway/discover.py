"""Discover (docs/FEATURE-DISCOVER.md): research proxy and the swipe -> deep dive -> agent decision logic.

Branches of a right swipe, after deep_dive_started and the briefer's DeepDive:
  agent_handshake + autonomy on + hourly limit free + request created  -> agent_decision agent_handshake (+ request_id)
  agent_handshake + autonomy off                                       -> agent_decision human_intro
  agent_handshake + MAX_AGENT_HANDSHAKES_PER_HOUR used                 -> agent_decision human_intro
  human_intro / skip (the briefer's guardrails)                        -> agent_decision as recommended
  deep dive unavailable                                                -> error event + agent_decision human_intro
The swarm only ever sees agent_decision (who and what), never the reason or research content.
"""

from __future__ import annotations

import logging

from rapport_common import names
from rapport_common.models import (
    AgentDecisionData,
    ConnectBody,
    DeepDive,
    DeepDiveRequest,
    DeepDiveStartedData,
    ResearchRequest,
    ResearchResult,
    SwipeBody,
)

from .briefers import BrieferClient
from .bus import EventBus
from .connect import ConnectService
from .errors import GatewayError, require_agent_persona, require_persona
from .ratelimit import SlidingWindowLimiter
from .remember import skip_record
from .tasks import BackgroundTasks

log = logging.getLogger("rapport.gateway.discover")
HANDSHAKE_WINDOW_S = 3600.0


class DiscoverService:
    def __init__(
        self,
        *,
        bus: EventBus,
        briefers: BrieferClient,
        connect: ConnectService,
        tasks: BackgroundTasks,
        handshakes: SlidingWindowLimiter | None = None,
        deep_dive_timeout_s: float = 20.0,
        remember_timeout_s: float = 10.0,
    ) -> None:
        self._bus = bus
        self._briefers = briefers
        self._connect = connect
        self._tasks = tasks
        self.handshakes = handshakes or SlidingWindowLimiter(names.MAX_AGENT_HANDSHAKES_PER_HOUR, HANDSHAKE_WINDOW_S)
        self._deep_dive_timeout_s = deep_dive_timeout_s
        self._remember_timeout_s = remember_timeout_s

    async def research(self, body: ResearchRequest) -> ResearchResult:
        viewer = require_agent_persona(body.persona_id)
        return await self._briefers.research(viewer.org_id, body)

    def swipe(self, body: SwipeBody) -> None:
        """Validate, then do the work in the background so the HTTP call can answer 202 at once."""
        viewer = require_agent_persona(body.persona_id)
        require_persona(body.target_persona_id)
        if body.target_persona_id == body.persona_id:
            raise GatewayError(422, "you cannot swipe on yourself")
        if body.direction == "left":
            self._tasks.spawn(self._remember_skip(body, viewer.org_id), name=f"skip-{body.persona_id}")
        else:
            self._tasks.spawn(self._deep_dive(body, viewer.org_id), name=f"deep-dive-{body.persona_id}")

    # ------------------------------------------------------------------ left
    async def _remember_skip(self, body: SwipeBody, org_id: str) -> None:
        record = skip_record(viewer_persona_id=body.persona_id, target_persona_id=body.target_persona_id)
        try:
            await self._briefers.remember(org_id, [record], timeout_s=self._remember_timeout_s)
        except GatewayError as exc:
            log.warning("could not remember a skip for %s: %s", body.persona_id, exc.detail)

    # ------------------------------------------------------------------ right
    async def _deep_dive(self, body: SwipeBody, org_id: str) -> None:
        viewer = body.persona_id
        self._bus.emit(
            "deep_dive_started", DeepDiveStartedData(target_persona_id=body.target_persona_id), persona_id=viewer
        )
        try:
            dive = await self._briefers.deep_dive(
                org_id,
                DeepDiveRequest(persona_id=viewer, target_persona_id=body.target_persona_id),
                timeout_s=self._deep_dive_timeout_s,
            )
        except GatewayError as exc:
            log.warning("deep dive %s -> %s failed: %s", viewer, body.target_persona_id, exc.detail)
            self._bus.emit("error", {"message": "The deep dive is unavailable right now."}, persona_id=viewer)
            self._bus.emit(
                "agent_decision",
                AgentDecisionData(target_persona_id=body.target_persona_id, action="human_intro"),
                persona_id=viewer,
            )
            return
        action, request_id, extra_checks = self._decide(body, dive)
        decision = dive.decision.model_copy(
            update={"action": action, "checks": [*dive.decision.checks[: 6 - len(extra_checks)], *extra_checks]}
        )
        self._bus.emit("deep_dive_ready", dive.model_copy(update={"decision": decision}), persona_id=viewer)
        self._bus.emit(
            "agent_decision",
            AgentDecisionData(target_persona_id=body.target_persona_id, action=action, request_id=request_id),
            persona_id=viewer,
        )
        if request_id is not None:
            self._connect.announce(request_id)

    def _decide(self, body: SwipeBody, dive: DeepDive) -> tuple[str, str | None, list[str]]:
        """Return (effective action, connect request id or None, extra guardrail lines for the deep dive)."""
        recommended = dive.decision.action
        if recommended != "agent_handshake":
            return recommended, None, []
        used = self.handshakes.used(body.persona_id)
        limit = self.handshakes.limit
        if not body.autonomy:
            return "human_intro", None, ["agent may act on its own: no"]
        if used >= limit:
            return "human_intro", None, [f"handshakes this hour {used}/{limit}: limit reached"]
        try:
            request_id = self._connect.connect(
                ConnectBody(
                    from_persona_id=body.persona_id,
                    to_persona_id=body.target_persona_id,
                    malicious=body.malicious,
                    initiated_by="agent",
                ),
                announce=False,  # the connect_request goes out after agent_decision, like the demo script
            )
        except GatewayError as exc:  # e.g. the target's company runs no agents: the person takes over
            log.info("agent handshake %s -> %s not sent: %s", body.persona_id, body.target_persona_id, exc.detail)
            return "human_intro", None, [f"connect request refused: {exc.status_code}"]
        self.handshakes.record(body.persona_id)
        checks = ["agent may act on its own: yes", f"handshakes this hour {used + 1}/{limit}: yes"]
        return "agent_handshake", request_id, checks
