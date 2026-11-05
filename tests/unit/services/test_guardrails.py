"""Unit tests for Basic Guardrail Engine (src/services/guardrails.py)."""

from __future__ import annotations

from src.models.schemas import TelemetryPayload, TelemetryPosition
from src.services.guardrails import (
    GuardrailReason,
    GuardrailResult,
    QualityFlag,
    evaluate_telemetry_point,
    evaluate_telemetry_window,
)


def test_healthy_telemetry():
    """Rule 1: Healthy telemetry should be unblocked with no reason and no quality flags."""
    payload = {
        "position": {"latitude": 21.0285, "longitude": 105.8542, "accuracy_m": 5.0},
        "speed_mps": 8.5,
        "bearing_deg": 90.0,
        "app_state": "foreground",
        "network_state": "online",
        "gps_state": "valid",
        "mock_location_reported": False,
    }

    result = evaluate_telemetry_point(payload)

    assert isinstance(result, GuardrailResult)
    assert result.blocked is False
    assert result.reason is None
    assert result.quality_flags == []


def test_app_crashed():
    """Rule 2: app_state=crashed should block with reason APP_CRASH and exempt position=None."""
    payload = {
        "position": None,
        "speed_mps": 0.0,
        "app_state": "crashed",
        "network_state": "online",
        "gps_state": "valid",
        "mock_location_reported": False,
    }

    result = evaluate_telemetry_point(payload)

    assert result.blocked is True
    assert result.reason == GuardrailReason.APP_CRASH.value
    assert QualityFlag.APP_CRASHED.value in result.quality_flags
    assert QualityFlag.POSITION_MISSING.value in result.quality_flags
    assert QualityFlag.INVALID_TELEMETRY.value not in result.quality_flags


def test_network_loss():
    """Rule 3: network_state=offline should block with reason NETWORK_LOSS and exempt position=None."""
    payload = {
        "position": None,
        "speed_mps": 0.0,
        "app_state": "foreground",
        "network_state": "offline",
        "gps_state": "valid",
        "mock_location_reported": False,
    }

    result = evaluate_telemetry_point(payload)

    assert result.blocked is True
    assert result.reason == GuardrailReason.NETWORK_LOSS.value
    assert QualityFlag.NETWORK_OFFLINE.value in result.quality_flags
    assert QualityFlag.POSITION_MISSING.value in result.quality_flags
    assert QualityFlag.INVALID_TELEMETRY.value not in result.quality_flags


def test_gps_unavailable():
    """Rule 4: gps_state=unavailable should block with reason GPS_UNAVAILABLE and exempt position=None."""
    payload = {
        "position": None,
        "speed_mps": 0.0,
        "app_state": "foreground",
        "network_state": "online",
        "gps_state": "unavailable",
        "mock_location_reported": False,
    }

    result = evaluate_telemetry_point(payload)

    assert result.blocked is True
    assert result.reason == GuardrailReason.GPS_UNAVAILABLE.value
    assert QualityFlag.GPS_UNAVAILABLE.value in result.quality_flags
    assert QualityFlag.POSITION_MISSING.value in result.quality_flags
    assert QualityFlag.INVALID_TELEMETRY.value not in result.quality_flags


def test_mock_gps_non_blocking():
    """Rule 5: mock location reported should add quality flag but NOT block as technical dropout."""
    payload_mock_bool = {
        "position": {"latitude": 21.0285, "longitude": 105.8542, "accuracy_m": 5.0},
        "speed_mps": 15.0,
        "app_state": "foreground",
        "network_state": "online",
        "gps_state": "valid",
        "mock_location_reported": True,
    }

    result_bool = evaluate_telemetry_point(payload_mock_bool)
    assert result_bool.blocked is False
    assert result_bool.reason is None
    assert QualityFlag.MOCK_PROVIDER_ACTIVE.value in result_bool.quality_flags

    payload_mock_state = {
        "position": {"latitude": 21.0285, "longitude": 105.8542, "accuracy_m": 5.0},
        "speed_mps": 15.0,
        "app_state": "foreground",
        "network_state": "online",
        "gps_state": "mock_reported",
        "mock_location_reported": False,
    }

    result_state = evaluate_telemetry_point(payload_mock_state)
    assert result_state.blocked is False
    assert result_state.reason is None
    assert QualityFlag.MOCK_PROVIDER_ACTIVE.value in result_state.quality_flags


def test_degraded_network_with_valid_position():
    """degraded network + valid position => non-blocking quality flag."""
    payload = {
        "position": {"latitude": 21.0285, "longitude": 105.8542, "accuracy_m": 5.0},
        "speed_mps": 5.0,
        "app_state": "foreground",
        "network_state": "degraded",
        "gps_state": "valid",
        "mock_location_reported": False,
    }

    result = evaluate_telemetry_point(payload)

    assert result.blocked is False
    assert result.reason is None
    assert QualityFlag.NETWORK_DEGRADED.value in result.quality_flags


def test_degraded_network_with_missing_position():
    """degraded network + missing position => blocked with INVALID_TELEMETRY (degraded network does NOT exempt position=None)."""
    payload = {
        "position": None,
        "speed_mps": 0.0,
        "app_state": "foreground",
        "network_state": "degraded",
        "gps_state": "valid",
        "mock_location_reported": False,
    }

    result = evaluate_telemetry_point(payload)

    assert result.blocked is True
    assert result.reason == GuardrailReason.INVALID_TELEMETRY.value
    assert QualityFlag.NETWORK_DEGRADED.value in result.quality_flags
    assert QualityFlag.POSITION_MISSING.value in result.quality_flags
    assert QualityFlag.INVALID_TELEMETRY.value in result.quality_flags


def test_gps_unknown_with_missing_position():
    """gps unknown + missing position => blocked with INVALID_TELEMETRY (gps_state=unknown does NOT exempt position=None)."""
    payload = {
        "position": None,
        "speed_mps": 0.0,
        "app_state": "foreground",
        "network_state": "online",
        "gps_state": "unknown",
        "mock_location_reported": False,
    }

    result = evaluate_telemetry_point(payload)

    assert result.blocked is True
    assert result.reason == GuardrailReason.INVALID_TELEMETRY.value
    assert QualityFlag.POSITION_MISSING.value in result.quality_flags
    assert QualityFlag.INVALID_TELEMETRY.value in result.quality_flags


def test_service_outage_incident_non_blocking_quality_flag():
    """service_outage incident adds dedicated quality flag without inventing independent blocking semantics unless telemetry/system points show a failure."""
    incidents = [{"incident_type": "service_outage"}]
    healthy_point = {
        "position": {"latitude": 21.0285, "longitude": 105.8542, "accuracy_m": 5.0},
        "speed_mps": 5.0,
        "app_state": "foreground",
        "network_state": "online",
        "gps_state": "valid",
    }

    result = evaluate_telemetry_window([healthy_point], incidents)

    assert result.blocked is False
    assert result.reason is None
    assert QualityFlag.SERVICE_OUTAGE.value in result.quality_flags


def test_invalid_coordinates():
    """Rule 7: Out-of-range coordinates should block with reason INVALID_TELEMETRY."""
    payload = {
        "position": {"latitude": 120.0, "longitude": 105.8542, "accuracy_m": 5.0},
        "speed_mps": 5.0,
        "app_state": "foreground",
        "network_state": "online",
        "gps_state": "valid",
        "mock_location_reported": False,
    }

    result = evaluate_telemetry_point(payload)

    assert result.blocked is True
    assert result.reason == GuardrailReason.INVALID_TELEMETRY.value
    assert QualityFlag.INVALID_TELEMETRY.value in result.quality_flags


def test_telemetry_payload_pydantic_model_support():
    """Verify function works with TelemetryPayload Pydantic instances."""
    payload = TelemetryPayload(
        position=TelemetryPosition(latitude=21.0285, longitude=105.8542, accuracy_m=4.0),
        speed_mps=10.0,
        bearing_deg=180.0,
        app_state="foreground",
        network_state="online",
        gps_state="valid",
        mock_location_reported=False,
    )

    result = evaluate_telemetry_point(payload)

    assert result.blocked is False
    assert result.reason is None


def test_priority_order_app_crash_over_network_loss():
    """Deterministic selection precedence: APP_CRASH takes precedence over NETWORK_LOSS when both occur."""
    payload = {
        "position": None,
        "speed_mps": 0.0,
        "app_state": "crashed",
        "network_state": "offline",
        "gps_state": "unavailable",
    }

    result = evaluate_telemetry_point(payload)

    assert result.blocked is True
    assert result.reason == GuardrailReason.APP_CRASH.value
    assert QualityFlag.APP_CRASHED.value in result.quality_flags
    assert QualityFlag.NETWORK_OFFLINE.value in result.quality_flags
    assert QualityFlag.GPS_UNAVAILABLE.value in result.quality_flags


def test_evaluate_telemetry_window_healthy():
    """Window of healthy points should evaluate to unblocked."""
    points = [
        {
            "position": {"latitude": 21.01, "longitude": 105.81, "accuracy_m": 5.0},
            "app_state": "foreground",
            "network_state": "online",
            "gps_state": "valid",
        },
        {
            "position": {"latitude": 21.02, "longitude": 105.82, "accuracy_m": 5.0},
            "app_state": "foreground",
            "network_state": "online",
            "gps_state": "valid",
        },
    ]

    result = evaluate_telemetry_window(points)

    assert result.blocked is False
    assert result.reason is None


def test_evaluate_telemetry_window_with_dropout_and_incidents():
    """Window containing a crash point or incident should be blocked."""
    points = [
        {
            "position": {"latitude": 21.01, "longitude": 105.81, "accuracy_m": 5.0},
            "app_state": "foreground",
            "network_state": "online",
            "gps_state": "valid",
        },
        {"position": None, "app_state": "crashed", "network_state": "offline", "gps_state": "unavailable"},
    ]
    incidents = [{"incident_type": "app_crash"}]

    result = evaluate_telemetry_window(points, incidents)

    assert result.blocked is True
    assert result.reason == GuardrailReason.APP_CRASH.value
    assert QualityFlag.APP_CRASHED.value in result.quality_flags
