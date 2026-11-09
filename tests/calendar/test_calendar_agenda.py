"""The agenda: briefer success, every failure falling back to the seed, filtering, and span hygiene."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
import respx
from calendar_support import NOW, local
from fastapi import HTTPException
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from rapport_calendar import service as service_module
from rapport_calendar.agenda import BRIEFER_TIMEOUT_SECONDS, BrieferTalkSource, SeedTalkSource, matches
from rapport_calendar.models import AddTalkBody, ProposeBody, RespondBody
from rapport_calendar.service import CalendarService
from rapport_common.models import TalkHit
from rapport_common.names import briefer_url
from rapport_common.telemetry import ATTR_PERSONA, ATTR_RESULT_COUNT

ACME_TALKS = f"{briefer_url('acme')}/v1/talks"


@pytest.fixture
def live(seed) -> CalendarService:
    """A service whose talk source calls the briefer (mocked with respx in each test)."""
    return CalendarService(seed=seed, talk_source=BrieferTalkSource(SeedTalkSource(seed.agenda)), now=lambda: NOW)


def briefer_hit(talk_id="talk-from-briefer", title="Agent-picked: tracing", hour=11) -> dict:
    hit = TalkHit(
        talk_id=talk_id, title=title, starts_at=local(1, hour), room="Room D", track="Observability", speakers=["Pia"],
        reason="Matches your interests",
    )
    return hit.model_dump(mode="json")


# ----------------------------------------------------------------------------- briefer success
async def test_agent_orgs_get_briefer_talks(live):
    with respx.mock(assert_all_called=True) as router:
        route = router.get(ACME_TALKS).mock(
            return_value=httpx.Response(
                200,
                json={"query": "tracing", "talks": [briefer_hit("talk-b", hour=15), briefer_hit("talk-a", hour=10)]},
            )
        )
        view = await live.agenda("acme.ava", "tracing")
    assert view.source == "briefer" and view.query == "tracing" and view.persona_id == "acme.ava"
    assert [i.talk.talk_id for i in view.items] == ["talk-a", "talk-b"]  # sorted by start
    assert view.items[0].ends_at - view.items[0].talk.starts_at == timedelta(minutes=30)
    assert view.items[0].in_calendar is False
    request = route.calls.last.request
    assert dict(request.url.params) == {"persona_id": "acme.ava", "q": "tracing"}
    assert request.extensions["timeout"]["read"] == BRIEFER_TIMEOUT_SECONDS == 3.0


async def test_a_briefer_talk_can_be_added_afterwards(live):
    with respx.mock() as router:
        router.get(ACME_TALKS).mock(return_value=httpx.Response(200, json={"query": "", "talks": [briefer_hit()]}))
        await live.agenda("acme.ava")
    added = await live.add_talk(AddTalkBody(persona_id="acme.ava", talk_id="talk-from-briefer"))
    assert added.event.title == "Agent-picked: tracing" and added.event.location == "Room D"
    with respx.mock() as router:
        router.get(ACME_TALKS).mock(return_value=httpx.Response(200, json={"query": "", "talks": [briefer_hit()]}))
        again = await live.agenda("acme.ava")
    assert again.items[0].in_calendar is True


async def test_unknown_talk_is_still_unknown_without_a_briefer_answer(live):
    with pytest.raises(HTTPException) as caught:
        await live.add_talk(AddTalkBody(persona_id="acme.ava", talk_id="talk-from-briefer"))
    assert caught.value.detail == "unknown_talk"


# ----------------------------------------------------------------------------- fallbacks
@pytest.mark.parametrize(
    "outcome",
    [
        httpx.ConnectTimeout("slow"),
        httpx.ConnectError("down"),
        httpx.Response(500, json={"detail": "boom"}),
        httpx.Response(404),
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, json={"query": "x", "talks": [{"talk_id": "t"}]}),  # fails the TalkHit contract
        httpx.Response(200, json=[]),
        httpx.Response(
            200,
            json={"query": "x", "talks": [{**briefer_hit(), "starts_at": "2026-11-10T11:00:00"}]},  # no timezone
        ),
    ],
    ids=["timeout", "connect-error", "http-500", "http-404", "bad-json", "bad-contract", "wrong-shape", "naive-time"],
)
async def test_any_briefer_failure_falls_back_to_the_seed(live, outcome, caplog):
    with respx.mock() as router, caplog.at_level("INFO"):
        route = router.get(ACME_TALKS)
        if isinstance(outcome, Exception):
            route.mock(side_effect=outcome)
        else:
            route.mock(return_value=outcome)
        view = await live.agenda("acme.ava", "ebpf")
    assert view.source == "seed"
    assert {i.talk.talk_id for i in view.items} == {"talk-ebpf-cost", "talk-ebpf-zero-code", "talk-ebpf-edge"}
    logged = " ".join(r.getMessage() for r in caplog.records if r.name.startswith("rapport.calendar"))
    assert "acme.ava" in logged and "ebpf" not in logged  # the persona id and error class, never the query


async def test_organisations_without_agents_never_call_a_briefer(live):
    with respx.mock(assert_all_called=False) as router:
        route = router.route()  # any request at all
        view = await live.agenda("lumenly.priya")
    assert view.source == "seed" and len(view.items) == 15 and route.call_count == 0


async def test_env_switch_forces_the_seed(live, monkeypatch):
    monkeypatch.setenv("RAPPORT_CALENDAR_AGENDA", "seed")
    with respx.mock(assert_all_called=False) as router:
        route = router.route()
        view = await live.agenda("acme.ava")
    assert view.source == "seed" and route.call_count == 0


# ----------------------------------------------------------------------------- seed filtering
async def test_seed_agenda_lists_everything_sorted_and_flags_my_talks(service):
    view = await service.agenda("acme.ava")
    assert view.source == "seed" and len(view.items) == 15
    assert [i.talk.starts_at for i in view.items] == sorted(i.talk.starts_at for i in view.items)
    flagged = {i.talk.talk_id for i in view.items if i.in_calendar}
    assert flagged == {"talk-otel-regulated", "talk-ebpf-zero-code", "talk-ebpf-edge"}  # Ava's three talks


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("ebpf", {"talk-ebpf-cost", "talk-ebpf-zero-code", "talk-ebpf-edge"}),
        ("EBPF", {"talk-ebpf-cost", "talk-ebpf-zero-code", "talk-ebpf-edge"}),
        ("ken", {"talk-search-ops-data"}),  # a speaker
        ("ebpf robots", {"talk-ebpf-edge"}),  # every word must match
        ("security", {"talk-hipaa-k8s", "talk-zero-trust-mesh", "talk-supply-chain"}),  # a track word
        ("nothing matches this", set()),
    ],
)
async def test_seed_filtering_is_a_case_insensitive_word_match(service, query, expected):
    view = await service.agenda("acme.sam", query)
    assert {i.talk.talk_id for i in view.items} == expected


def test_matches_helper():
    talk = TalkHit(
        talk_id="t", title="Hybrid search", starts_at=local(0, 9), room="Room A", track="Data", speakers=["Ken"]
    )
    assert matches(talk, "") and matches(talk, "   ") and matches(talk, "hyb sea") and matches(talk, "KEN")
    assert not matches(talk, "hybrid cooking") and not matches(talk, "ybrid")


async def test_agenda_query_rules(service):
    assert (await service.agenda("acme.sam", "  ebpf  ")).query == "ebpf"
    with pytest.raises(HTTPException) as caught:
        await service.agenda("acme.sam", "x" * 101)
    assert caught.value.detail == "query_too_long"
    with pytest.raises(HTTPException) as caught:
        await service.agenda("nobody.here")
    assert (caught.value.status_code, caught.value.detail) == (404, "unknown_persona")


async def test_agenda_is_capped_at_twenty_items(seed):
    many = [
        TalkHit(talk_id=f"t-{n}", title=f"Talk {n}", starts_at=local(0, 9) + (local(0, 10) - local(0, 9)) * n,
                room="R", track="T")
        for n in range(30)
    ]
    svc = CalendarService(seed=seed, talk_source=SeedTalkSource(many), now=lambda: NOW)
    assert len((await svc.agenda("acme.sam")).items) == 20


# ----------------------------------------------------------------------------- telemetry hygiene
async def test_spans_carry_only_ids_and_counts(service, monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(service_module, "tracer", lambda name="rapport": provider.get_tracer(name))

    await service.view("acme.ava")
    await service.agenda("acme.ava", "secret query")
    proposal = await service.propose(ProposeBody(persona_id="acme.sam", with_persona_id="kestrel.raj"))
    await service.respond(proposal.event.event_id, RespondBody(persona_id="acme.sam", response="accept"))

    spans = exporter.get_finished_spans()
    assert [s.name for s in spans] == ["calendar.view", "calendar.agenda", "calendar.propose", "calendar.respond"]
    for span in spans:
        assert set(span.attributes) <= {ATTR_PERSONA, ATTR_RESULT_COUNT}
        assert ATTR_PERSONA in span.attributes
    assert "secret query" not in repr([dict(s.attributes) for s in spans])


async def test_the_search_text_reaches_no_span_and_no_url_attribute(seed, monkeypatch):
    """init_telemetry instruments httpx and FastAPI, whose spans record full URLs; the query must not survive."""
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from rapport_calendar.app import create_app

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(service_module, "tracer", lambda name="rapport": provider.get_tracer(name))
    live = CalendarService(seed=seed, talk_source=BrieferTalkSource(SeedTalkSource(seed.agenda)), now=lambda: NOW)
    app = create_app(live)
    HTTPXClientInstrumentor().instrument(tracer_provider=provider)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    try:
        with respx.mock() as router:
            router.get(ACME_TALKS).mock(return_value=httpx.Response(200, json={"query": "", "talks": [briefer_hit()]}))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
                params = {"persona_id": "acme.ava", "q": "jobhuntingsecret"}
                res = await http.get("/api/calendar/agenda", params=params)
                # requests that fail validation (422) must lose their query too: the scrub is a route dependency
                no_persona = await http.get("/api/calendar/agenda", params={"q": "missingpersonasecret"})
                too_long = await http.get(
                    "/api/calendar/agenda", params={"persona_id": "acme.ava", "q": "overlimitsecret" + "x" * 100}
                )
        assert res.status_code == 200 and res.json()["source"] == "briefer"
        assert no_persona.status_code == 422 and too_long.status_code == 422
    finally:
        FastAPIInstrumentor.uninstrument_app(app)
        HTTPXClientInstrumentor().uninstrument()
    spans = exporter.get_finished_spans()
    assert any(s.name == "calendar.agenda" for s in spans) and any(s.kind.name == "SERVER" for s in spans)
    assert not [s for s in spans if s.kind.name == "CLIENT"]  # calendar.agenda already covers the briefer call
    attributes = repr([dict(s.attributes) for s in spans])
    for secret in ("jobhuntingsecret", "missingpersonasecret", "overlimitsecret"):
        assert secret not in attributes
