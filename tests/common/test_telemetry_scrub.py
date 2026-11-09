"""Query strings (search text) must not reach Dash0 on spans or logs; everything else must survive untouched."""

import logging

import httpx
import pytest
import respx
from fastapi import FastAPI
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, Status, StatusCode

from rapport_common.telemetry import _ScrubbingLoggingHandler, _ScrubbingSpanExporter

SECRET = "secret"


@pytest.fixture
def spans():
    sink = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(_ScrubbingSpanExporter(sink)))
    return provider, sink


def test_server_style_span_loses_its_query_but_keeps_everything_else(spans):
    provider, sink = spans
    with provider.get_tracer("t").start_as_current_span("GET /api/talks", kind=SpanKind.SERVER) as span:
        span.set_attributes({
            "http.method": "GET",
            "http.url": f"http://rapport.example/api/talks?persona_id=acme.ava&q={SECRET}",
            "http.target": f"/api/talks?persona_id=acme.ava&q={SECRET}",
            "url.full": f"http://rapport.example/api/talks?q={SECRET}",
            "url.path": "/api/talks",
            "url.query": f"persona_id=acme.ava&q={SECRET}",
            "http.status_code": 200,
            "rapport.persona_id": "acme.ava",
        })
    (out,) = sink.get_finished_spans()
    assert out.name == "GET /api/talks" and out.kind == SpanKind.SERVER
    assert dict(out.attributes) == {
        "http.method": "GET",
        "http.url": "http://rapport.example/api/talks",
        "http.target": "/api/talks",
        "url.full": "http://rapport.example/api/talks",
        "url.path": "/api/talks",
        "http.status_code": 200,
        "rapport.persona_id": "acme.ava",
    }


def test_client_style_span_loses_its_query_in_attributes_events_and_status(spans):
    provider, sink = spans
    url = f"http://briefer:8080/v1/talks?q={SECRET}"
    with provider.get_tracer("t").start_as_current_span("GET", kind=SpanKind.CLIENT, record_exception=False) as span:
        span.set_attributes({"http.url": url, "http.method": "GET", "http.status_code": 500, "server.port": 8080})
        span.add_event("exception", {"exception.message": f"Server error '500' for url '{url}'", "n": 1})
        span.set_status(Status(StatusCode.ERROR, f"500 for {url}"))
    (out,) = sink.get_finished_spans()
    assert out.attributes["http.url"] == "http://briefer:8080/v1/talks"
    assert out.attributes["http.method"] == "GET" and out.attributes["server.port"] == 8080
    (event,) = out.events
    assert event.name == "exception" and event.attributes["n"] == 1
    assert event.attributes["exception.message"] == "Server error '500' for url 'http://briefer:8080/v1/talks'"
    assert out.status.status_code == StatusCode.ERROR and out.status.description == "500 for http://briefer:8080/v1/talks"
    assert SECRET not in repr(out.to_json())


def test_span_without_a_query_is_passed_through_unchanged(spans):
    provider, sink = spans
    with provider.get_tracer("t").start_as_current_span("GET /healthz") as span:
        span.set_attribute("http.url", "http://rapport.example/healthz")
    (out,) = sink.get_finished_spans()
    assert out.attributes["http.url"] == "http://rapport.example/healthz"


async def test_real_fastapi_and_httpx_instrumentation_spans_are_scrubbed(spans):
    """The attribute names the installed instrumentations really emit are the ones the scrubber knows."""
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    provider, sink = spans
    app = FastAPI()

    @app.get("/api/talks")
    async def talks(q: str = ""):
        return {"n": 0}

    HTTPXClientInstrumentor().uninstrument()  # init_telemetry in other tests may have instrumented httpx already
    HTTPXClientInstrumentor().instrument(tracer_provider=provider)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    try:
        with respx.mock() as router:
            router.get("http://briefer:8080/v1/talks").mock(return_value=httpx.Response(200, json={}))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
                assert (await http.get("/api/talks", params={"q": SECRET})).status_code == 200
            async with httpx.AsyncClient() as http:
                assert (await http.get("http://briefer:8080/v1/talks", params={"q": SECRET})).status_code == 200
    finally:
        FastAPIInstrumentor.uninstrument_app(app)
        HTTPXClientInstrumentor().uninstrument()
    spans_out = sink.get_finished_spans()
    kinds = {s.kind for s in spans_out}
    assert SpanKind.SERVER in kinds and SpanKind.CLIENT in kinds
    assert SECRET not in repr([dict(s.attributes) for s in spans_out])
    server = next(s for s in spans_out if s.kind == SpanKind.SERVER)
    assert server.attributes["http.method"] == "GET" and server.attributes["http.status_code"] == 200


def test_otel_log_records_lose_query_strings():
    sink = InMemoryLogRecordExporter()
    provider = LoggerProvider()
    provider.add_log_record_processor(SimpleLogRecordProcessor(sink))
    handler = _ScrubbingLoggingHandler(level=logging.INFO, logger_provider=provider)
    logger = logging.getLogger("telemetry_test_scrub")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(handler)
    try:
        url = f"http://briefer:8080/v1/talks?q={SECRET}"
        logger.info('HTTP Request: %s %s "%s %d %s"', "GET", url, "HTTP/1.1", 200, "OK")
        logger.info("served persona %s", "acme.ava")
        try:
            raise RuntimeError(f"failed for url 'http://briefer:8080/v1/talks?q={SECRET}'")
        except RuntimeError:
            logger.exception("lookup failed")
    finally:
        logger.removeHandler(handler)
    bodies = [r.log_record.body for r in sink.get_finished_logs()]
    assert bodies[0] == 'HTTP Request: GET http://briefer:8080/v1/talks "HTTP/1.1 200 OK"'
    assert bodies[1] == "served persona acme.ava"
    failed = sink.get_finished_logs()[2].log_record
    assert failed.body == "lookup failed"
    assert SECRET not in repr(dict(failed.attributes))
    assert "http://briefer:8080/v1/talks'" in failed.attributes["exception.message"]
