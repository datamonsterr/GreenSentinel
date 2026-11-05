"""Basic Guardrail Engine for Ride-Hailing Telemetry.

Evaluates technical and system-health issues (app crash, network loss, GPS unavailable,
invalid telemetry) before fraud classification.

Deterministic logic only — system failures are technical dropouts, not fraud.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from src.models.schemas import TelemetryPayload


class GuardrailReason(StrEnum):
    """Machine-readable reason codes for blocking technical guardrails."""

    APP_CRASH = "APP_CRASH"
    NETWORK_LOSS = "NETWORK_LOSS"
    GPS_UNAVAILABLE = "GPS_UNAVAILABLE"
    INVALID_TELEMETRY = "INVALID_TELEMETRY"


class QualityFlag(StrEnum):
    """Quality flags for telemetry preprocessor and forensic analysis."""

    APP_CRASHED = "app_crashed"
    SERVICE_OUTAGE = "service_outage"
    NETWORK_OFFLINE = "network_offline"
    NETWORK_DEGRADED = "network_degraded"
    GPS_UNAVAILABLE = "gps_unavailable"
    MOCK_PROVIDER_ACTIVE = "mock_provider_active"
    INVALID_TELEMETRY = "invalid_telemetry"
    POSITION_MISSING = "position_missing"
    GPS_JITTER = "gps_jitter"


class GuardrailResult(BaseModel):
    """Structured result from technical guardrail evaluation."""

    blocked: bool = Field(
        ...,
        description="True if technical/system-health failure blocks fraud classification.",
    )
    reason: GuardrailReason | None = Field(
        default=None,
        description="Primary machine-readable blocking reason code if blocked is True.",
    )
    quality_flags: list[QualityFlag] = Field(
        default_factory=list,
        description="List of all quality flags detected during evaluation.",
    )


def is_valid_coordinate(lat: Any, lon: Any) -> bool:
    """Return True only for finite numeric WGS84 coordinates.

    ``bool`` is rejected explicitly because it is a subclass of ``int``; strings are
    rejected rather than parsed so malformed producer payloads stay visible.
    """
    for value in (lat, lon):
        if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        if not math.isfinite(value):
            return False
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def extract_position(payload: dict[str, Any]) -> tuple[Any, Any] | None:
    """Extract raw ``(latitude, longitude)`` from any supported telemetry shape.

    Supported shapes:
    1. ``{"position": {"latitude": ..., "longitude": ...}}`` (TelemetryPayload)
    2. ``{"position": {"type": "Point", "coordinates": [lon, lat]}}`` (CaseService in-memory)
    3. ``{"latitude": ..., "longitude": ...}`` flat (telemetry_queue_worker frames)

    Returns ``None`` when no position is present. A present but malformed position
    returns ``(None, None)`` so the caller treats it as invalid, not missing.
    Values are returned unvalidated; use ``is_valid_coordinate``.
    """
    position = payload.get("position")
    if isinstance(position, BaseModel):
        position = position.model_dump()
    if position is not None:
        if not isinstance(position, dict):
            return (None, None)
        if "coordinates" in position:
            coords = position.get("coordinates")
            if isinstance(coords, (list, tuple)) and len(coords) == 2:
                return (coords[1], coords[0])
            return (None, None)
        return (position.get("latitude"), position.get("longitude"))
    if "latitude" in payload or "longitude" in payload:
        return (payload.get("latitude"), payload.get("longitude"))
    return None


def _resolve_primary_reason(reasons: list[GuardrailReason]) -> GuardrailReason:
    """Select the primary blocking reason deterministically.

    Note: This ordering represents an implementation-level deterministic precedence
    to select a single primary reason string when multiple technical issues co-occur.
    It is NOT a fraud severity or business-policy ranking.
    """
    priority_order = [
        GuardrailReason.APP_CRASH,
        GuardrailReason.NETWORK_LOSS,
        GuardrailReason.GPS_UNAVAILABLE,
        GuardrailReason.INVALID_TELEMETRY,
    ]
    for r in priority_order:
        if r in reasons:
            return r
    return reasons[0]


def evaluate_telemetry_point(
    telemetry: TelemetryPayload | dict[str, Any],
) -> GuardrailResult:
    """Evaluate a single telemetry point or payload for technical issues.

    Rules:
    1. app_state == "crashed" -> blocked=True, reason="APP_CRASH", quality_flag="app_crashed"
    2. network_state == "offline" -> blocked=True, reason="NETWORK_LOSS", quality_flag="network_offline"
    3. gps_state == "unavailable" -> blocked=True, reason="GPS_UNAVAILABLE", quality_flag="gps_unavailable"
    4. mock_location_reported == True or gps_state == "mock_reported" -> blocked=False, quality_flag="mock_provider_active"
    5. network_state == "degraded" -> blocked=False (if position present), quality_flag="network_degraded"
    6. gps_state == "jitter" -> blocked=False (if position present), quality_flag="gps_jitter"
    7. Invalid coordinates or missing position without explicit technical outage -> blocked=True, reason="INVALID_TELEMETRY"
    """
    if isinstance(telemetry, TelemetryPayload):
        payload_dict = telemetry.model_dump()
    elif isinstance(telemetry, dict):
        payload_dict = telemetry
    else:
        return GuardrailResult(
            blocked=True,
            reason=GuardrailReason.INVALID_TELEMETRY,
            quality_flags=[QualityFlag.INVALID_TELEMETRY],
        )

    app_state = str(payload_dict.get("app_state") or "unknown").lower()
    network_state = str(payload_dict.get("network_state") or "unknown").lower()
    gps_state = str(payload_dict.get("gps_state") or "unknown").lower()
    mock_reported = bool(payload_dict.get("mock_location_reported") or gps_state == "mock_reported")

    position = extract_position(payload_dict)

    quality_flags: list[QualityFlag] = []
    blocking_reasons: list[GuardrailReason] = []

    # Rule 1: App crash
    if app_state == "crashed":
        blocking_reasons.append(GuardrailReason.APP_CRASH)
        quality_flags.append(QualityFlag.APP_CRASHED)

    # Rule 2: Network state
    if network_state == "offline":
        blocking_reasons.append(GuardrailReason.NETWORK_LOSS)
        quality_flags.append(QualityFlag.NETWORK_OFFLINE)
    elif network_state == "degraded":
        quality_flags.append(QualityFlag.NETWORK_DEGRADED)

    # Rule 3: GPS state
    if gps_state == "unavailable":
        blocking_reasons.append(GuardrailReason.GPS_UNAVAILABLE)
        quality_flags.append(QualityFlag.GPS_UNAVAILABLE)
    elif gps_state == "jitter":
        quality_flags.append(QualityFlag.GPS_JITTER)

    # Rule 4: Mock location (preserves ERR-05 fraud evaluation semantics; non-blocking for technical dropout)
    if mock_reported:
        quality_flags.append(QualityFlag.MOCK_PROVIDER_ACTIVE)

    # Rule 5: Position validation and technical exemption rules
    if position is not None:
        if not is_valid_coordinate(*position):
            blocking_reasons.append(GuardrailReason.INVALID_TELEMETRY)
            quality_flags.append(QualityFlag.INVALID_TELEMETRY)
    else:
        quality_flags.append(QualityFlag.POSITION_MISSING)
        # Position can only be exempted if an explicit technical outage is active:
        # - app_state == "crashed"
        # - network_state == "offline"
        # - gps_state == "unavailable"
        # Degraded network and unknown GPS state do NOT exempt a missing position.
        has_technical_outage_exemption = (
            app_state == "crashed" or network_state == "offline" or gps_state == "unavailable"
        )
        if not has_technical_outage_exemption:
            blocking_reasons.append(GuardrailReason.INVALID_TELEMETRY)
            quality_flags.append(QualityFlag.INVALID_TELEMETRY)

    # Deduplicate quality_flags preserving order
    unique_flags = list(dict.fromkeys(quality_flags))

    if blocking_reasons:
        return GuardrailResult(
            blocked=True,
            reason=_resolve_primary_reason(blocking_reasons),
            quality_flags=unique_flags,
        )

    return GuardrailResult(
        blocked=False,
        reason=None,
        quality_flags=unique_flags,
    )


_GAP_CORRELATION_THRESHOLD_S = 30.0


def _window_payload_dict(point: TelemetryPayload | dict[str, Any]) -> dict[str, Any]:
    """Return a plain dict view of a window point (Pydantic or dict shape)."""
    if isinstance(point, TelemetryPayload):
        return point.model_dump()
    return point if isinstance(point, dict) else {}


def _is_offline_payload(payload: dict[str, Any]) -> bool:
    """Return True when the raw payload reports ``network_state == "offline"``."""
    return str(payload.get("network_state") or "unknown").lower() == "offline"


def _parse_occurred_at(value: Any) -> datetime | None:
    """Parse an ``occurred_at`` value; return None when missing or unparseable.

    Naive datetimes are normalized to UTC so mixed naive/aware windows never
    raise ``TypeError`` on subtraction.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed
    return None


def _gap_seconds(value: Any) -> float | None:
    """Return a finite ``data_gap_s`` value; None when missing or non-numeric."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if math.isfinite(seconds) else None


def _exceeds_gap_threshold(value: Any, threshold_s: float) -> bool:
    """Return True when a ``data_gap_s`` value is finite and above threshold."""
    seconds = _gap_seconds(value)
    return seconds is not None and seconds > threshold_s


def _has_consecutive_offline_run(offline: list[bool], run_length: int = 2) -> bool:
    """Return True when ``offline`` contains a run of ``run_length`` consecutive True."""
    run = 0
    for is_offline in offline:
        run = run + 1 if is_offline else 0
        if run >= run_length:
            return True
    return False


def _is_gap_correlated(
    offline_indexes: list[int],
    payloads: list[dict[str, Any]],
    threshold_s: float = _GAP_CORRELATION_THRESHOLD_S,
) -> bool:
    """Return True when any offline point is adjacent to a >threshold_s telemetry gap.

    Gap evidence is either a parseable ``occurred_at`` delta to an immediate
    neighbour, or a ``data_gap_s`` field > threshold on the offline point or an
    immediate neighbour (fallback when timestamps are missing/unparseable).
    """
    for i in offline_indexes:
        if _exceeds_gap_threshold(payloads[i].get("data_gap_s"), threshold_s):
            return True
        ts_i = _parse_occurred_at(payloads[i].get("occurred_at"))
        for j in (i - 1, i + 1):
            if 0 <= j < len(payloads):
                if _exceeds_gap_threshold(payloads[j].get("data_gap_s"), threshold_s):
                    return True
                ts_j = _parse_occurred_at(payloads[j].get("occurred_at"))
                if ts_i is not None and ts_j is not None:
                    try:
                        gap_exceeded = abs((ts_j - ts_i).total_seconds()) > threshold_s
                    except TypeError:
                        continue
                    if gap_exceeded:
                        return True
    return False


def _neutralize_network_state(
    point: TelemetryPayload | dict[str, Any], payload: dict[str, Any]
) -> TelemetryPayload | dict[str, Any]:
    """Return a copy of ``point`` with ``network_state`` neutralized to unknown."""
    if isinstance(point, TelemetryPayload):
        return point.model_copy(update={"network_state": "unknown"})
    return {**payload, "network_state": "unknown"}


def _is_sustained_offline(
    payloads: list[dict[str, Any]],
    offline: list[bool],
    incident_offline_count: int,
) -> bool:
    """Return True when offline evidence in the window is a sustained outage.

    Sustained means: a run of >=2 consecutive offline points (a
    ``network_loss`` incident counts as an offline slot in the run, so one
    incident plus one offline point is sustained), or an offline point adjacent
    to a >30 s gap, or a degenerate single-point window that is offline
    (deny-by-default). A lone ``network_loss`` incident with zero offline points
    keeps blocking via its own incident reason (deny-by-default); this helper
    only gates point-contributed NETWORK_LOSS reasons.
    """
    offline_indexes = [i for i, is_offline in enumerate(offline) if is_offline]
    if not offline_indexes:
        return False
    if len(payloads) == 1:
        return True
    if incident_offline_count > 0:
        return True
    if _has_consecutive_offline_run(offline):
        return True
    return _is_gap_correlated(offline_indexes, payloads)


def evaluate_telemetry_window(
    points: list[TelemetryPayload | dict[str, Any]],
    incidents: list[dict[str, Any]] | None = None,
) -> GuardrailResult:
    """Evaluate a window of telemetry points and platform incidents.

    Aggregates quality flags and determines if any technical failure blocks
    fraud classification for the trip assignment window.

    Point-level tripwire semantics are preserved (a single offline point still
    blocks at point level), but at window level an offline point contributes a
    blocking NETWORK_LOSS reason only when sustained: part of a run of >=2
    consecutive offline points (a ``network_loss`` incident counts as an
    offline slot), gap-correlated (>30 s adjacent timestamp jump or
    ``data_gap_s`` > 30), or a degenerate single-point offline window. An
    isolated single offline blip keeps its ``network_offline`` quality flag for
    forensics without blocking the window.
    """
    all_flags: list[QualityFlag] = []
    blocking_reasons: list[GuardrailReason] = []

    # Process platform incidents if provided
    # Note: service_outage is recorded as a dedicated quality flag (QualityFlag.SERVICE_OUTAGE).
    # Since no repository policy explicitly defines service_outage as an independent blocking GuardrailReason,
    # it adds quality_flag="service_outage" and leaves blocked determination to actual telemetry/system states.
    for inc in incidents or []:
        inc_type = str(inc.get("incident_type") or "").lower() if isinstance(inc, dict) else ""
        if inc_type == "app_crash":
            blocking_reasons.append(GuardrailReason.APP_CRASH)
            all_flags.append(QualityFlag.APP_CRASHED)
        elif inc_type == "network_loss":
            blocking_reasons.append(GuardrailReason.NETWORK_LOSS)
            all_flags.append(QualityFlag.NETWORK_OFFLINE)
        elif inc_type == "gps_unavailable":
            blocking_reasons.append(GuardrailReason.GPS_UNAVAILABLE)
            all_flags.append(QualityFlag.GPS_UNAVAILABLE)
        elif inc_type == "service_outage":
            all_flags.append(QualityFlag.SERVICE_OUTAGE)

    # No telemetry at all can never support classification, whatever incidents say.
    # Incident reasons stay in the list, so a blocking incident still wins as primary reason.
    if not points:
        blocking_reasons.append(GuardrailReason.INVALID_TELEMETRY)
        all_flags.append(QualityFlag.INVALID_TELEMETRY)

    payload_dicts = [_window_payload_dict(pt) for pt in points]
    offline = [_is_offline_payload(payload) for payload in payload_dicts]
    incident_offline_count = sum(1 for r in blocking_reasons if r == GuardrailReason.NETWORK_LOSS)
    sustained_offline = _is_sustained_offline(payload_dicts, offline, incident_offline_count)

    for pt, payload in zip(points, payload_dicts):
        res = evaluate_telemetry_point(pt)
        all_flags.extend(res.quality_flags)
        if res.blocked and res.reason:
            if res.reason == GuardrailReason.NETWORK_LOSS and not sustained_offline:
                # Non-sustained NETWORK_LOSS is suppressed, but co-occurring
                # non-network reasons on the same point must survive. Re-evaluate
                # with network neutralized and keep any surviving block.
                surviving = evaluate_telemetry_point(_neutralize_network_state(pt, payload))
                if surviving.blocked and surviving.reason:
                    blocking_reasons.append(surviving.reason)
                continue
            blocking_reasons.append(res.reason)

    unique_flags = list(dict.fromkeys(all_flags))

    if blocking_reasons:
        return GuardrailResult(
            blocked=True,
            reason=_resolve_primary_reason(blocking_reasons),
            quality_flags=unique_flags,
        )

    return GuardrailResult(
        blocked=False,
        reason=None,
        quality_flags=unique_flags,
    )


def to_prompt_context(result: GuardrailResult) -> dict[str, bool]:
    """Map a guardrail result onto the boolean fields the analyst prompt expects.

    ``platform_outage`` and ``gps_degraded`` are derived only from the blocking reason,
    so non-blocking flags (degraded network, jitter) never trip the prompt's
    insufficient-evidence rule on their own.
    """
    reason = result.reason if result.blocked else None
    return {
        "platform_outage": reason in (GuardrailReason.APP_CRASH, GuardrailReason.NETWORK_LOSS),
        "gps_degraded": reason in (GuardrailReason.GPS_UNAVAILABLE, GuardrailReason.INVALID_TELEMETRY),
        "service_outage_reported": QualityFlag.SERVICE_OUTAGE in result.quality_flags,
        "mock_provider_active": QualityFlag.MOCK_PROVIDER_ACTIVE in result.quality_flags,
    }


def should_short_circuit(result: GuardrailResult) -> bool:
    """Return True when fraud classification must be skipped entirely.

    A blocked window that also reports a mock location provider still goes to the
    classifier: mock GPS is ERR-05 evidence, not a technical dropout.
    """
    return result.blocked and QualityFlag.MOCK_PROVIDER_ACTIVE not in result.quality_flags


def build_guardrail_assessment(result: GuardrailResult) -> dict[str, Any]:
    """Build a neutral ``insufficient_evidence`` assessment for a short-circuited trip.

    The dict has the same shape as ``JevAssessmentAgent.assess`` output so the worker
    can persist it unchanged.
    """
    reason = result.reason.value if result.reason else GuardrailReason.INVALID_TELEMETRY.value
    return {
        "category": "insufficient_evidence",
        "priority_tier": 2,
        "priority_label": "P2",
        "priority_score": 10,
        "confidence": 0.0,
        "reason_codes": [f"guardrail_{reason.lower()}", *(flag.value for flag in result.quality_flags)],
        "forensic_brief": (
            f"Dữ liệu telemetry không đủ điều kiện để phân loại gian lận do lỗi kỹ thuật ({reason}). "
            "Chưa kết luận vi phạm; chuyển Fraud Analyst xem xét thủ công."
        ),
        "maneuvers": [],
        "maneuver_narrative": "",
    }


def cap_priority_for_guardrail(assessment: dict[str, Any], result: GuardrailResult) -> dict[str, Any]:
    """Cap a P0 assessment to P1 when a technical guardrail blocks the window.

    POC_DESIGN assigns P0 only when no blocking technical guardrail is present.
    Returns a new dict; the input is never mutated.
    """
    capped = dict(assessment)
    if not result.blocked or capped.get("priority_tier") != 0:
        return capped
    capped["priority_tier"] = 1
    capped["priority_label"] = "P1"
    capped["reason_codes"] = [*capped.get("reason_codes", []), "priority_capped_by_guardrail"]
    return capped


# Backward-compatible private aliases.
_extract_position = extract_position
_is_valid_coordinate = is_valid_coordinate
