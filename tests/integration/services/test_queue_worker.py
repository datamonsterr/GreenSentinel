from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from scripts.simulate_trip_stream import (
    build_trip_lifecycle_frames,
    simulate_single_trip,
)
from src.models.classifier import ClassifierResult
from src.models.schemas import AdjudicationRequest
from src.services.case_service import get_case_service
from src.services.telemetry_queue_worker import (
    JevAssessmentAgent,
    process_telemetry_event,
)

pytestmark = pytest.mark.docker

_DRIVER_IDS = [f"018f2f4e-3000-7000-8000-{i:012d}" for i in range(1, 21)]
_VEHICLE_IDS = [f"018f2f4e-4000-7000-8000-{i:012d}" for i in range(1, 21)]
_PASSENGER_IDS = [f"018f2f4e-2000-7000-8000-{i:012d}" for i in range(1, 11)]
_ANALYST_IDS = [f"018f2f4e-1000-7000-8000-{i:012d}" for i in range(1, 11)]
_HANOI = (21.0285, 105.8542)


class FakeClassifier:
    """Deterministic classifier stand-in for queue worker integration tests."""

    def __init__(self, category: str = "ERR-02", confidence: float = 0.92) -> None:
        self.category = category
        self.confidence = confidence
        self.model_version = "r3d-2026.10.18"

    def predict(self, bundle: dict[str, Any]) -> ClassifierResult:
        probs = {
            "no_violation": 0.0,
            "ERR-01": 0.0,
            "ERR-02": 0.0,
            "ERR-03": 0.0,
            "ERR-04": 0.0,
            "ERR-05": 0.0,
            "insufficient_evidence": 0.0,
        }
        probs[self.category] = self.confidence
        return ClassifierResult(
            category=self.category,
            confidence=self.confidence,
            probabilities=probs,
            guardrail_blocked=False,
            guardrail_reason=None,
            model_version=self.model_version,
            artifact_sha="test1234",
            feature_ms=1.0,
            inference_ms=2.0,
            assessment_source="r3d_classifier",
        )


@pytest.fixture
def case_service(monkeypatch):
    service = get_case_service()
    # Pin tests to the JevAssessmentAgent rule path; classifier path has its own tests.
    monkeypatch.setattr(service.settings, "fraud_classifier_enabled", False)
    return service


@pytest.mark.asyncio
async def test_jev_agent_assessment_matrix():
    """Test Jev Assessment Agent classification across fraud categories."""
    agent = JevAssessmentAgent()

    # 1. Driver Stall Cancel -> ERR-02 (P1, 0.92)
    stall_event = {
        "scenario": "driver_stall_cancel",
        "stationary_duration_s": 210,
        "points": [{"speed_mps": 0.0}],
        "cancellation_reason": "driver_stalled_too_long",
    }
    r_stall = await agent.assess(stall_event)
    assert r_stall["category"] == "ERR-02"
    assert r_stall["priority_tier"] == 1
    assert r_stall["priority_label"] == "P1"
    assert r_stall["confidence"] == 0.92
    assert "stationary_duration_over_180s" in r_stall["reason_codes"]

    # 2. GPS Spoofing -> ERR-05 (P0, 0.98)
    gps_event = {
        "scenario": "gps_spoofing",
        "points": [{"mock_location_reported": True, "speed_mps": 140.0}],
    }
    r_gps = await agent.assess(gps_event)
    assert r_gps["category"] == "ERR-05"
    assert r_gps["priority_tier"] == 0
    assert r_gps["priority_label"] == "P0"
    assert r_gps["confidence"] == 0.98
    assert "mock_location_api_detected" in r_gps["reason_codes"]

    # 3. Route Deviation -> ERR-03 (P1, 0.88) driven by observable evidence (diverging from pickup)
    route_event = {
        "pickup": [105.8542, 21.0350],
        "dropoff": [105.8542, 21.0500],
        "points": [
            {"latitude": 21.0250, "longitude": 105.8542, "speed_mps": 10.0, "occurred_at": "2026-10-01T00:00:00Z"},
            {"latitude": 21.0200, "longitude": 105.8542, "speed_mps": 10.0, "occurred_at": "2026-10-01T00:00:30Z"},
            {"latitude": 21.0150, "longitude": 105.8542, "speed_mps": 10.0, "occurred_at": "2026-10-01T00:01:00Z"},
        ],
    }
    r_route = await agent.assess(route_event)
    assert r_route["category"] == "ERR-03"
    assert r_route["priority_tier"] == 1
    assert r_route["confidence"] == 0.88

    # 4. Phantom booking label alone without evidence -> no_violation (labels stripped, evidence only)
    phantom_event = {
        "scenario": "phantom_booking",
        "points": [{"speed_mps": 5.0}],
    }
    r_phantom = await agent.assess(phantom_event)
    assert r_phantom["category"] == "no_violation"
    assert r_phantom["priority_tier"] == 2
    assert r_phantom["confidence"] == 0.95

    # 5. Normal Trip -> no_violation (P2, 0.95)
    normal_event = {
        "scenario": "normal_trip",
        "points": [{"speed_mps": 8.5}],
    }
    r_normal = await agent.assess(normal_event)
    assert r_normal["category"] == "no_violation"
    assert r_normal["priority_tier"] == 2
    assert r_normal["confidence"] == 0.95


def test_simulate_trip_stream_lifecycle():
    """Test generation of trip lifecycle frames: coming -> picked_up -> complete/cancelled."""
    trip_id = str(uuid4())
    asgn_id = str(uuid4())
    driver_id = _DRIVER_IDS[0]

    # Test stall cancellation lifecycle
    frames_stall = build_trip_lifecycle_frames(trip_id, asgn_id, driver_id, "driver_stall_cancel", _HANOI, _HANOI)
    assert len(frames_stall) == 3
    assert frames_stall[0]["lifecycle_state"] == "coming"
    assert frames_stall[1]["lifecycle_state"] == "picked_up"
    assert frames_stall[2]["lifecycle_state"] == "cancelled"
    assert frames_stall[2]["stationary_duration_s"] >= 180

    # Test normal trip lifecycle
    frames_norm = build_trip_lifecycle_frames(trip_id, asgn_id, driver_id, "normal_trip", _HANOI, _HANOI)
    assert len(frames_norm) == 3
    assert frames_norm[0]["lifecycle_state"] == "coming"
    assert frames_norm[1]["lifecycle_state"] == "on_trip"
    assert frames_norm[2]["lifecycle_state"] == "complete"


def test_simulation_driver_suspension_rejection():
    """Test that simulate_single_trip rejects trips when driver is suspended."""
    driver_id = _DRIVER_IDS[2]

    # Patch DB suspension check - simulate suspended
    with patch("scripts.simulate_trip_stream.is_driver_suspended_db", return_value=True):
        result = simulate_single_trip(
            driver_id=driver_id,
            vehicle_id=_VEHICLE_IDS[0],
            passenger_id=_PASSENGER_IDS[0],
            scenario="normal_trip",
            analyst_id=_ANALYST_IDS[0],
            loc_pickup=_HANOI,
            loc_dropoff=_HANOI,
            redis_client=None,
        )
    assert result["status"] == "rejected"
    assert result["reason"] == "driver_suspended"

    # Patch as active - should attempt simulation
    mock_redis = MagicMock()
    with (
        patch("scripts.simulate_trip_stream.is_driver_suspended_db", return_value=False),
        patch("scripts.simulate_trip_stream.insert_trip_to_db", return_value=str(uuid4())),
    ):
        result_active = simulate_single_trip(
            driver_id=driver_id,
            vehicle_id=_VEHICLE_IDS[0],
            passenger_id=_PASSENGER_IDS[0],
            scenario="normal_trip",
            analyst_id=_ANALYST_IDS[0],
            loc_pickup=_HANOI,
            loc_dropoff=_HANOI,
            redis_client=mock_redis,
        )
    assert result_active["status"] == "simulated"
    assert mock_redis.xadd.call_count == 3


@pytest.mark.asyncio
async def test_process_telemetry_event_and_db_write(case_service):
    """Test processing event, writing to PostgreSQL / CaseService, and verifying records."""
    trip_id = str(uuid4())
    asgn_id = str(uuid4())
    case_id = str(uuid4())
    driver_id = _DRIVER_IDS[3]
    case_service.set_driver_status(driver_id, "active")

    event_data = {
        "trip_id": trip_id,
        "assignment_id": asgn_id,
        "case_id": case_id,
        "driver_id": driver_id,
        "scenario": "driver_stall_cancel",
        "lifecycle_state": "cancelled",
        "stationary_duration_s": 210,
        "cancellation_reason": "driver_stalled_too_long",
        "points": [
            {
                "latitude": 21.0285,
                "occurred_at": "2026-09-27T08:00:00Z",
                "sequence": 0,
                "longitude": 105.8542,
                "speed_mps": 0.0,
                "bearing_deg": 0.0,
                "accuracy_m": 4.0,
                "app_state": "foreground",
                "network_state": "online",
                "gps_state": "valid",
                "mock_location_reported": False,
            }
        ],
    }

    res = await process_telemetry_event(
        event_data,
        case_service=case_service,
        classifier=FakeClassifier(category="ERR-02", confidence=0.92),
    )
    assert res["status"] == "processed"
    assert res["assessment"]["category"] == "ERR-02"
    assert res["assessment"]["confidence"] == 0.92

    # Verify synced in CaseService
    assert trip_id in case_service._trips
    assert asgn_id in case_service._assignments
    assert res["case_id"] in case_service._cases
    assert case_service._cases[res["case_id"]]["suspected_category"] == "ERR-02"


@pytest.mark.asyncio
async def test_process_telemetry_event_preserves_unknown_accuracy(case_service):
    """Archival GPS without an accuracy estimate must remain explicitly unknown."""
    assignment_id = str(uuid4())
    event_data = {
        "trip_id": str(uuid4()),
        "assignment_id": assignment_id,
        "driver_id": _DRIVER_IDS[5],
        "scenario": "normal_trip",
        "points": [
            {
                "latitude": 21.0285,
                "occurred_at": "2026-09-27T08:00:00Z",
                "sequence": 0,
                "longitude": 105.8542,
                "accuracy_m": None,
                "app_state": "unknown",
                "network_state": "unknown",
                "gps_state": "unknown",
            }
        ],
    }

    await process_telemetry_event(event_data, case_service=case_service)
    observed = [p for p in case_service._telemetry_points if p["assignment_id"] == assignment_id]
    assert len(observed) == 1
    assert observed[0]["accuracy_m"] is None


@pytest.mark.asyncio
async def test_process_telemetry_event_blocks_suspended_driver(case_service):
    """Test that telemetry worker raises 403 when processing telemetry for a suspended driver."""
    driver_id = _DRIVER_IDS[4]
    case_service.set_driver_status(driver_id, "suspended")

    event_data = {
        "trip_id": str(uuid4()),
        "driver_id": driver_id,
        "scenario": "normal_trip",
    }

    with pytest.raises(HTTPException) as exc:
        await process_telemetry_event(event_data, case_service=case_service)
    assert exc.value.status_code == 403
    assert f"Driver {driver_id} is currently suspended" in exc.value.detail

    case_service.set_driver_status(driver_id, "active")


@pytest.mark.asyncio
async def _ingest_and_get_analyst(
    case_service,
    driver_id: str,
    event: dict,
    classifier: Any | None = None,
) -> tuple[dict, str]:
    case_service.set_driver_status(driver_id, "active")
    proc = await process_telemetry_event(
        {
            "trip_id": str(uuid4()),
            "assignment_id": str(uuid4()),
            "case_id": str(uuid4()),
            "driver_id": driver_id,
            **event,
        },
        case_service=case_service,
        classifier=classifier,
    )
    detail = await case_service.get_case_detail(proc["case_id"])
    return proc, detail.case.assigned_analyst_id or _ANALYST_IDS[0]


@pytest.mark.asyncio
async def test_guardrail_is_advisory_and_does_not_block_adjudication(case_service):
    """A technical-fault case has advisory guardrail: AGREE and DISAGREE are not blocked."""
    proc, analyst = await _ingest_and_get_analyst(
        case_service,
        _DRIVER_IDS[7],
        {
            "scenario": "driver_stall_cancel",
            "lifecycle_state": "cancelled",
            "stationary_duration_s": 210,
            "points": [
                {
                    "latitude": 21.0285,
                    "occurred_at": "2026-09-27T08:00:00Z",
                    "sequence": 0,
                    "longitude": 105.8542,
                    "speed_mps": 0.0,
                    "app_state": "crashed",
                    "network_state": "online",
                    "gps_state": "valid",
                }
            ],
        },
    )
    assert proc["assessment"]["category"] == "insufficient_evidence"
    assert proc["assessment"]["guardrail"]["reason"] == "APP_CRASH"

    detail = await case_service.get_case_detail(proc["case_id"])
    assert detail.guardrails["blocking_guardrail"] is True
    assert "app_crash_incident" in detail.guardrails["active_guardrails"]
    assert detail.guardrails.get("suggested_outcome") == "Disagree (System Error)"

    dismissed = await case_service.adjudicate_case(
        proc["case_id"],
        AdjudicationRequest(
            outcome="DISAGREE",
            analyst_id=analyst,
            rationale="Technical dropout, not fraud",
            expected_case_version=1,
        ),
    )
    assert dismissed.outcome == "DISAGREE"


@pytest.mark.asyncio
async def test_mock_location_case_allows_agree(case_service):
    """Mock location is ERR-05 evidence; without a technical fault it allows AGREE."""
    proc, analyst = await _ingest_and_get_analyst(
        case_service,
        _DRIVER_IDS[8],
        {
            "scenario": "gps_spoofing",
            "lifecycle_state": "cancelled",
            "points": [
                {
                    "latitude": 21.0285,
                    "occurred_at": "2026-09-27T08:00:00Z",
                    "sequence": 0,
                    "longitude": 105.8542,
                    "speed_mps": 5.0,
                    "app_state": "foreground",
                    "network_state": "online",
                    "gps_state": "mock_reported",
                    "mock_location_reported": True,
                }
            ],
        },
        classifier=FakeClassifier(category="ERR-05", confidence=0.98),
    )
    assert proc["assessment"]["category"] == "ERR-05"
    assert proc["assessment"]["guardrail"]["blocked"] is False
    assert "mock_provider_active" in proc["assessment"]["guardrail"]["quality_flags"]

    detail = await case_service.get_case_detail(proc["case_id"])
    assert detail.guardrails["blocking_guardrail"] is False

    approved = await case_service.adjudicate_case(
        proc["case_id"],
        AdjudicationRequest(
            outcome="AGREE",
            analyst_id=analyst,
            rationale="Mock location provider confirmed on driver device",
            expected_case_version=1,
        ),
    )
    assert approved.outcome == "AGREE"
