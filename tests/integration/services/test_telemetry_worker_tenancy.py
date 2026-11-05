"""Disposable PostgreSQL proof for trusted telemetry tenant gates.

Run with ``DATABASE_URL=postgresql://.../worker_tenancy``.  The fixture only
creates actor/catalog rows; rejection happens before any telemetry write.
"""

import os
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from psycopg.rows import dict_row

from src.config import Settings
from src.services import telemetry_queue_worker as worker
from src.services.case_service import CaseService

psycopg = pytest.importorskip("psycopg")


@pytest.fixture
def db():
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is required for disposable PostgreSQL proof")
    conn = psycopg.connect(url, row_factory=dict_row)
    ids = {name: uuid4() for name in ("org", "driver", "passenger", "vehicle", "policy")}
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("INSERT INTO app.organizations (id, name) VALUES (%s, %s)", (ids["org"], "worker-test"))
            cur.execute(
                "INSERT INTO app.drivers (id, organization_id, partner_type) VALUES (%s, %s, 'owner_driver')",
                (ids["driver"], ids["org"]),
            )
            cur.execute(
                "INSERT INTO app.passengers (id, organization_id) VALUES (%s, %s)",
                (ids["passenger"], ids["org"]),
            )
            cur.execute(
                "INSERT INTO app.vehicles (id, organization_id, registration_ref, vehicle_type, service_class, telemetry_source) VALUES (%s, %s, %s, 'car', 'car_standard', 'simulator')",
                (ids["vehicle"], ids["org"], str(ids["vehicle"])),
            )
            cur.execute(
                "INSERT INTO app.policy_versions (id, version, status, source_hash, action_matrix) VALUES (%s, %s, 'published', %s, '{}'::jsonb)",
                (ids["policy"], f"worker-test-{ids['policy']}", b"worker-test"),
            )
    yield conn, ids
    if not conn.closed:
        conn.rollback()
        conn.close()
    cleanup = psycopg.connect(url)
    with cleanup.transaction():
        with cleanup.cursor() as cur:
            cur.execute(
                "DELETE FROM app.telemetry_points WHERE assignment_id IN (SELECT id FROM app.trip_assignments WHERE vehicle_id = %s)",
                (ids["vehicle"],),
            )
            cur.execute(
                "DELETE FROM app.ingest_events WHERE assignment_id IN (SELECT id FROM app.trip_assignments WHERE vehicle_id = %s)",
                (ids["vehicle"],),
            )
            cur.execute(
                "DELETE FROM app.route_snapshots WHERE assignment_id IN (SELECT id FROM app.trip_assignments WHERE vehicle_id = %s)",
                (ids["vehicle"],),
            )
            cur.execute("DELETE FROM app.trip_assignments WHERE vehicle_id = %s", (ids["vehicle"],))
            cur.execute("DELETE FROM app.trips WHERE passenger_id = %s", (ids["passenger"],))
            for table, key in (
                ("policy_versions", "policy"),
                ("vehicles", "vehicle"),
                ("passengers", "passenger"),
                ("drivers", "driver"),
                ("organizations", "org"),
            ):
                cur.execute(f"DELETE FROM app.{table} WHERE id = %s", (ids[key],))
    cleanup.close()


@pytest.mark.asyncio
async def test_disposable_db_rejects_cross_tenant_actor_before_write(db):
    conn, ids = db
    event = {
        "organization_id": str(ids["org"]),
        "driver_id": str(ids["driver"]),
        "passenger_id": str(ids["passenger"]),
        "vehicle_id": str(ids["vehicle"]),
        "policy_version_id": str(ids["policy"]),
        "pickup": [105.0, 21.0],
        "dropoff": [105.1, 21.1],
        "points": [{"longitude": 105.0, "latitude": 21.0}],
    }
    with pytest.raises(Exception):
        worker._validate_tenant_telemetry(conn, event, str(uuid4()))


def test_disposable_db_actor_catalog_is_tenant_scoped(db):
    conn, ids = db
    other = uuid4()
    foreign_driver = uuid4()
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("INSERT INTO app.organizations (id, name) VALUES (%s, 'foreign')", (other,))
            cur.execute(
                "INSERT INTO app.drivers (id, organization_id, partner_type, external_ref) VALUES (%s, %s, 'owner_driver', 'foreign-driver')",
                (foreign_driver, other),
            )
    service = CaseService(settings=Settings(app_env="test", database_url=os.environ["DATABASE_URL"]))
    actors = service.list_simulation_actors(str(ids["org"]))
    actor_ids = {str(row["id"]) for row in actors["drivers"]}
    assert str(ids["driver"]) in actor_ids
    assert str(foreign_driver) not in actor_ids
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api import test_routes
    from src.api.auth import Principal

    api = FastAPI()
    api.include_router(test_routes.router, prefix="/test/api/v1")
    api.dependency_overrides[test_routes.require_test_operator] = lambda: Principal(
        "member", str(ids["org"]), frozenset()
    )
    api.dependency_overrides[test_routes.get_case_service] = lambda: service
    with TestClient(api, raise_server_exceptions=False) as client:
        response = client.get("/test/api/v1/actors", headers={"X-Test-Context": "true"})
    assert response.status_code == 200, response.text
    assert str(ids["driver"]) in {row["id"] for row in response.json()["drivers"]}
    assert str(foreign_driver) not in {row["id"] for row in response.json()["drivers"]}
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("DELETE FROM app.drivers WHERE id = %s", (foreign_driver,))
            cur.execute("DELETE FROM app.organizations WHERE id = %s", (other,))
    conn.rollback()
    check = psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)
    with check.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM app.trips WHERE id = %s", (uuid4(),))
        assert cur.fetchone()["n"] == 0


@pytest.mark.asyncio
async def test_disposable_db_persists_owned_nominal_trip_without_case(db, monkeypatch):
    conn, ids = db
    trip_id, assignment_id = uuid4(), uuid4()
    event = {
        "organization_id": str(ids["org"]),
        "trip_id": str(trip_id),
        "assignment_id": str(assignment_id),
        "driver_id": str(ids["driver"]),
        "passenger_id": str(ids["passenger"]),
        "vehicle_id": str(ids["vehicle"]),
        "policy_version_id": str(ids["policy"]),
        "pickup": [105.0, 21.0],
        "dropoff": [105.1, 21.1],
        "points": [{"longitude": 105.0, "latitude": 21.0, "speed_mps": 4.0}],
    }
    route = {
        "geometry": {"coordinates": [[105.0, 21.0], [105.1, 21.1]]},
        "distance_m": 100,
        "duration_s": 10,
        "provenance": {},
    }
    monkeypatch.setattr(worker, "fetch_osrm_route", lambda *_: route)
    monkeypatch.setattr(
        worker.JevAssessmentAgent,
        "assess",
        AsyncMock(
            return_value={
                "category": "no_violation",
                "priority_tier": 2,
                "priority_score": 0,
                "confidence": 0.99,
                "reason_codes": [],
                "forensic_brief": "clear",
                "model_used": "test-provider",
            }
        ),
    )
    service = CaseService(settings=Settings(app_env="production", database_url=""))
    service._get_db_connection = lambda: conn
    result = await worker.process_telemetry_event(event, service, organization_id=str(ids["org"]))
    assert result["status"] == "processed"
    assert result["case_id"] is None
    check = psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)
    with check.cursor() as cur:
        cur.execute("SELECT organization_id FROM app.trips WHERE id = %s", (trip_id,))
        assert str(cur.fetchone()["organization_id"]) == str(ids["org"])
        cur.execute(
            "SELECT t.organization_id FROM app.trip_assignments a JOIN app.trips t ON t.id=a.trip_id WHERE a.id=%s",
            (assignment_id,),
        )
        assert str(cur.fetchone()["organization_id"]) == str(ids["org"])
        cur.execute("SELECT count(*) AS n FROM app.fraud_cases WHERE assignment_id=%s", (assignment_id,))
        assert cur.fetchone()["n"] == 0
        cur.execute(
            "SELECT count(*) AS n FROM app.ingest_events WHERE assignment_id=%s AND organization_id=%s",
            (assignment_id, ids["org"]),
        )
        assert cur.fetchone()["n"] == 1
    check.close()


@pytest.mark.asyncio
async def test_disposable_db_scoped_write_failure_rolls_back(db, monkeypatch):
    conn, ids = db
    trip_id = uuid4()
    event = {
        "organization_id": str(ids["org"]),
        "trip_id": str(trip_id),
        "assignment_id": str(uuid4()),
        "driver_id": str(ids["driver"]),
        "passenger_id": str(ids["passenger"]),
        "vehicle_id": str(ids["vehicle"]),
        "policy_version_id": str(ids["policy"]),
        "pickup": [105.0, 21.0],
        "dropoff": [105.1, 21.1],
        "points": [{"longitude": 105.0, "latitude": 21.0, "speed_mps": "invalid"}],
    }
    monkeypatch.setattr(
        worker.JevAssessmentAgent,
        "assess",
        AsyncMock(
            return_value={
                "category": "no_violation",
                "priority_tier": 2,
                "priority_score": 0,
                "confidence": 0.99,
                "reason_codes": [],
                "forensic_brief": "clear",
                "model_used": "test-provider",
            }
        ),
    )
    service = CaseService(settings=Settings(app_env="production", database_url=""))
    service._get_db_connection = lambda: conn
    with pytest.raises(ValueError, match="could not convert"):
        await worker.process_telemetry_event(event, service, organization_id=str(ids["org"]))
    check = psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)
    with check.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM app.trips WHERE id = %s", (trip_id,))
        assert cur.fetchone()["n"] == 0
    check.close()
