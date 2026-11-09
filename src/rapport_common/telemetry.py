"""One-call OpenTelemetry setup for every Rapport service.

Traces, metrics and logs go over OTLP/HTTP straight to Dash0. Configuration comes
only from the standard env vars OTEL_EXPORTER_OTLP_ENDPOINT and
OTEL_EXPORTER_OTLP_HEADERS (the `dash0-otlp` Secret). Without them (local dev,
tests) providers are created with no exporters, so everything is a quiet no-op.

OpenLIT is initialised after our providers exist; it detects and reuses them
(checked against openlit 1.45 source), so LLM spans and token/cost metrics land
in the same traces. Prompt/response capture is OFF.

House rule (AGENTS.md): never put memory text, prompts, asks, briefs or CV content
on spans, metrics or logs. IDs, counts, decisions and rule IDs only.
"""

from __future__ import annotations

import copy
import logging
import os
import re
from collections.abc import Sequence
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.attributes import BoundedAttributes
from opentelemetry.context import Context
from opentelemetry.sdk._logs import LoggingHandler
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Event, ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.util import BoundedList
from opentelemetry.trace.status import Status
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

log = logging.getLogger("rapport.telemetry")

# Span attribute keys (use these constants, not string literals)
ATTR_ENCOUNTER = "rapport.encounter_id"
ATTR_ORG = "rapport.org_id"
ATTR_COUNTERPARTY_ORG = "rapport.counterparty_org_id"
ATTR_PERSONA = "rapport.persona_id"
ATTR_ROUND = "rapport.exchange.round"
ATTR_SIDE = "rapport.exchange.side"
ATTR_POLICY_ACTION = "rapport.policy.action"
ATTR_POLICY_DECISION = "rapport.policy.decision"
ATTR_POLICY_RULE = "rapport.policy.rule_id"
ATTR_ITEM = "rapport.item_id"
ATTR_RESULT_COUNT = "rapport.result_count"

# Metric names
METRIC_BRIEF_LATENCY = "rapport.brief.latency"  # histogram, ms, gateway: accept -> private_brief pushed
METRIC_EXCHANGE_DURATION = "rapport.exchange.duration"  # histogram, ms, initiator delegate
METRIC_POLICY_DECISIONS = "rapport.policy.decisions"  # counter, attrs: decision, rule_id, org_id
METRIC_ENCOUNTERS = "rapport.encounters.started"  # counter, gateway

_providers: dict[str, Any] = {}
_propagator = TraceContextTextMapPropagator()

# --- Query-string scrubbing --------------------------------------------------------------------------------------
# Search text travels in URL query strings (GET /api/talks?q=..., GET /v1/talks?q=...). The FastAPI and httpx
# instrumentations record the full URL on every span (http.url / url.full; http.target / url.query on the server
# side), so every exporter below strips queries before spans and logs leave the process. Paths stay: they hold IDs.
_URL_KEYS_DROPPED = frozenset({"url.query"})
_URL_KEYS_TRIMMED = frozenset({"http.url", "http.target", "url.full", "http.request.target"})
_ABS_URL_QUERY_RE = re.compile(r"""(https?://[^\s'"<>?#]*)\?[^\s'"<>#]*""")
_REQUEST_LINE_QUERY_RE = re.compile(r"\b((?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) [^\s?]*)\?\S*")


def _strip_query(value: str) -> str:
    """Drop the query and fragment from one URL or request target; scheme, host and path stay."""
    return value.split("?", 1)[0].split("#", 1)[0]


def _scrub_text(value: str) -> str:
    """Remove query strings from URLs and request lines embedded in free text (exception messages, log lines)."""
    if "?" not in value:
        return value
    return _REQUEST_LINE_QUERY_RE.sub(r"\1", _ABS_URL_QUERY_RE.sub(r"\1", value))


def _scrub_attributes(attributes: Any) -> dict[str, Any] | None:
    """Scrubbed copy of an attribute mapping, or None when nothing needed changing."""
    if not attributes:
        return None
    out: dict[str, Any] = {}
    changed = False
    for key, value in attributes.items():
        if key in _URL_KEYS_DROPPED:
            changed = True
            continue
        if isinstance(value, str):
            new = _strip_query(value) if key in _URL_KEYS_TRIMMED else _scrub_text(value)
            changed = changed or new != value
            value = new
        out[key] = value
    return out if changed else None


def scrub_span(span: ReadableSpan) -> ReadableSpan:
    """The span itself if it carries no query string, else a copy with URL attributes, events and status scrubbed."""
    attributes = _scrub_attributes(span.attributes)
    events = []
    events_changed = False
    for event in span.events:
        new_attrs = _scrub_attributes(event.attributes)
        events_changed = events_changed or new_attrs is not None
        events.append(Event(event.name, new_attrs if new_attrs is not None else event.attributes, event.timestamp))
    status = span.status
    description = status.description
    if description and _scrub_text(description) != description:
        status = Status(status.status_code, _scrub_text(description))
    if attributes is None and not events_changed and status is span.status:
        return span
    # The span's properties expose plain mappings/tuples; the OTLP encoder reads the dropped counts off the bounded
    # containers, so rebuild those and carry the counts over.
    kept = attributes if attributes is not None else span.attributes
    bounded_attributes = BoundedAttributes(attributes=kept, immutable=True)
    bounded_attributes.dropped = span.dropped_attributes
    bounded_events = BoundedList(None)
    bounded_events.extend(events)
    bounded_events.dropped = span.dropped_events
    bounded_links = BoundedList(None)
    bounded_links.extend(span.links)
    bounded_links.dropped = span.dropped_links
    return ReadableSpan(
        name=span.name,
        context=span.context,
        parent=span.parent,
        resource=span.resource,
        attributes=bounded_attributes,
        events=bounded_events,
        links=bounded_links,
        kind=span.kind,
        status=status,
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


class _ScrubbingSpanExporter(SpanExporter):
    """Wraps the real exporter. Spans are immutable once ended, so scrubbed copies are what get exported."""

    def __init__(self, inner: SpanExporter) -> None:
        self._inner = inner

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        return self._inner.export([scrub_span(s) for s in spans])

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._inner.force_flush(timeout_millis)


class _ScrubbingLoggingHandler(LoggingHandler):
    """OTel log handler that strips query strings (httpx's 'HTTP Request: GET http://...?q=...' line, exceptions)."""

    @staticmethod
    def _get_attributes(record: logging.LogRecord) -> Any:
        attributes = LoggingHandler._get_attributes(record)
        return _scrub_attributes(attributes) or attributes

    def _translate(self, record: logging.LogRecord) -> Any:
        if isinstance(record.msg, str) and "?" in record.getMessage():
            record = copy.copy(record)  # other handlers (stderr) keep the original record untouched
            record.msg, record.args = _scrub_text(record.getMessage()), None
        return super()._translate(record)


def init_telemetry(service_name: str, *, org_id: str | None = None, fastapi_app: Any = None) -> None:
    """Call once at process start, before creating clients. Safe to call in tests."""
    if _providers:
        return
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    attrs: dict[str, str] = {
        "service.name": service_name,
        "service.namespace": "rapport",
        "deployment.environment.name": os.environ.get("RAPPORT_ENV", "hackathon"),
    }
    for key, env in (("k8s.namespace.name", "POD_NAMESPACE"), ("k8s.pod.name", "POD_NAME")):
        if os.environ.get(env):
            attrs[key] = os.environ[env]
    if org_id:
        attrs[ATTR_ORG] = org_id
    resource = Resource.create(attrs)

    tracer_provider = TracerProvider(resource=resource)
    readers = []
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        tracer_provider.add_span_processor(BatchSpanProcessor(_ScrubbingSpanExporter(OTLPSpanExporter())))
        readers.append(PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=10_000))
    trace.set_tracer_provider(tracer_provider)
    meter_provider = MeterProvider(resource=resource, metric_readers=readers)
    metrics.set_meter_provider(meter_provider)
    _providers.update(tracer=tracer_provider, meter=meter_provider)

    if endpoint:
        try:
            from opentelemetry._logs import set_logger_provider
            from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
            from opentelemetry.sdk._logs import LoggerProvider
            from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

            logger_provider = LoggerProvider(resource=resource)
            logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
            set_logger_provider(logger_provider)
            handler = _ScrubbingLoggingHandler(level=logging.INFO, logger_provider=logger_provider)
            logging.getLogger().addHandler(handler)
            _providers["logger"] = logger_provider
        except Exception:  # logs are a bonus; never block startup
            log.exception("OTel log export not configured")

    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
    except Exception:
        log.exception("httpx instrumentation failed")
    if fastapi_app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(fastapi_app)

    try:
        import openlit

        openlit.init(
            application_name=service_name,
            environment=attrs["deployment.environment.name"],
            capture_message_content=False,
        )
    except Exception:
        log.exception("OpenLIT init failed; LLM spans will be missing")


def tracer(name: str = "rapport") -> trace.Tracer:
    return trace.get_tracer(name)


def meter(name: str = "rapport") -> metrics.Meter:
    return metrics.get_meter(name)


def current_traceparent() -> str | None:
    """W3C traceparent of the active span (gateway writes it on the Encounter annotation)."""
    carrier: dict[str, str] = {}
    _propagator.inject(carrier)
    return carrier.get("traceparent")


def context_from_traceparent(traceparent: str | None) -> Context | None:
    """Parent context for a delegate pod: tracer().start_as_current_span(..., context=this)."""
    if not traceparent:
        return None
    return _propagator.extract({"traceparent": traceparent})


def current_trace_id() -> str | None:
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None


def shutdown_telemetry() -> None:
    """Flush everything. Delegate Jobs MUST call this before exiting or their spans are lost."""
    for key in ("tracer", "meter", "logger"):
        provider = _providers.get(key)
        if provider is not None:
            try:
                provider.force_flush()
                provider.shutdown()
            except Exception:
                log.exception("telemetry shutdown failed for %s", key)
