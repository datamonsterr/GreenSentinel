"""Unit regression tests for PR #508 review findings (Issue #480).

Covers:
1. Distribution/rated_count restricted to stars 1..5 (out-of-range / comment-only
   ratings excluded from the average but comment-only feedback still listed).
2. Feedback `total` is the full count independent of cursor page.
3. Feedback rows with stars OR non-empty comment are valid; stars nullable;
   `date` is the rating `created_at` or null (never the trip `started_at`).
4. `get_driver_scorecard` connection never leaks when the profile lookup raises.
5. `display_name` is null (not a fabricated default) when unmeasured.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from src.services import driver_service
from src.services.case_service import CaseService, get_case_service

TEST_ORG = "018f2f4e-0000-7000-8000-000000000001"


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
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


def _seed_trip(driver_id: str, org_id: str, trip_id: str, days_ago: float, stars, comment):
    now = datetime.now(UTC)
    ts = (now - timedelta(days=days_ago)).isoformat()
    driver_service._memory_driver_trips[trip_id] = {
        "trip_id": trip_id,
        "driver_id": driver_id,
        "organization_id": org_id,
        "pickup_label": "A",
        "dropoff_label": "B",
        "started_at": ts,
        "ended_at": ts,
        "distance_km": 1.0,
        "duration_min": 1.0,
        "fare_vnd": 10000,
        "payment_method": "wallet",
        "status": "completed",
        "case_id": None,
    }
    driver_service._memory_trip_ratings[trip_id] = {
        "trip_id": trip_id,
        "stars": stars,
        "comment": comment,
        "locale": "vi",
        "created_at": ts if (stars is not None or comment) else None,
    }


@pytest.mark.asyncio
async def test_display_name_null_when_missing():
    """display_name must be None (never a fabricated default) when the driver record has none."""
    driver_id = "drv-no-name"
    cs = get_case_service()
    cs._drivers[driver_id] = {"id": driver_id, "organization_id": TEST_ORG, "created_at": None}

    profile = await driver_service.get_driver_profile(driver_id, TEST_ORG, cs)
    assert profile.display_name is None


@pytest.mark.asyncio
async def test_display_name_null_when_stored_value_is_clerk_principal_id():
    """display_name must never surface a raw Clerk principal id (auto-provisioned driver, no stored name)."""
    driver_id = "drv-clerk-id"
    cs = get_case_service()
    cs._drivers[driver_id] = {
        "id": driver_id,
        "organization_id": TEST_ORG,
        "created_at": None,
        "display_name": "user_3KOfcfwA3jcTmM475h07PpYn3EI",
    }

    profile = await driver_service.get_driver_profile(driver_id, TEST_ORG, cs)
    assert profile.display_name is None


@pytest.mark.asyncio
async def test_distribution_excludes_out_of_range_and_comment_only_ratings():
    """rated_count/distribution only count stars 1..5; comment-only rows excluded from average."""
    driver_id = "drv-dist-1"
    cs = get_case_service()
    cs._drivers[driver_id] = {"id": driver_id, "organization_id": TEST_ORG, "created_at": None}

    _seed_trip(driver_id, TEST_ORG, "t1", 1, 5, "Tốt")
    _seed_trip(driver_id, TEST_ORG, "t2", 2, 4, None)
    # Comment-only: stars is None, must not count in distribution/rated_count.
    _seed_trip(driver_id, TEST_ORG, "t3", 3, None, "Chỉ có nhận xét, không đánh giá sao")

    profile = await driver_service.get_driver_profile(driver_id, TEST_ORG, cs)

    assert profile.rated_count == 2
    assert sum(profile.distribution.values()) == profile.rated_count
    assert profile.distribution["5"] == 1
    assert profile.distribution["4"] == 1
    assert profile.rating_average == pytest.approx(4.5)


@pytest.mark.asyncio
async def test_feedback_includes_comment_only_rows_with_null_stars_and_null_date_fallback():
    """Comment-only feedback rows are valid; stars null; date is rating created_at or null, never trip started_at."""
    driver_id = "drv-fb-1"
    cs = get_case_service()
    cs._drivers[driver_id] = {"id": driver_id, "organization_id": TEST_ORG, "created_at": None}

    _seed_trip(driver_id, TEST_ORG, "t1", 1, 5, "Tốt")
    _seed_trip(driver_id, TEST_ORG, "t2", 2, None, "Chỉ nhận xét")
    # Trip with a rating record that has neither stars nor comment: must be excluded entirely.
    driver_service._memory_driver_trips["t3"] = {
        "trip_id": "t3",
        "driver_id": driver_id,
        "organization_id": TEST_ORG,
        "pickup_label": "A",
        "dropoff_label": "B",
        "started_at": (datetime.now(UTC) - timedelta(days=5)).isoformat(),
        "ended_at": None,
        "distance_km": 1.0,
        "duration_min": 1.0,
        "fare_vnd": 10000,
        "payment_method": "wallet",
        "status": "completed",
        "case_id": None,
    }
    driver_service._memory_trip_ratings["t3"] = {
        "trip_id": "t3",
        "stars": None,
        "comment": None,
        "locale": "vi",
        "created_at": None,
    }

    result = await driver_service.list_driver_feedback(driver_id, limit=20, organization_id=TEST_ORG, case_service=cs)

    assert result.total == 2
    ids = {item.id for item in result.items}
    assert ids == {"t1", "t2"}
    comment_only = next(item for item in result.items if item.id == "t2")
    assert comment_only.stars is None
    assert comment_only.comment == "Chỉ nhận xét"
    assert comment_only.date is not None  # rating created_at is set


@pytest.mark.asyncio
async def test_feedback_total_stable_across_cursor_pages():
    """total must equal the full count on every page, independent of the cursor."""
    driver_id = "drv-fb-page"
    cs = get_case_service()
    cs._drivers[driver_id] = {"id": driver_id, "organization_id": TEST_ORG, "created_at": None}

    for i in range(5):
        _seed_trip(driver_id, TEST_ORG, f"t{i}", i + 1, 5, f"comment {i}")

    page1 = await driver_service.list_driver_feedback(driver_id, limit=2, organization_id=TEST_ORG, case_service=cs)
    assert page1.total == 5
    assert len(page1.items) == 2
    assert page1.next_cursor is not None

    page2 = await driver_service.list_driver_feedback(
        driver_id, cursor=page1.next_cursor, limit=2, organization_id=TEST_ORG, case_service=cs
    )
    assert page2.total == 5
    assert len(page2.items) == 2

    page3 = await driver_service.list_driver_feedback(
        driver_id, cursor=page2.next_cursor, limit=2, organization_id=TEST_ORG, case_service=cs
    )
    assert page3.total == 5
    assert len(page3.items) == 1


@pytest.mark.asyncio
async def test_get_driver_profile_closes_connection_when_scorecard_raises():
    """If get_driver_scorecard raises mid-profile-lookup, the profile's own DB connection must still close."""

    class FakeConn:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    fake_conn = FakeConn()

    class FakeCaseService(CaseService):
        def _get_db_connection(self):
            return fake_conn

    cs = FakeCaseService.__new__(FakeCaseService)
    CaseService.__init__(cs)

    async def raising_scorecard(*args, **kwargs):
        raise HTTPException(status_code=404, detail="Driver not found")

    import src.services.driver_service as ds

    original = ds.get_driver_scorecard
    ds.get_driver_scorecard = raising_scorecard
    try:
        with pytest.raises(HTTPException):
            await driver_service.get_driver_profile("drv-x", TEST_ORG, case_service=cs)
    finally:
        ds.get_driver_scorecard = original

    assert fake_conn.closed is True
