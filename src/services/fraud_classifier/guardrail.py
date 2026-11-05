"""Telemetry guardrail evaluation and bundle normalization for production fraud classification.

Reuses pure guardrail functions from src.services.guardrails while enforcing recursive
metadata scrubbing and schema normalization across raw bundles and telemetry events.
"""

from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel

from src.services.guardrails import evaluate_telemetry_window, should_short_circuit

# Generator-metadata keys that must never reach the detector or feature extractors.
_SCRUB_KEYS = frozenset(
    {
        "label",
        "fraud_propensity",
        "profile_provenance",
        "label_provenance",
        "scenario",
        "expected_category",
        "expected_guardrail",
        "expected_guardrail_reason",
        "expected_outcome",
        "intent",
        "simulation_id",
        "anomaly_type",
        "anomaly_score",
        "simulation_labels",
    }
)
_SCRUB_PREFIXES = ("expected_", "simulation_", "anomaly_")


def scrub_bundle(value: Any) -> Any:
    """Recursively strip generator labels and synthetic ground-truth metadata."""
    if isinstance(value, dict):
        return {
            k: scrub_bundle(v)
            for k, v in value.items()
            if k not in _SCRUB_KEYS and not any(k.startswith(p) for p in _SCRUB_PREFIXES)
        }
    if isinstance(value, (list, tuple)):
        return [scrub_bundle(v) for v in value]
    return value


def normalise_bundle(bundle_or_event: Any) -> dict[str, Any]:
    """Normalize raw benchmark bundle or telemetry event into feature-ready dictionary.

    Supports:
    1. Raw benchmark trip bundles (releases_v2.1 / run_10k bundle format).
    2. Telemetry event payloads from queue workers.
    3. Mapped JevAssessmentInput objects from src.services.jev_state_builder.
    """
    if isinstance(bundle_or_event, BaseModel):
        data = bundle_or_event.model_dump()
    elif isinstance(bundle_or_event, dict):
        data = copy.deepcopy(bundle_or_event)
    else:
        data = {}

    scrubbed = scrub_bundle(data)

    # Telemetry normalization
    telemetry = scrubbed.get("telemetry")
    if isinstance(telemetry, dict) and "points" in telemetry:
        points = telemetry.get("points") or []
    elif isinstance(telemetry, list):
        points = telemetry
    elif "points" in scrubbed and isinstance(scrubbed["points"], list):
        points = scrubbed["points"]
    elif "samples" in scrubbed and isinstance(scrubbed["samples"], list):
        points = scrubbed["samples"]
    else:
        points = []

    scrubbed["telemetry"] = points

    # Trip and coordinates normalization
    trip = scrubbed.get("trip") if isinstance(scrubbed.get("trip"), dict) else {}
    assignment = scrubbed.get("assignment") if isinstance(scrubbed.get("assignment"), dict) else {}
    trip_data = scrubbed.get("trip_data") if isinstance(scrubbed.get("trip_data"), dict) else {}

    if not scrubbed.get("pickup"):
        scrubbed["pickup"] = trip.get("pickup") or assignment.get("pickup") or trip_data.get("pickup")
    if not scrubbed.get("dropoff"):
        scrubbed["dropoff"] = trip.get("dropoff") or assignment.get("dropoff") or trip_data.get("dropoff")

    if not scrubbed.get("planned_route"):
        scrubbed["planned_route"] = (
            scrubbed.get("route") or trip.get("planned_route") or trip.get("route") or trip_data.get("planned_route")
        )

    if not scrubbed.get("driver_profile"):
        scrubbed["driver_profile"] = trip.get("driver_profile") or (
            scrubbed.get("driver") if isinstance(scrubbed.get("driver"), dict) else {}
        ).get("profile")
    if not scrubbed.get("driver_analytics"):
        scrubbed["driver_analytics"] = trip.get("driver_analytics") or (
            scrubbed.get("driver") if isinstance(scrubbed.get("driver"), dict) else {}
        ).get("analytics")

    # Incident normalization
    incident = scrubbed.get("platform_incident")
    if not incident and isinstance(scrubbed.get("incidents"), list) and scrubbed["incidents"]:
        scrubbed["platform_incident"] = scrubbed["incidents"][0]

    return scrubbed


def evaluate_bundle_guardrail(bundle: dict[str, Any]) -> dict[str, Any]:
    """Evaluate technical guardrail conditions against bundle telemetry and incidents."""
    norm = normalise_bundle(bundle)
    points = norm.get("telemetry") or []
    incident = norm.get("platform_incident")
    incidents = [incident] if isinstance(incident, dict) else (norm.get("incidents") or [])

    guardrail = evaluate_telemetry_window(points, incidents)
    short_circuited = should_short_circuit(guardrail)
    reason_code = guardrail.reason.value if guardrail.reason else None

    return {
        "should_short_circuit": short_circuited,
        "blocked": bool(guardrail.blocked),
        "reason": reason_code,
        "quality_flags": [q.value for q in guardrail.quality_flags],
    }
