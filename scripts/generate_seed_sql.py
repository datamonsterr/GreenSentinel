"""
Generate SQL seed statements for supabase db query -f / supabase cli execution.
Reads data/synthetic/seed_data.json and produces a clean SQL file.
"""

import json
from pathlib import Path


def sql_quote(val):
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, (dict, list)):
        escaped = json.dumps(val).replace("'", "''")
        return f"'{escaped}'::jsonb"
    escaped = str(val).replace("'", "''")
    return f"'{escaped}'"


def sql_bytea(hex_str):
    if hex_str.startswith("\\x"):
        hex_str = hex_str[2:]
    return f"decode('{hex_str}', 'hex')"


def generate_sql(seed_file: Path, out_file: Path):
    with open(seed_file, encoding="utf-8") as f:
        data = json.load(f)

    lines = []
    lines.append("BEGIN;")
    lines.append("SET search_path = app, extensions, public;\n")
    versioned_dataset = bool(data.get("manifest", {}).get("dataset_version"))
    route_conflict = (
        "DO NOTHING"
        if versioned_dataset
        else "DO UPDATE SET provider = EXCLUDED.provider, route = EXCLUDED.route, distance_m = EXCLUDED.distance_m, duration_s = EXCLUDED.duration_s, provenance = EXCLUDED.provenance WHERE app.route_snapshots.provenance->>'dataset_version' IS NULL AND app.route_snapshots.provenance->>'origin' IN ('synthetic', 'osrm')"
    )

    # 1. Org
    org = data["organization"]
    lines.append(
        f"INSERT INTO app.organizations (id, name, created_at) VALUES ({sql_quote(org['id'])}, {sql_quote(org['name'])}, {sql_quote(org['created_at'])}) ON CONFLICT (id) DO NOTHING;\n"
    )

    # 2. Principals
    for a in data["analysts"]:
        lines.append(
            f"INSERT INTO app.principals (id, organization_id, external_subject, display_name, status, created_at) VALUES ({sql_quote(a['id'])}, {sql_quote(a['organization_id'])}, {sql_quote(a['external_subject'])}, {sql_quote(a['display_name'])}, {sql_quote(a['status'])}, {sql_quote(a['created_at'])}) ON CONFLICT (id) DO NOTHING;"
        )
    lines.append("")

    # 3. Roles
    for pr in data["principal_roles"]:
        lines.append(
            f"INSERT INTO app.principal_roles (principal_id, role, granted_at) VALUES ({sql_quote(pr['principal_id'])}, {sql_quote(pr['role'])}, {sql_quote(pr['granted_at'])}) ON CONFLICT DO NOTHING;"
        )
    lines.append("")

    # 4. Passengers (50)
    for p in data["passengers"]:
        lines.append(
            f"INSERT INTO app.passengers (id, organization_id, external_ref, is_synthetic, created_at) VALUES ({sql_quote(p['id'])}, {sql_quote(p['organization_id'])}, {sql_quote(p['external_ref'])}, {sql_quote(p['is_synthetic'])}, {sql_quote(p['created_at'])}) ON CONFLICT DO NOTHING;"
        )
    lines.append("")

    # 5. Drivers (20)
    for d in data["drivers"]:
        lines.append(
            f"INSERT INTO app.drivers (id, organization_id, display_name, external_ref, partner_type, account_status, is_synthetic, created_at, avatar_url, rating, acceptance_rate, cancellation_rate, total_trips) VALUES ({sql_quote(d['id'])}, {sql_quote(d['organization_id'])}, {sql_quote(d['display_name'])}, {sql_quote(d['external_ref'])}, {sql_quote(d['partner_type'])}, {sql_quote(d['account_status'])}, {sql_quote(d['is_synthetic'])}, {sql_quote(d['created_at'])}, {sql_quote(d.get('avatar_url'))}, {sql_quote(d.get('rating', 4.85))}, {sql_quote(d.get('acceptance_rate', 92.5))}, {sql_quote(d.get('cancellation_rate', 2.1))}, {sql_quote(d.get('total_trips', 1250))}) ON CONFLICT (id) DO UPDATE SET display_name = EXCLUDED.display_name, avatar_url = EXCLUDED.avatar_url, rating = EXCLUDED.rating, acceptance_rate = EXCLUDED.acceptance_rate, cancellation_rate = EXCLUDED.cancellation_rate, total_trips = EXCLUDED.total_trips;"
        )
    lines.append("")

    # 6. Vehicles (20)
    for v in data["vehicles"]:
        lines.append(
            f"INSERT INTO app.vehicles (id, organization_id, registration_ref, vehicle_type, service_class, telemetry_source, created_at) VALUES ({sql_quote(v['id'])}, {sql_quote(v['organization_id'])}, {sql_quote(v['registration_ref'])}, {sql_quote(v['vehicle_type'])}, {sql_quote(v['service_class'])}, {sql_quote(v['telemetry_source'])}, {sql_quote(v['created_at'])}) ON CONFLICT DO NOTHING;"
        )
    lines.append("")

    # 7. Assignments (20)
    for dva in data["driver_vehicle_assignments"]:
        lines.append(
            f"INSERT INTO app.driver_vehicle_assignments (id, driver_id, vehicle_id, effective_from, effective_to) VALUES ({sql_quote(dva['id'])}, {sql_quote(dva['driver_id'])}, {sql_quote(dva['vehicle_id'])}, {sql_quote(dva['effective_from'])}, {sql_quote(dva['effective_to'])}) ON CONFLICT DO NOTHING;"
        )
    lines.append("")

    # 8. Policy Version & Chunks
    pv = data["policy_version"]
    lines.append(
        f"INSERT INTO app.policy_versions (id, version, status, effective_from, effective_to, source_hash, action_matrix, is_demo_policy, created_at) VALUES ({sql_quote(pv['id'])}, {sql_quote(pv['version'])}, {sql_quote(pv['status'])}, {sql_quote(pv['effective_from'])}, {sql_quote(pv['effective_to'])}, {sql_bytea(pv['source_hash'])}, {sql_quote(pv['action_matrix'])}, {sql_quote(pv['is_demo_policy'])}, {sql_quote(pv['created_at'])}) ON CONFLICT DO NOTHING;"
    )
    for pc in data["policy_chunks"]:
        lines.append(
            f"INSERT INTO app.policy_chunks (id, policy_version_id, source_ref, section_ref, content, content_hash, embedding, embedding_model) VALUES ({sql_quote(pc['id'])}, {sql_quote(pc['policy_version_id'])}, {sql_quote(pc['source_ref'])}, {sql_quote(pc['section_ref'])}, {sql_quote(pc['content'])}, {sql_bytea(pc['content_hash'])}, '{pc['embedding']}'::extensions.vector, {sql_quote(pc['embedding_model'])}) ON CONFLICT DO NOTHING;"
        )
    lines.append("")

    # 9. Simulation Runs
    for sr in data["simulation_runs"]:
        lines.append(
            f"INSERT INTO app.simulation_runs (id, organization_id, scenario, seed, generator_version, status, simulated_clock_origin, started_at, finished_at, requested_by, created_at) VALUES ({sql_quote(sr['id'])}, {sql_quote(sr['organization_id'])}, {sql_quote(sr['scenario'])}, {sql_quote(sr['seed'])}, {sql_quote(sr['generator_version'])}, {sql_quote(sr['status'])}, {sql_quote(sr['simulated_clock_origin'])}, {sql_quote(sr['started_at'])}, {sql_quote(sr['finished_at'])}, {sql_quote(sr['requested_by'])}, {sql_quote(sr['created_at'])}) ON CONFLICT DO NOTHING;"
        )
    lines.append("")

    # 10. Trips (100)
    for t in data["trips"]:
        lines.append(
            f"INSERT INTO app.trips (id, organization_id, passenger_id, requested_at, pickup, dropoff, requested_service_class, status, cancelled_at, completed_at, created_at, pickup_address, dropoff_address, district, match_type) VALUES ({sql_quote(t['id'])}, {sql_quote(t['organization_id'])}, {sql_quote(t['passenger_id'])}, {sql_quote(t['requested_at'])}, ST_GeogFromText({sql_quote(t['pickup'])}), ST_GeogFromText({sql_quote(t['dropoff'])}), {sql_quote(t['requested_service_class'])}, {sql_quote(t['status'])}, {sql_quote(t['cancelled_at'])}, {sql_quote(t['completed_at'])}, {sql_quote(t['created_at'])}, {sql_quote(t.get('pickup_address'))}, {sql_quote(t.get('dropoff_address'))}, {sql_quote(t.get('district'))}, {sql_quote(t.get('match_type', 'auto'))}) ON CONFLICT DO NOTHING;"
        )
    lines.append("")

    # 11. Trip Assignments (100)
    for ta in data["trip_assignments"]:
        lines.append(
            f"INSERT INTO app.trip_assignments (id, trip_id, driver_id, vehicle_id, state, offered_at, accepted_at, arrived_at, started_at, ended_at, cancellation_actor, cancellation_reason, created_at) VALUES ({sql_quote(ta['id'])}, {sql_quote(ta['trip_id'])}, {sql_quote(ta['driver_id'])}, {sql_quote(ta['vehicle_id'])}, {sql_quote(ta['state'])}, {sql_quote(ta['offered_at'])}, {sql_quote(ta['accepted_at'])}, {sql_quote(ta['arrived_at'])}, {sql_quote(ta['started_at'])}, {sql_quote(ta['ended_at'])}, {sql_quote(ta['cancellation_actor'])}, {sql_quote(ta['cancellation_reason'])}, {sql_quote(ta['created_at'])}) ON CONFLICT DO NOTHING;"
        )
    lines.append("")

    # 12. Fare Quotes & Payments
    for fq in data["fare_quotes"]:
        lines.append(
            f"INSERT INTO app.fare_quotes (id, trip_id, version, currency, estimated_amount_minor, estimated_distance_m, estimated_duration_s, quoted_at) VALUES ({sql_quote(fq['id'])}, {sql_quote(fq['trip_id'])}, {sql_quote(fq['version'])}, {sql_quote(fq['currency'])}, {sql_quote(fq['estimated_amount_minor'])}, {sql_quote(fq['estimated_distance_m'])}, {sql_quote(fq['estimated_duration_s'])}, {sql_quote(fq['quoted_at'])}) ON CONFLICT DO NOTHING;"
        )
    for pt in data["payment_transactions"]:
        lines.append(
            f"INSERT INTO app.payment_transactions (id, trip_id, kind, amount_minor, currency, status, provider_ref, is_simulated, occurred_at) VALUES ({sql_quote(pt['id'])}, {sql_quote(pt['trip_id'])}, {sql_quote(pt['kind'])}, {sql_quote(pt['amount_minor'])}, {sql_quote(pt['currency'])}, {sql_quote(pt['status'])}, {sql_quote(pt['provider_ref'])}, {sql_quote(pt['is_simulated'])}, {sql_quote(pt['occurred_at'])}) ON CONFLICT DO NOTHING;"
        )
    lines.append("")

    # 13. Route Snapshots
    for rs in data["route_snapshots"]:
        lines.append(
            f"INSERT INTO app.route_snapshots (id, assignment_id, leg, calculated_at, provider, routing_profile, map_version, route, distance_m, duration_s, provenance) VALUES ({sql_quote(rs['id'])}, {sql_quote(rs['assignment_id'])}, {sql_quote(rs['leg'])}, {sql_quote(rs['calculated_at'])}, {sql_quote(rs['provider'])}, {sql_quote(rs['routing_profile'])}, {sql_quote(rs['map_version'])}, ST_GeogFromText({sql_quote(rs['route'])}), {sql_quote(rs['distance_m'])}, {sql_quote(rs['duration_s'])}, {sql_quote(rs['provenance'])}) ON CONFLICT (assignment_id, leg) {route_conflict};"
        )
    lines.append("")

    # 14. Traffic Observations
    for tro in data["traffic_observations"]:
        lines.append(
            f"INSERT INTO app.traffic_observations (id, assignment_id, observed_at, valid_until, average_speed_mps, congestion_level, source, is_simulated, provenance) VALUES ({sql_quote(tro['id'])}, {sql_quote(tro['assignment_id'])}, {sql_quote(tro['observed_at'])}, {sql_quote(tro['valid_until'])}, {sql_quote(tro['average_speed_mps'])}, {sql_quote(tro['congestion_level'])}, {sql_quote(tro['source'])}, {sql_quote(tro['is_simulated'])}, {sql_quote(tro['provenance'])}) ON CONFLICT DO NOTHING;"
        )
    lines.append("")

    # 15. Platform Incidents
    for pi in data["platform_incidents"]:
        lines.append(
            f"INSERT INTO app.platform_incidents (id, assignment_id, incident_type, state, started_at, ended_at, details) VALUES ({sql_quote(pi['id'])}, {sql_quote(pi['assignment_id'])}, {sql_quote(pi['incident_type'])}, {sql_quote(pi['state'])}, {sql_quote(pi['started_at'])}, {sql_quote(pi['ended_at'])}, {sql_quote(pi['details'])}) ON CONFLICT DO NOTHING;"
        )
    lines.append("")

    # 16. Passenger Feedback
    for pf in data["passenger_feedback"]:
        lines.append(
            f"INSERT INTO app.passenger_feedback (id, assignment_id, submitted_at, reason_code, statement, is_synthetic) VALUES ({sql_quote(pf['id'])}, {sql_quote(pf['assignment_id'])}, {sql_quote(pf['submitted_at'])}, {sql_quote(pf['reason_code'])}, {sql_quote(pf['statement'])}, {sql_quote(pf['is_synthetic'])}) ON CONFLICT DO NOTHING;"
        )
    lines.append("")

    # 17. Ingest Events & Telemetry
    for ie in data["ingest_events"]:
        lines.append(
            f"INSERT INTO app.ingest_events (event_id, organization_id, schema_version, event_type, source, occurred_at, received_at, correlation_id, causation_id, simulation_run_id, trip_id, assignment_id, driver_id, producer_sequence, payload, payload_hash) VALUES ({sql_quote(ie['event_id'])}, {sql_quote(ie['organization_id'])}, {sql_quote(ie['schema_version'])}, {sql_quote(ie['event_type'])}, {sql_quote(ie['source'])}, {sql_quote(ie['occurred_at'])}, {sql_quote(ie['received_at'])}, {sql_quote(ie['correlation_id'])}, {sql_quote(ie['causation_id'])}, {sql_quote(ie['simulation_run_id'])}, {sql_quote(ie['trip_id'])}, {sql_quote(ie['assignment_id'])}, {sql_quote(ie['driver_id'])}, {sql_quote(ie['producer_sequence'])}, {sql_quote(ie['payload'])}, {sql_bytea(ie['payload_hash'])}) ON CONFLICT DO NOTHING;"
        )
    for tp in data["telemetry_points"]:
        pos_expr = f"ST_GeogFromText({sql_quote(tp['position'])})" if tp["position"] else "NULL"
        lines.append(
            f"INSERT INTO app.telemetry_points (event_id, assignment_id, occurred_at, position, speed_mps, bearing_deg, accuracy_m, app_state, network_state, gps_state, mock_location_reported) VALUES ({sql_quote(tp['event_id'])}, {sql_quote(tp['assignment_id'])}, {sql_quote(tp['occurred_at'])}, {pos_expr}, {sql_quote(tp['speed_mps'])}, {sql_quote(tp['bearing_deg'])}, {sql_quote(tp['accuracy_m'])}, {sql_quote(tp['app_state'])}, {sql_quote(tp['network_state'])}, {sql_quote(tp['gps_state'])}, {sql_quote(tp['mock_location_reported'])}) ON CONFLICT DO NOTHING;"
        )
    lines.append("")

    # 18. Fraud Cases
    for fc in data["fraud_cases"]:
        lines.append(
            f"INSERT INTO app.fraud_cases (id, organization_id, assignment_id, status, suspected_category, priority_tier, priority_score, priority_rule_version, assigned_analyst_id, required_role, version, sla_due_at, created_at, updated_at, resolved_at) VALUES ({sql_quote(fc['id'])}, {sql_quote(fc['organization_id'])}, {sql_quote(fc['assignment_id'])}, {sql_quote(fc['status'])}, {sql_quote(fc['suspected_category'])}, {sql_quote(fc['priority_tier'])}, {sql_quote(fc['priority_score'])}, {sql_quote(fc['priority_rule_version'])}, {sql_quote(fc['assigned_analyst_id'])}, {sql_quote(fc['required_role'])}, {sql_quote(fc['version'])}, {sql_quote(fc['sla_due_at'])}, {sql_quote(fc['created_at'])}, {sql_quote(fc['updated_at'])}, {sql_quote(fc['resolved_at'])}) ON CONFLICT DO NOTHING;"
        )
    lines.append("")

    # 19. Simulation Labels
    for sl in data["simulation_labels"]:
        lines.append(
            f"INSERT INTO app.simulation_labels (simulation_run_id, assignment_id, expected_category, expected_guardrail, expected_outcome) VALUES ({sql_quote(sl['simulation_run_id'])}, {sql_quote(sl['assignment_id'])}, {sql_quote(sl['expected_category'])}, {sql_quote(sl['expected_guardrail'])}, {sql_quote(sl['expected_outcome'])}) ON CONFLICT DO NOTHING;"
        )
    lines.append("")

    # 20. Case Assignment History
    for cah in data["case_assignment_history"]:
        lines.append(
            f"INSERT INTO app.case_assignment_history (id, case_id, from_analyst_id, to_analyst_id, to_required_role, assigned_by, reason, assigned_at) VALUES ({sql_quote(cah['id'])}, {sql_quote(cah['case_id'])}, {sql_quote(cah['from_analyst_id'])}, {sql_quote(cah['to_analyst_id'])}, {sql_quote(cah['to_required_role'])}, {sql_quote(cah['assigned_by'])}, {sql_quote(cah['reason'])}, {sql_quote(cah['assigned_at'])}) ON CONFLICT DO NOTHING;"
        )
    lines.append("")

    # 21. Driver Submissions
    for ds in data["driver_submissions"]:
        lines.append(
            f"INSERT INTO app.driver_submissions (id, case_id, status, statement, deadline_at, received_at, provenance) VALUES ({sql_quote(ds['id'])}, {sql_quote(ds['case_id'])}, {sql_quote(ds['status'])}, {sql_quote(ds['statement'])}, {sql_quote(ds['deadline_at'])}, {sql_quote(ds['received_at'])}, {sql_quote(ds['provenance'])}) ON CONFLICT DO NOTHING;"
        )
    lines.append("")

    # 22. Evidence Snapshots
    for es in data["evidence_snapshots"]:
        lines.append(
            f"INSERT INTO app.evidence_snapshots (id, case_id, version, policy_version_id, event_cutoff_at, stage, dossier, dossier_hash, created_at) VALUES ({sql_quote(es['id'])}, {sql_quote(es['case_id'])}, {sql_quote(es['version'])}, {sql_quote(es['policy_version_id'])}, {sql_quote(es['event_cutoff_at'])}, {sql_quote(es['stage'])}, {sql_quote(es['dossier'])}, {sql_bytea(es['dossier_hash'])}, {sql_quote(es['created_at'])}) ON CONFLICT DO NOTHING;"
        )
    lines.append("")

    # 23. Feature Sets
    for fs in data["feature_sets"]:
        lines.append(
            f"INSERT INTO app.feature_sets (id, evidence_snapshot_id, preprocessing_version, window_start, window_end, telemetry_coverage, max_gap_s, davi, stationary_duration_s, traffic_observation_age_s, quality_flags, features, created_at) VALUES ({sql_quote(fs['id'])}, {sql_quote(fs['evidence_snapshot_id'])}, {sql_quote(fs['preprocessing_version'])}, {sql_quote(fs['window_start'])}, {sql_quote(fs['window_end'])}, {sql_quote(fs['telemetry_coverage'])}, {sql_quote(fs['max_gap_s'])}, {sql_quote(fs['davi'])}, {sql_quote(fs['stationary_duration_s'])}, {sql_quote(fs['traffic_observation_age_s'])}, {sql_quote(fs['quality_flags'])}, {sql_quote(fs['features'])}, {sql_quote(fs['created_at'])}) ON CONFLICT DO NOTHING;"
        )
    lines.append("")

    # 24. Model Assessments
    for ma in data["model_assessments"]:
        lines.append(
            f"INSERT INTO app.model_assessments (id, evidence_snapshot_id, feature_set_id, provider, model_id, prompt_version, output_schema_version, status, category, confidence, score_semantics, reason_codes, evidence_refs, forensic_brief, raw_response, latency_ms, trace_id, created_at) VALUES ({sql_quote(ma['id'])}, {sql_quote(ma['evidence_snapshot_id'])}, {sql_quote(ma['feature_set_id'])}, {sql_quote(ma['provider'])}, {sql_quote(ma['model_id'])}, {sql_quote(ma['prompt_version'])}, {sql_quote(ma['output_schema_version'])}, {sql_quote(ma['status'])}, {sql_quote(ma['category'])}, {sql_quote(ma['confidence'])}, {sql_quote(ma['score_semantics'])}, {sql_quote(ma['reason_codes'])}, {sql_quote(ma['evidence_refs'])}, {sql_quote(ma['forensic_brief'])}, {sql_quote(ma['raw_response'])}, {sql_quote(ma['latency_ms'])}, {sql_quote(ma['trace_id'])}, {sql_quote(ma['created_at'])}) ON CONFLICT DO NOTHING;"
        )
    lines.append("")

    # 25. Review Leases
    for rl in data["review_leases"]:
        lines.append(
            f"INSERT INTO app.review_leases (case_id, analyst_id, token_hash, case_version, evidence_snapshot_id, acquired_at, expires_at) VALUES ({sql_quote(rl['case_id'])}, {sql_quote(rl['analyst_id'])}, {sql_bytea(rl['token_hash'])}, {sql_quote(rl['case_version'])}, {sql_quote(rl['evidence_snapshot_id'])}, {sql_quote(rl['acquired_at'])}, {sql_quote(rl['expires_at'])}) ON CONFLICT DO NOTHING;"
        )
    lines.append("")

    # 26. Adjudications & Sanctions
    for adj in data["adjudications"]:
        lines.append(
            f"INSERT INTO app.adjudications (id, case_id, evidence_snapshot_id, policy_version_id, analyst_id, outcome, rationale, explicit_human_approval, idempotency_key, request_hash, approved_at) VALUES ({sql_quote(adj['id'])}, {sql_quote(adj['case_id'])}, {sql_quote(adj['evidence_snapshot_id'])}, {sql_quote(adj['policy_version_id'])}, {sql_quote(adj['analyst_id'])}, {sql_quote(adj['outcome'])}, {sql_quote(adj['rationale'])}, {sql_quote(adj['explicit_human_approval'])}, {sql_quote(adj['idempotency_key'])}, {sql_bytea(adj['request_hash'])}, {sql_quote(adj['approved_at'])}) ON CONFLICT DO NOTHING;"
        )
    for sanc in data["sanctions"]:
        lines.append(
            f"INSERT INTO app.sanctions (id, adjudication_id, driver_id, kind, amount_minor, currency, starts_at, ends_at, status, external_effect_key, is_simulated, created_at) VALUES ({sql_quote(sanc['id'])}, {sql_quote(sanc['adjudication_id'])}, {sql_quote(sanc['driver_id'])}, {sql_quote(sanc['kind'])}, {sql_quote(sanc['amount_minor'])}, {sql_quote(sanc['currency'])}, {sql_quote(sanc['starts_at'])}, {sql_quote(sanc['ends_at'])}, {sql_quote(sanc['status'])}, {sql_quote(sanc['external_effect_key'])}, {sql_quote(sanc['is_simulated'])}, {sql_quote(sanc['created_at'])}) ON CONFLICT DO NOTHING;"
        )
    lines.append("")

    lines.append("COMMIT;")

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Generated {len(lines)} SQL lines to {out_file}")


if __name__ == "__main__":
    generate_sql(Path("data/synthetic/seed_data.json"), Path("db/seed_cloud.sql"))
