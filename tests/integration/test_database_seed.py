"""
Integration test to verify full database schema and seed integrity in Supabase/Postgres.
"""

import os

try:
    import psycopg
except ImportError:
    psycopg = None
import pytest
from dotenv import load_dotenv

pytestmark = pytest.mark.docker


@pytest.fixture(scope="module")
def db_conn():
    if psycopg is None:
        pytest.skip("psycopg is not installed")
    load_dotenv()
    required_target = os.environ.get("ISSUE63_DATABASE_URL")
    required = bool(required_target)
    db_url = required_target or os.environ.get("DATABASE_URL") or os.environ.get("MIGRATION_DATABASE_URL")
    if not db_url or "localhost:5432/dbname" in db_url:
        db_url = "postgresql://postgres:postgres@localhost:54322/postgres"

    conn = None
    for _ in range(5):
        try:
            conn = psycopg.connect(db_url)
            break
        except Exception:
            import time

            time.sleep(1)

    if conn is None:
        if required:
            pytest.fail("Required seed proof database is unavailable")
        pytest.skip("Optional seed proof database is unavailable")

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_schema = 'app' AND table_name = 'passengers';"
            )
            if not cur.fetchone():
                conn.close()
                if required:
                    pytest.fail("Required seed proof schema app.passengers is missing")
                pytest.skip("Optional seed proof schema app.passengers is missing")
        yield conn
        conn.close()
    except Exception as exc:
        if required:
            pytest.fail(f"Required seed proof database operation failed: {type(exc).__name__}")
        pytest.skip(f"Optional seed proof database operation failed: {type(exc).__name__}")


def test_database_table_counts(db_conn):
    with db_conn.cursor() as cur:
        # Check users / passengers count
        cur.execute("SELECT count(*) FROM app.passengers;")
        assert cur.fetchone()[0] == 50, "Expected 50 passengers"

        # Check drivers count
        cur.execute("SELECT count(*) FROM app.drivers;")
        assert cur.fetchone()[0] == 20, "Expected 20 drivers"

        # Check fraud analysts count
        cur.execute(
            "SELECT count(*) FROM app.principal_roles WHERE role IN ('analyst', 'senior_analyst', 'demo_operator', 'admin');"
        )
        assert cur.fetchone()[0] == 10, "Expected 10 fraud analysts"

        # Check trips count
        cur.execute("SELECT count(*) FROM app.trips;")
        assert cur.fetchone()[0] >= 100, "Expected at least 100 trips"

        # Check fraud cases count
        cur.execute("SELECT count(*) FROM app.fraud_cases;")
        assert cur.fetchone()[0] >= 100, "Expected at least 100 fraud cases"

        # Check telemetry count
        cur.execute("SELECT count(*) FROM app.telemetry_points;")
        assert cur.fetchone()[0] >= 1000, "Expected at least 1000 telemetry points"


def test_database_spatial_integrity(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SET search_path = app, extensions, public;")
        cur.execute("""
            SELECT ST_AsText(pickup), ST_AsText(dropoff)
            FROM app.trips
            LIMIT 5;
        """)
        rows = cur.fetchall()
        assert len(rows) == 5
        for pickup, dropoff in rows:
            assert pickup.startswith("POINT("), f"Invalid pickup geometry: {pickup}"
            assert dropoff.startswith("POINT("), f"Invalid dropoff geometry: {dropoff}"
