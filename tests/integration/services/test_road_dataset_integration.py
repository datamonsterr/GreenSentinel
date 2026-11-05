"""Opt-in proof against an explicitly supplied migrated, isolated PostgreSQL database."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import psycopg
import pytest

from scripts.generate_synthetic_data import generate_synthetic_dataset
from scripts.road_dataset import validate_dataset, wkt
from scripts.seed_database import import_data
from src.config import Settings
from src.main import app
from src.services.case_service import CaseService, get_case_service


@dataclass
class DatabaseProof:
    url: str = field(repr=False)
    data: dict = field(repr=False)
    seed: Path

    def __iter__(self):
        return iter((self.url, self.data, self.seed))


@pytest.fixture(scope="module")
def proof(tmp_path_factory):
    url = os.getenv("ISSUE63_DATABASE_URL")
    if not url:
        pytest.skip("Set ISSUE63_DATABASE_URL to a migrated isolated database")
    data = generate_synthetic_dataset()
    seed = tmp_path_factory.mktemp("road-proof") / "seed.json"
    seed.write_text(json.dumps(data))
    with psycopg.connect(url) as conn:
        import_data(seed, conn)
    return DatabaseProof(url, data, seed)


def database_snapshot(conn):
    result = {}
    for table in (
        "ingest_events",
        "telemetry_points",
        "route_snapshots",
        "traffic_observations",
        "platform_incidents",
        "adjudications",
        "audit_events",
    ):
        result[table] = conn.execute(
            f"SELECT count(*), md5(coalesce(string_agg(row_data::text, '' ORDER BY row_data::text), '')) FROM (SELECT to_jsonb(t) row_data FROM app.{table} t) x"
        ).fetchone()
    return result


def test_every_demo_case_validates_and_repeated_seed_preserves_database(proof):
    url, data, seed = proof
    assert validate_dataset(data)["passed"]
    with psycopg.connect(url) as conn:
        before = database_snapshot(conn)
        import_data(seed, conn)
        assert database_snapshot(conn) == before
        assert (
            conn.execute(
                "SELECT count(*) FROM app.route_snapshots WHERE provenance->>'dataset_version'='road-v1'"
            ).fetchone()[0]
            == 200
        )
        assert (
            conn.execute(
                "SELECT bool_and(is_simulated AND source='synthetic-road-simulator') FROM app.traffic_observations"
            ).fetchone()[0]
            is True
        )


async def test_shared_gis_artifact_round_trips_through_public_ingestion_and_case_api(proof):
    url, _, _ = proof
    canonical = json.loads(Path("tests/fixtures/road_telemetry/normal_trip.json").read_text())
    trip, assignment, case = canonical["trip"], canonical["trip_assignment"], canonical["fraud_case"]
    with psycopg.connect(url) as conn:
        conn.execute("SET search_path=app,extensions,public")
        conn.execute(
            "INSERT INTO app.trips(id,organization_id,passenger_id,requested_at,pickup,dropoff,requested_service_class,status,completed_at) VALUES (%s,%s,%s,%s,ST_GeogFromText(%s),ST_GeogFromText(%s),'car','completed',%s) ON CONFLICT DO NOTHING",
            (
                trip["id"],
                trip["organization_id"],
                trip["passenger_id"],
                trip["requested_at"],
                wkt(trip["pickup"]),
                wkt(trip["dropoff"]),
                trip["completed_at"],
            ),
        )
        conn.execute(
            "INSERT INTO app.trip_assignments(id,trip_id,driver_id,vehicle_id,state,offered_at,accepted_at,arrived_at,started_at,ended_at) VALUES (%s,%s,%s,%s,'completed',%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            tuple(
                assignment[k]
                for k in (
                    "id",
                    "trip_id",
                    "driver_id",
                    "vehicle_id",
                    "offered_at",
                    "accepted_at",
                    "arrived_at",
                    "started_at",
                    "ended_at",
                )
            ),
        )
        conn.execute(
            "INSERT INTO app.fraud_cases(id,organization_id,assignment_id,status,suspected_category,priority_tier,priority_score,priority_rule_version) VALUES (%s,%s,%s,'ready','no_violation',2,10,'road-v1') ON CONFLICT DO NOTHING",
            (case["id"], trip["organization_id"], assignment["id"]),
        )
        for route in canonical["route_snapshots"]:
            conn.execute(
                "INSERT INTO app.route_snapshots(id,assignment_id,leg,calculated_at,provider,routing_profile,map_version,route,distance_m,duration_s,provenance) VALUES (%s,%s,%s,%s,'osrm','driving',%s,ST_GeogFromText(%s),%s,%s,%s) ON CONFLICT DO NOTHING",
                (
                    route["id"],
                    assignment["id"],
                    route["leg"],
                    route["calculated_at"],
                    route["map_version"],
                    wkt(route["route_geojson"]),
                    route["distance_m"],
                    route["duration_s"],
                    json.dumps(route["provenance"]),
                ),
            )
    service = CaseService(Settings(database_url=url, app_env="test"))
    app.dependency_overrides[get_case_service] = lambda: service
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            for event in canonical["ingest_events"]:
                body = dict(event, simulation_run_id=None)
                response = await client.post("/api/v1/telemetry/ingest", json=body)
                assert response.status_code == 200, response.text
            assert (await client.post("/api/v1/telemetry/ingest", json=body)).json()["duplicate"] is True
            changed = json.loads(json.dumps(body))
            changed["payload"]["speed_mps"] = 45
            assert (await client.post("/api/v1/telemetry/ingest", json=changed)).status_code == 409
            response = await client.get(f"/api/v1/cases/{case['id']}")
            assert response.status_code == 200, response.text
            detail = response.json()
            assert set(detail["route_geometry"]) == {"pickup_route", "destination_route"}
            assert len(detail["telemetry_samples"]) == len(canonical["ingest_events"])
            for actual, expected in zip(detail["telemetry_samples"], canonical["ingest_events"]):
                position = expected["payload"]["position"]
                assert actual["position"]["coordinates"] == [position["longitude"], position["latitude"]]
                assert actual["speed_mps"] == expected["payload"]["speed_mps"]
            assert detail["case"]["status"] == "ready"
    finally:
        app.dependency_overrides.pop(get_case_service, None)


@pytest.mark.parametrize("index", [0, 1, 25, 40, 80])
async def test_each_scenario_retrieves_persisted_roads_and_timeline(proof, index):
    url, data, _ = proof
    canonical = data["road_cases"][index]
    service = CaseService(Settings(database_url=url, app_env="test"))
    detail = await service.get_case_detail(canonical["fraud_case"]["id"])
    assert set(detail.route_geometry) == {"pickup_route", "destination_route"}
    assert len(detail.telemetry_samples) == len(canonical["ingest_events"])
    if index == 40:
        assert detail.missingness_alerts
        assert detail.guardrails["platform_incident"]["incident_type"] == "app_crash"
