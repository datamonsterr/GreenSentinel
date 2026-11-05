"""Model input projection — strips evaluation labels before any model/classifier touch.

This is the single source of truth for what constitutes admissible model input.
The allowlist retains:
- Operational telemetry lifecycle facts (lifecycle_state, cancellation_reason, cancellation_actor)
- Raw GPS/kinematic stream (points) — with nested label keys removed per-point
- Route endpoints (pickup, dropoff, dropoff_address)
- Trip / assignment / driver identity references (trip_id, assignment_id, driver_id, case_id)
- Traffic / incident context (platform_incidents, incidents)
- Timing scalars (stationary_duration_s, occurred_at)

The denylist removes all evaluation-harness labels:
    scenario, expected_category, expected_guardrail, expected_guardrail_reason,
    expected_outcome, intent, simulation_id

Operational correlation provenance (trip_id, event_id) may remain in the stored
envelope *outside* the model features; this module only governs model input.
"""

from __future__ import annotations

import math
from typing import Any

# Keys that must NEVER reach a model or deterministic classifier.
_EVAL_LABEL_KEYS: frozenset[str] = frozenset(
    {
        "scenario",
        "expected_category",
        "expected_guardrail",
        "expected_guardrail_reason",
        "expected_outcome",
        "intent",
        "simulation_id",
    }
)

# Keys explicitly allowed at the top level of a telemetry event for model input.
# Anything not in this set is stripped from the projection.
_ALLOWLIST_TOP: frozenset[str] = frozenset(
    {
        # Identity / correlation (operational, not eval)
        "trip_id",
        "assignment_id",
        "case_id",
        "driver_id",
        "event_id",
        # Route endpoints
        "pickup",
        "dropoff",
        "dropoff_address",
        # Lifecycle / cancellation facts
        "lifecycle_state",
        "cancellation_reason",
        "cancellation_actor",
        "arrived_at",  # ghost-trip lifecycle fallback (#264): pickup presence evidence
        "started_at",  # ghost-trip lifecycle fallback (#264): pickup presence evidence
        # Kinematic scalars
        "stationary_duration_s",
        # Traffic / platform incidents
        "platform_incidents",
        "incidents",
        "traffic_observations",
        # Raw telemetry stream
        "points",
    }
)

# Keys allowed inside each telemetry point dict.
_ALLOWLIST_POINT: frozenset[str] = frozenset(
    {
        "latitude",
        "longitude",
        "position",
        "speed_mps",
        "bearing_deg",
        "accuracy_m",
        "app_state",
        "network_state",
        "gps_state",
        "mock_location_reported",
        "occurred_at",
        "event_id",
    }
)

_ALLOWLIST_GEOMETRY: frozenset[str] = frozenset({"type", "coordinates"})
_ALLOWLIST_INCIDENT: frozenset[str] = frozenset(
    {
        "incident_id",
        "incident_type",
        "type",
        "state",
        "started_at",
        "ended_at",
        "start",
        "end",
        "occurred_at",
        "resolved_at",
        "severity",
        "source",
        "source_event_id",
    }
)
_ALLOWLIST_TRAFFIC: frozenset[str] = frozenset(
    {
        "observed_at",
        "valid_until",
        "average_speed_mps",
        "congestion_level",
        "speed",
        "congestion",
        "source",
        "is_simulated",
        "provenance",
    }
)
_ALLOWLIST_PROVENANCE: frozenset[str] = frozenset(
    {"origin", "sensor_id", "channel", "source", "provider", "status", "is_shortest_path"}
)


def _scalar(value: Any) -> Any:
    return value if value is None or isinstance(value, (str, int, float, bool)) else None


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _finite_coordinates(value: Any) -> Any:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return value
    if isinstance(value, list):
        values = [_finite_coordinates(item) for item in value]
        return values if all(item is not None for item in values) else None
    return None


def _project_point(point: Any) -> dict[str, Any]:
    """Return a copy of a telemetry point with only allowlisted keys."""
    if not isinstance(point, dict):
        return {}
    projected = {k: v for k, v in point.items() if k in _ALLOWLIST_POINT}
    if isinstance(point.get("position"), dict):
        projected["position"] = _project_geometry(point["position"])
    return projected


def _project_geometry(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    projected = {}
    for key in ("type", "latitude", "longitude", "accuracy_m"):
        if key in value and _is_scalar(value[key]):
            projected[key] = value[key]
    if "coordinates" in value:
        coordinates = _finite_coordinates(value["coordinates"])
        if coordinates is not None:
            projected["coordinates"] = coordinates
    return projected


def _project_records(value: Any, allowlist: frozenset[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    records = []
    for record in value:
        if not isinstance(record, dict):
            continue
        projected = {}
        for key in allowlist:
            if key not in record:
                continue
            if key == "provenance" and isinstance(record[key], dict):
                projected[key] = {
                    nested_key: record[key][nested_key]
                    for nested_key in _ALLOWLIST_PROVENANCE
                    if nested_key in record[key] and _is_scalar(record[key][nested_key])
                }
            elif _is_scalar(record[key]):
                projected[key] = record[key]
        records.append(projected)
    return records


def project_model_input(event_data: dict[str, Any]) -> dict[str, Any]:
    """Return a projection of *event_data* safe for model/classifier consumption.

    - Top-level keys not in _ALLOWLIST_TOP are dropped.
    - Evaluation label keys are always dropped regardless of allowlist.
    - Each element of ``points`` is projected through ``_project_point``.
    - The original dict is never mutated.
    """
    projected: dict[str, Any] = {}
    for key, value in event_data.items():
        if key in _EVAL_LABEL_KEYS:
            continue
        if key not in _ALLOWLIST_TOP:
            continue
        if key == "points" and isinstance(value, list):
            projected[key] = [_project_point(pt) for pt in value]
        elif key in {"pickup", "dropoff"}:
            if isinstance(value, dict):
                projected[key] = _project_geometry(value)
            elif isinstance(value, list):
                projected[key] = _project_geometry({"coordinates": value}).get("coordinates", {})
            else:
                projected[key] = None
        elif key in {"incidents", "platform_incidents"}:
            projected[key] = _project_records(value, _ALLOWLIST_INCIDENT)
        elif key == "traffic_observations":
            projected[key] = _project_records(value, _ALLOWLIST_TRAFFIC)
        else:
            projected[key] = value.copy() if isinstance(value, dict) else value
    return projected
