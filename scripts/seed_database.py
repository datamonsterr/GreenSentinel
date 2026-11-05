"""
Database Seeder and Importer for Supabase / PostgreSQL.

Connects to PostgreSQL (local Supabase on port 54322 or DATABASE_URL / MIGRATION_DATABASE_URL),
loads data/synthetic/seed_data.json, and executes bulk idempotent inserts into the app schema.
"""

import json
import logging
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def get_connection(db_url: str | None = None):
    load_dotenv()
    url = (
        db_url
        or os.environ.get("TARGET_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("MIGRATION_DATABASE_URL")
        or "postgresql://postgres:postgrespassword@localhost:5432/postgres"
    )
    if "localhost:5432/dbname" in url:
        url = "postgresql://postgres:postgrespassword@localhost:5432/postgres"

    logger.info(f"Connecting to database at: {url.split('@')[-1]}")
    return psycopg.connect(url, autocommit=False)


def import_data(seed_path: Path, conn: psycopg.Connection | None = None):
    if not seed_path.exists():
        logger.error(f"Seed file not found: {seed_path}")
        sys.exit(1)

    with open(seed_path, encoding="utf-8") as f:
        data = json.load(f)

    # Road datasets are source-owned.  Their manifest is the durable boundary
    # between a seed replay and live evidence already present in the database.
    versioned_dataset = bool(data.get("manifest", {}).get("dataset_version"))
    route_conflict = (
        "DO NOTHING"
        if versioned_dataset
        else """DO UPDATE SET
                        provider = EXCLUDED.provider,
                        route = EXCLUDED.route,
                        distance_m = EXCLUDED.distance_m,
                        duration_s = EXCLUDED.duration_s,
                        provenance = EXCLUDED.provenance
                    WHERE app.route_snapshots.provenance->>'dataset_version' IS NULL
                      AND app.route_snapshots.provenance->>'origin' IN ('synthetic', 'osrm')"""
    )

    close_conn = False
    if conn is None:
        conn = get_connection()
        close_conn = True
    restore_autocommit = False
    try:
        # Migration connections are commonly opened with autocommit=True.
        # Seed the whole payload as one unit even when a caller supplied that
        # connection, then restore its setting for the caller.
        if getattr(conn, "autocommit", False):
            conn.autocommit = False
            restore_autocommit = True
        with conn.cursor() as cur:
            # Set search path
            cur.execute("SET search_path = app, extensions, public;")

            # 1. Organization
            org = data["organization"]
            cur.execute(
                """
                INSERT INTO app.organizations (id, name, created_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name;
            """,
                (org["id"], org["name"], org["created_at"]),
            )
            logger.info("Imported Organization: %s", org["name"])

            # 2. Principals (Analysts)
            for a in data["analysts"]:
                cur.execute(
                    """
                    INSERT INTO app.principals (id, organization_id, external_subject, display_name, status, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET display_name = EXCLUDED.display_name;
                """,
                    (
                        a["id"],
                        a["organization_id"],
                        a["external_subject"],
                        a["display_name"],
                        a["status"],
                        a["created_at"],
                    ),
                )
            logger.info("Imported %d Principals (Analysts)", len(data["analysts"]))

            # 3. Principal Roles
            for pr in data["principal_roles"]:
                cur.execute(
                    """
                    INSERT INTO app.principal_roles (principal_id, role, granted_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (principal_id, role) DO NOTHING;
                """,
                    (pr["principal_id"], pr["role"], pr["granted_at"]),
                )
            logger.info("Imported %d Principal Roles", len(data["principal_roles"]))

            # 4. Passengers (50)
            for p in data["passengers"]:
                cur.execute(
                    """
                    INSERT INTO app.passengers (id, organization_id, external_ref, is_synthetic, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """,
                    (p["id"], p["organization_id"], p["external_ref"], p["is_synthetic"], p["created_at"]),
                )
            logger.info("Imported %d Passengers", len(data["passengers"]))

            # 5. Drivers (20)
            for d in data["drivers"]:
                cur.execute(
                    """
                    INSERT INTO app.drivers (id, organization_id, external_ref, display_name, partner_type, account_status, is_synthetic, created_at, avatar_url, rating, acceptance_rate, cancellation_rate, total_trips)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET display_name = EXCLUDED.display_name, avatar_url = EXCLUDED.avatar_url, rating = EXCLUDED.rating, acceptance_rate = EXCLUDED.acceptance_rate, cancellation_rate = EXCLUDED.cancellation_rate, total_trips = EXCLUDED.total_trips;
                """,
                    (
                        d["id"],
                        d["organization_id"],
                        d["external_ref"],
                        d["display_name"],
                        d["partner_type"],
                        d["account_status"],
                        d["is_synthetic"],
                        d["created_at"],
                        d.get("avatar_url"),
                        d.get("rating", 4.85),
                        d.get("acceptance_rate", 92.5),
                        d.get("cancellation_rate", 2.1),
                        d.get("total_trips", 1250),
                    ),
                )
            logger.info("Imported %d Drivers", len(data["drivers"]))

            # 6. Vehicles (20)
            for v in data["vehicles"]:
                cur.execute(
                    """
                    INSERT INTO app.vehicles (id, organization_id, registration_ref, vehicle_type, service_class, telemetry_source, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """,
                    (
                        v["id"],
                        v["organization_id"],
                        v["registration_ref"],
                        v["vehicle_type"],
                        v["service_class"],
                        v["telemetry_source"],
                        v["created_at"],
                    ),
                )
            logger.info("Imported %d Vehicles", len(data["vehicles"]))

            # 7. Driver Vehicle Assignments (20)
            for dva in data["driver_vehicle_assignments"]:
                cur.execute(
                    """
                    INSERT INTO app.driver_vehicle_assignments (id, driver_id, vehicle_id, effective_from, effective_to)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """,
                    (dva["id"], dva["driver_id"], dva["vehicle_id"], dva["effective_from"], dva["effective_to"]),
                )
            logger.info("Imported %d Driver Vehicle Assignments", len(data["driver_vehicle_assignments"]))

            # 8. Policy Version & Policy Chunks
            pv = data["policy_version"]
            cur.execute(
                """
                INSERT INTO app.policy_versions (id, version, status, effective_from, effective_to, source_hash, action_matrix, is_demo_policy, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING;
            """,
                (
                    pv["id"],
                    pv["version"],
                    pv["status"],
                    pv["effective_from"],
                    pv["effective_to"],
                    bytes.fromhex(pv["source_hash"][2:]),
                    json.dumps(pv["action_matrix"]),
                    pv["is_demo_policy"],
                    pv["created_at"],
                ),
            )

            for pc in data["policy_chunks"]:
                cur.execute(
                    """
                    INSERT INTO app.policy_chunks (id, policy_version_id, source_ref, section_ref, content, content_hash, embedding, embedding_model)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """,
                    (
                        pc["id"],
                        pc["policy_version_id"],
                        pc["source_ref"],
                        pc["section_ref"],
                        pc["content"],
                        bytes.fromhex(pc["content_hash"][2:]),
                        str(pc["embedding"]),
                        pc["embedding_model"],
                    ),
                )
            logger.info("Imported Policy Version and %d Policy Chunks", len(data["policy_chunks"]))

            # 9. Simulation Runs
            for sr in data["simulation_runs"]:
                cur.execute(
                    """
                    INSERT INTO app.simulation_runs (id, organization_id, scenario, seed, generator_version, status, simulated_clock_origin, started_at, finished_at, requested_by, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """,
                    (
                        sr["id"],
                        sr["organization_id"],
                        sr["scenario"],
                        sr["seed"],
                        sr["generator_version"],
                        sr["status"],
                        sr["simulated_clock_origin"],
                        sr["started_at"],
                        sr["finished_at"],
                        sr["requested_by"],
                        sr["created_at"],
                    ),
                )
            logger.info("Imported %d Simulation Runs", len(data["simulation_runs"]))

            logger.info("Imported %d Simulation Runs", len(data["simulation_runs"]))

            # 10. Trips (100)
            if data.get("trips"):
                cur.executemany(
                    """
                    INSERT INTO app.trips (id, organization_id, passenger_id, requested_at, pickup, dropoff, requested_service_class, status, cancelled_at, completed_at, created_at, pickup_address, dropoff_address, district, match_type)
                    VALUES (%s, %s, %s, %s, ST_GeogFromText(%s), ST_GeogFromText(%s), %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        pickup_address = coalesce(EXCLUDED.pickup_address, app.trips.pickup_address),
                        dropoff_address = coalesce(EXCLUDED.dropoff_address, app.trips.dropoff_address),
                        district = coalesce(EXCLUDED.district, app.trips.district),
                        match_type = coalesce(EXCLUDED.match_type, app.trips.match_type);
                """,
                    [
                        (
                            t["id"],
                            t["organization_id"],
                            t["passenger_id"],
                            t["requested_at"],
                            t["pickup"],
                            t["dropoff"],
                            t["requested_service_class"],
                            t["status"],
                            t["cancelled_at"],
                            t["completed_at"],
                            t["created_at"],
                            t.get("pickup_address"),
                            t.get("dropoff_address"),
                            t.get("district"),
                            t.get("match_type", "auto"),
                        )
                        for t in data["trips"]
                    ],
                )
            logger.info("Imported %d Trips (with PostGIS Point Geography)", len(data.get("trips", [])))

            # 11. Trip Assignments (100)
            if data.get("trip_assignments"):
                cur.executemany(
                    """
                    INSERT INTO app.trip_assignments (id, trip_id, driver_id, vehicle_id, state, offered_at, accepted_at, arrived_at, started_at, ended_at, cancellation_actor, cancellation_reason, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """,
                    [
                        (
                            ta["id"],
                            ta["trip_id"],
                            ta["driver_id"],
                            ta["vehicle_id"],
                            ta["state"],
                            ta["offered_at"],
                            ta["accepted_at"],
                            ta["arrived_at"],
                            ta["started_at"],
                            ta["ended_at"],
                            ta["cancellation_actor"],
                            ta["cancellation_reason"],
                            ta["created_at"],
                        )
                        for ta in data["trip_assignments"]
                    ],
                )
            logger.info("Imported %d Trip Assignments", len(data.get("trip_assignments", [])))

            # 12. Fare Quotes & Payments
            if data.get("fare_quotes"):
                cur.executemany(
                    """
                    INSERT INTO app.fare_quotes (id, trip_id, version, currency, estimated_amount_minor, estimated_distance_m, estimated_duration_s, quoted_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """,
                    [
                        (
                            fq["id"],
                            fq["trip_id"],
                            fq["version"],
                            fq["currency"],
                            fq["estimated_amount_minor"],
                            fq["estimated_distance_m"],
                            fq["estimated_duration_s"],
                            fq["quoted_at"],
                        )
                        for fq in data["fare_quotes"]
                    ],
                )

            if data.get("payment_transactions"):
                cur.executemany(
                    """
                    INSERT INTO app.payment_transactions (id, trip_id, kind, amount_minor, currency, status, provider_ref, is_simulated, occurred_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """,
                    [
                        (
                            pt["id"],
                            pt["trip_id"],
                            pt["kind"],
                            pt["amount_minor"],
                            pt["currency"],
                            pt["status"],
                            pt["provider_ref"],
                            pt["is_simulated"],
                            pt["occurred_at"],
                        )
                        for pt in data["payment_transactions"]
                    ],
                )
            logger.info("Imported %d Fare Quotes & Payments", len(data.get("fare_quotes", [])))

            # 13. Route Snapshots (LineString Geography)
            if data.get("route_snapshots"):
                cur.executemany(
                    f"""
                    INSERT INTO app.route_snapshots (id, assignment_id, leg, calculated_at, provider, routing_profile, map_version, route, distance_m, duration_s, provenance)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, ST_GeogFromText(%s), %s, %s, %s)
                    ON CONFLICT (assignment_id, leg) {route_conflict};
                """,
                    [
                        (
                            rs["id"],
                            rs["assignment_id"],
                            rs.get("leg", "pickup"),
                            rs["calculated_at"],
                            rs["provider"],
                            rs["routing_profile"],
                            rs["map_version"],
                            rs["route"],
                            rs["distance_m"],
                            rs["duration_s"],
                            json.dumps(rs["provenance"]),
                        )
                        for rs in data["route_snapshots"]
                    ],
                )
            logger.info("Imported %d Route Snapshots (with PostGIS LineString)", len(data.get("route_snapshots", [])))

            # 14. Traffic Observations
            if data.get("traffic_observations"):
                cur.executemany(
                    """
                    INSERT INTO app.traffic_observations (id, assignment_id, observed_at, valid_until, average_speed_mps, congestion_level, source, is_simulated, provenance)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """,
                    [
                        (
                            tro["id"],
                            tro["assignment_id"],
                            tro["observed_at"],
                            tro["valid_until"],
                            tro["average_speed_mps"],
                            tro["congestion_level"],
                            tro["source"],
                            tro["is_simulated"],
                            json.dumps(tro["provenance"]),
                        )
                        for tro in data["traffic_observations"]
                    ],
                )
            logger.info("Imported %d Traffic Observations", len(data.get("traffic_observations", [])))

            # 15. Platform Incidents
            if data.get("platform_incidents"):
                cur.executemany(
                    """
                    INSERT INTO app.platform_incidents (id, assignment_id, incident_type, state, started_at, ended_at, details)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """,
                    [
                        (
                            pi["id"],
                            pi["assignment_id"],
                            pi["incident_type"],
                            pi["state"],
                            pi["started_at"],
                            pi["ended_at"],
                            json.dumps(pi["details"]),
                        )
                        for pi in data["platform_incidents"]
                    ],
                )
            logger.info("Imported %d Platform Incidents", len(data.get("platform_incidents", [])))

            # 16. Passenger Feedback
            if data.get("passenger_feedback"):
                cur.executemany(
                    """
                    INSERT INTO app.passenger_feedback (id, assignment_id, submitted_at, reason_code, statement, is_synthetic)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """,
                    [
                        (
                            pf["id"],
                            pf["assignment_id"],
                            pf["submitted_at"],
                            pf["reason_code"],
                            pf["statement"],
                            pf["is_synthetic"],
                        )
                        for pf in data["passenger_feedback"]
                    ],
                )
            logger.info("Imported %d Passenger Feedback entries", len(data.get("passenger_feedback", [])))

            # 17. Ingest Events & Telemetry Points
            if data.get("ingest_events"):
                cur.executemany(
                    """
                    INSERT INTO app.ingest_events (event_id, organization_id, schema_version, event_type, source, occurred_at, received_at, correlation_id, causation_id, simulation_run_id, trip_id, assignment_id, driver_id, producer_sequence, payload, payload_hash)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source, assignment_id, producer_sequence) DO NOTHING;
                """,
                    [
                        (
                            ie["event_id"],
                            ie["organization_id"],
                            ie["schema_version"],
                            ie["event_type"],
                            ie["source"],
                            ie["occurred_at"],
                            ie["received_at"],
                            ie["correlation_id"],
                            ie["causation_id"],
                            ie["simulation_run_id"],
                            ie["trip_id"],
                            ie["assignment_id"],
                            ie["driver_id"],
                            ie["producer_sequence"],
                            json.dumps(ie["payload"]),
                            bytes.fromhex(ie["payload_hash"][2:]),
                        )
                        for ie in data["ingest_events"]
                    ],
                )

            if data.get("telemetry_points"):
                cur.executemany(
                    """
                    INSERT INTO app.telemetry_points (
                        event_id, assignment_id, occurred_at, position, speed_mps,
                        bearing_deg, accuracy_m, app_state, network_state, gps_state, mock_location_reported
                    )
                    VALUES (
                        %s, %s, %s,
                        ST_GeogFromText(%s),
                        %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (event_id) DO NOTHING;
                """,
                    [
                        (
                            tp["event_id"],
                            tp["assignment_id"],
                            tp["occurred_at"],
                            tp["position"],
                            tp["speed_mps"],
                            tp["bearing_deg"],
                            tp["accuracy_m"],
                            tp["app_state"],
                            tp["network_state"],
                            tp["gps_state"],
                            tp["mock_location_reported"],
                        )
                        for tp in data["telemetry_points"]
                    ],
                )
            logger.info("Imported %d Telemetry Points and Ingest Events", len(data.get("telemetry_points", [])))

            # 18. Fraud Cases (100)
            if data.get("fraud_cases"):
                cur.executemany(
                    """
                    INSERT INTO app.fraud_cases (id, organization_id, assignment_id, status, suspected_category, priority_tier, priority_score, priority_rule_version, assigned_analyst_id, required_role, version, sla_due_at, created_at, updated_at, resolved_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """,
                    [
                        (
                            fc["id"],
                            fc["organization_id"],
                            fc["assignment_id"],
                            fc["status"],
                            fc["suspected_category"],
                            fc["priority_tier"],
                            fc["priority_score"],
                            fc["priority_rule_version"],
                            fc["assigned_analyst_id"],
                            fc["required_role"],
                            fc["version"],
                            fc["sla_due_at"],
                            fc["created_at"],
                            fc["updated_at"],
                            fc["resolved_at"],
                        )
                        for fc in data["fraud_cases"]
                    ],
                )
            logger.info("Imported %d Fraud Cases", len(data.get("fraud_cases", [])))

            # 19. Simulation Labels (100)
            if data.get("simulation_labels"):
                cur.executemany(
                    """
                    INSERT INTO app.simulation_labels (simulation_run_id, assignment_id, expected_category, expected_guardrail, expected_outcome)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (simulation_run_id, assignment_id) DO NOTHING;
                """,
                    [
                        (
                            sl["simulation_run_id"],
                            sl["assignment_id"],
                            sl["expected_category"],
                            sl["expected_guardrail"],
                            sl["expected_outcome"],
                        )
                        for sl in data["simulation_labels"]
                    ],
                )
            logger.info("Imported %d Simulation Labels", len(data.get("simulation_labels", [])))

            # 20. Case Assignment History
            if data.get("case_assignment_history"):
                cur.executemany(
                    """
                    INSERT INTO app.case_assignment_history (id, case_id, from_analyst_id, to_analyst_id, to_required_role, assigned_by, reason, assigned_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """,
                    [
                        (
                            cah["id"],
                            cah["case_id"],
                            cah.get("from_analyst_id"),
                            cah["to_analyst_id"],
                            cah["to_required_role"],
                            cah["assigned_by"],
                            cah.get("reason"),
                            cah["assigned_at"],
                        )
                        for cah in data["case_assignment_history"]
                    ],
                )

            # 21. Driver Submissions
            for ds in data["driver_submissions"]:
                cur.execute(
                    """
                    INSERT INTO app.driver_submissions (id, case_id, status, statement, deadline_at, received_at, provenance)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """,
                    (
                        ds["id"],
                        ds["case_id"],
                        ds["status"],
                        ds["statement"],
                        ds["deadline_at"],
                        ds["received_at"],
                        json.dumps(ds["provenance"]),
                    ),
                )

            # 22. Evidence Snapshots
            for es in data["evidence_snapshots"]:
                cur.execute(
                    """
                    INSERT INTO app.evidence_snapshots (id, case_id, version, policy_version_id, event_cutoff_at, stage, dossier, dossier_hash, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """,
                    (
                        es["id"],
                        es["case_id"],
                        es["version"],
                        es["policy_version_id"],
                        es["event_cutoff_at"],
                        es["stage"],
                        json.dumps(es["dossier"]),
                        bytes.fromhex(es["dossier_hash"][2:]),
                        es["created_at"],
                    ),
                )

            # 23. Feature Sets
            for fs in data["feature_sets"]:
                cur.execute(
                    """
                    INSERT INTO app.feature_sets (id, evidence_snapshot_id, preprocessing_version, window_start, window_end, telemetry_coverage, max_gap_s, davi, stationary_duration_s, traffic_observation_age_s, quality_flags, features, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """,
                    (
                        fs["id"],
                        fs["evidence_snapshot_id"],
                        fs["preprocessing_version"],
                        fs["window_start"],
                        fs["window_end"],
                        fs["telemetry_coverage"],
                        fs["max_gap_s"],
                        fs["davi"],
                        fs["stationary_duration_s"],
                        fs["traffic_observation_age_s"],
                        json.dumps(fs["quality_flags"]),
                        json.dumps(fs["features"]),
                        fs["created_at"],
                    ),
                )

            # 24. Model Assessments
            for ma in data["model_assessments"]:
                cur.execute(
                    """
                    INSERT INTO app.model_assessments (id, evidence_snapshot_id, feature_set_id, provider, model_id, prompt_version, output_schema_version, status, category, confidence, score_semantics, reason_codes, evidence_refs, forensic_brief, raw_response, latency_ms, trace_id, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """,
                    (
                        ma["id"],
                        ma["evidence_snapshot_id"],
                        ma["feature_set_id"],
                        ma["provider"],
                        ma["model_id"],
                        ma["prompt_version"],
                        ma["output_schema_version"],
                        ma["status"],
                        ma["category"],
                        ma["confidence"],
                        ma["score_semantics"],
                        json.dumps(ma["reason_codes"]),
                        json.dumps(ma["evidence_refs"]),
                        ma["forensic_brief"],
                        json.dumps(ma["raw_response"]),
                        ma["latency_ms"],
                        ma["trace_id"],
                        ma["created_at"],
                    ),
                )

            # 25. Review Leases
            for rl in data["review_leases"]:
                cur.execute(
                    """
                    INSERT INTO app.review_leases (case_id, analyst_id, token_hash, case_version, evidence_snapshot_id, acquired_at, expires_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (case_id) DO NOTHING;
                """,
                    (
                        rl["case_id"],
                        rl["analyst_id"],
                        bytes.fromhex(rl["token_hash"][2:]),
                        rl["case_version"],
                        rl["evidence_snapshot_id"],
                        rl["acquired_at"],
                        rl["expires_at"],
                    ),
                )

            # 26. Adjudications & Sanctions
            for adj in data["adjudications"]:
                cur.execute(
                    """
                    INSERT INTO app.adjudications (id, case_id, evidence_snapshot_id, policy_version_id, analyst_id, outcome, rationale, explicit_human_approval, idempotency_key, request_hash, approved_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """,
                    (
                        adj["id"],
                        adj["case_id"],
                        adj["evidence_snapshot_id"],
                        adj["policy_version_id"],
                        adj["analyst_id"],
                        adj["outcome"],
                        adj["rationale"],
                        adj["explicit_human_approval"],
                        adj["idempotency_key"],
                        bytes.fromhex(adj["request_hash"][2:]),
                        adj["approved_at"],
                    ),
                )

            for sanc in data["sanctions"]:
                cur.execute(
                    """
                    INSERT INTO app.sanctions (id, adjudication_id, driver_id, kind, amount_minor, currency, starts_at, ends_at, status, external_effect_key, is_simulated, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                """,
                    (
                        sanc["id"],
                        sanc["adjudication_id"],
                        sanc["driver_id"],
                        sanc["kind"],
                        sanc["amount_minor"],
                        sanc["currency"],
                        sanc["starts_at"],
                        sanc["ends_at"],
                        sanc["status"],
                        sanc["external_effect_key"],
                        sanc["is_simulated"],
                        sanc["created_at"],
                    ),
                )

            # Commit the entire transaction
            conn.commit()
            logger.info("ALL DATA SUCCESSFULLY COMMITTED TO DATABASE!")
    except Exception as e:
        conn.rollback()
        logger.exception(f"Import failed, transaction rolled back: {e}")
        raise
    finally:
        if restore_autocommit:
            conn.autocommit = True
        if close_conn:
            conn.close()


def main():
    seed_file = Path("data/synthetic/seed_data.json")
    import_data(seed_file)


if __name__ == "__main__":
    main()
