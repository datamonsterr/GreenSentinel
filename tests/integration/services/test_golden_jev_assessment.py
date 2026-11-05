"""Golden Dataset Evaluation Test for Jev Anomaly Scoring (DoD 3).

Spawns test cases from golden data containing ONLY raw input without error types,
passes them through the TypeSafe Jev assessment layer, and validates predicted output.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest

from src.services.case_service import get_case_service
from src.services.jev_assessment_service import JevAssessmentInput, JevAssessmentService
from src.services.telemetry_queue_worker import process_telemetry_event
from tests.support.repo import REPO_ROOT

GOLDEN_SET_PATH = REPO_ROOT / "eval" / "golden_set" / "forensic_mock_cases.json"


@pytest.fixture
def golden_cases() -> list[dict[str, Any]]:
    assert GOLDEN_SET_PATH.exists(), f"Golden set missing at {GOLDEN_SET_PATH}"
    cases = json.loads(GOLDEN_SET_PATH.read_text(encoding="utf-8"))
    assert len(cases) >= 3, "Golden set must contain at least 3 cases"
    return cases


@pytest.mark.asyncio
async def test_golden_data_evaluation_through_jev(golden_cases):
    """DoD 3: Feed golden cases without error type to Jev and verify predicted error type and confidence."""
    service = JevAssessmentService()

    for idx, item in enumerate(golden_cases):
        raw_input = item["input"]
        expected_category = item["expected_category"]

        # Invariant check: input must NEVER contain error type or category labels
        assert "expected_category" not in raw_input
        assert "category" not in raw_input
        assert "violation_code" not in raw_input

        # Map raw input into JevAssessmentInput
        stationary_s = int(raw_input.get("stationary_duration_s", 0))
        is_mock = bool(raw_input.get("mock_location_reported", False))
        lifecycle = str(raw_input.get("lifecycle_state", "completed"))
        cancellation_actor = str(raw_input.get("cancellation_actor", "none"))

        points = []
        if is_mock:
            for _ in range(2):
                points.append(
                    {
                        "latitude": 21.0285,
                        "longitude": 105.8542,
                        "speed_mps": 35.0,
                        "mock_location_reported": True,
                        "gps_state": "mock_reported",
                    }
                )
        elif stationary_s > 0:
            for _ in range(3):
                points.append(
                    {
                        "latitude": 21.0285,
                        "longitude": 105.8542,
                        "speed_mps": 0.0,
                        "mock_location_reported": False,
                    }
                )
        elif raw_input.get("telemetry_points", 0) > 0:
            for _ in range(int(raw_input.get("telemetry_points", 5))):
                points.append(
                    {
                        "latitude": 21.0285,
                        "longitude": 105.8542,
                        "speed_mps": 10.0,
                        "mock_location_reported": False,
                    }
                )

        jev_input = JevAssessmentInput(
            telemetry={
                "telemetry_points": raw_input.get("telemetry_points", len(points)),
                "stationary_duration_s": stationary_s,
                "mock_location_reported": is_mock,
                "points": points,
                "platform_outage": raw_input.get("platform_outage", False),
                "gps_degraded": raw_input.get("gps_degraded", False),
            },
            trip_data={
                "case_id": raw_input.get("case_id"),
                "lifecycle_state": lifecycle,
                "cancellation_actor": cancellation_actor,
            },
        )

        result = await service.assess(jev_input)

        assert result.category == expected_category, (
            f"Case {idx} ({raw_input.get('case_id')}): expected {expected_category}, got {result.category}"
        )
        assert result.priority in ("P0", "P1", "P2"), f"Invalid priority: {result.priority}"
        if expected_category != "insufficient_evidence":
            assert result.confidence >= 0.80, f"Confidence too low: {result.confidence}"


@pytest.mark.asyncio
async def test_spawn_case_from_golden_input_and_verify_intake():
    """DoD 3: Spawn a case with input without error type through queue worker and verify created case in service."""
    case_service = get_case_service()

    # Input has NO error type or category
    unlabeled_event = {
        "event_id": str(uuid4()),
        "trip_id": str(uuid4()),
        "assignment_id": str(uuid4()),
        "case_id": str(uuid4()),
        "driver_id": "018f2f4e-3000-7000-8000-000000000001",
        "stationary_duration_s": 250,
        "lifecycle_state": "cancelled",
        "cancellation_actor": "passenger",
        "cancellation_reason": "Tài xế cố tình đứng yên một chỗ câu giờ ép khách hủy",
        "points": [
            {"latitude": 21.0285, "longitude": 105.8542, "speed_mps": 0.0, "mock_location_reported": False},
            {"latitude": 21.0285, "longitude": 105.8542, "speed_mps": 0.0, "mock_location_reported": False},
        ],
        "pickup": [105.8542, 21.0285],
        "dropoff": [105.8600, 21.0350],
    }

    # Verify input has no category or error type
    assert "category" not in unlabeled_event
    assert "error_type" not in unlabeled_event
    assert "violation_code" not in unlabeled_event

    processed = await process_telemetry_event(unlabeled_event, case_service=case_service)

    assert processed["category"] == "ERR-02"
    assert processed["confidence"] >= 0.85
    assert processed["priority_label"] in ("P0", "P1")
    assert "stationary_duration" in processed["forensic_brief"].lower() or "dừng" in processed["forensic_brief"].lower()
