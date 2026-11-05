"""Sensor passthrough on GET /cases/{id} (issue #100).

telemetry_samples must carry the enriched sensor fields
(drift_distance_m, ping_latency_ms, battery_level_pct) end to end.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from src.services.case_service import CaseService, get_case_service


@pytest.fixture(autouse=True)
def force_memory_backend(monkeypatch):
    """Force the in-memory fallback so tests are deterministic with or without a live DB."""
    monkeypatch.setattr(CaseService, "_get_db_connection", lambda self: None)
    yield


def _seed_case_with_telemetry(case_id="case-tlm-1"):
    cs = get_case_service()
    driver_id = "drv-tlm-1"
    asgn_id = f"asgn-{case_id}"
    trip_id = f"trip-{case_id}"
    now = datetime.now(UTC)
    cs._drivers[driver_id] = {"id": driver_id, "display_name": "Driver TLM"}
    cs._assignments[asgn_id] = {"id": asgn_id, "driver_id": driver_id, "trip_id": trip_id}
    cs._trips[trip_id] = {"id": trip_id, "status": "completed"}
    cs._cases[case_id] = {
        "id": case_id,
        "assignment_id": asgn_id,
        "status": "ready",
        "dispute_status": "not_disputed",
        "suspected_category": "ERR-01",
        "priority_score": 65,
        "priority_tier": 1,
        "version": 1,
        "created_at": (now - timedelta(hours=1)).isoformat(),
        "updated_at": now.isoformat(),
    }
    cs._telemetry_points.extend(
        [
            {
                "assignment_id": asgn_id,
                "event_id": f"evt-{case_id}-1",
                "occurred_at": (now - timedelta(minutes=20)).isoformat(),
                "position": {"type": "Point", "coordinates": [105.8342, 21.0278]},
                "speed_mps": 8.5,
                "drift_distance_m": 12.4,
                "ping_latency_ms": 87.0,
                "battery_level_pct": 76.0,
            },
            {
                "assignment_id": asgn_id,
                "event_id": f"evt-{case_id}-2",
                "occurred_at": (now - timedelta(minutes=19)).isoformat(),
                "position": {"type": "Point", "coordinates": [105.8345, 21.0281]},
                "speed_mps": 9.1,
                "drift_distance_m": 9.8,
                "ping_latency_ms": 92.0,
                "battery_level_pct": 75.0,
            },
        ]
    )
    return cs


@pytest.mark.asyncio
async def test_case_detail_telemetry_samples_carry_sensor_fields(client: AsyncClient):
    _seed_case_with_telemetry()
    res = await client.get("/api/v1/cases/case-tlm-1")
    assert res.status_code == 200, res.text
    samples = res.json()["telemetry_samples"]
    assert len(samples) == 2
    for sample in samples:
        assert "drift_distance_m" in sample
        assert "ping_latency_ms" in sample
        assert "battery_level_pct" in sample
    assert samples[0]["drift_distance_m"] == 12.4
    assert samples[0]["ping_latency_ms"] == 87.0
    assert samples[0]["battery_level_pct"] == 76.0
