"""Metric instruments (names from rapport_common.telemetry). Created lazily, so they bind to whichever meter
provider is installed when they are first used (tests: none, which is a quiet no-op)."""

from __future__ import annotations

from opentelemetry.metrics import Counter, Histogram

from rapport_common import telemetry


class DelegateMetrics:
    def __init__(self) -> None:
        m = telemetry.meter("rapport.delegate")
        self.policy_decisions: Counter = m.create_counter(
            telemetry.METRIC_POLICY_DECISIONS, description="Policy decisions by decision, rule and org"
        )
        self.exchange_duration: Histogram = m.create_histogram(
            telemetry.METRIC_EXCHANGE_DURATION, unit="ms", description="Initiator: whole exchange"
        )

    def record_decision(self, *, decision: str, rule_id: str, org_id: str) -> None:
        self.policy_decisions.add(1, {"decision": decision, "rule_id": rule_id, "org_id": org_id})
