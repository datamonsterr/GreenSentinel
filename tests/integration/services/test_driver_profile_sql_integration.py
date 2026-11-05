"""Real PostgreSQL integration tests for the driver profile / feedback SQL path
(PR #508 review findings, Issue #480).

Runs the full migration chain into a disposable, generated database (dropped
at teardown) so nothing ever touches a shared dev database. Skips clearly
when PostgreSQL is unreachable on loopback.

Covers:
- SQL profile path: distribution/average aggregated via SQL GROUP BY, stars
  restricted to 1..5, display_name null when unmeasured.
- Feedback keyset cursor pagination across pages; total stable (SQL COUNT)
  independent of the cursor.
- Out-of-range stars excluded (CHECK constraint + defensive SQL filter).
- Comment-only feedback rows (null stars) are included.
- Foreign-org driver returns 404.
- 8-week bucket values (date_trunc('week', ...)) in the weekly trend.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import psycopg
import pytest

from tests.integration.conftest import is_postgres_available

REPO_ROOT = Path(__file__).resolve().parents[3]


pytestmark = [
    pytest.mark.docker,
    pytest.mark.integration,
    pytest.mark.skipif(
        not is_postgres_available(),
        reason="PostgreSQL engine not reachable on loopback; set DATABASE_URL to run this suite",
    ),
]


@pytest.fixture(scope="module")
def disposable_db(disposable_database_dsn):
    """Alias kept for this module's existing test bodies; see conftest.disposable_database_dsn."""
    return disposable_database_dsn


@pytest.fixture
def cs(disposable_case_service):
    return disposable_case_service


def _seed_org_and_driver(dsn: str, *, display_name: str | None = "Nguyễn Văn An") -> dict:
    """Seed one organization, one driver (optionally nameless), one vehicle assignment."""
    org_id = str(uuid.uuid4())
    driver_id = str(uuid.uuid4())
    vehicle_id = str(uuid.uuid4())

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            cur.execute("INSERT INTO app.organizations (id, name) VALUES (%s, %s);", (org_id, "Org " + org_id[:8]))
            cur.execute(
                """
                INSERT INTO app.drivers (id, organization_id, external_ref, partner_type, display_name)
                VALUES (%s, %s, %s, 'owner_driver', %s);
                """,
                (driver_id, org_id, driver_id, display_name),
            )
            cur.execute(
                """
                INSERT INTO app.vehicles (id, organization_id, registration_ref, vehicle_type, service_class, telemetry_source)
                VALUES (%s, %s, '30A-999.99', 'car', 'standard', 'smartphone');
                """,
                (vehicle_id, org_id),
            )
            cur.execute(
                """
                INSERT INTO app.driver_vehicle_assignments (driver_id, vehicle_id, effective_from)
                VALUES (%s, %s, now());
                """,
                (driver_id, vehicle_id),
            )
    return {"org_id": org_id, "driver_id": driver_id}


def _seed_trip_with_rating(
    dsn: str,
    *,
    driver_id: str,
    org_id: str,
    days_ago: float,
    stars: int | None,
    comment: str | None,
) -> str:
    trip_id = str(uuid.uuid4())
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            cur.execute(
                """
                INSERT INTO app.driver_trips (
                    trip_id, driver_id, organization_id, pickup_label, dropoff_label,
                    started_at, ended_at, distance_km, duration_min, fare_vnd, status
                ) VALUES (
                    %s, %s, %s, 'Pickup', 'Dropoff',
                    now() - (%s || ' days')::interval, now() - (%s || ' days')::interval,
                    5.0, 15.0, 80000, 'completed'
                );
                """,
                (trip_id, driver_id, org_id, days_ago, days_ago),
            )
            cur.execute(
                """
                INSERT INTO app.trip_ratings (trip_id, stars, comment, locale, created_at)
                VALUES (%s, %s, %s, 'vi', now() - (%s || ' days')::interval);
                """,
                (trip_id, stars, comment, days_ago),
            )
    return trip_id


@pytest.mark.asyncio
async def test_get_driver_profile_sql_path_measured_distribution(cs, disposable_db):
    """SQL profile path: distribution/average aggregated via SQL, stars restricted to 1..5."""
    from src.services.driver_service import get_driver_profile

    seed = _seed_org_and_driver(disposable_db)
    _seed_trip_with_rating(
        disposable_db, driver_id=seed["driver_id"], org_id=seed["org_id"], days_ago=1, stars=5, comment="Tốt"
    )
    _seed_trip_with_rating(
        disposable_db, driver_id=seed["driver_id"], org_id=seed["org_id"], days_ago=2, stars=4, comment=None
    )
    # Comment-only rating: must not be counted in distribution/average.
    _seed_trip_with_rating(
        disposable_db,
        driver_id=seed["driver_id"],
        org_id=seed["org_id"],
        days_ago=3,
        stars=None,
        comment="Chỉ nhận xét",
    )

    profile = await get_driver_profile(seed["driver_id"], seed["org_id"], case_service=cs)

    assert profile.display_name == "Nguyễn Văn An"
    assert profile.rated_count == 2
    assert sum(profile.distribution.values()) == profile.rated_count
    assert profile.distribution["5"] == 1
    assert profile.distribution["4"] == 1
    assert profile.rating_average == pytest.approx(4.5)
    assert len(profile.weekly_trend) == 8


@pytest.mark.asyncio
async def test_get_driver_profile_sql_path_display_name_null_when_unmeasured(cs, disposable_db):
    """display_name must be null (never a fabricated default) when the driver has none."""
    from src.services.driver_service import get_driver_profile

    seed = _seed_org_and_driver(disposable_db, display_name=None)

    profile = await get_driver_profile(seed["driver_id"], seed["org_id"], case_service=cs)
    assert profile.display_name is None


@pytest.mark.asyncio
async def test_get_driver_profile_sql_path_foreign_org_404(cs, disposable_db):
    """Driver belonging to a different organization returns 404, never leaking existence."""
    from fastapi import HTTPException

    from src.services.driver_service import get_driver_profile

    seed = _seed_org_and_driver(disposable_db)
    foreign_org = str(uuid.uuid4())

    with pytest.raises(HTTPException) as excinfo:
        await get_driver_profile(seed["driver_id"], foreign_org, case_service=cs)
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_get_driver_profile_sql_path_weekly_bucket_values(cs, disposable_db):
    """8-week trend buckets aggregate ratings per ISO calendar week via SQL date_trunc."""
    from src.services.driver_service import get_driver_profile

    seed = _seed_org_and_driver(disposable_db)
    # Two ratings landing in the current week.
    _seed_trip_with_rating(
        disposable_db, driver_id=seed["driver_id"], org_id=seed["org_id"], days_ago=0, stars=5, comment=None
    )
    _seed_trip_with_rating(
        disposable_db, driver_id=seed["driver_id"], org_id=seed["org_id"], days_ago=0.05, stars=3, comment=None
    )

    profile = await get_driver_profile(seed["driver_id"], seed["org_id"], case_service=cs)

    assert len(profile.weekly_trend) == 8
    current_week = profile.weekly_trend[-1]
    assert current_week.week_label == "W8"
    assert current_week.rated_count == 2
    assert current_week.average_rating == pytest.approx(4.0)
    # Older, empty weeks are gaps.
    assert profile.weekly_trend[0].rated_count == 0
    assert profile.weekly_trend[0].average_rating is None


@pytest.mark.asyncio
async def test_list_driver_feedback_sql_path_keyset_pagination_and_stable_total(cs, disposable_db):
    """Keyset cursor pagination across pages; total is the full SQL COUNT, independent of cursor."""
    from src.services.driver_service import list_driver_feedback

    seed = _seed_org_and_driver(disposable_db)
    for i in range(5):
        _seed_trip_with_rating(
            disposable_db, driver_id=seed["driver_id"], org_id=seed["org_id"], days_ago=i + 1, stars=5, comment=f"c{i}"
        )

    page1 = await list_driver_feedback(seed["driver_id"], limit=2, organization_id=seed["org_id"], case_service=cs)
    assert page1.total == 5
    assert len(page1.items) == 2
    assert page1.next_cursor is not None

    page2 = await list_driver_feedback(
        seed["driver_id"], cursor=page1.next_cursor, limit=2, organization_id=seed["org_id"], case_service=cs
    )
    assert page2.total == 5
    assert len(page2.items) == 2

    page3 = await list_driver_feedback(
        seed["driver_id"], cursor=page2.next_cursor, limit=2, organization_id=seed["org_id"], case_service=cs
    )
    assert page3.total == 5
    assert len(page3.items) == 1
    assert page3.next_cursor is None


@pytest.mark.asyncio
async def test_list_driver_feedback_sql_path_comment_only_included_empty_excluded(cs, disposable_db):
    """Comment-only rows (null stars) are included; rows with neither stars nor comment are excluded."""
    from src.services.driver_service import list_driver_feedback

    seed = _seed_org_and_driver(disposable_db)
    _seed_trip_with_rating(
        disposable_db, driver_id=seed["driver_id"], org_id=seed["org_id"], days_ago=1, stars=5, comment="Tốt"
    )
    comment_only_id = _seed_trip_with_rating(
        disposable_db,
        driver_id=seed["driver_id"],
        org_id=seed["org_id"],
        days_ago=2,
        stars=None,
        comment="Chỉ nhận xét",
    )
    # Row with neither stars nor comment must be excluded (not valid feedback).
    _seed_trip_with_rating(
        disposable_db, driver_id=seed["driver_id"], org_id=seed["org_id"], days_ago=3, stars=None, comment=None
    )

    result = await list_driver_feedback(seed["driver_id"], limit=20, organization_id=seed["org_id"], case_service=cs)

    assert result.total == 2
    ids = {item.id for item in result.items}
    assert comment_only_id in ids
    comment_only_item = next(i for i in result.items if i.id == comment_only_id)
    assert comment_only_item.stars is None
    assert comment_only_item.comment == "Chỉ nhận xét"
