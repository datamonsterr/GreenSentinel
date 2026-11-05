-- GreenSentinel PoC schema: ride operations, telemetry, fraud analysis, and HITL review.
-- PostgreSQL 15+ / Supabase. All timestamps are UTC timestamptz values.

create schema if not exists extensions;
create schema if not exists app;

create extension if not exists pgcrypto with schema extensions;
create extension if not exists postgis with schema extensions;
do $$
begin
    create extension if not exists vector with schema extensions;
exception when others then
    if not exists (select 1 from pg_type where typname = 'vector') then
        create domain extensions.vector as text;
    end if;
end $$;

set search_path = app, extensions, public;

create table app.organizations (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    created_at timestamptz not null default now()
);

create table app.principals (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references app.organizations(id),
    external_subject text not null,
    display_name text not null,
    status text not null default 'active' check (status in ('active', 'disabled')),
    created_at timestamptz not null default now(),
    unique (organization_id, external_subject)
);

create table app.principal_roles (
    principal_id uuid not null references app.principals(id),
    role text not null check (role in ('analyst', 'senior_analyst', 'demo_operator', 'admin')),
    granted_at timestamptz not null default now(),
    primary key (principal_id, role)
);

create table app.passengers (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references app.organizations(id),
    principal_id uuid unique references app.principals(id),
    external_ref text,
    is_synthetic boolean not null default false,
    created_at timestamptz not null default now(),
    unique (organization_id, external_ref)
);

create table app.drivers (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references app.organizations(id),
    principal_id uuid unique references app.principals(id),
    external_ref text,
    partner_type text not null check (partner_type in ('fleet', 'owner_driver', 'rent_to_own')),
    account_status text not null default 'active' check (account_status in ('active', 'suspended', 'closed')),
    is_synthetic boolean not null default false,
    created_at timestamptz not null default now(),
    unique (organization_id, external_ref)
);

create table app.vehicles (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references app.organizations(id),
    registration_ref text not null,
    vehicle_type text not null check (vehicle_type in ('car', 'motorbike')),
    service_class text not null,
    telemetry_source text not null check (telemetry_source in ('tcu', 'smartphone', 'simulator')),
    created_at timestamptz not null default now(),
    unique (organization_id, registration_ref)
);

create table app.driver_vehicle_assignments (
    id uuid primary key default gen_random_uuid(),
    driver_id uuid not null references app.drivers(id),
    vehicle_id uuid not null references app.vehicles(id),
    effective_from timestamptz not null,
    effective_to timestamptz,
    check (effective_to is null or effective_to > effective_from)
);

create table app.trips (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references app.organizations(id),
    passenger_id uuid not null references app.passengers(id),
    requested_at timestamptz not null,
    pickup geography(Point, 4326) not null,
    dropoff geography(Point, 4326) not null,
    requested_service_class text not null,
    status text not null check (status in ('requested', 'matched', 'driver_arriving', 'in_progress', 'completed', 'cancelled')),
    cancelled_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz not null default now()
);

create table app.trip_assignments (
    id uuid primary key default gen_random_uuid(),
    trip_id uuid not null references app.trips(id),
    driver_id uuid not null references app.drivers(id),
    vehicle_id uuid not null references app.vehicles(id),
    state text not null check (state in ('offered', 'accepted', 'rejected', 'cancelled', 'arrived', 'started', 'completed')),
    offered_at timestamptz not null,
    accepted_at timestamptz,
    arrived_at timestamptz,
    started_at timestamptz,
    ended_at timestamptz,
    cancellation_actor text check (cancellation_actor in ('passenger', 'driver', 'platform')),
    cancellation_reason text,
    created_at timestamptz not null default now()
);

create unique index uq_trip_one_active_assignment
    on app.trip_assignments (trip_id)
    where state in ('accepted', 'arrived', 'started');

create table app.fare_quotes (
    id uuid primary key default gen_random_uuid(),
    trip_id uuid not null references app.trips(id),
    version integer not null check (version > 0),
    currency char(3) not null,
    estimated_amount_minor bigint not null check (estimated_amount_minor >= 0),
    estimated_distance_m integer check (estimated_distance_m >= 0),
    estimated_duration_s integer check (estimated_duration_s >= 0),
    quoted_at timestamptz not null,
    unique (trip_id, version)
);

create table app.payment_transactions (
    id uuid primary key default gen_random_uuid(),
    trip_id uuid not null references app.trips(id),
    kind text not null check (kind in ('charge', 'refund', 'adjustment')),
    amount_minor bigint not null check (amount_minor >= 0),
    currency char(3) not null,
    status text not null check (status in ('pending', 'succeeded', 'failed', 'voided')),
    provider_ref text,
    is_simulated boolean not null default true,
    occurred_at timestamptz not null,
    unique (provider_ref)
);

create table app.trip_events (
    id uuid primary key,
    trip_id uuid not null references app.trips(id),
    assignment_id uuid references app.trip_assignments(id),
    event_type text not null,
    aggregate_version integer not null check (aggregate_version > 0),
    occurred_at timestamptz not null,
    received_at timestamptz not null default now(),
    actor_type text not null check (actor_type in ('passenger', 'driver', 'platform', 'simulator')),
    payload jsonb not null,
    unique (trip_id, aggregate_version)
);

create table app.simulation_runs (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references app.organizations(id),
    scenario text not null check (scenario in ('intentional_dic', 'traffic_gridlock', 'technical_dropout', 'fake_gps', 'gps_jitter')),
    seed bigint not null,
    generator_version text not null,
    status text not null check (status in ('queued', 'running', 'completed', 'failed')),
    simulated_clock_origin timestamptz not null,
    started_at timestamptz,
    finished_at timestamptz,
    requested_by uuid references app.principals(id),
    created_at timestamptz not null default now()
);

create table app.ingest_events (
    event_id uuid primary key,
    organization_id uuid not null references app.organizations(id),
    schema_version integer not null check (schema_version > 0),
    event_type text not null,
    source text not null,
    occurred_at timestamptz not null,
    received_at timestamptz not null default now(),
    correlation_id uuid not null,
    causation_id uuid,
    simulation_run_id uuid references app.simulation_runs(id),
    trip_id uuid not null references app.trips(id),
    assignment_id uuid not null references app.trip_assignments(id),
    driver_id uuid not null references app.drivers(id),
    producer_sequence bigint,
    payload jsonb not null,
    payload_hash bytea not null,
    unique (source, assignment_id, producer_sequence)
);

create table app.telemetry_points (
    event_id uuid primary key references app.ingest_events(event_id),
    assignment_id uuid not null references app.trip_assignments(id),
    occurred_at timestamptz not null,
    position geography(Point, 4326),
    speed_mps double precision check (speed_mps is null or speed_mps >= 0),
    bearing_deg double precision check (bearing_deg is null or (bearing_deg >= 0 and bearing_deg < 360)),
    accuracy_m double precision check (accuracy_m is null or accuracy_m >= 0),
    app_state text check (app_state in ('foreground', 'background', 'crashed', 'unknown')),
    network_state text check (network_state in ('online', 'offline', 'degraded', 'unknown')),
    gps_state text check (gps_state in ('valid', 'jitter', 'unavailable', 'mock_reported', 'unknown')),
    mock_location_reported boolean,
    check (position is not null or app_state = 'crashed' or network_state in ('offline', 'degraded') or gps_state in ('unavailable', 'unknown'))
);

create table app.route_snapshots (
    id uuid primary key default gen_random_uuid(),
    assignment_id uuid not null references app.trip_assignments(id),
    calculated_at timestamptz not null,
    provider text not null,
    routing_profile text not null,
    map_version text,
    route geography(LineString, 4326) not null,
    distance_m integer not null check (distance_m >= 0),
    duration_s integer not null check (duration_s >= 0),
    provenance jsonb not null default '{}'::jsonb
);

create table app.traffic_observations (
    id uuid primary key default gen_random_uuid(),
    assignment_id uuid not null references app.trip_assignments(id),
    observed_at timestamptz not null,
    valid_until timestamptz,
    average_speed_mps double precision check (average_speed_mps is null or average_speed_mps >= 0),
    congestion_level text check (congestion_level in ('clear', 'moderate', 'heavy', 'unknown')),
    source text not null,
    is_simulated boolean not null,
    provenance jsonb not null default '{}'::jsonb,
    check (valid_until is null or valid_until >= observed_at)
);

create table app.platform_incidents (
    id uuid primary key default gen_random_uuid(),
    assignment_id uuid not null references app.trip_assignments(id),
    incident_type text not null check (incident_type in ('app_crash', 'network_loss', 'gps_unavailable', 'service_outage')),
    state text not null check (state in ('observed', 'inferred', 'unknown')),
    started_at timestamptz not null,
    ended_at timestamptz,
    source_event_id uuid references app.ingest_events(event_id),
    details jsonb not null default '{}'::jsonb
);

create table app.passenger_feedback (
    id uuid primary key default gen_random_uuid(),
    assignment_id uuid not null references app.trip_assignments(id),
    submitted_at timestamptz not null,
    reason_code text,
    statement text,
    is_synthetic boolean not null default false
);

create table app.policy_versions (
    id uuid primary key default gen_random_uuid(),
    version text not null unique,
    status text not null check (status in ('draft', 'published', 'retired')),
    effective_from timestamptz,
    effective_to timestamptz,
    source_hash bytea not null,
    action_matrix jsonb not null,
    is_demo_policy boolean not null default true,
    created_at timestamptz not null default now(),
    check (effective_to is null or effective_to > effective_from)
);

create table app.policy_chunks (
    id uuid primary key default gen_random_uuid(),
    policy_version_id uuid not null references app.policy_versions(id),
    source_ref text not null,
    section_ref text,
    content text not null,
    content_hash bytea not null,
    embedding extensions.vector,
    embedding_model text,
    unique (policy_version_id, content_hash)
);

create table app.fraud_cases (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references app.organizations(id),
    assignment_id uuid not null unique references app.trip_assignments(id),
    status text not null check (status in ('ingested', 'processing', 'ready', 'in_review', 'evidence_requested', 'escalated', 'resolved', 'processing_failed')),
    suspected_category text check (suspected_category in ('ERR-01', 'ERR-02', 'ERR-03', 'ERR-04', 'ERR-05', 'no_violation', 'insufficient_evidence')),
    priority_tier smallint not null check (priority_tier between 0 and 2),
    priority_score integer not null,
    priority_rule_version text not null,
    assigned_analyst_id uuid references app.principals(id),
    required_role text not null default 'analyst' check (required_role in ('analyst', 'senior_analyst')),
    version integer not null default 1 check (version > 0),
    sla_due_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    resolved_at timestamptz
);

create table app.driver_submissions (
    id uuid primary key default gen_random_uuid(),
    case_id uuid not null references app.fraud_cases(id),
    status text not null check (status in ('requested', 'present', 'late', 'rejected', 'quarantined', 'no_report')),
    statement text,
    deadline_at timestamptz,
    received_at timestamptz,
    provenance jsonb not null default '{}'::jsonb
);

create table app.evidence_snapshots (
    id uuid primary key default gen_random_uuid(),
    case_id uuid not null references app.fraud_cases(id),
    version integer not null check (version > 0),
    policy_version_id uuid not null references app.policy_versions(id),
    event_cutoff_at timestamptz not null,
    stage text not null check (stage in ('pre_cancellation', 'post_cancellation')),
    dossier jsonb not null,
    dossier_hash bytea not null,
    created_at timestamptz not null default now(),
    unique (case_id, version)
);

create table app.feature_sets (
    id uuid primary key default gen_random_uuid(),
    evidence_snapshot_id uuid not null references app.evidence_snapshots(id),
    preprocessing_version text not null,
    window_start timestamptz not null,
    window_end timestamptz not null,
    telemetry_coverage double precision not null check (telemetry_coverage between 0 and 1),
    max_gap_s integer not null check (max_gap_s >= 0),
    davi double precision check (davi is null or davi between -1 and 1),
    stationary_duration_s integer check (stationary_duration_s is null or stationary_duration_s >= 0),
    traffic_observation_age_s integer check (traffic_observation_age_s is null or traffic_observation_age_s >= 0),
    quality_flags jsonb not null default '[]'::jsonb,
    features jsonb not null,
    created_at timestamptz not null default now(),
    check (window_end >= window_start),
    unique (evidence_snapshot_id, preprocessing_version)
);

create table app.model_assessments (
    id uuid primary key default gen_random_uuid(),
    evidence_snapshot_id uuid not null references app.evidence_snapshots(id),
    feature_set_id uuid not null references app.feature_sets(id),
    provider text not null,
    model_id text not null,
    prompt_version text not null,
    output_schema_version integer not null,
    status text not null check (status in ('pending', 'completed', 'failed', 'invalid_output')),
    category text check (category in ('ERR-01', 'ERR-02', 'ERR-03', 'ERR-04', 'ERR-05', 'no_violation', 'insufficient_evidence')),
    confidence double precision check (confidence is null or confidence between 0 and 1),
    score_semantics text not null,
    reason_codes jsonb not null default '[]'::jsonb,
    evidence_refs jsonb not null default '[]'::jsonb,
    forensic_brief text,
    raw_response jsonb,
    latency_ms integer check (latency_ms is null or latency_ms >= 0),
    trace_id text,
    created_at timestamptz not null default now()
);

create table app.case_assignment_history (
    id uuid primary key default gen_random_uuid(),
    case_id uuid not null references app.fraud_cases(id),
    from_analyst_id uuid references app.principals(id),
    to_analyst_id uuid references app.principals(id),
    to_required_role text check (to_required_role in ('analyst', 'senior_analyst')),
    assigned_by uuid not null references app.principals(id),
    reason text not null,
    assigned_at timestamptz not null default now()
);

create table app.review_leases (
    case_id uuid primary key references app.fraud_cases(id),
    analyst_id uuid not null references app.principals(id),
    token_hash bytea not null unique,
    case_version integer not null,
    evidence_snapshot_id uuid not null references app.evidence_snapshots(id),
    acquired_at timestamptz not null default now(),
    expires_at timestamptz not null,
    check (expires_at > acquired_at)
);

create table app.review_actions (
    id uuid primary key default gen_random_uuid(),
    case_id uuid not null references app.fraud_cases(id),
    evidence_snapshot_id uuid not null references app.evidence_snapshots(id),
    actor_id uuid not null references app.principals(id),
    action text not null check (action in ('request_evidence', 'escalate', 'defer')),
    comment text not null check (length(btrim(comment)) > 0),
    deadline_at timestamptz,
    idempotency_key uuid not null,
    created_at timestamptz not null default now(),
    unique (actor_id, idempotency_key)
);

create table app.adjudications (
    id uuid primary key default gen_random_uuid(),
    case_id uuid not null unique references app.fraud_cases(id),
    evidence_snapshot_id uuid not null references app.evidence_snapshots(id),
    policy_version_id uuid not null references app.policy_versions(id),
    analyst_id uuid not null references app.principals(id),
    outcome text not null check (outcome in ('dismiss', 'warn', 'fine', 'suspend')),
    rationale text not null check (length(btrim(rationale)) > 0),
    explicit_human_approval boolean not null check (explicit_human_approval),
    idempotency_key uuid not null,
    request_hash bytea not null,
    approved_at timestamptz not null default now(),
    unique (analyst_id, idempotency_key)
);

create table app.sanctions (
    id uuid primary key default gen_random_uuid(),
    adjudication_id uuid not null references app.adjudications(id),
    driver_id uuid not null references app.drivers(id),
    kind text not null check (kind in ('warning', 'fine', 'suspension')),
    amount_minor bigint check (amount_minor is null or amount_minor >= 0),
    currency char(3),
    starts_at timestamptz,
    ends_at timestamptz,
    status text not null check (status in ('approved', 'simulated_delivered', 'delivery_failed', 'revoked')),
    external_effect_key uuid not null unique,
    is_simulated boolean not null default true,
    created_at timestamptz not null default now(),
    check ((kind = 'fine' and amount_minor is not null and currency is not null)
        or (kind = 'suspension' and starts_at is not null and ends_at > starts_at)
        or (kind = 'warning' and amount_minor is null and starts_at is null))
);

create table app.jobs (
    id uuid primary key default gen_random_uuid(),
    kind text not null,
    aggregate_id uuid not null,
    aggregate_version integer not null,
    deduplication_key text not null unique,
    state text not null check (state in ('queued', 'running', 'retry', 'completed', 'failed')),
    attempts integer not null default 0 check (attempts >= 0),
    run_after timestamptz not null default now(),
    lease_expires_at timestamptz,
    last_error text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table app.outbox_events (
    id uuid primary key default gen_random_uuid(),
    aggregate_type text not null,
    aggregate_id uuid not null,
    aggregate_version integer not null,
    event_type text not null,
    payload jsonb not null,
    created_at timestamptz not null default now(),
    delivered_at timestamptz,
    unique (aggregate_type, aggregate_id, aggregate_version, event_type)
);

create table app.audit_events (
    sequence bigint generated always as identity primary key,
    event_id uuid not null unique default gen_random_uuid(),
    organization_id uuid not null references app.organizations(id),
    actor_id uuid references app.principals(id),
    case_id uuid references app.fraud_cases(id),
    action text not null,
    result text not null check (result in ('accepted', 'denied', 'failed')),
    request_id uuid not null,
    redacted_payload jsonb not null,
    previous_hash bytea,
    event_hash bytea not null,
    created_at timestamptz not null default now()
);

create table app.simulation_labels (
    simulation_run_id uuid not null references app.simulation_runs(id),
    assignment_id uuid not null references app.trip_assignments(id),
    expected_category text not null check (expected_category in ('ERR-02', 'ERR-05', 'no_violation', 'insufficient_evidence')),
    expected_guardrail text not null,
    expected_outcome text,
    primary key (simulation_run_id, assignment_id)
);

create table app.evaluation_runs (
    id uuid primary key default gen_random_uuid(),
    dataset_version text not null,
    model_id text not null,
    preprocessing_version text not null,
    sample_count integer not null check (sample_count > 0),
    metrics jsonb not null,
    started_at timestamptz not null,
    completed_at timestamptz
);

create index idx_trip_assignments_driver_time on app.trip_assignments (driver_id, accepted_at desc);
create index idx_telemetry_assignment_time on app.telemetry_points (assignment_id, occurred_at, event_id);
create index idx_ingest_received_brin on app.ingest_events using brin (received_at);
create index idx_trip_pickup_gist on app.trips using gist (pickup);
create index idx_trip_dropoff_gist on app.trips using gist (dropoff);
create index idx_telemetry_position_gist on app.telemetry_points using gist (position) where position is not null;
create index idx_case_queue on app.fraud_cases (priority_tier, priority_score desc, sla_due_at, created_at, id)
    where status in ('ready', 'in_review', 'evidence_requested', 'escalated');
create index idx_jobs_runnable on app.jobs (run_after, created_at)
    where state in ('queued', 'retry');
do $$
begin
    create index idx_policy_embedding on app.policy_chunks
        using hnsw (embedding vector_cosine_ops) where embedding is not null;
exception when others then
    null;
end $$;

create or replace function app.reject_mutation()
returns trigger
language plpgsql
as $$
begin
    raise exception '% is append-only', tg_table_name using errcode = '55000';
end;
$$;

create trigger evidence_snapshots_append_only
before update or delete on app.evidence_snapshots
for each row execute function app.reject_mutation();

create trigger feature_sets_append_only
before update or delete on app.feature_sets
for each row execute function app.reject_mutation();

create trigger model_assessments_append_only
before update or delete on app.model_assessments
for each row execute function app.reject_mutation();

create trigger adjudications_append_only
before update or delete on app.adjudications
for each row execute function app.reject_mutation();

create trigger audit_events_append_only
before update or delete on app.audit_events
for each row execute function app.reject_mutation();

revoke all on schema app from public;
revoke all on all tables in schema app from public;
revoke all on all functions in schema app from public;

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'anon') then
        execute 'revoke all on schema app from anon';
        execute 'revoke all on all tables in schema app from anon';
    end if;
    if exists (select 1 from pg_roles where rolname = 'authenticated') then
        execute 'revoke all on schema app from authenticated';
        execute 'revoke all on all tables in schema app from authenticated';
    end if;
end;
$$;

comment on column app.model_assessments.confidence is
    'Provider-returned per-case score. It is not evaluation accuracy and is a calibrated probability only when score_semantics says so.';
comment on table app.simulation_labels is
    'Ground truth for evaluation only. Detection workers must have no read access to this table.';
comment on table app.review_leases is
    'Short-lived exclusive submit right; separate from durable fraud_cases.assigned_analyst_id.';
comment on table app.audit_events is
    'Application append-only log. External checkpoints are required to detect privileged database-owner rewrites.';
