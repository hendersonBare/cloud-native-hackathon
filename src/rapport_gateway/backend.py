"""The seam between the HTTP routers and what answers them.

Routers only know this Protocol. LiveBackend (below) talks to the briefers and Kubernetes; MockBackend
(mock.py) replays contracts/*.json. Both raise GatewayError for client-visible failures.
"""

from __future__ import annotations

from typing import Protocol

from rapport_common.models import (
    AcceptBody,
    AskAnswer,
    AskRequest,
    ConnectBody,
    PersonaProfile,
    ResearchRequest,
    ResearchResult,
    SwipeBody,
    TalkSearchResult,
)

from .briefers import BrieferClient
from .bus import EventBus
from .connect import ConnectService
from .discover import DiscoverService
from .encounters import EncounterService
from .errors import require_agent_persona
from .ratelimit import SlidingWindowLimiter
from .tasks import BackgroundTasks

UploadFile = tuple[str, bytes, str]  # (filename, content, content type)


class Backend(Protocol):
    async def upload_context(
        self, persona_id: str, visibility: str, text: str | None, file: UploadFile | None
    ) -> PersonaProfile: ...

    async def profile(self, persona_id: str) -> PersonaProfile: ...

    async def connect(self, body: ConnectBody) -> str: ...

    async def accept(self, request_id: str, body: AcceptBody) -> str: ...

    async def ask(self, body: AskRequest) -> AskAnswer: ...

    async def talks(self, persona_id: str, q: str) -> TalkSearchResult: ...

    async def research(self, body: ResearchRequest) -> ResearchResult: ...

    async def swipe(self, body: SwipeBody) -> None: ...

    async def reset(self) -> None: ...


class LiveBackend:
    def __init__(
        self,
        *,
        bus: EventBus,
        briefers: BrieferClient,
        connect: ConnectService,
        discover: DiscoverService,
        encounters: EncounterService,
        tasks: BackgroundTasks,
        limiters: list[SlidingWindowLimiter],
    ) -> None:
        self._bus = bus
        self._briefers = briefers
        self._connect = connect
        self._discover = discover
        self._encounters = encounters
        self._tasks = tasks
        self._limiters = limiters

    async def upload_context(
        self, persona_id: str, visibility: str, text: str | None, file: UploadFile | None
    ) -> PersonaProfile:
        persona = require_agent_persona(persona_id)
        profile = await self._briefers.context(
            persona.org_id, persona_id=persona_id, visibility=visibility, text=text, file=file
        )
        self._bus.emit("profile_updated", profile, persona_id=persona_id)
        return profile

    async def profile(self, persona_id: str) -> PersonaProfile:
        persona = require_agent_persona(persona_id)
        return await self._briefers.profile(persona.org_id, persona_id)

    async def connect(self, body: ConnectBody) -> str:
        return self._connect.connect(body)

    async def accept(self, request_id: str, body: AcceptBody) -> str:
        return await self._connect.accept(request_id, body)

    async def ask(self, body: AskRequest) -> AskAnswer:
        persona = require_agent_persona(body.persona_id)
        return await self._briefers.ask(persona.org_id, body)

    async def talks(self, persona_id: str, q: str) -> TalkSearchResult:
        persona = require_agent_persona(persona_id)
        return await self._briefers.talks(persona.org_id, persona_id, q)

    async def research(self, body: ResearchRequest) -> ResearchResult:
        return await self._discover.research(body)

    async def swipe(self, body: SwipeBody) -> None:
        self._discover.swipe(body)

    async def reset(self) -> None:
        self._tasks.cancel_all()
        self._encounters.reset()
        self._connect.reset()
        self._bus.clear()
        for limiter in self._limiters:
            limiter.clear()
