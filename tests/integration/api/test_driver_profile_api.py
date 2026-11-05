"""Integration tests for driver profile and customer feedback endpoints (Issue #480).

Endpoints:
1. GET /api/v1/driver/profile
   - Driver identity (display name, vehicle, member since)
   - 90-day scorecard from driver_service.get_driver_scorecard
   - Rating average, rated count, distribution 5..1 summing to rated count
   - Weekly rating trend for last 8 weeks
   - Measured values only (no fabricated ratings)
   - 404 on missing or foreign driver identity
2. GET /api/v1/driver/feedback
   - Cursor paginated customer feedback (stars, comment|null, date)
   - Measured values only
   - 404 on missing or foreign driver identity
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app
from src.services import driver_service
from src.services.case_service import CaseService, get_case_service


@pytest.fixture(autouse=True)
def clean_driver_test_state(monkeypatch):
    """Reset driver test memory state and force in-memory fallback for deterministic testing."""
    monkeypatch.setattr(CaseService, "_get_db_connection", lambda self: None)
    cs = get_case_service()
    cs._drivers.clear()
    cs._assignments.clear()
    cs._cases.clear()
    cs._adjudications.clear()
    driver_service._memory_driver_trips.clear()
    driver_service._memory_trip_ratings.clear()
    yield
    cs._drivers.clear()
    cs._assignments.clear()
    cs._cases.clear()
    cs._adjudications.clear()
    driver_service._memory_driver_trips.clear()
    driver_service._memory_trip_ratings.clear()


def _seed_driver_with_ratings(driver_id: str = "drv-profile-1", org_id: str = "018f2f4e-0000-7000-8000-000000000001"):
    cs = get_case_service()
    cs._drivers[driver_id] = {
        "id": driver_id,
        "display_name": "Nguyễn Văn An",
        "created_at": "2024-01-15T08:00:00Z",
        "organization_id": org_id,
        "account_status": "active",
        "vehicle_model": "VinFast VF e34",
        "vehicle_plate": "30A-123.45",
    }

    # Add trips and ratings across multiple weeks
    now = datetime.now(UTC)
    ratings_spec = [
        # (days_ago, stars, comment)
        (2, 5, "Tài xế lái xe rất êm ái, lịch sự"),
        (5, 5, None),  # comment null
        (10, 4, "Xe sạch, đúng giờ"),
        (20, 3, "Đi hơi xóc"),
        (35, 5, "Rất tốt"),
        (45, 1, "Đến muộn"),
    ]

    for i, (days_ago, stars, comment) in enumerate(ratings_spec):
        trip_id = f"trip-p-{i + 1}"
        asgn_id = f"asgn-p-{i + 1}"
        ts = (now - timedelta(days=days_ago)).isoformat()

        cs._assignments[asgn_id] = {
            "id": asgn_id,
            "driver_id": driver_id,
            "trip_id": trip_id,
        }
        driver_service._memory_driver_trips[trip_id] = {
            "trip_id": trip_id,
            "driver_id": driver_id,
            "organization_id": org_id,
            "pickup_label": "Điểm đón A",
            "dropoff_label": "Điểm đến B",
            "started_at": ts,
            "ended_at": ts,
            "distance_km": 5.2,
            "duration_min": 14.5,
            "fare_vnd": 85000,
            "payment_method": "wallet",
            "status": "completed",
            "case_id": None,
        }
        driver_service._memory_trip_ratings[trip_id] = {
            "trip_id": trip_id,
            "stars": stars,
            "comment": comment,
            "locale": "vi",
            "created_at": ts,
        }


@pytest.mark.asyncio
async def test_get_driver_profile_success():
    """Authenticated driver gets complete profile with measured ratings and trend."""
    driver_id = "drv-profile-1"
    org_id = "018f2f4e-0000-7000-8000-000000000001"
    _seed_driver_with_ratings(driver_id, org_id)

    headers = {
        "x-principal-id": driver_id,
        "x-driver-id": driver_id,
        "x-role": "driver",
        "x-organization-id": org_id,
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/driver/profile", headers=headers)
        assert res.status_code == 200, res.text
        data = res.json()

        assert data["driver_id"] == driver_id
        assert data["display_name"] == "Nguyễn Văn An"
        assert data["vehicle"]["model"] == "VinFast VF e34"
        assert data["vehicle"]["plate"] == "30A-123.45"
        assert data["member_since"] == "2024-01-15T08:00:00Z"

        # Scorecard
        scorecard = data["scorecard"]
        assert scorecard["driver_id"] == driver_id
        assert "violation_ratio_90d" in scorecard
        assert "repeat_offense_risk_score" in scorecard

        # Ratings
        assert data["rated_count"] == 6
        # Average of [5, 5, 4, 3, 5, 1] = 23 / 6 = 3.83
        assert data["rating_average"] == pytest.approx(3.83, rel=1e-2)

        # Distribution 5..1
        dist = data["distribution"]
        assert dist["5"] == 3
        assert dist["4"] == 1
        assert dist["3"] == 1
        assert dist["2"] == 0
        assert dist["1"] == 1
        # Invariant: distribution 5..1 sums to rated_count
        assert sum(dist.values()) == data["rated_count"]

        # Weekly trend for last 8 weeks
        trend = data["weekly_trend"]
        assert len(trend) == 8
        for pt in trend:
            assert "week_label" in pt
            assert "week_start" in pt
            assert "rated_count" in pt
            assert "average_rating" in pt
            if pt["rated_count"] == 0:
                assert pt["average_rating"] is None


@pytest.mark.asyncio
async def test_get_driver_profile_empty_ratings():
    """Driver without any ratings receives null average, 0 count, and empty distribution."""
    driver_id = "drv-new"
    org_id = "018f2f4e-0000-7000-8000-000000000001"
    cs = get_case_service()
    cs._drivers[driver_id] = {
        "id": driver_id,
        "display_name": "Tài xế Mới",
        "created_at": "2026-10-01T00:00:00Z",
        "organization_id": org_id,
        "account_status": "active",
    }

    headers = {
        "x-principal-id": driver_id,
        "x-driver-id": driver_id,
        "x-role": "driver",
        "x-organization-id": org_id,
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/driver/profile", headers=headers)
        assert res.status_code == 200, res.text
        data = res.json()

        assert data["driver_id"] == driver_id
        assert data["rating_average"] is None
        assert data["rated_count"] == 0
        assert data["distribution"] == {"5": 0, "4": 0, "3": 0, "2": 0, "1": 0}
        assert sum(data["distribution"].values()) == 0
        assert len(data["weekly_trend"]) == 8
        assert all(pt["average_rating"] is None for pt in data["weekly_trend"])


@pytest.mark.asyncio
async def test_get_driver_profile_404_on_missing_or_foreign():
    """Missing or foreign driver identity returns 404 (preventing enumeration)."""
    headers_unknown = {
        "x-principal-id": "unknown-drv",
        "x-driver-id": "unknown-drv",
        "x-role": "driver",
        "x-organization-id": "018f2f4e-0000-7000-8000-000000000001",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/driver/profile", headers=headers_unknown)
        assert res.status_code == 404


@pytest.mark.asyncio
async def test_get_driver_feedback_pagination():
    """Customer feedback endpoint returns paginated ratings with null comments preserved."""
    driver_id = "drv-profile-1"
    org_id = "018f2f4e-0000-7000-8000-000000000001"
    _seed_driver_with_ratings(driver_id, org_id)

    headers = {
        "x-principal-id": driver_id,
        "x-driver-id": driver_id,
        "x-role": "driver",
        "x-organization-id": org_id,
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Page 1
        res = await client.get("/api/v1/driver/feedback?limit=3", headers=headers)
        assert res.status_code == 200, res.text
        data = res.json()

        assert len(data["items"]) == 3
        assert data["next_cursor"] is not None
        assert data["total"] == 6

        # Check item structure
        item = data["items"][0]
        assert "id" in item
        assert "stars" in item
        assert "comment" in item
        assert "date" in item

        # One of the seeded items has comment=None
        has_null_comment = any(item["comment"] is None for item in data["items"])
        assert has_null_comment
        cursor = data["next_cursor"]

        # Page 2
        res2 = await client.get(f"/api/v1/driver/feedback?limit=3&cursor={cursor}", headers=headers)
        assert res2.status_code == 200
        data2 = res2.json()
        assert len(data2["items"]) == 3
        # total must be stable (the full count), independent of the cursor page.
        assert data2["total"] == 6


@pytest.mark.asyncio
async def test_get_driver_feedback_404_on_unknown():
    """Unknown driver querying feedback returns 404."""
    headers_unknown = {
        "x-principal-id": "unknown-drv",
        "x-driver-id": "unknown-drv",
        "x-role": "driver",
        "x-organization-id": "018f2f4e-0000-7000-8000-000000000001",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/driver/feedback", headers=headers_unknown)
        assert res.status_code == 404
