"""Integration tests for driver_trips and trip_ratings PostgreSQL tables, migrations, and seed script (Issue #478).

Runs all operations inside disposable schemas (CREATE SCHEMA test_<uuid>, drop at teardown).
Never touches or drops app.* on a shared DB.
Skips clearly when DATABASE_URL is unset.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import psycopg
import pytest

from tests.integration.conftest import DsnCaseService

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    pytest.skip("DATABASE_URL unset", allow_module_level=True)

# Safety check: if DB name does not end with _test and disposable schema is not used, skip.
parsed_url = urlparse(DATABASE_URL)
DB_NAME = parsed_url.path.lstrip("/")
IS_TEST_DB = DB_NAME.endswith("_test")

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = REPO_ROOT / "db" / "migrations" / "20261017100000_driver_trips_ratings.sql"
ROLLBACK_PATH = REPO_ROOT / "db" / "rollbacks" / "20261017100000_driver_trips_ratings.down.sql"


@pytest.fixture(scope="module")
def db_conn():
    """Module-level postgres connection."""
    conn = psycopg.connect(DATABASE_URL, autocommit=True)
    yield conn
    conn.close()


@pytest.fixture
def disposable_schema(db_conn: psycopg.Connection):
    """Disposable schema ensuring tests run isolated and never touch or drop app.*."""
    schema = f"test_{uuid4().hex[:12]}"
    with db_conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA {schema};")
        cur.execute(f"SET search_path = {schema}, public;")
    try:
        yield schema
    finally:
        with db_conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE;")


def load_scoped_migration_sql(schema: str) -> str:
    """Load migration SQL scoped to the disposable schema instead of app.*."""
    raw = MIGRATION_PATH.read_text(encoding="utf-8")
    return raw.replace("app.", f"{schema}.").replace(
        "CREATE SCHEMA IF NOT EXISTS app;", f"CREATE SCHEMA IF NOT EXISTS {schema};"
    )


def load_scoped_rollback_sql(schema: str) -> str:
    """Load rollback SQL scoped to the disposable schema instead of app.*."""
    raw = ROLLBACK_PATH.read_text(encoding="utf-8")
    return raw.replace("app.", f"{schema}.")


def test_migration_and_rollback_clean(db_conn: psycopg.Connection, disposable_schema: str):
    """Verify migration applies cleanly, rollback drops tables cleanly, and re-applying works inside disposable schema."""
    schema = disposable_schema
    with db_conn.cursor() as cur:
        # Apply migration inside disposable schema
        cur.execute(load_scoped_migration_sql(schema))

        # Verify tables exist in disposable schema
        cur.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = %s AND table_name IN ('driver_trips', 'trip_ratings');
            """,
            (schema,),
        )
        tables = {row[0] for row in cur.fetchall()}
        assert "driver_trips" in tables
        assert "trip_ratings" in tables

        # Verify indexes exist in disposable schema
        cur.execute(
            """
            SELECT indexname FROM pg_indexes
            WHERE schemaname = %s AND tablename = 'driver_trips';
            """,
            (schema,),
        )
        indexes = {row[0] for row in cur.fetchall()}
        assert "idx_driver_trips_driver_started" in indexes
        assert "idx_driver_trips_case_id" in indexes
        # Review findings: unnecessary indexes dropped
        assert "idx_driver_trips_org_driver" not in indexes

        # Apply rollback in disposable schema
        cur.execute(load_scoped_rollback_sql(schema))

        # Verify tables dropped
        cur.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = %s AND table_name IN ('driver_trips', 'trip_ratings');
            """,
            (schema,),
        )
        tables_after = {row[0] for row in cur.fetchall()}
        assert "driver_trips" not in tables_after
        assert "trip_ratings" not in tables_after

        # Re-apply migration for subsequent tests
        cur.execute(load_scoped_migration_sql(schema))


def test_table_constraints_and_nullability(db_conn: psycopg.Connection, disposable_schema: str):
    """Verify check constraint on stars (1..5) and nullability inside disposable schema."""
    schema = disposable_schema
    with db_conn.cursor() as cur:
        # Re-apply migration
        cur.execute(load_scoped_migration_sql(schema))

        test_trip_id = str(uuid4())
        test_driver_id = str(uuid4())
        test_org_id = "018f2f4e-b000-7000-8000-000000000001"

        # Insert a trip
        cur.execute(
            f"""
            INSERT INTO {schema}.driver_trips (
                trip_id, driver_id, organization_id, pickup_label, pickup_lat, pickup_lng,
                dropoff_label, dropoff_lat, dropoff_lng, started_at, ended_at,
                distance_km, duration_min, fare_vnd, payment_method, payment_method_synthetic,
                status, fraud_label, case_id
            ) VALUES (
                %s, %s, %s, 'Pickup', 21.0, 105.8,
                'Dropoff', 20.9, 105.8, now(), now(),
                5.0, 15.0, 50000, 'wallet', true, 'completed', 'no_violation', NULL
            );
            """,
            (test_trip_id, test_driver_id, test_org_id),
        )

        # Insert rating with NULL stars, valid comment, default source='seed'
        cur.execute(
            f"""
            INSERT INTO {schema}.trip_ratings (trip_id, stars, comment, locale)
            VALUES (%s, NULL, 'Chuyến đi ổn', 'vi');
            """,
            (test_trip_id,),
        )

        # Check row
        cur.execute(f"SELECT stars, comment, source FROM {schema}.trip_ratings WHERE trip_id = %s;", (test_trip_id,))
        row = cur.fetchone()
        assert row[0] is None
        assert row[1] == "Chuyến đi ổn"
        assert row[2] == "seed"

        # Update rating with valid stars (1..5) and NULL comment
        cur.execute(
            f"""
            UPDATE {schema}.trip_ratings
            SET stars = 5, comment = NULL
            WHERE trip_id = %s;
            """,
            (test_trip_id,),
        )
        cur.execute(f"SELECT stars, comment FROM {schema}.trip_ratings WHERE trip_id = %s;", (test_trip_id,))
        row = cur.fetchone()
        assert row[0] == 5
        assert row[1] is None

        # Inserting stars < 1 must violate CHECK constraint
        with pytest.raises(psycopg.Error):
            cur.execute(
                f"""
                UPDATE {schema}.trip_ratings
                SET stars = 0
                WHERE trip_id = %s;
                """,
                (test_trip_id,),
            )

        # Inserting stars > 5 must violate CHECK constraint
        with pytest.raises(psycopg.Error):
            cur.execute(
                f"""
                UPDATE {schema}.trip_ratings
                SET stars = 6
                WHERE trip_id = %s;
                """,
                (test_trip_id,),
            )


def test_seed_driver_trips_idempotent_and_deterministic(db_conn: psycopg.Connection, disposable_schema: str):
    """Seed script runs against Postgres idempotently: assert exact row counts and compare DB row hashes."""
    from scripts.seed.seed_driver_trips import seed_driver_trips

    schema = disposable_schema
    with db_conn.cursor() as cur:
        cur.execute(load_scoped_migration_sql(schema))

    sample_path = REPO_ROOT / "data" / "benchmark-10k" / "v1" / "sample_100.jsonl"
    assert sample_path.exists()

    # Seed run 1
    stats1 = seed_driver_trips(
        conn=db_conn,
        jsonl_path=sample_path,
        seed=42,
        batch_size=50,
        schema=schema,
    )

    assert stats1["trips_count"] == 100
    assert stats1["ratings_count"] > 0

    # SELECT ordered rows from both tables and compute hash after run 1
    with db_conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT trip_id, driver_id, organization_id, pickup_label, pickup_lat, pickup_lng,
                   dropoff_label, dropoff_lat, dropoff_lng, started_at, ended_at,
                   distance_km, duration_min, fare_vnd, payment_method, payment_method_synthetic,
                   status, fraud_label, case_id
            FROM {schema}.driver_trips ORDER BY trip_id;
            """
        )
        trips_run1 = cur.fetchall()

        cur.execute(
            f"""
            SELECT trip_id, stars, comment, locale, source
            FROM {schema}.trip_ratings ORDER BY trip_id;
            """
        )
        ratings_run1 = cur.fetchall()

    # Assert exact row counts after run 1
    assert len(trips_run1) == 100
    assert len(ratings_run1) == stats1["ratings_count"]

    db_hash1 = hashlib.sha256((repr(trips_run1) + ":" + repr(ratings_run1)).encode("utf-8")).hexdigest()

    # Seed run 2 (idempotent re-run with same seed)
    stats2 = seed_driver_trips(
        conn=db_conn,
        jsonl_path=sample_path,
        seed=42,
        batch_size=50,
        schema=schema,
    )

    assert stats2["trips_count"] == 100
    assert stats2["ratings_count"] == stats1["ratings_count"]

    # SELECT ordered rows from both tables and compute hash after run 2
    with db_conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT trip_id, driver_id, organization_id, pickup_label, pickup_lat, pickup_lng,
                   dropoff_label, dropoff_lat, dropoff_lng, started_at, ended_at,
                   distance_km, duration_min, fare_vnd, payment_method, payment_method_synthetic,
                   status, fraud_label, case_id
            FROM {schema}.driver_trips ORDER BY trip_id;
            """
        )
        trips_run2 = cur.fetchall()

        cur.execute(
            f"""
            SELECT trip_id, stars, comment, locale, source
            FROM {schema}.trip_ratings ORDER BY trip_id;
            """
        )
        ratings_run2 = cur.fetchall()

    # Assert exact row counts after run 2
    assert len(trips_run2) == 100
    assert len(ratings_run2) == stats1["ratings_count"]

    db_hash2 = hashlib.sha256((repr(trips_run2) + ":" + repr(ratings_run2)).encode("utf-8")).hexdigest()

    # Determinism assertion: hashes and rows must match exactly
    assert db_hash1 == db_hash2, "Re-running seed with same seed must yield identical DB row hash"
    assert trips_run1 == trips_run2, "driver_trips rows must match identically"
    assert ratings_run1 == ratings_run2, "trip_ratings rows must match identically"

    # Verify non-seed ratings are never overwritten
    test_trip = trips_run1[0][0]
    with db_conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {schema}.trip_ratings
            SET stars = 5, comment = 'User manual rating', source = 'user'
            WHERE trip_id = %s;
            """,
            (test_trip,),
        )

    # Re-run seed: must NOT overwrite user rating
    seed_driver_trips(conn=db_conn, jsonl_path=sample_path, seed=42, batch_size=50, schema=schema)
    with db_conn.cursor() as cur:
        cur.execute(
            f"SELECT stars, comment, source FROM {schema}.trip_ratings WHERE trip_id = %s;",
            (test_trip,),
        )
        user_row = cur.fetchone()
        assert user_row == (5, "User manual rating", "user"), "Non-seed user rating must be preserved"


@pytest.mark.asyncio
async def test_list_driver_trips_keyset_pagination_sql(disposable_database_dsn: str):
    """Verify keyset pagination in SQL path (WHERE (started_at, trip_id) < (cursor)).

    Uses a disposable *database* (not a disposable schema) because
    src/services/driver_service.py hardcodes `SET search_path = app, ...`
    on every query, which would otherwise bypass a schema-scoped fixture.
    """
    from src.services.driver_service import (
        decode_trip_cursor,
        list_driver_trips,
    )

    driver_id = "018f2f4e-b300-7000-8000-000000000001"
    org_id = "018f2f4e-0000-7000-8000-000000000001"

    with psycopg.connect(disposable_database_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, public;")
            for i in range(5):
                tid = f"018f2f4e-b100-7000-8000-00000000000{i}"
                cur.execute(
                    """
                    INSERT INTO app.driver_trips (
                        trip_id, driver_id, organization_id, pickup_label, dropoff_label,
                        started_at, ended_at, distance_km, duration_min, fare_vnd, status
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, 10.0, 20.0, 100000, 'completed'
                    );
                    """,
                    (
                        tid,
                        driver_id,
                        org_id,
                        f"Pickup {i}",
                        f"Dropoff {i}",
                        f"2026-10-15T0{i + 1}:00:00+00:00",
                        f"2026-10-15T0{i + 1}:30:00+00:00",
                    ),
                )

    mock_cs = DsnCaseService(disposable_database_dsn)

    # Page 1: limit=2 (should get trips 4 and 3 in descending order)
    p1 = await list_driver_trips(driver_id=driver_id, limit=2, case_service=mock_cs)
    assert len(p1["trips"]) == 2
    assert p1["trips"][0]["trip_id"] == "018f2f4e-b100-7000-8000-000000000004"
    assert p1["trips"][1]["trip_id"] == "018f2f4e-b100-7000-8000-000000000003"
    assert p1["next_cursor"] is not None

    # Cursor should be opaque base64 string
    assert not p1["next_cursor"].isdigit()
    decoded = decode_trip_cursor(p1["next_cursor"])
    assert decoded is not None
    assert decoded[1] == "018f2f4e-b100-7000-8000-000000000003"

    # Page 2: with cursor (should get trips 2 and 1)
    p2 = await list_driver_trips(driver_id=driver_id, cursor=p1["next_cursor"], limit=2, case_service=mock_cs)
    assert len(p2["trips"]) == 2
    assert p2["trips"][0]["trip_id"] == "018f2f4e-b100-7000-8000-000000000002"
    assert p2["trips"][1]["trip_id"] == "018f2f4e-b100-7000-8000-000000000001"
    assert p2["next_cursor"] is not None

    # Page 3: with cursor (should get trip 0)
    p3 = await list_driver_trips(driver_id=driver_id, cursor=p2["next_cursor"], limit=2, case_service=mock_cs)
    assert len(p3["trips"]) == 1
    assert p3["trips"][0]["trip_id"] == "018f2f4e-b100-7000-8000-000000000000"
    assert p3["next_cursor"] is None

    # total and counts are stable across every page (independent of cursor).
    assert p1["total"] == p2["total"] == p3["total"] == 5
    assert p1["counts"] == p2["counts"] == p3["counts"]
    assert p1["counts"]["all"] == 5


@pytest.mark.asyncio
async def test_list_driver_trips_keyset_pagination_ties_on_started_at_sql(disposable_database_dsn: str):
    """Keyset pagination disambiguates rows sharing the exact same started_at via trip_id tiebreak."""
    from src.services.driver_service import list_driver_trips

    driver_id = "018f2f4e-b400-7000-8000-000000000001"
    org_id = "018f2f4e-0000-7000-8000-000000000001"
    same_started_at = "2026-10-15T05:00:00+00:00"

    with psycopg.connect(disposable_database_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, public;")
            for i in range(3):
                tid = f"018f2f4e-b200-7000-8000-00000000000{i}"
                cur.execute(
                    """
                    INSERT INTO app.driver_trips (
                        trip_id, driver_id, organization_id, pickup_label, dropoff_label,
                        started_at, ended_at, distance_km, duration_min, fare_vnd, status
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, 10.0, 20.0, 100000, 'completed'
                    );
                    """,
                    (
                        tid,
                        driver_id,
                        org_id,
                        f"Pickup {i}",
                        f"Dropoff {i}",
                        same_started_at,
                        same_started_at,
                    ),
                )

    mock_cs = DsnCaseService(disposable_database_dsn)

    seen_ids: list[str] = []
    cursor = None
    for _ in range(4):
        page = await list_driver_trips(driver_id=driver_id, cursor=cursor, limit=2, case_service=mock_cs)
        seen_ids.extend(t["trip_id"] for t in page["trips"])
        cursor = page["next_cursor"]
        if not cursor:
            break

    # All 3 tied rows are returned exactly once across pages (no skip/duplicate on ties).
    assert sorted(seen_ids) == [
        "018f2f4e-b200-7000-8000-000000000000",
        "018f2f4e-b200-7000-8000-000000000001",
        "018f2f4e-b200-7000-8000-000000000002",
    ]


@pytest.mark.asyncio
async def test_driver_trips_month_tz_boundary_sql(disposable_database_dsn: str):
    """Month filter uses Asia/Ho_Chi_Minh half-open boundaries, not UTC prefix matching."""
    from src.services.driver_service import list_driver_trips

    driver_id = "018f2f4e-b500-7000-8000-000000000001"
    org_id = "018f2f4e-0000-7000-8000-000000000001"

    # 2026-10-31T17:30:00Z == 2026-11-01T00:30:00+07:00 -> belongs to November in VN time,
    # even though its UTC date string starts with "2026-10".
    boundary_trip_id = "018f2f4e-b600-7000-8000-000000000001"
    october_trip_id = "018f2f4e-b600-7000-8000-000000000002"

    with psycopg.connect(disposable_database_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, public;")
            for tid, started_at in (
                (boundary_trip_id, "2026-10-31T17:30:00+00:00"),
                (october_trip_id, "2026-10-31T10:00:00+00:00"),  # 2026-10-31T17:00+07:00, still October
            ):
                cur.execute(
                    """
                    INSERT INTO app.driver_trips (
                        trip_id, driver_id, organization_id, pickup_label, dropoff_label,
                        started_at, ended_at, distance_km, duration_min, fare_vnd, status
                    ) VALUES (
                        %s, %s, %s, 'Pickup', 'Dropoff', %s, %s, 10.0, 20.0, 100000, 'completed'
                    );
                    """,
                    (tid, driver_id, org_id, started_at, started_at),
                )

    mock_cs = DsnCaseService(disposable_database_dsn)

    october = await list_driver_trips(driver_id=driver_id, month="2026-10", case_service=mock_cs)
    november = await list_driver_trips(driver_id=driver_id, month="2026-11", case_service=mock_cs)

    october_ids = {t["trip_id"] for t in october["trips"]}
    november_ids = {t["trip_id"] for t in november["trips"]}

    assert october_trip_id in october_ids
    assert boundary_trip_id not in october_ids
    assert boundary_trip_id in november_ids


@pytest.mark.asyncio
async def test_driver_trip_detail_malformed_and_foreign_id_both_404_sql(disposable_database_dsn: str):
    """GET single trip: malformed (non-UUID) id and foreign-driver id both 404, never 503."""
    from src.services.driver_service import get_driver_trip_summary

    owner_driver_id = "018f2f4e-b700-7000-8000-000000000001"
    other_driver_id = "018f2f4e-b700-7000-8000-000000000002"
    org_id = "018f2f4e-0000-7000-8000-000000000001"
    trip_id = "018f2f4e-b800-7000-8000-000000000001"

    with psycopg.connect(disposable_database_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, public;")
            cur.execute(
                """
                INSERT INTO app.driver_trips (
                    trip_id, driver_id, organization_id, pickup_label, dropoff_label,
                    started_at, ended_at, distance_km, duration_min, fare_vnd, status
                ) VALUES (
                    %s, %s, %s, 'Pickup', 'Dropoff', now(), now(), 10.0, 20.0, 100000, 'completed'
                );
                """,
                (trip_id, owner_driver_id, org_id),
            )

    mock_cs = DsnCaseService(disposable_database_dsn)

    from fastapi import HTTPException

    # Malformed trip_id -> 404, never a 503 from an invalid UUID literal reaching Postgres.
    with pytest.raises(HTTPException) as exc_malformed:
        await get_driver_trip_summary(trip_id="not-a-uuid", driver_id=owner_driver_id, case_service=mock_cs)
    assert exc_malformed.value.status_code == 404

    # Foreign driver -> 404 (prevents existence probing).
    with pytest.raises(HTTPException) as exc_foreign:
        await get_driver_trip_summary(trip_id=trip_id, driver_id=other_driver_id, case_service=mock_cs)
    assert exc_foreign.value.status_code == 404

    # Owner -> 200-equivalent (no raise).
    result = await get_driver_trip_summary(trip_id=trip_id, driver_id=owner_driver_id, case_service=mock_cs)
    assert result["trip_id"] == trip_id


def test_seed_demo_driver_trips_idempotent_and_only_demo(db_conn: psycopg.Connection, disposable_schema: str):
    """Seed demo driver trips with --only-demo: assert exact row counts, ratings, and idempotency."""
    from scripts.seed.seed_driver_trips import seed_driver_trips

    schema = disposable_schema
    with db_conn.cursor() as cur:
        cur.execute(load_scoped_migration_sql(schema))

    sample_path = REPO_ROOT / "data" / "benchmark-10k" / "v1" / "sample_100.jsonl"
    assert sample_path.exists()

    demo_driver_id = "018f2f4e-b900-7000-8000-000000000001"
    demo_org_id = "018f2f4e-b900-7000-8000-000000000002"

    # Run 1: only_demo with demo_trip_count=20
    stats1 = seed_driver_trips(
        conn=db_conn,
        jsonl_path=sample_path,
        seed=42,
        batch_size=50,
        schema=schema,
        demo_driver_id=demo_driver_id,
        demo_organization_id=demo_org_id,
        demo_trip_count=20,
        demo_window_days=30,
        demo_anchor="2026-10-19",
        only_demo=True,
    )

    assert stats1["trips_count"] == 20
    assert stats1["demo_trips_count"] == 20
    assert stats1["ratings_count"] > 0

    with db_conn.cursor() as cur:
        # Check only 20 trips exist in table total (bulk 100 trips were skipped)
        cur.execute(f"SELECT count(*) FROM {schema}.driver_trips;")
        assert cur.fetchone()[0] == 20

        # All 20 belong to demo_driver_id and demo_org_id
        cur.execute(
            f"SELECT count(*) FROM {schema}.driver_trips WHERE driver_id = %s AND organization_id = %s;",
            (demo_driver_id, demo_org_id),
        )
        assert cur.fetchone()[0] == 20

        # Ratings exist and match
        cur.execute(f"SELECT count(*) FROM {schema}.trip_ratings WHERE source = 'seed';")
        assert cur.fetchone()[0] == stats1["ratings_count"]

    # Run 2: idempotent re-run with same seed
    stats2 = seed_driver_trips(
        conn=db_conn,
        jsonl_path=sample_path,
        seed=42,
        batch_size=50,
        schema=schema,
        demo_driver_id=demo_driver_id,
        demo_organization_id=demo_org_id,
        demo_trip_count=20,
        demo_window_days=30,
        demo_anchor="2026-10-19",
        only_demo=True,
    )

    assert stats2["trips_count"] == 20
    assert stats2["dataset_hash"] == stats1["dataset_hash"]

    with db_conn.cursor() as cur:
        # Count still exactly 20
        cur.execute(f"SELECT count(*) FROM {schema}.driver_trips;")
        assert cur.fetchone()[0] == 20
        cur.execute(f"SELECT count(*) FROM {schema}.trip_ratings WHERE source = 'seed';")
        assert cur.fetchone()[0] == stats1["ratings_count"]
