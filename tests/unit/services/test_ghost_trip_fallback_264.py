"""Ghost-trip lifecycle fallback rule tests (issue #264).

TDD contract:
- completed AND known never-arrived (arrived_at/started_at keys present-None)
  AND passenger denial -> ERR-04 candidate for P1 analyst review (advisory only).
- Fail closed: unknown arrival (keys absent), arrived trips, missing denial,
  or cancelled lifecycle must NOT yield ERR-04 via this rule.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.config import Settings
from src.services.jev_assessment_service import JevAssessmentInput, JevAssessmentService


def _offline_service() -> JevAssessmentService:
    return JevAssessmentService(settings=Settings(project_jev_api_key="", openrouter_api_key=""))


_POINT_MOVE = {
    "latitude": 21.0285,
    "longitude": 105.8542,
    "speed_mps": 8.5,
    "app_state": "foreground",
    "network_state": "online",
    "gps_state": "valid",
    "mock_location_reported": False,
}


def _trip(lifecycle: str = "completed", **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"lifecycle_state": lifecycle, "status": lifecycle}
    base.update(extra)
    return base


def _telem(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"points": [_POINT_MOVE], "max_speed_kmh": 30.6}
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# Target behavior: ghost fallback fires (RED before implementation)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ghost_keyword_denial_fires_err04() -> None:
    """Completed + never arrived + keyword denial -> ERR-04 P1 advisory."""
    res = await _offline_service().assess(
        JevAssessmentInput(
            telemetry=_telem(),
            trip_data=_trip(arrived_at=None, started_at=None),
            customer_reports="Chuyến này là cuốc ảo, em chưa hề lên xe",
        )
    )
    assert res.category == "ERR-04"
    assert res.priority == "P1"
    assert res.priority_tier == 1
    assert 0.8 <= res.confidence <= 0.95
    assert any("ghost" in c or "pickup" in c or "denial" in c for c in res.reason_codes)
    assert (res.probabilities.get("ERR-04") or 0.0) >= 0.5
    assert res.model_used == "jev_calibrated_heuristic"


@pytest.mark.asyncio
async def test_ghost_paraphrase_denial_fires_err04() -> None:
    """Paraphrase denial with no keyword anywhere in inputs still fires."""
    res = await _offline_service().assess(
        JevAssessmentInput(
            telemetry=_telem(),
            trip_data=_trip(arrived_at=None, started_at=None),
            customer_reports="Em chưa hề bước lên xe mà chuyến đã xong",
            trip_conversation=[{"role": "customer", "text": "Tài xế bấm hoàn thành khi em còn ở nhà"}],
        )
    )
    assert "ảo" not in (res.forensic_brief or "")
    assert res.category == "ERR-04"
    assert res.priority_tier == 1


@pytest.mark.asyncio
async def test_ghost_english_denial_fires_err04() -> None:
    res = await _offline_service().assess(
        JevAssessmentInput(
            telemetry=_telem(),
            trip_data=_trip(arrived_at=None, started_at=None),
            customer_reports="Never met the driver, yet I got charged",
        )
    )
    assert res.category == "ERR-04"


def test_bundle_mapping_carries_arrival_evidence() -> None:
    """bundle_to_input passes arrival presence: None for ghost, timestamps for honest."""
    from scripts.benchmark.run_10k import bundle_to_input

    rows = [
        json.loads(line)
        for line in Path("data/benchmark-10k/v1/sample_100.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ghost = next(r for r in rows if r.get("label") == "ERR-04")
    honest = next(
        r for r in rows if r.get("label") == "no_violation" and (r.get("trip") or {}).get("status") == "completed"
    )
    ghost_inp, _, _ = bundle_to_input(ghost)
    honest_inp, _, _ = bundle_to_input(honest)
    assert ghost_inp.trip_data.get("lifecycle_state") == "completed"
    assert "arrived_at" in ghost_inp.trip_data and ghost_inp.trip_data.get("arrived_at") is None
    assert "started_at" in ghost_inp.trip_data and ghost_inp.trip_data.get("started_at") is None
    assert honest_inp.trip_data.get("arrived_at")
    assert honest_inp.trip_data.get("started_at")


# ---------------------------------------------------------------------------
# Guards: precision + fail-closed (must hold before and after)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_honest_completed_with_arrival_stays_no_violation() -> None:
    """Arrival evidence excludes honest completed trips even with a complaint."""
    res = await _offline_service().assess(
        JevAssessmentInput(
            telemetry=_telem(),
            trip_data=_trip(arrived_at="2026-10-09T18:47:21+00:00", started_at="2026-10-09T18:47:21+00:00"),
            customer_reports="Anh đậu đâu vậy, em không thấy xe",
        )
    )
    assert res.category == "no_violation"


@pytest.mark.asyncio
async def test_unknown_arrival_fails_closed() -> None:
    """Missing arrival keys = unknown -> never fire, even with strong denial."""
    res = await _offline_service().assess(
        JevAssessmentInput(
            telemetry=_telem(),
            trip_data=_trip(),
            customer_reports="Chuyến này là cuốc ảo, em chưa hề lên xe",
        )
    )
    assert res.category == "no_violation"


@pytest.mark.asyncio
async def test_cancelled_lifecycle_no_err04_from_fallback() -> None:
    res = await _offline_service().assess(
        JevAssessmentInput(
            telemetry=_telem(),
            trip_data=_trip("cancelled", cancellation_actor="passenger", cancellation_reason="changed mind"),
            customer_reports="Chuyến này là cuốc ảo, em chưa hề lên xe",
        )
    )
    assert res.category != "ERR-04"


@pytest.mark.asyncio
async def test_phantom_label_without_evidence_no_err04() -> None:
    res = await _offline_service().assess(
        JevAssessmentInput(
            telemetry=_telem(),
            trip_data=_trip(),
            driver_analytics={"scenario": "phantom_booking"},
        )
    )
    assert res.category != "ERR-04"


@pytest.mark.asyncio
async def test_mock_gps_with_arrival_stays_err05() -> None:
    """ERR-05 keeps precedence when mock evidence is present."""
    res = await _offline_service().assess(
        JevAssessmentInput(
            telemetry={"points": [{"mock_location_reported": True, "speed_mps": 5.0}], "max_speed_kmh": 18.0},
            trip_data=_trip(arrived_at="2026-10-16T17:34:04+00:00", started_at="2026-10-16T17:34:04+00:00"),
            customer_reports="Em chưa hề bước lên xe mà chuyến đã xong",
        )
    )
    assert res.category == "ERR-05"


@pytest.mark.asyncio
async def test_never_arrived_without_denial_stays_no_violation() -> None:
    """Denial is required: silent never-arrived completion is not a ghost verdict."""
    res = await _offline_service().assess(
        JevAssessmentInput(
            telemetry=_telem(),
            trip_data=_trip(arrived_at=None, started_at=None),
        )
    )
    assert res.category == "no_violation"
