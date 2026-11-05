"""B2: scorecard total_trips must come from measured app.driver_trips volume.

A driver with 60 rows in app.driver_trips (last 90 days) and 2 fraud cases
must report total_trips=60 (ratio 3.3), not total_trips=2 (ratio 100.0).
When app.driver_trips is empty, the legacy app.trips count remains.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest

from tests.integration.conftest import is_postgres_available

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
    return disposable_database_dsn


@pytest.fixture
def cs(disposable_case_service):
    return disposable_case_service


def _seed_org_and_driver(dsn: str) -> dict:
    org_id = str(uuid.uuid4())
    driver_id = str(uuid.uuid4())
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            cur.execute("INSERT INTO app.organizations (id, name) VALUES (%s, %s);", (org_id, "Org " + org_id[:8]))
            cur.execute(
                """
                INSERT INTO app.drivers (id, organization_id, external_ref, partner_type, display_name)
                VALUES (%s, %s, %s, 'owner_driver', 'Measured Driver');
                """,
                (driver_id, org_id, driver_id),
            )
    return {"org_id": org_id, "driver_id": driver_id}


def _seed_driver_trips(dsn: str, *, driver_id: str, org_id: str, count: int) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            for i in range(count):
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
                    (str(uuid.uuid4()), driver_id, org_id, (i % 80) + 1, (i % 80) + 1),
                )


def _seed_legacy_trip_and_case(dsn: str, *, driver_id: str, org_id: str) -> None:
    """One legacy app.trips row + assignment + fraud case (the old denominator)."""
    passenger_id = str(uuid.uuid4())
    vehicle_id = str(uuid.uuid4())
    trip_id = str(uuid.uuid4())
    asgn_id = str(uuid.uuid4())
    case_id = str(uuid.uuid4())
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            cur.execute("INSERT INTO app.passengers (id, organization_id) VALUES (%s, %s);", (passenger_id, org_id))
            cur.execute(
                """
                INSERT INTO app.vehicles (id, organization_id, registration_ref, vehicle_type, service_class, telemetry_source)
                VALUES (%s, %s, %s, 'car', 'standard', 'smartphone');
                """,
                (vehicle_id, org_id, "30B-" + trip_id[:5]),
            )
            cur.execute(
                """
                INSERT INTO app.trips (id, organization_id, passenger_id, requested_at, pickup, dropoff, requested_service_class, status)
                VALUES (%s, %s, %s, now() - interval '10 days',
                        ST_GeogFromText('SRID=4326;POINT(105.85 21.02)'),
                        ST_GeogFromText('SRID=4326;POINT(105.84 21.00)'),
                        'standard', 'completed');
                """,
                (trip_id, org_id, passenger_id),
            )
            cur.execute(
                """
                INSERT INTO app.trip_assignments (id, trip_id, driver_id, vehicle_id, state, offered_at)
                VALUES (%s, %s, %s, %s, 'completed', now() - interval '10 days');
                """,
                (asgn_id, trip_id, driver_id, vehicle_id),
            )
            cur.execute(
                """
                INSERT INTO app.fraud_cases (id, organization_id, assignment_id, status, suspected_category,
                                             priority_tier, priority_score, priority_rule_version)
                VALUES (%s, %s, %s, 'ready', 'ERR-01', 1, 65, 'v1');
                """,
                (case_id, org_id, asgn_id),
            )


@pytest.mark.asyncio
async def test_scorecard_prefers_measured_driver_trips(cs, disposable_db):
    """60 measured trips + 2 legacy cases -> total_trips 60, ratio 3.3 (not 2 / 100.0)."""
    from src.services.driver_service import get_driver_scorecard

    seed = _seed_org_and_driver(disposable_db)
    _seed_driver_trips(disposable_db, driver_id=seed["driver_id"], org_id=seed["org_id"], count=60)
    _seed_legacy_trip_and_case(disposable_db, driver_id=seed["driver_id"], org_id=seed["org_id"])
    _seed_legacy_trip_and_case(disposable_db, driver_id=seed["driver_id"], org_id=seed["org_id"])

    score = await get_driver_scorecard(seed["driver_id"], seed["org_id"], case_service=cs)
    assert score.total_trips == 60, f"measured driver_trips must win, got {score.total_trips}"
    assert score.total_cases == 2
    assert score.violation_ratio_90d == round(2 / 60 * 100, 1)


@pytest.mark.asyncio
async def test_scorecard_falls_back_to_trips_table(cs, disposable_db):
    """No driver_trips rows -> legacy app.trips count preserved."""
    from src.services.driver_service import get_driver_scorecard

    seed = _seed_org_and_driver(disposable_db)
    _seed_legacy_trip_and_case(disposable_db, driver_id=seed["driver_id"], org_id=seed["org_id"])
    _seed_legacy_trip_and_case(disposable_db, driver_id=seed["driver_id"], org_id=seed["org_id"])

    score = await get_driver_scorecard(seed["driver_id"], seed["org_id"], case_service=cs)
    assert score.total_trips == 2, f"fallback trips count must hold, got {score.total_trips}"
    assert score.total_cases == 2
    assert score.violation_ratio_90d == 100.0
