"""Gateway metrics (SPEC 8). Attributes are IDs only; never content."""

from __future__ import annotations

from rapport_common.telemetry import ATTR_ORG, METRIC_BRIEF_LATENCY, METRIC_ENCOUNTERS, meter


class Instruments:
    """Created lazily so they bind to the meter provider installed by init_telemetry() in main()."""

    def __init__(self) -> None:
        self._latency = None
        self._started = None

    def brief_latency(self, millis: float, org_id: str) -> None:
        if self._latency is None:
            self._latency = meter().create_histogram(
                METRIC_BRIEF_LATENCY, unit="ms", description="Accept until the private brief is pushed"
            )
        self._latency.record(millis, {ATTR_ORG: org_id})

    def encounter_started(self) -> None:
        if self._started is None:
            self._started = meter().create_counter(METRIC_ENCOUNTERS, description="Encounters created")
        self._started.add(1)
