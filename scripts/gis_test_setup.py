import json
import os
import sys
import tempfile
import time
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlparse

import httpx
import psycopg
from psycopg import sql

from scripts.road_dataset import wkt

SCENARIO_FIXTURES = (
    "normal_trip.json",
    "gps_absent_trip.json",
    "gps_unavailable_trip.json",
    "route_unavailable_trip.json",
)


def validate_database_url(url: str | None) -> str:
    """Require the explicitly supplied, local, disposable Issue 61 database."""
    if not url:
        raise ValueError("ISSUE61_DATABASE_URL must be set")
    parsed = urlparse(url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("ISSUE61_DATABASE_URL must be a PostgreSQL URL")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("ISSUE61_DATABASE_URL must target loopback")
    if not parsed.path.removeprefix("/").startswith("issue61_"):
        raise ValueError("ISSUE61_DATABASE_URL must target an issue61_* database")
    return url


def validate_local_service_url(url: str | None, name: str = "service URL") -> str:
    """Require an explicitly configured loopback HTTP service endpoint."""
    if not url:
        raise ValueError(f"{name} must be set")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"{name} must target loopback")
    return url


def validate_local_redis_url(url: str | None) -> str:
    """Require a Redis URL whose parsed hostname is loopback."""
    if not url:
        raise ValueError("REDIS_URL must be set")
    parsed = urlparse(url)
    if parsed.scheme != "redis" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("REDIS_URL must target loopback")
    return url


def parse_health_response(body: str) -> bool:
    """Return true only for the exact healthy API response contract."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and payload.get("status") == "ok" and payload.get("database") == "connected"


def scenario_lifecycle_values(trip: dict, assignment: dict, case: dict) -> tuple[str, str, str]:
    """Preserve fixture lifecycle values, with defaults for sparse legacy fixtures."""
    return trip.get("status", "completed"), assignment.get("state", "completed"), case.get("status", "ready")


def gis_schema_ready(url: str) -> bool:
    """Probe the required GIS schema without replaying historical data backfills."""
    try:
        with psycopg.connect(validate_database_url(url)) as conn:
            found = conn.execute("SELECT to_regclass('app.fraud_cases')").fetchone()[0]
            if found is None:
                return False
            conn.execute("SELECT arrived_at, ended_at FROM app.trip_assignments LIMIT 0")
            conn.execute("SELECT pickup, dropoff FROM app.trips LIMIT 0")
            conn.execute("SELECT leg, provenance FROM app.route_snapshots LIMIT 0")
            conn.execute("SELECT gps_state, position FROM app.telemetry_points LIMIT 0")
            return True
    except (psycopg.errors.UndefinedTable, psycopg.errors.UndefinedColumn):
        return False


def database_fingerprint(url: str) -> dict[str, tuple[int, str]]:
    """Return per-app-table row counts and content hashes without printing rows."""
    fingerprint: dict[str, tuple[int, str]] = {}
    with psycopg.connect(url) as conn:
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'app' AND table_type = 'BASE TABLE' ORDER BY table_name"
        ).fetchall()
        for (table_name,) in tables:
            table = sql.Identifier("app", table_name)
            query = sql.SQL(
                "SELECT count(*), COALESCE(string_agg(md5(to_jsonb(t)::text), '' ORDER BY to_jsonb(t)::text), '') FROM {} AS t"
            ).format(table)
            count, digest_text = conn.execute(query).fetchone()
            fingerprint[table_name] = (count, sha256(digest_text.encode()).hexdigest())
    return fingerprint


def filter_case_dependents(data: dict) -> None:
    """Keep generated assignment telemetry, while removing rows for omitted cases."""
    case_ids = {str(row["id"]) for row in data.get("fraud_cases", [])}
    for key in (
        "case_assignment_history",
        "review_leases",
        "driver_submissions",
        "evidence_snapshots",
        "adjudications",
        "sanctions",
    ):
        data[key] = [row for row in data.get(key, []) if str(row.get("case_id")) in case_ids]
    evidence_ids = {str(row["id"]) for row in data.get("evidence_snapshots", [])}
    data["feature_sets"] = [
        row for row in data.get("feature_sets", []) if str(row.get("evidence_snapshot_id")) in evidence_ids
    ]
    feature_ids = {str(row["id"]) for row in data.get("feature_sets", [])}
    data["model_assessments"] = [
        row
        for row in data.get("model_assessments", [])
        if str(row.get("evidence_snapshot_id")) in evidence_ids and str(row.get("feature_set_id")) in feature_ids
    ]


def insert_case_scenario(canonical: dict, url: str) -> None:
    """Persist one scenario's trip, assignment, case and routing snapshots."""
    trip, assignment, case = canonical["trip"], canonical["trip_assignment"], canonical["fraud_case"]
    trip_status, assignment_state, case_status = scenario_lifecycle_values(trip, assignment, case)
    with psycopg.connect(url) as conn:
        conn.execute("SET search_path=app,extensions,public")
        conn.execute(
            "INSERT INTO app.trips(id,organization_id,passenger_id,requested_at,pickup,dropoff,requested_service_class,status,completed_at) VALUES (%s,%s,%s,%s,ST_GeogFromText(%s),ST_GeogFromText(%s),'car',%s,%s) ON CONFLICT DO NOTHING",
            (
                trip["id"],
                trip["organization_id"],
                trip["passenger_id"],
                trip["requested_at"],
                wkt(trip["pickup"]),
                wkt(trip["dropoff"]),
                trip_status,
                trip["completed_at"],
            ),
        )
        conn.execute(
            "INSERT INTO app.trip_assignments(id,trip_id,driver_id,vehicle_id,state,offered_at,accepted_at,arrived_at,started_at,ended_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (
                assignment["id"],
                assignment["trip_id"],
                assignment["driver_id"],
                assignment["vehicle_id"],
                assignment_state,
                *(assignment[k] for k in ("offered_at", "accepted_at", "arrived_at", "started_at", "ended_at")),
            ),
        )
        conn.execute(
            "INSERT INTO app.fraud_cases(id,organization_id,assignment_id,status,suspected_category,priority_tier,priority_score,priority_rule_version) VALUES (%s,%s,%s,%s,'no_violation',%s,%s,'road-v1') ON CONFLICT DO NOTHING",
            (
                case["id"],
                trip["organization_id"],
                assignment["id"],
                case_status,
                case["priority_tier"],
                case["priority_score"],
            ),
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


def ingest_case_events(canonical: dict, client: httpx.Client) -> None:
    """Push one scenario's telemetry through the real ingestion endpoint."""
    for event in canonical.get("ingest_events", []):
        body = dict(event, simulation_run_id=None)
        response = client.post("/api/v1/telemetry/ingest", json=body)
        if response.status_code != 200:
            raise RuntimeError(f"Telemetry ingest failed ({response.status_code}): {response.text}")
        result = response.json()
        expected_id = event["event_id"]
        if (
            result.get("event_id") != expected_id
            or result.get("status") not in {"ingested", "duplicate"}
            or result.get("duplicate") is not (result.get("status") == "duplicate")
        ):
            raise RuntimeError(f"Unexpected telemetry ingest result for {expected_id}: {result}")


def seed_database():
    url = os.getenv("ISSUE61_DATABASE_URL")
    try:
        url = validate_database_url(url)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    print("Generating synthetic dataset...")
    from scripts.generate_synthetic_data import generate_synthetic_dataset
    from scripts.seed_database import import_data

    data = generate_synthetic_dataset()

    # Remove all generated fraud_cases to keep only the canonical one later
    data["fraud_cases"] = []
    filter_case_dependents(data)

    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".json") as temp_seed:
        temp_seed.write(json.dumps(data))
        temp_seed_path = Path(temp_seed.name)

    try:
        print("Seeding database via psycopg...")
        with psycopg.connect(url) as conn:
            import_data(temp_seed_path, conn)

        for fixture_name in SCENARIO_FIXTURES:
            scenario = json.loads(Path("tests/fixtures/road_telemetry", fixture_name).read_text())
            insert_case_scenario(scenario, url)

        print("Waiting for FastAPI backend to be ready on port 18662...")
        api_url = os.getenv("API_BASE_URL", "http://127.0.0.1:18662").rstrip("/")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                r = httpx.get(f"{api_url}/health", timeout=2.0)
                if r.status_code == 200 and parse_health_response(r.text):
                    break
            except httpx.RequestError:
                pass
            time.sleep(0.5)
        else:
            print("ERROR: Backend did not become ready")
            sys.exit(1)

        print("Ingesting telemetry events via API...")
        with httpx.Client(
            base_url=api_url,
            headers={"x-role": "demo_operator", "x-principal-id": "gis-persisted-test"},
        ) as client:
            for fixture_name in SCENARIO_FIXTURES:
                scenario = json.loads(Path("tests/fixtures/road_telemetry", fixture_name).read_text())
                ingest_case_events(scenario, client)

        print("Seeding complete.")
    finally:
        # Cleanup must never fail the seed: /tmp reaping on busy shared
        # runners can remove the temp seed file before we get here.
        temp_seed_path.unlink(missing_ok=True)


def verify_repeat() -> None:
    """Re-run setup against the current isolated DB and require identical content."""
    url = validate_database_url(os.getenv("ISSUE61_DATABASE_URL"))
    before = database_fingerprint(url)
    seed_database()
    after = database_fingerprint(url)
    if before != after:
        changed = sorted(set(before) | set(after))
        changed = [table for table in changed if before.get(table) != after.get(table)]
        raise RuntimeError(f"Persisted setup changed database tables: {', '.join(changed)}")
    print(f"Repeat setup preserved {len(after)} app table fingerprints.")


if __name__ == "__main__":
    if "--verify-repeat" in sys.argv[1:]:
        verify_repeat()
    else:
        seed_database()
