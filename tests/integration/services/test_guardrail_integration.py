"""Integration tests: guardrail position shapes, helpers, and telemetry worker wiring."""

from __future__ import annotations

import asyncio
import math
from types import SimpleNamespace
from typing import Any

import pytest

from src.services import telemetry_queue_worker as worker
from src.services.guardrails import (
    GuardrailReason,
    GuardrailResult,
    QualityFlag,
    build_guardrail_assessment,
    cap_priority_for_guardrail,
    evaluate_telemetry_point,
    evaluate_telemetry_window,
    should_short_circuit,
    to_prompt_context,
)

pytestmark = pytest.mark.docker

_HEALTHY_STATES = {"app_state": "foreground", "network_state": "online", "gps_state": "valid"}


def _flat_point(t: int = 0, **overrides: Any) -> dict[str, Any]:
    return {
        "latitude": 21.0285,
        "longitude": 105.8542,
        "speed_mps": 5.0,
        "occurred_at": f"2026-09-27T08:00:{t:02d}Z",
        "sequence": t // 15,
        **_HEALTHY_STATES,
        **overrides,
    }


# ---------------------------------------------------------------------------
# Position shapes and coordinate validation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "point",
    [
        {"position": {"latitude": 21.0285, "longitude": 105.8542}, **_HEALTHY_STATES},
        {"position": {"type": "Point", "coordinates": [105.8542, 21.0285]}, **_HEALTHY_STATES},
        {"latitude": 21.0285, "longitude": 105.8542, **_HEALTHY_STATES},
    ],
    ids=["telemetry_payload", "geojson_point", "flat_frame"],
)
def test_all_position_shapes_are_accepted(point):
    result = evaluate_telemetry_point(point)
    assert result.blocked is False
    assert result.reason is None
    assert result.quality_flags == []


def test_geojson_coordinates_are_lon_lat_order():
    # [lon, lat] = [105.85, 95.0] -> latitude 95 is out of range.
    point = {"position": {"type": "Point", "coordinates": [105.85, 95.0]}, **_HEALTHY_STATES}
    assert evaluate_telemetry_point(point).reason == GuardrailReason.INVALID_TELEMETRY


@pytest.mark.parametrize(
    "lat, lon",
    [
        (math.nan, 105.8542),
        (21.0285, math.inf),
        (True, 105.8542),
        (21.0285, False),
        ("21.0285", 105.8542),
        (21.0285, "105.8542"),
        (None, 105.8542),
    ],
    ids=["nan", "inf", "bool_lat", "bool_lon", "str_lat", "str_lon", "none_lat"],
)
def test_invalid_coordinate_values_are_blocked(lat, lon):
    result = evaluate_telemetry_point({"latitude": lat, "longitude": lon, **_HEALTHY_STATES})
    assert result.blocked is True
    assert result.reason == GuardrailReason.INVALID_TELEMETRY
    assert QualityFlag.INVALID_TELEMETRY in result.quality_flags


def test_malformed_geojson_is_invalid_not_missing():
    result = evaluate_telemetry_point({"position": {"type": "Point", "coordinates": [105.85]}, **_HEALTHY_STATES})
    assert result.reason == GuardrailReason.INVALID_TELEMETRY
    assert QualityFlag.POSITION_MISSING not in result.quality_flags


# ---------------------------------------------------------------------------
# Window: incidents without points
# ---------------------------------------------------------------------------
def test_service_outage_without_points_is_blocked():
    result = evaluate_telemetry_window([], [{"incident_type": "service_outage"}])
    assert result.blocked is True
    assert result.reason == GuardrailReason.INVALID_TELEMETRY
    assert QualityFlag.SERVICE_OUTAGE in result.quality_flags


def test_blocking_incident_wins_reason_without_points():
    result = evaluate_telemetry_window([], [{"incident_type": "app_crash"}])
    assert result.blocked is True
    assert result.reason == GuardrailReason.APP_CRASH
    assert QualityFlag.INVALID_TELEMETRY in result.quality_flags


def test_serialized_result_uses_plain_strings():
    dumped = evaluate_telemetry_window([], [{"incident_type": "network_loss"}]).model_dump(mode="json")
    assert dumped == {
        "blocked": True,
        "reason": "NETWORK_LOSS",
        "quality_flags": ["network_offline", "invalid_telemetry"],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def test_to_prompt_context_derives_only_from_blocking_reason():
    network = GuardrailResult(blocked=True, reason=GuardrailReason.NETWORK_LOSS, quality_flags=[])
    assert to_prompt_context(network)["platform_outage"] is True
    assert to_prompt_context(network)["gps_degraded"] is False

    gps = GuardrailResult(blocked=True, reason=GuardrailReason.GPS_UNAVAILABLE, quality_flags=[])
    assert to_prompt_context(gps) == {
        "platform_outage": False,
        "gps_degraded": True,
        "service_outage_reported": False,
        "mock_provider_active": False,
    }

    # Non-blocking degradation flags never trip the prompt's insufficient-evidence rule.
    degraded = GuardrailResult(
        blocked=False,
        quality_flags=[QualityFlag.NETWORK_DEGRADED, QualityFlag.GPS_JITTER, QualityFlag.SERVICE_OUTAGE],
    )
    assert to_prompt_context(degraded) == {
        "platform_outage": False,
        "gps_degraded": False,
        "service_outage_reported": True,
        "mock_provider_active": False,
    }


def test_mock_provider_prevents_short_circuit():
    blocked = GuardrailResult(blocked=True, reason=GuardrailReason.NETWORK_LOSS, quality_flags=[])
    assert should_short_circuit(blocked) is True

    blocked_with_mock = GuardrailResult(
        blocked=True,
        reason=GuardrailReason.NETWORK_LOSS,
        quality_flags=[QualityFlag.NETWORK_OFFLINE, QualityFlag.MOCK_PROVIDER_ACTIVE],
    )
    assert should_short_circuit(blocked_with_mock) is False
    assert to_prompt_context(blocked_with_mock)["mock_provider_active"] is True

    assert should_short_circuit(GuardrailResult(blocked=False)) is False


def test_build_guardrail_assessment_shape():
    result = GuardrailResult(blocked=True, reason=GuardrailReason.APP_CRASH, quality_flags=[QualityFlag.APP_CRASHED])
    assessment = build_guardrail_assessment(result)
    assert assessment["category"] == "insufficient_evidence"
    assert assessment["priority_tier"] == 2
    assert assessment["priority_label"] == "P2"
    assert assessment["priority_score"] == 10
    assert assessment["confidence"] == 0.0
    assert assessment["reason_codes"] == ["guardrail_app_crash", "app_crashed"]
    assert "APP_CRASH" in assessment["forensic_brief"]


def test_cap_priority_does_not_mutate_input():
    blocked = GuardrailResult(blocked=True, reason=GuardrailReason.NETWORK_LOSS)
    original = {"category": "ERR-05", "priority_tier": 0, "priority_label": "P0", "reason_codes": ["a"]}
    capped = cap_priority_for_guardrail(original, blocked)
    assert capped["priority_tier"] == 1
    assert capped["priority_label"] == "P1"
    assert capped["reason_codes"] == ["a", "priority_capped_by_guardrail"]
    assert original == {"category": "ERR-05", "priority_tier": 0, "priority_label": "P0", "reason_codes": ["a"]}

    # Not blocked, or not P0: unchanged.
    assert cap_priority_for_guardrail(original, GuardrailResult(blocked=False))["priority_tier"] == 0
    p1 = {**original, "priority_tier": 1, "priority_label": "P1"}
    assert cap_priority_for_guardrail(p1, blocked)["reason_codes"] == ["a"]


# ---------------------------------------------------------------------------
# Worker wiring
# ---------------------------------------------------------------------------
class FakeService:
    """Minimal in-memory CaseService stand-in; no database."""

    def __init__(self) -> None:
        self.settings = SimpleNamespace(
            app_env="test",
            openrouter_api_key=None,
            fraud_classifier_enabled=False,
        )
        self._telemetry_points: list[dict[str, Any]] = []
        self._trips: dict[str, Any] = {}
        self._assignments: dict[str, Any] = {}
        self._cases: dict[str, Any] = {}
        self._model_assessments: dict[str, Any] = {}
        self._guardrails: dict[str, Any] = {}
        self._analysts: dict[str, Any] = {}

    def is_driver_suspended(self, driver_id: str) -> bool:
        return False

    def _get_db_connection(self) -> None:
        return None


_ERR05_P0 = {
    "category": "ERR-05",
    "priority_tier": 0,
    "priority_label": "P0",
    "priority_score": 98,
    "confidence": 0.98,
    "reason_codes": ["mock_location_api_detected"],
    "forensic_brief": "mock",
    "maneuvers": [],
    "maneuver_narrative": "",
}
_NO_VIOLATION = {
    **_ERR05_P0,
    "category": "no_violation",
    "priority_tier": 2,
    "priority_label": "P2",
    "priority_score": 15,
    "reason_codes": ["telemetry_nominal"],
}


@pytest.fixture
def agent_calls(monkeypatch):
    """Stub the agent and route analytics; record agent invocations."""
    calls: list[dict[str, Any]] = []
    response: dict[str, Any] = {"value": _NO_VIOLATION}

    async def fake_assess(self, event_data, use_llm=False):
        calls.append(event_data)
        return dict(response["value"])

    monkeypatch.setattr(worker.JevAssessmentAgent, "assess", fake_assess)
    monkeypatch.setattr(worker, "detect_telemetry_missingness", lambda points: [])
    monkeypatch.setattr(worker, "build_trip_timeline_milestones", lambda **kwargs: [])
    monkeypatch.delenv("TELEMETRY_GUARDRAIL_ENABLED", raising=False)
    return SimpleNamespace(calls=calls, response=response)


def _run(event: dict[str, Any], service: FakeService) -> dict[str, Any]:
    return asyncio.run(worker.process_telemetry_event(event, case_service=service))


def test_worker_blocked_trip_short_circuits_agent(agent_calls):
    service = FakeService()
    event = {"case_id": "case-blocked", "points": [_flat_point(app_state="crashed")]}

    result = _run(event, service)

    assert agent_calls.calls == []
    assessment = result["assessment"]
    assert assessment["category"] == "insufficient_evidence"
    assert assessment["priority_label"] == "P2"
    assert assessment["guardrail"]["reason"] == "APP_CRASH"
    assert result["case_id"] == "case-blocked"
    assert service._cases["case-blocked"]["suspected_category"] == "insufficient_evidence"
    assert service._model_assessments["case-blocked"]["guardrail"]["blocked"] is True
    assert service._guardrails["case-blocked"]["reason"] == "APP_CRASH"


def test_worker_mock_and_offline_is_err05_capped_to_p1(agent_calls):
    agent_calls.response["value"] = _ERR05_P0
    service = FakeService()
    event = {
        "case_id": "case-mock",
        "points": [_flat_point(network_state="offline", mock_location_reported=True)],
    }

    result = _run(event, service)

    assert len(agent_calls.calls) == 1
    assessment = result["assessment"]
    assert assessment["category"] == "ERR-05"
    assert assessment["priority_tier"] == 1
    assert assessment["priority_label"] == "P1"
    assert "priority_capped_by_guardrail" in assessment["reason_codes"]
    assert assessment["guardrail"]["reason"] == "NETWORK_LOSS"
    assert "mock_provider_active" in assessment["guardrail"]["quality_flags"]
    assert service._cases["case-mock"]["priority_tier"] == 1


def test_worker_clean_flat_frame_is_not_blocked(agent_calls):
    service = FakeService()
    event = {"points": [_flat_point(), _flat_point(t=15, latitude=21.03)]}

    result = _run(event, service)

    assert len(agent_calls.calls) == 1
    assert result["assessment"]["category"] == "no_violation"
    assert result["assessment"]["guardrail"] == {"blocked": False, "reason": None, "quality_flags": []}
    assert result["case_id"] is None


def test_worker_guardrail_disabled_by_env(agent_calls, monkeypatch):
    monkeypatch.setenv("TELEMETRY_GUARDRAIL_ENABLED", "false")
    service = FakeService()
    event = {"case_id": "case-off", "points": [_flat_point(app_state="crashed")]}

    result = _run(event, service)

    assert len(agent_calls.calls) == 1
    assert result["assessment"]["guardrail"] is None
    assert service._model_assessments["case-off"]["guardrail"] is None
