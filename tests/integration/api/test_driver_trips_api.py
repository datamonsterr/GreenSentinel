"""Integration tests for driver trips history and summary endpoints (Issue #479).

Endpoints:
- GET /api/v1/driver/trips?cursor=&status=&month=
- GET /api/v1/driver/trips/summary?month=
- GET /api/v1/driver/trips/{trip_id}
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from src.services.case_service import CaseService
from src.services.driver_service import _memory_driver_trips, _memory_trip_ratings

TEST_ORG = "018f2f4e-0000-7000-8000-000000000001"
OTHER_ORG = "018f2f4e-0000-7000-8000-000000000002"
DRIVER_ID_1 = "018f2f4e-1111-7000-8000-000000000001"
DRIVER_ID_2 = "018f2f4e-2222-7000-8000-000000000002"


def _trip_uuid(driver_id: str, n: int) -> str:
    """Deterministic UUID derived from driver_id + index, for stable test fixtures."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{driver_id}-trip-{n}"))


DRIVER_1_HEADERS = {"X-Driver-ID": DRIVER_ID_1, "X-Role": "driver"}
DRIVER_2_HEADERS = {"X-Driver-ID": DRIVER_ID_2, "X-Role": "driver"}
ANALYST_HEADERS = {"X-Role": "analyst"}


@pytest.fixture(autouse=True)
def force_memory_backend(monkeypatch):
    """Force the in-memory fallback so tests run deterministically."""
    monkeypatch.setattr(CaseService, "_get_db_connection", lambda self: None)
    _memory_driver_trips.clear()
    _memory_trip_ratings.clear()
    yield
    _memory_driver_trips.clear()
    _memory_trip_ratings.clear()


def _seed_trips(driver_id: str = DRIVER_ID_1, org: str = TEST_ORG) -> list[dict[str, Any]]:
    base_time = datetime(2026, 10, 15, 10, 0, 0, tzinfo=UTC)
    seeded = []

    # Trip 1: normal completed trip with 5-star rating
    t1 = {
        "trip_id": _trip_uuid(driver_id, 1),
        "driver_id": driver_id,
        "organization_id": org,
        "pickup_label": "Sảnh R1, Vinhomes Ocean Park 1",
        "pickup_lat": 21.0,
        "pickup_lng": 105.9,
        "dropoff_label": "Nhà ga T2, Sân bay Nội Bài",
        "dropoff_lat": 21.2,
        "dropoff_lng": 105.8,
        "started_at": (base_time - timedelta(hours=2)).isoformat(),
        "ended_at": (base_time - timedelta(hours=1)).isoformat(),
        "distance_km": 32.0,
        "duration_min": 47.0,
        "fare_vnd": 285000,
        "payment_method": "wallet",
        "payment_method_synthetic": True,
        "status": "completed",
        "case_id": None,
    }
    _memory_driver_trips[t1["trip_id"]] = t1
    _memory_trip_ratings[t1["trip_id"]] = {
        "trip_id": t1["trip_id"],
        "stars": 5,
        "comment": "Tài xế lái xe êm, điều hòa mát.",
        "locale": "vi",
        "created_at": base_time.isoformat(),
    }
    seeded.append(t1)

    # Trip 2: flagged trip linked to case
    t2 = {
        "trip_id": _trip_uuid(driver_id, 2),
        "driver_id": driver_id,
        "organization_id": org,
        "pickup_label": "Tòa Landmark 81",
        "pickup_lat": 10.79,
        "pickup_lng": 106.72,
        "dropoff_label": "Bitexco Financial Tower",
        "dropoff_lat": 10.77,
        "dropoff_lng": 106.70,
        "started_at": (base_time - timedelta(days=1)).isoformat(),
        "ended_at": (base_time - timedelta(days=1, minutes=-35)).isoformat(),
        "distance_km": 14.5,
        "duration_min": 35.0,
        "fare_vnd": 142000,
        "payment_method": "credit_card",
        "payment_method_synthetic": True,
        "status": "completed",
        "case_id": "018f2f4e-case-7000-8000-000000000002",
    }
    _memory_driver_trips[t2["trip_id"]] = t2
    seeded.append(t2)

    # Trip 3: unrated completed trip from previous month (September 2026)
    t3 = {
        "trip_id": _trip_uuid(driver_id, 3),
        "driver_id": driver_id,
        "organization_id": org,
        "pickup_label": "TTTM Aeon Mall Long Biên",
        "pickup_lat": 21.02,
        "pickup_lng": 105.90,
        "dropoff_label": "Phố đi bộ Hoàn Kiếm",
        "dropoff_lat": 21.03,
        "dropoff_lng": 105.85,
        "started_at": datetime(2026, 9, 20, 14, 0, 0, tzinfo=UTC).isoformat(),
        "ended_at": datetime(2026, 9, 20, 14, 30, 0, tzinfo=UTC).isoformat(),
        "distance_km": 10.0,
        "duration_min": 30.0,
        "fare_vnd": 100000,
        "payment_method": "cash",
        "payment_method_synthetic": True,
        "status": "completed",
        "case_id": None,
    }
    _memory_driver_trips[t3["trip_id"]] = t3
    seeded.append(t3)

    return seeded


@pytest.mark.asyncio
async def test_driver_trips_requires_driver_role():
    """Analyst or non-driver principal cannot access driver trips list."""
    from fastapi import FastAPI
    from httpx import ASGITransport

    from src.api.auth import Principal, require_principal
    from src.api.routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_principal] = lambda: Principal(
        id="analyst-1",
        organization_id=TEST_ORG,
        roles=frozenset({"analyst"}),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/api/v1/driver/trips")
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_driver_trips_returns_authenticated_driver_trips_and_schema(client: AsyncClient):
    """Driver only sees their own trips with required response schema."""
    _seed_trips(DRIVER_ID_1)
    _seed_trips(DRIVER_ID_2)

    res = await client.get("/api/v1/driver/trips", headers=DRIVER_1_HEADERS)
    assert res.status_code == 200, res.text
    data = res.json()

    assert "trips" in data
    assert "total" in data
    assert "next_cursor" in data
    assert data["total"] == 3

    for item in data["trips"]:
        assert "pickup_label" in item
        assert "dropoff_label" in item
        assert "started_at" in item
        assert "ended_at" in item
        assert "distance_km" in item
        assert "duration_min" in item
        assert "fare_vnd" in item
        assert "payment_method" in item
        assert "payment_method_synthetic" in item
        assert "rating" in item
        assert "status" in item
        assert "has_case" in item
        assert "case_id" in item

    # Trip 1 check: rated 5 stars, no case
    trip1 = next(t for t in data["trips"] if t["trip_id"] == _trip_uuid(DRIVER_ID_1, 1))
    assert trip1["rating"] is not None
    assert trip1["rating"]["stars"] == 5
    assert trip1["has_case"] is False
    assert trip1["case_id"] is None

    # Trip 2 check: flagged trip with case link
    trip2 = next(t for t in data["trips"] if t["trip_id"] == _trip_uuid(DRIVER_ID_1, 2))
    assert trip2["has_case"] is True
    assert trip2["case_id"] == "018f2f4e-case-7000-8000-000000000002"
    assert trip2["rating"] is None


@pytest.mark.asyncio
async def test_driver_trips_status_and_month_filtering(client: AsyncClient):
    """Query filters by status (completed, flagged) and month (YYYY-MM)."""
    _seed_trips(DRIVER_ID_1)

    # Filter month 2026-10: should have 2 trips
    res_month = await client.get("/api/v1/driver/trips?month=2026-10", headers=DRIVER_1_HEADERS)
    assert res_month.status_code == 200
    assert len(res_month.json()["trips"]) == 2

    # Filter status=flagged: should only have Trip 2
    res_flagged = await client.get("/api/v1/driver/trips?status=flagged", headers=DRIVER_1_HEADERS)
    assert res_flagged.status_code == 200
    flagged = res_flagged.json()["trips"]
    assert len(flagged) == 1
    assert flagged[0]["has_case"] is True

    # Filter status=completed: should exclude flagged trips
    res_completed = await client.get("/api/v1/driver/trips?status=completed", headers=DRIVER_1_HEADERS)
    assert res_completed.status_code == 200
    completed = res_completed.json()["trips"]
    assert len(completed) == 2
    assert all(not t["has_case"] for t in completed)


@pytest.mark.asyncio
async def test_driver_trips_keyset_pagination(client: AsyncClient):
    """Keyset pagination via cursor parameter; total is stable across pages (independent of cursor)."""
    _seed_trips(DRIVER_ID_1)

    # Request limit=2
    res_p1 = await client.get("/api/v1/driver/trips?limit=2", headers=DRIVER_1_HEADERS)
    assert res_p1.status_code == 200
    p1 = res_p1.json()
    assert len(p1["trips"]) == 2
    assert p1["next_cursor"] is not None
    assert p1["total"] == 3

    # Request second page with next_cursor
    res_p2 = await client.get(f"/api/v1/driver/trips?limit=2&cursor={p1['next_cursor']}", headers=DRIVER_1_HEADERS)
    assert res_p2.status_code == 200
    p2 = res_p2.json()
    assert len(p2["trips"]) == 1
    assert p2["next_cursor"] is None
    # total must be identical on every page: independent of cursor.
    assert p2["total"] == 3 == p1["total"]


@pytest.mark.asyncio
async def test_driver_trips_total_independent_of_cursor_with_status_filter(client: AsyncClient):
    """total reflects the (driver, status, month) WHERE regardless of pagination cursor."""
    _seed_trips(DRIVER_ID_1)

    res = await client.get("/api/v1/driver/trips?status=completed&limit=1", headers=DRIVER_1_HEADERS)
    assert res.status_code == 200
    data = res.json()
    # 2 completed trips total (trip1, trip3) even though only 1 is returned on this page.
    assert data["total"] == 2
    assert len(data["trips"]) == 1


@pytest.mark.asyncio
async def test_driver_trips_counts_reflect_all_statuses_regardless_of_filter(client: AsyncClient):
    """counts (all/completed/flagged) come from the backend and ignore the active status filter."""
    _seed_trips(DRIVER_ID_1)

    for qs in ("", "?status=flagged", "?status=completed"):
        res = await client.get(f"/api/v1/driver/trips{qs}", headers=DRIVER_1_HEADERS)
        assert res.status_code == 200, res.text
        counts = res.json()["counts"]
        assert counts == {"all": 3, "completed": 2, "flagged": 1}


@pytest.mark.asyncio
async def test_driver_trips_month_rejects_malformed_value(client: AsyncClient):
    """month must match YYYY-MM (01..12); garbage returns 422."""
    _seed_trips(DRIVER_ID_1)

    for bad_month in ("2026-13", "2026-00", "26-10", "not-a-month", "2026/10"):
        res = await client.get(f"/api/v1/driver/trips?month={bad_month}", headers=DRIVER_1_HEADERS)
        assert res.status_code == 422, f"{bad_month} should be rejected"

    res_summary = await client.get("/api/v1/driver/trips/summary?month=garbage", headers=DRIVER_1_HEADERS)
    assert res_summary.status_code == 422


@pytest.mark.asyncio
async def test_driver_trips_limit_clamps_instead_of_422(client: AsyncClient):
    """Out-of-range limit is clamped to [1, 50], never a 422."""
    _seed_trips(DRIVER_ID_1)

    res_high = await client.get("/api/v1/driver/trips?limit=9999", headers=DRIVER_1_HEADERS)
    assert res_high.status_code == 200
    assert len(res_high.json()["trips"]) == 3  # clamped to 50, still only 3 trips exist

    res_low = await client.get("/api/v1/driver/trips?limit=0", headers=DRIVER_1_HEADERS)
    assert res_low.status_code == 200
    assert len(res_low.json()["trips"]) == 1  # clamped to 1

    res_negative = await client.get("/api/v1/driver/trips?limit=-5", headers=DRIVER_1_HEADERS)
    assert res_negative.status_code == 200
    assert len(res_negative.json()["trips"]) == 1  # clamped to 1


@pytest.mark.asyncio
async def test_driver_trips_summary_endpoint(client: AsyncClient):
    """GET /api/v1/driver/trips/summary?month= returns total fare, trip count, km."""
    _seed_trips(DRIVER_ID_1)

    # Month 2026-10 summary: trips 1 and 2
    # fare = 285000 + 142000 = 427000
    # distance = 32.0 + 14.5 = 46.5
    # count = 2
    res = await client.get("/api/v1/driver/trips/summary?month=2026-10", headers=DRIVER_1_HEADERS)
    assert res.status_code == 200, res.text
    summary = res.json()
    assert summary["month"] == "2026-10"
    assert summary["trip_count"] == 2
    assert summary["total_fare_vnd"] == 427000
    assert summary["total_distance_km"] == pytest.approx(46.5)


@pytest.mark.asyncio
async def test_driver_single_trip_ownership_and_missing_both_404(client: AsyncClient):
    """Single trip lookup returns 404 for missing, malformed, or foreign trips to prevent existence probing."""
    _seed_trips(DRIVER_ID_1)
    _seed_trips(DRIVER_ID_2)

    # Missing (but well-formed UUID) trip -> 404
    res_missing = await client.get(f"/api/v1/driver/trips/{uuid.uuid4()}", headers=DRIVER_1_HEADERS)
    assert res_missing.status_code == 404

    # Malformed trip id (not a UUID) -> 404, never 503
    res_malformed = await client.get("/api/v1/driver/trips/not-a-uuid", headers=DRIVER_1_HEADERS)
    assert res_malformed.status_code == 404

    # Foreign trip belonging to DRIVER_ID_2 accessed by DRIVER_ID_1 -> 404
    foreign_tid = _trip_uuid(DRIVER_ID_2, 1)
    res_foreign = await client.get(f"/api/v1/driver/trips/{foreign_tid}", headers=DRIVER_1_HEADERS)
    assert res_foreign.status_code == 404

    # Own trip -> 200
    own_tid = _trip_uuid(DRIVER_ID_1, 1)
    res_own = await client.get(f"/api/v1/driver/trips/{own_tid}", headers=DRIVER_1_HEADERS)
    assert res_own.status_code == 200
    assert res_own.json()["trip_id"] == own_tid
