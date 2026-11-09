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

import logging
import os
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.context import Context
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
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

        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        readers.append(PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=10_000))
    trace.set_tracer_provider(tracer_provider)
    meter_provider = MeterProvider(resource=resource, metric_readers=readers)
    metrics.set_meter_provider(meter_provider)
    _providers.update(tracer=tracer_provider, meter=meter_provider)

    if endpoint:
        try:
            from opentelemetry._logs import set_logger_provider
            from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
            from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
            from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

            logger_provider = LoggerProvider(resource=resource)
            logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
            set_logger_provider(logger_provider)
            logging.getLogger().addHandler(LoggingHandler(level=logging.INFO, logger_provider=logger_provider))
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
