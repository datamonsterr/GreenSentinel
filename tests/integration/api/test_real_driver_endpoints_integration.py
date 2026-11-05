"""Real database integration tests for driver endpoints (BUG 2 (a)).

Tests GET /api/v1/driver/profile, GET /api/v1/driver/trips, GET /api/v1/driver/trips/summary
through FastAPI TestClient against disposable Postgres (conftest disposable_database_dsn)
with a real driver Principal (driver_id and organization_id set, principal.id != driver_id),
without mocking driver_service.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

from src.config import Settings, get_settings
from src.main import app
from src.services.case_service import CaseService, get_case_service
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
def seeded_real_db(disposable_database_dsn):
    """Seed disposable Postgres with organizations, principals, drivers, vehicles, trips, and ratings."""
    org_1_id = str(uuid.uuid4())
    org_2_id = str(uuid.uuid4())

    p_1_id = str(uuid.uuid4())
    d_1_id = str(uuid.uuid4())

    p_2_id = str(uuid.uuid4())
    d_2_id = str(uuid.uuid4())

    v_1_id = str(uuid.uuid4())

    now = datetime.now(UTC)

    with psycopg.connect(disposable_database_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")

            # 1. Organizations
            cur.execute("INSERT INTO app.organizations (id, name) VALUES (%s, %s);", (org_1_id, "Org Primary"))
            cur.execute("INSERT INTO app.organizations (id, name) VALUES (%s, %s);", (org_2_id, "Org Secondary"))

            # 2. Principals
            cur.execute(
                """
                INSERT INTO app.principals (id, organization_id, external_subject, display_name, status)
                VALUES (%s, %s, %s, %s, 'active');
                """,
                (p_1_id, org_1_id, f"auth|{p_1_id[:8]}", "Nguyễn Văn Lái"),
            )
            cur.execute(
                "INSERT INTO app.principal_roles (principal_id, role) VALUES (%s, 'driver');",
                (p_1_id,),
            )

            cur.execute(
                """
                INSERT INTO app.principals (id, organization_id, external_subject, display_name, status)
                VALUES (%s, %s, %s, %s, 'active');
                """,
                (p_2_id, org_1_id, f"auth|{p_2_id[:8]}", "Tài Xế Mới Chưa Chạy"),
            )
            cur.execute(
                "INSERT INTO app.principal_roles (principal_id, role) VALUES (%s, 'driver');",
                (p_2_id,),
            )

            # 3. Drivers (driver.id != principal.id)
            cur.execute(
                """
                INSERT INTO app.drivers (id, organization_id, principal_id, external_ref, partner_type, display_name)
                VALUES (%s, %s, %s, %s, 'owner_driver', %s);
                """,
                (d_1_id, org_1_id, p_1_id, "DRV-REAL-001", "Nguyễn Văn Lái"),
            )
            cur.execute(
                """
                INSERT INTO app.drivers (id, organization_id, principal_id, external_ref, partner_type, display_name)
                VALUES (%s, %s, %s, %s, 'owner_driver', %s);
                """,
                (d_2_id, org_1_id, p_2_id, "DRV-REAL-EMPTY", "Tài Xế Mới Chưa Chạy"),
            )

            # 4. Vehicle for Driver 1 only (Driver 2 has no vehicle)
            cur.execute(
                """
                INSERT INTO app.vehicles (id, organization_id, registration_ref, vehicle_type, service_class, telemetry_source)
                VALUES (%s, %s, '29A-888.99', 'car', 'VinFast VF 8', 'smartphone');
                """,
                (v_1_id, org_1_id),
            )
            cur.execute(
                """
                INSERT INTO app.driver_vehicle_assignments (driver_id, vehicle_id, effective_from)
                VALUES (%s, %s, now());
                """,
                (d_1_id, v_1_id),
            )

            # 5. Trips & Ratings for Driver 1 only (Driver 2 has no trips or ratings)
            trips_data = [
                (
                    str(uuid.uuid4()),
                    (now - timedelta(days=2)).isoformat(),
                    (now - timedelta(days=2, minutes=-25)).isoformat(),
                    8.5,
                    22.0,
                    120000,
                    "completed",
                    None,
                    5,
                    "Chuyến đi rất êm ái!",
                ),
                (
                    str(uuid.uuid4()),
                    (now - timedelta(days=8)).isoformat(),
                    (now - timedelta(days=8, minutes=-30)).isoformat(),
                    12.0,
                    35.0,
                    180000,
                    "completed",
                    None,
                    4,
                    "Tài xế lái tốt, xe sạch sẽ.",
                ),
                (
                    str(uuid.uuid4()),
                    (now - timedelta(days=15)).isoformat(),
                    (now - timedelta(days=15, minutes=-15)).isoformat(),
                    5.0,
                    15.0,
                    75000,
                    "flagged",
                    str(uuid.uuid4()),
                    None,
                    None,
                ),
            ]

            for tid, s_at, e_at, dist, dur, fare, status, cid, stars, comment in trips_data:
                cur.execute(
                    """
                    INSERT INTO app.driver_trips (
                        trip_id, driver_id, organization_id, pickup_label, dropoff_label,
                        started_at, ended_at, distance_km, duration_min, fare_vnd,
                        payment_method, payment_method_synthetic, status, case_id
                    ) VALUES (%s, %s, %s, 'Điểm đón A', 'Điểm đến B', %s, %s, %s, %s, %s, 'wallet', false, %s, %s);
                    """,
                    (tid, d_1_id, org_1_id, s_at, e_at, dist, dur, fare, status, cid),
                )
                if stars is not None:
                    cur.execute(
                        """
                        INSERT INTO app.trip_ratings (trip_id, stars, comment, locale, source)
                        VALUES (%s, %s, %s, 'vi-VN', 'seed');
                        """,
                        (tid, stars, comment),
                    )

    return {
        "dsn": disposable_database_dsn,
        "org_1_id": org_1_id,
        "org_2_id": org_2_id,
        "p_1_id": p_1_id,
        "d_1_id": d_1_id,
        "p_2_id": p_2_id,
        "d_2_id": d_2_id,
    }


@pytest.fixture
def test_client(seeded_real_db, monkeypatch):
    """FastAPI TestClient wired to the disposable database."""
    real_dsn = seeded_real_db["dsn"]
    monkeypatch.setenv("DATABASE_URL", real_dsn)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("TEST_AUTH_ENABLED", "true")

    # Clear cached settings/service
    get_settings.cache_clear()
    settings = Settings(database_url=real_dsn, app_env="test", test_auth_enabled=True)
    real_cs = CaseService(settings=settings)

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_case_service] = lambda: real_cs

    with TestClient(app) as client:
        yield client, seeded_real_db

    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_driver_profile_real_db_active_driver(test_client):
    """GET /api/v1/driver/profile returns 200 with vehicle, ratings, and scorecard for active driver."""
    client, seed = test_client
    headers = {
        "x-principal-id": seed["p_1_id"],
        "x-driver-id": seed["d_1_id"],
        "x-organization-id": seed["org_1_id"],
        "x-role": "driver",
    }

    res = client.get("/api/v1/driver/profile", headers=headers)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()

    assert data["driver_id"] == seed["d_1_id"]
    assert data["display_name"] == "Nguyễn Văn Lái"
    assert data["vehicle"] is not None
    assert data["vehicle"]["plate"] == "29A-888.99"
    assert "VF 8" in (data["vehicle"]["model"] or "")
    assert data["rated_count"] == 2
    assert data["rating_average"] == 4.5
    assert data["distribution"]["5"] == 1
    assert data["distribution"]["4"] == 1
    assert len(data["weekly_trend"]) == 8
    assert data["scorecard"]["total_trips"] == 3


def test_driver_trips_real_db_active_driver(test_client):
    """GET /api/v1/driver/trips returns 200 with paginated trips and badge counts."""
    client, seed = test_client
    headers = {
        "x-principal-id": seed["p_1_id"],
        "x-driver-id": seed["d_1_id"],
        "x-organization-id": seed["org_1_id"],
        "x-role": "driver",
    }

    res = client.get("/api/v1/driver/trips", headers=headers)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()

    assert data["total"] == 3
    assert len(data["trips"]) == 3
    assert data["counts"]["all"] == 3
    assert data["counts"]["completed"] == 2
    assert data["counts"]["flagged"] == 1

    # Check trip details and rating structure
    completed_trip = next(t for t in data["trips"] if t["status"] == "completed" and t.get("rating"))
    assert completed_trip["rating"]["stars"] in (4, 5)
    assert completed_trip["driver_id"] == seed["d_1_id"]


def test_driver_trips_summary_real_db_active_driver(test_client):
    """GET /api/v1/driver/trips/summary returns 200 with correct totals."""
    client, seed = test_client
    headers = {
        "x-principal-id": seed["p_1_id"],
        "x-driver-id": seed["d_1_id"],
        "x-organization-id": seed["org_1_id"],
        "x-role": "driver",
    }

    res = client.get("/api/v1/driver/trips/summary", headers=headers)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()

    assert data["trip_count"] == 3
    assert data["total_fare_vnd"] == 375000  # 120k + 180k + 75k
    assert data["total_distance_km"] == 25.5  # 8.5 + 12.0 + 5.0
    assert data["avg_rating"] == 4.5


def test_driver_profile_empty_driver_no_vehicle_no_ratings_no_trips(test_client):
    """GET /api/v1/driver/profile returns 200 (never 500) with empty/null fields when driver has no vehicle/trips."""
    client, seed = test_client
    headers = {
        "x-principal-id": seed["p_2_id"],
        "x-driver-id": seed["d_2_id"],
        "x-organization-id": seed["org_1_id"],
        "x-role": "driver",
    }

    res = client.get("/api/v1/driver/profile", headers=headers)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()

    assert data["driver_id"] == seed["d_2_id"]
    assert data["vehicle"] is None
    assert data["rating_average"] is None
    assert data["rated_count"] == 0
    assert data["distribution"] == {"5": 0, "4": 0, "3": 0, "2": 0, "1": 0}
    assert len(data["weekly_trend"]) == 8
    assert all(w["average_rating"] is None and w["rated_count"] == 0 for w in data["weekly_trend"])
    assert data["scorecard"]["total_trips"] == 0
    assert data["scorecard"]["total_cases"] == 0
    assert data["scorecard"]["past_incidents"] == []


def test_driver_trips_empty_driver_no_trips(test_client):
    """GET /api/v1/driver/trips returns 200 (never 500) with empty list when driver has no trips."""
    client, seed = test_client
    headers = {
        "x-principal-id": seed["p_2_id"],
        "x-driver-id": seed["d_2_id"],
        "x-organization-id": seed["org_1_id"],
        "x-role": "driver",
    }

    res = client.get("/api/v1/driver/trips", headers=headers)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()

    assert data["total"] == 0
    assert data["trips"] == []
    assert data["counts"] == {"all": 0, "completed": 0, "flagged": 0}
    assert data["next_cursor"] is None


def test_driver_trips_summary_empty_driver_no_trips(test_client):
    """GET /api/v1/driver/trips/summary returns 200 (never 500) with zeroed stats when driver has no trips."""
    client, seed = test_client
    headers = {
        "x-principal-id": seed["p_2_id"],
        "x-driver-id": seed["d_2_id"],
        "x-organization-id": seed["org_1_id"],
        "x-role": "driver",
    }

    res = client.get("/api/v1/driver/trips/summary", headers=headers)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()

    assert data["trip_count"] == 0
    assert data["total_fare_vnd"] == 0
    assert data["total_distance_km"] == 0.0
    assert data["avg_rating"] is None


def test_identity_resolution_uses_driver_id_not_principal_id(test_client):
    """Identity resolution must use driver_id (app.drivers.id) and not principal.id."""
    client, seed = test_client
    assert seed["p_1_id"] != seed["d_1_id"]

    # When header passes only x-principal-id, resolution must resolve driver_id from app.drivers
    headers = {
        "x-principal-id": seed["p_1_id"],
        "x-organization-id": seed["org_1_id"],
        "x-role": "driver",
    }

    res_profile = client.get("/api/v1/driver/profile", headers=headers)
    assert res_profile.status_code == 200
    assert res_profile.json()["driver_id"] == seed["d_1_id"]

    res_trips = client.get("/api/v1/driver/trips", headers=headers)
    assert res_trips.status_code == 200
    assert res_trips.json()["total"] == 3


def test_cross_organization_driver_access_denied(test_client):
    """Cross-organization access must return 404 for driver profile and 0 trips for driver trips."""
    client, seed = test_client

    # Driver 1 in Org 1 requested under Org 2 header
    headers = {
        "x-principal-id": seed["p_1_id"],
        "x-driver-id": seed["d_1_id"],
        "x-organization-id": seed["org_2_id"],
        "x-role": "driver",
    }

    res_profile = client.get("/api/v1/driver/profile", headers=headers)
    assert res_profile.status_code == 404

    res_trips = client.get("/api/v1/driver/trips", headers=headers)
    assert res_trips.status_code == 200
    assert res_trips.json()["total"] == 0


def test_search_path_does_not_break_other_queries(test_client):
    """SET search_path = app, extensions, public does not break subsequent queries."""
    client, seed = test_client
    headers = {
        "x-principal-id": seed["p_1_id"],
        "x-driver-id": seed["d_1_id"],
        "x-organization-id": seed["org_1_id"],
        "x-role": "driver",
    }

    # 1. Hit driver endpoint that sets search_path
    res = client.get("/api/v1/driver/profile", headers=headers)
    assert res.status_code == 200

    # 2. Run system / information_schema query on a fresh DB connection
    settings = get_settings()
    cs = CaseService(settings=settings)
    conn = cs._get_db_connection()
    assert conn is not None
    try:
        with conn.cursor() as cur:
            # Verify system information schema queries work
            cur.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'app' AND table_name IN ('drivers', 'driver_trips');"
            )
            tables = [row["table_name"] if isinstance(row, dict) else row[0] for row in cur.fetchall()]
            assert "drivers" in tables
            assert "driver_trips" in tables

            # Verify standard schema-qualified queries work normally
            cur.execute("SELECT COUNT(*) AS total_orgs FROM app.organizations;")
            org_count = cur.fetchone() or {}
            count_val = org_count["total_orgs"] if isinstance(org_count, dict) else org_count[0]
            assert count_val >= 2
    finally:
        conn.close()
