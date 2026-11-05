"""Real PostgreSQL integration test verifying schema-portable PostGIS migration and spatial durability.

Tests that repository migrations run idempotently and safely against both actual
PostGIS schema layouts ('public' and 'extensions'), preserving pre-existing spatial data,
enabling representative telemetry writes/reads, and maintaining schema-only defaults.
"""

from __future__ import annotations

import os
import time
from urllib.parse import urlparse
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import dict_row

from scripts.migrate_postgres import apply_migrations, get_target_connection


def _get_base_dsn() -> str:
    return (
        os.environ.get("TARGET_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("MIGRATION_DATABASE_URL")
        or "postgresql://postgres:postgrespassword@127.0.0.1:5432/postgres"
    )


def _assert_loopback_target(dsn: str) -> None:
    parsed = urlparse(dsn)
    host = (parsed.hostname or "127.0.0.1").lower()
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise RuntimeError(
            f"Safety guard: refusing to run disposable PostGIS integration test against non-loopback host '{host}'"
        )


def is_postgres_available() -> bool:
    try:
        base_dsn = _get_base_dsn()
        _assert_loopback_target(base_dsn)
        with psycopg.connect(base_dsn, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                return bool(cur.fetchone())
    except Exception:
        return False


pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        not is_postgres_available(),
        reason="PostgreSQL engine not reachable on loopback",
    ),
]


def _create_disposable_postgis_db(layout_schema: str):
    """Helper creating a disposable database with PostGIS in the specified schema ('public' or 'extensions')."""
    base_dsn = _get_base_dsn()
    _assert_loopback_target(base_dsn)

    stamp = int(time.time() * 1000)
    dbname = f"test_p063_spatial_{layout_schema}_{stamp}"

    parsed = urlparse(base_dsn)
    user = parsed.username or "postgres"
    password = parsed.password or "postgrespassword"
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 5432

    admin_dsn = f"postgresql://{user}:{password}@{host}:{port}/postgres"

    with psycopg.connect(admin_dsn, autocommit=True) as root_conn:
        with root_conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {};").format(sql.Identifier(dbname)))

    target_dsn = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"

    # Setup pre-existing PostGIS in the chosen schema with pre-existing spatial data
    with psycopg.connect(target_dsn, autocommit=True) as setup_conn:
        with setup_conn.cursor() as cur:
            if layout_schema == "extensions":
                cur.execute("CREATE SCHEMA IF NOT EXISTS extensions;")
                cur.execute("CREATE EXTENSION postgis WITH SCHEMA extensions;")
                cur.execute("SET search_path = extensions, public;")
            else:
                cur.execute("CREATE EXTENSION postgis WITH SCHEMA public;")
                cur.execute("SET search_path = public;")

            cur.execute(
                """
                CREATE TABLE public.legacy_spatial_fleet (
                    id serial PRIMARY KEY,
                    vehicle_callsign text NOT NULL,
                    last_known_location geography(Point, 4326) NOT NULL
                );
                """
            )
            cur.execute(
                """
                INSERT INTO public.legacy_spatial_fleet (vehicle_callsign, last_known_location)
                VALUES
                    ('HN-CAB-101', ST_SetSRID(ST_MakePoint(105.8542, 21.0285), 4326)::geography),
                    ('HN-CAB-202', ST_SetSRID(ST_MakePoint(105.8048, 21.0073), 4326)::geography);
                """
            )

    return target_dsn, dbname, admin_dsn


def _teardown_disposable_db(admin_dsn: str, dbname: str) -> None:
    with psycopg.connect(admin_dsn, autocommit=True) as root_conn:
        with root_conn.cursor() as cur:
            cur.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid();
                """,
                (dbname,),
            )
            cur.execute(sql.SQL("DROP DATABASE IF EXISTS {};").format(sql.Identifier(dbname)))


def _verify_postgis_migration_and_telemetry(db_dsn: str, expected_schema: str) -> None:
    """Core verification proving migrations, data preservation, and telemetry read/write."""
    # 1. Apply migrations
    conn = get_target_connection(db_dsn)
    try:
        apply_migrations(conn, target_url=db_dsn)
    finally:
        conn.close()

    # 2. Verify schema invariants
    with psycopg.connect(db_dsn) as check_conn:
        with check_conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")

            # 2.1 PostGIS extension remains in expected_schema without relocation
            cur.execute(
                "SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace WHERE e.extname = 'postgis';"
            )
            ext_row = cur.fetchone()
            assert ext_row is not None, "PostGIS extension must exist"
            assert ext_row[0] == expected_schema, f"PostGIS extension must remain in '{expected_schema}'"

            # 2.2 Geography type remains in expected_schema
            cur.execute(
                "SELECT n.nspname FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace WHERE t.typname = 'geography';"
            )
            assert cur.fetchone()[0] == expected_schema, f"Geography type must reside in '{expected_schema}'"

            # 2.3 Pre-existing spatial table and nonempty data are completely preserved
            cur.execute(
                "SELECT vehicle_callsign, ST_AsText(last_known_location) FROM public.legacy_spatial_fleet ORDER BY id;"
            )
            fleet_rows = cur.fetchall()
            assert len(fleet_rows) == 2, "All pre-existing spatial rows must be preserved"
            assert fleet_rows[0] == ("HN-CAB-101", "POINT(105.8542 21.0285)")
            assert fleet_rows[1] == ("HN-CAB-202", "POINT(105.8048 21.0073)")

            # 2.4 Application tables created properly
            cur.execute("SELECT to_regclass('app.trips');")
            assert cur.fetchone()[0] is not None, "app.trips table must be created by migrations"
            cur.execute("SELECT to_regclass('app.telemetry_points');")
            assert cur.fetchone()[0] is not None, "app.telemetry_points table must be created by migrations"

            # 2.5 Default migrator must never seed mock records
            cur.execute("SELECT count(*) FROM app.passengers;")
            assert cur.fetchone()[0] == 0, "Default migration must never seed mock passengers"
            cur.execute("SELECT count(*) FROM app.drivers;")
            assert cur.fetchone()[0] == 0, "Default migration must never seed mock drivers"
            cur.execute("SELECT count(*) FROM app.trips;")
            assert cur.fetchone()[0] == 0, "Default migration must never seed mock trips"

    # 3. Representative telemetry write and read
    with psycopg.connect(db_dsn, row_factory=dict_row) as app_conn:
        with app_conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            org_id = str(uuid4())
            passenger_id = str(uuid4())
            driver_id = str(uuid4())
            vehicle_id = str(uuid4())
            trip_id = str(uuid4())
            assignment_id = str(uuid4())
            event_id = str(uuid4())

            cur.execute("INSERT INTO app.organizations (id, name) VALUES (%s, 'Test Org');", (org_id,))
            cur.execute(
                "INSERT INTO app.passengers (id, organization_id, external_ref) VALUES (%s, %s, 'pax-1');",
                (passenger_id, org_id),
            )
            cur.execute(
                "INSERT INTO app.drivers (id, organization_id, external_ref, partner_type) VALUES (%s, %s, 'drv-1', 'owner_driver');",
                (driver_id, org_id),
            )
            cur.execute(
                "INSERT INTO app.vehicles (id, organization_id, registration_ref, vehicle_type, service_class, telemetry_source) VALUES (%s, %s, '29A-12345', 'car', 'car_standard', 'smartphone');",
                (vehicle_id, org_id),
            )

            # Insert trip with geography points
            cur.execute(
                """
                INSERT INTO app.trips (
                    id, organization_id, passenger_id, requested_at, pickup, dropoff,
                    requested_service_class, status
                ) VALUES (
                    %s, %s, %s, now(),
                    ST_SetSRID(ST_MakePoint(105.8542, 21.0285), 4326)::geography,
                    ST_SetSRID(ST_MakePoint(105.7839, 21.0167), 4326)::geography,
                    'car_standard', 'in_progress'
                );
                """,
                (trip_id, org_id, passenger_id),
            )

            cur.execute(
                """
                INSERT INTO app.trip_assignments (
                    id, trip_id, driver_id, vehicle_id, state, offered_at
                ) VALUES (%s, %s, %s, %s, 'accepted', now());
                """,
                (assignment_id, trip_id, driver_id, vehicle_id),
            )

            correlation_id = str(uuid4())
            # Ingest event & telemetry point with geography point
            cur.execute(
                """
                INSERT INTO app.ingest_events (
                    event_id, organization_id, schema_version, event_type, source, occurred_at,
                    correlation_id, trip_id, assignment_id, driver_id, producer_sequence, payload, payload_hash
                ) VALUES (
                    %s, %s, 1, 'telemetry.frame', 'driver_app', now(),
                    %s, %s, %s, %s, 1, '{}'::jsonb, '\\x00'::bytea
                );
                """,
                (event_id, org_id, correlation_id, trip_id, assignment_id, driver_id),
            )

            cur.execute(
                """
                INSERT INTO app.telemetry_points (
                    event_id, assignment_id, occurred_at, position, speed_mps, bearing_deg
                ) VALUES (
                    %s, %s, now(),
                    ST_SetSRID(ST_MakePoint(105.8500, 21.0250), 4326)::geography,
                    8.5, 45.0
                );
                """,
                (event_id, assignment_id),
            )
            app_conn.commit()

            # Read back and verify spatial resolution
            cur.execute(
                """
                SELECT ST_AsGeoJSON(pickup)::jsonb AS pickup_geo,
                       ST_AsGeoJSON(dropoff)::jsonb AS dropoff_geo
                FROM app.trips WHERE id = %s;
                """,
                (trip_id,),
            )
            trip_row = cur.fetchone()
            assert trip_row is not None
            assert trip_row["pickup_geo"]["coordinates"] == [105.8542, 21.0285]
            assert trip_row["dropoff_geo"]["coordinates"] == [105.7839, 21.0167]

            cur.execute(
                """
                SELECT ST_X(position::geometry) AS lon,
                       ST_Y(position::geometry) AS lat,
                       speed_mps
                FROM app.telemetry_points WHERE event_id = %s;
                """,
                (event_id,),
            )
            tp_row = cur.fetchone()
            assert tp_row is not None
            assert abs(float(tp_row["lon"]) - 105.8500) < 1e-4
            assert abs(float(tp_row["lat"]) - 21.0250) < 1e-4
            assert float(tp_row["speed_mps"]) == 8.5


def test_postgis_public_layout_migration_and_spatial_durability():
    """Verify migrations and telemetry read/write succeed with PostGIS in 'public' schema."""
    target_dsn, dbname, admin_dsn = _create_disposable_postgis_db("public")
    try:
        _verify_postgis_migration_and_telemetry(target_dsn, "public")
    finally:
        _teardown_disposable_db(admin_dsn, dbname)


def test_postgis_extensions_layout_migration_and_spatial_durability():
    """Verify migrations and telemetry read/write succeed with PostGIS in 'extensions' schema."""
    target_dsn, dbname, admin_dsn = _create_disposable_postgis_db("extensions")
    try:
        _verify_postgis_migration_and_telemetry(target_dsn, "extensions")
    finally:
        _teardown_disposable_db(admin_dsn, dbname)
