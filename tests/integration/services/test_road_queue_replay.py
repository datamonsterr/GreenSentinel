"""Queue replay invariants for telemetry evidence and classification."""

from unittest.mock import patch
from uuid import uuid4

import pytest

from src.config import Settings
from src.services.case_service import CaseService
from src.services.telemetry_queue_worker import process_telemetry_event


def _service() -> CaseService:
    return CaseService(Settings(app_env="test", database_url="", _env_file=None))


def _event() -> dict:
    return {
        "event_id": str(uuid4()),
        "trip_id": str(uuid4()),
        "assignment_id": str(uuid4()),
        "driver_id": str(uuid4()),
        "sequence": 7,
        "points": [{"latitude": 21.0285, "longitude": 105.8542, "speed_mps": 8.5}],
    }


@pytest.mark.asyncio
async def test_exact_queue_replay_returns_prior_result_without_reclassification():
    service = _service()
    event = _event()

    with patch("src.services.telemetry_queue_worker.JevAssessmentAgent.assess", wraps=None) as assess:
        assess.return_value = {
            "category": "no_violation",
            "priority_tier": 2,
            "priority_label": "P2",
            "priority_score": 95,
            "confidence": 0.95,
            "reason_codes": [],
            "forensic_brief": "",
        }
        first = await process_telemetry_event(event, case_service=service)
        replay = await process_telemetry_event(dict(event), case_service=service)

    assert replay == first
    assert assess.call_count == 1


@pytest.mark.asyncio
async def test_changed_queue_payload_with_same_identity_is_rejected():
    service = _service()
    event = _event()
    event.pop("event_id")

    with patch("src.services.telemetry_queue_worker.JevAssessmentAgent.assess") as assess:
        assess.return_value = {
            "category": "no_violation",
            "priority_tier": 2,
            "priority_label": "P2",
            "priority_score": 95,
            "confidence": 0.95,
            "reason_codes": [],
            "forensic_brief": "",
        }
        await process_telemetry_event(event, case_service=service)
        changed = dict(event, points=[{"latitude": 21.0285, "longitude": 105.8542, "speed_mps": 9.5}])

        with pytest.raises(ValueError, match="different payload"):
            await process_telemetry_event(changed, case_service=service)

    assert assess.call_count == 1


@pytest.mark.asyncio
async def test_failed_processing_does_not_poison_corrected_retry():
    service = _service()
    event = _event()
    assessment = {
        "category": "no_violation",
        "priority_tier": 2,
        "priority_label": "P2",
        "priority_score": 95,
        "confidence": 0.95,
        "reason_codes": [],
        "forensic_brief": "",
    }

    with patch(
        "src.services.telemetry_queue_worker.JevAssessmentAgent.assess",
        side_effect=[RuntimeError("transient classifier failure"), assessment],
    ) as assess:
        with pytest.raises(RuntimeError, match="transient classifier failure"):
            await process_telemetry_event(event, case_service=service)
        result = await process_telemetry_event(event, case_service=service)

    assert result["status"] == "processed"
    assert assess.call_count == 2
