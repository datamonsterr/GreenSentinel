"""Backend smoke tests for driver profile and trips endpoints (BUG 2 (d)).

Hits /api/v1/driver/profile and /api/v1/driver/trips with a test driver principal
against disposable PostgreSQL.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient
from psycopg import sql

from scripts.migrate_postgres import apply_migrations, get_target_connection
from src.config import Settings, get_settings
from src.main import app
from src.services.case_service import CaseService, get_case_service
from tests.integration.conftest import assert_loopback_target, get_base_dsn, is_postgres_available

pytestmark = [
    pytest.mark.docker,
    pytest.mark.integration,
    pytest.mark.skipif(
        not is_postgres_available(),
        reason="PostgreSQL engine not reachable on loopback; set DATABASE_URL to run this suite",
    ),
]


@pytest.fixture(scope="module")
def smoke_db():
    """Seed disposable Postgres with a test driver and trips for backend smoke testing."""
    base_dsn = get_base_dsn()
    assert_loopback_target(base_dsn)

    stamp = int(time.time() * 1000)
    dbname = f"test_greensentinel_smoke_{stamp}"

    parsed = urlparse(base_dsn)
    user = parsed.username or "postgres"
    password = parsed.password or "postgrespassword"
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 5432
    admin_dsn = f"postgresql://{user}:{password}@{host}:{port}/postgres"
    target_dsn = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"

    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {};").format(sql.Identifier(dbname)))

    mig_conn = get_target_connection(target_dsn)
    try:
        apply_migrations(mig_conn, target_url=target_dsn)
    finally:
        mig_conn.close()
    org_id = str(uuid.uuid4())
    p_id = str(uuid.uuid4())
    d_id = str(uuid.uuid4())
    v_id = str(uuid.uuid4())

    now = datetime.now(UTC)

    with psycopg.connect(target_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            cur.execute("INSERT INTO app.organizations (id, name) VALUES (%s, 'Smoke Org');", (org_id,))
            cur.execute(
                """
                INSERT INTO app.principals (id, organization_id, external_subject, display_name, status)
                VALUES (%s, %s, %s, 'Smoke Test Driver', 'active');
                """,
                (p_id, org_id, f"auth|{p_id[:8]}"),
            )
            cur.execute("INSERT INTO app.principal_roles (principal_id, role) VALUES (%s, 'driver');", (p_id,))
            cur.execute(
                """
                INSERT INTO app.drivers (id, organization_id, principal_id, external_ref, partner_type, display_name)
                VALUES (%s, %s, %s, 'DRV-SMOKE-01', 'owner_driver', 'Smoke Test Driver');
                """,
                (d_id, org_id, p_id),
            )
            cur.execute(
                """
                INSERT INTO app.vehicles (id, organization_id, registration_ref, vehicle_type, service_class, telemetry_source)
                VALUES (%s, %s, '29A-SMOKE', 'car', 'VinFast VF e34', 'smartphone');
                """,
                (v_id, org_id),
            )
            cur.execute(
                "INSERT INTO app.driver_vehicle_assignments (driver_id, vehicle_id, effective_from) VALUES (%s, %s, now());",
                (d_id, v_id),
            )

            trip_id = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO app.driver_trips (
                    trip_id, driver_id, organization_id, pickup_label, dropoff_label,
                    started_at, ended_at, distance_km, duration_min, fare_vnd,
                    payment_method, payment_method_synthetic, status
                ) VALUES (%s, %s, %s, 'Smoke Pickup', 'Smoke Dropoff', %s, %s, 10.0, 20.0, 100000, 'wallet', false, 'completed');
                """,
                (trip_id, d_id, org_id, now.isoformat(), (now + timedelta(minutes=20)).isoformat()),
            )

    yield {
        "dsn": target_dsn,
        "org_id": org_id,
        "p_id": p_id,
        "d_id": d_id,
    }

    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid()
                """,
                (dbname,),
            )
            cur.execute(sql.SQL("DROP DATABASE IF EXISTS {};").format(sql.Identifier(dbname)))


@pytest.mark.asyncio
async def test_backend_smoke_driver_profile_and_trips(smoke_db, monkeypatch):
    """Smoke test: verify /api/v1/driver/profile and /api/v1/driver/trips return 200 with test driver principal."""
    real_dsn = smoke_db["dsn"]
    monkeypatch.setenv("DATABASE_URL", real_dsn)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("TEST_AUTH_ENABLED", "true")

    get_settings.cache_clear()
    settings = Settings(database_url=real_dsn, app_env="test", test_auth_enabled=True)
    real_cs = CaseService(settings=settings)

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_case_service] = lambda: real_cs

    headers = {
        "x-principal-id": smoke_db["p_id"],
        "x-driver-id": smoke_db["d_id"],
        "x-organization-id": smoke_db["org_id"],
        "x-role": "driver",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Hit /api/v1/driver/profile
        res_profile = await client.get("/api/v1/driver/profile", headers=headers)
        assert res_profile.status_code == 200
        profile_json = res_profile.json()
        assert profile_json["driver_id"] == smoke_db["d_id"]
        assert profile_json["display_name"] == "Smoke Test Driver"
        assert profile_json["vehicle"]["plate"] == "29A-SMOKE"

        # Hit /api/v1/driver/trips
        res_trips = await client.get("/api/v1/driver/trips", headers=headers)
        assert res_trips.status_code == 200
        trips_json = res_trips.json()
        assert trips_json["total"] >= 1
        assert len(trips_json["trips"]) >= 1
        assert trips_json["trips"][0]["driver_id"] == smoke_db["d_id"]

    app.dependency_overrides.clear()
    get_settings.cache_clear()
