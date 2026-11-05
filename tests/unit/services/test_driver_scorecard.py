"""Unit contracts for the live driver scorecard (issue #100).

Covers pure metric math (ratios, risk clamp, 90-day window constant),
verdict mapping, and the CaseService-backed in-memory fallback used when
the database handle is unavailable on the test stack.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from src.config import Settings
from src.services import driver_service
from src.services.case_service import CaseService, get_case_service

TEST_ORG = "018f2f4e-0000-7000-8000-000000000001"


def test_score_window_is_90_days():
    assert driver_service.SCORE_WINDOW_DAYS == 90


@pytest.mark.parametrize(
    ("trips", "cases", "penalized", "violation", "fined", "risk"),
    [
        (100, 4, 2, 4.0, 50.0, 99),  # 4*15+2*25=110 -> clamp 99
        (200, 1, 0, 0.5, 0.0, 15),  # 1*15+0=15
        (50, 0, 0, 0.0, 0.0, 10),  # floor 10
        (0, 3, 1, 300.0, 33.3, 70),  # zero trips -> max(trips,1); 3*15+25=70
        (0, 0, 0, 0.0, 0.0, 10),  # zero cases -> fined uses max(cases,1)
    ],
)
def test_compute_scorecard_metrics_math(trips, cases, penalized, violation, fined, risk):
    metrics = driver_service.compute_scorecard_metrics(trips, cases, penalized)
    assert metrics["violation_ratio_90d"] == violation
    assert metrics["fined_ratio"] == fined
    assert metrics["repeat_offense_risk_score"] == risk
    assert metrics["benchmark_violation_ratio"] == 5.0


@pytest.mark.parametrize(
    ("outcome", "status", "action"),
    [
        ("dismiss", "exonerated", "Miễn trừ xử phạt (Exonerated)"),
        ("approve", "exonerated", "Miễn trừ xử phạt (Exonerated)"),
        ("fine", "penalized", "Cảnh cáo & Khấu trừ vi phạm"),
        ("suspend", "penalized", "Cảnh cáo & Khấu trừ vi phạm"),
        ("reject", "penalized", "Cảnh cáo & Khấu trừ vi phạm"),
        ("warn", "warned", "Cảnh cáo kỹ thuật hệ thống"),
        (None, "warned", "Cảnh cáo kỹ thuật hệ thống"),
    ],
)
def test_incident_verdict_mapping(outcome, status, action):
    assert driver_service.map_incident_status(outcome) == status
    assert driver_service.map_action_taken(outcome) == action


def _seed_memory(driver_id="drv-score-1", org=TEST_ORG, n_trips=5, n_cases=2, penalized=1):
    cs = get_case_service()
    created = datetime.now(UTC) - timedelta(days=400)
    cs._drivers[driver_id] = {"id": driver_id, "created_at": created.isoformat(), "organization_id": org}
    for i in range(n_trips):
        asgn = f"asgn-{driver_id}-{i}"
        cs._assignments[asgn] = {"id": asgn, "driver_id": driver_id, "trip_id": f"trip-{driver_id}-{i}"}
        cs._trips[f"trip-{driver_id}-{i}"] = {"id": f"trip-{driver_id}-{i}"}
    for i in range(n_cases):
        case_id = f"case-{driver_id}-{i}"
        asgn = f"asgn-{driver_id}-{i}"
        cs._cases[case_id] = {
            "id": case_id,
            "assignment_id": asgn,
            "organization_id": org,
            "suspected_category": "ERR-01",
            "created_at": datetime.now(UTC).isoformat(),
        }
    for i in range(penalized):
        cs._adjudications.append({"case_id": f"case-{driver_id}-{i}", "outcome": "fine", "organization_id": org})
    return cs


@pytest.mark.asyncio
async def test_memory_scorecard_values():
    cs = _seed_memory()
    scorecard = await driver_service.get_driver_scorecard("drv-score-1", TEST_ORG, case_service=cs)
    assert scorecard.driver_id == "drv-score-1"
    assert scorecard.violation_ratio_90d == round(2 / 5 * 100, 1)
    assert scorecard.fined_ratio == 50.0
    assert scorecard.repeat_offense_risk_score == min(99, max(10, 2 * 15 + 1 * 25))
    assert scorecard.benchmark_violation_ratio == 5.0
    assert scorecard.tenure_months >= 12
    assert len(scorecard.past_incidents) == 2
    assert {i.status for i in scorecard.past_incidents} == {"penalized", "warned"}


@pytest.mark.asyncio
async def test_memory_scorecard_counts_legacy_reject_as_penalized():
    """Legacy 'reject' (adjudications_outcome_check) counts toward fined_ratio."""
    cs = _seed_memory(driver_id="drv-legacy", n_trips=4, n_cases=2, penalized=0)
    cs._adjudications.append({"case_id": "case-drv-legacy-0", "outcome": "reject", "organization_id": TEST_ORG})
    scorecard = await driver_service.get_driver_scorecard("drv-legacy", TEST_ORG, case_service=cs)
    assert scorecard.fined_ratio == 50.0
    assert {i.status for i in scorecard.past_incidents} == {"penalized", "warned"}


@pytest.mark.asyncio
async def test_memory_scorecard_prefers_measured_driver_trips():
    """Measured _memory_driver_trips rows win over the legacy assignment count."""
    from src.services.driver_service import _memory_driver_trips

    cs = _seed_memory(driver_id="drv-measured", n_trips=2, n_cases=2, penalized=0)
    _memory_driver_trips.clear()
    try:
        for i in range(60):
            tid = f"mtrip-drv-measured-{i}"
            _memory_driver_trips[tid] = {
                "trip_id": tid,
                "driver_id": "drv-measured",
                "started_at": datetime.now(UTC) - timedelta(days=i % 80 + 1),
            }
        scorecard = await driver_service.get_driver_scorecard("drv-measured", TEST_ORG, case_service=cs)
        assert scorecard.total_trips == 60
        assert scorecard.violation_ratio_90d == round(2 / 60 * 100, 1)
    finally:
        _memory_driver_trips.clear()


@pytest.mark.asyncio
async def test_memory_scorecard_empty_history():
    cs = _seed_memory(driver_id="drv-empty", n_trips=0, n_cases=0, penalized=0)
    scorecard = await driver_service.get_driver_scorecard("drv-empty", TEST_ORG, case_service=cs)
    assert scorecard.violation_ratio_90d == 0.0
    assert scorecard.fined_ratio == 0.0
    assert scorecard.repeat_offense_risk_score == 10
    assert scorecard.past_incidents == []


@pytest.mark.asyncio
async def test_memory_scorecard_unknown_driver_is_404():
    cs = _seed_memory()
    with pytest.raises(HTTPException) as exc:
        await driver_service.get_driver_scorecard("drv-missing", TEST_ORG, case_service=cs)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_scorecard_db_unavailable_is_503():
    prod = CaseService(settings=Settings(app_env="production", database_url=""))
    with pytest.raises(HTTPException) as exc:
        await driver_service.get_driver_scorecard("drv-score-1", TEST_ORG, case_service=prod)
    assert exc.value.status_code == 503


def test_load_case_timeline_mapping():
    from src.services.jev_precedent_service import _load_case_timeline

    rows = [
        {"event_type": "dispatched", "occurred_at": datetime(2026, 10, 1, 14, 20, 0)},
        {"event_type": "driver_arriving", "occurred_at": datetime(2026, 10, 1, 14, 22, 15)},
        {"event_type": "other_noise", "occurred_at": datetime(2026, 10, 1, 14, 25, 0)},
    ]

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query, params=None):
            assert "dispatched" in query and "trip_events" in query

        def fetchall(self):
            return rows

    class Conn:
        def cursor(self):
            return Cursor()

    events = _load_case_timeline(Conn(), "case-1")
    assert [e.event_type for e in events] == ["dispatched", "driver_arriving", "other_noise"]
    assert events[0].label == "Điều phối"
    assert events[0].occurred_at.startswith("2026-10-01T14:20:00")


def test_load_case_timeline_db_error_is_empty():
    from src.services.jev_precedent_service import _load_case_timeline

    class BadConn:
        def cursor(self):
            raise RuntimeError("down")

    assert _load_case_timeline(BadConn(), "case-1") == []
