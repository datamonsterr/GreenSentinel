-- SPEC-0130: Tester Trip Simulation & Evaluation Architecture
-- Tables for isolated simulation authoring, execution, telemetry sampling, and intercepted notification sink.

create schema if not exists extensions;
create schema if not exists app;

create extension if not exists pgcrypto with schema extensions;
create extension if not exists postgis with schema extensions;

set search_path = app, extensions, public;

-- Test Scenario Container
create table if not exists test_plans (
    id uuid primary key default gen_random_uuid(),
    name varchar(255) not null,
    description text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- Immutable Scenario Definitions
create table if not exists test_definition_revisions (
    id uuid primary key default gen_random_uuid(),
    plan_id uuid not null references test_plans(id) on delete cascade,
    revision_number int not null default 1,
    route_geometry jsonb not null,
    driver_config jsonb not null default '{}'::jsonb,
    passenger_config jsonb not null default '{}'::jsonb,
    fault_configs jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    constraint unique_plan_revision unique(plan_id, revision_number)
);

-- Active & Historical Simulation Runs
create table if not exists test_runs (
    id uuid primary key default gen_random_uuid(),
    definition_revision_id uuid not null references test_definition_revisions(id),
    status varchar(32) not null default 'QUEUED',
    current_step int not null default 0,
    total_steps int not null default 0,
    simulation_clock timestamptz not null,
    speed_factor float not null default 1.0,
    created_at timestamptz not null default now(),
    started_at timestamptz,
    completed_at timestamptz
);

-- Link operational trips to isolated simulation runs without changing their
-- production meaning.  The tester repository uses this marker to enforce
-- test tenancy at the database boundary.
alter table if exists app.trips
    add column if not exists test_run_id uuid references test_runs(id) on delete set null;

-- Real-time Control Overrides
create table if not exists test_controls (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references test_runs(id) on delete cascade,
    command varchar(32) not null,
    payload jsonb default '{}'::jsonb,
    executed_at timestamptz not null default now()
);

-- Emitted Telemetry Log
create table if not exists test_samples (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references test_runs(id) on delete cascade,
    step_index int not null,
    latitude float not null,
    longitude float not null,
    speed_mps float not null default 0.0,
    heading_deg float not null default 0.0,
    is_fault_injected boolean not null default false,
    fault_type varchar(32),
    emitted_at timestamptz not null default now()
);

-- Execution Events Stream
create table if not exists test_events (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references test_runs(id) on delete cascade,
    event_type varchar(64) not null,
    event_payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

-- Audio Conversation Scripts
create table if not exists test_messages (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references test_runs(id) on delete cascade,
    sender_role varchar(32) not null,
    content text not null,
    offset_seconds int not null,
    created_at timestamptz not null default now()
);

-- Intercepted Sink Notifications
create table if not exists test_notifications (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references test_runs(id) on delete cascade,
    recipient_type varchar(32) not null,
    recipient_id varchar(128) not null,
    channel varchar(32) not null,
    body text not null,
    intercepted_at timestamptz not null default now()
);

-- Transactional Outbox Pattern
create table if not exists test_outbox (
    id uuid primary key default gen_random_uuid(),
    aggregate_type varchar(64) not null,
    aggregate_id varchar(128) not null,
    payload jsonb not null,
    processed boolean not null default false,
    created_at timestamptz not null default now()
);

-- Idempotency Locks
create table if not exists test_idempotency_keys (
    key varchar(255) primary key,
    run_id uuid references test_runs(id) on delete cascade,
    created_at timestamptz not null default now()
);

-- Compatibility view for the tester repository.  The operational schema owns
-- fraud_cases and trip_assignments; expose the legacy simulation shape while
-- retaining organization and run isolation through the joined trip marker.
create or replace view app.cases as
select
    c.id,
    a.trip_id,
    c.priority_score as risk_score,
    case when c.suspected_category is null then '[]'::jsonb
         else jsonb_build_array(c.suspected_category) end as anomaly_types,
    c.status,
    c.created_at,
    c.updated_at
from app.fraud_cases c
join app.trip_assignments a on a.id = c.assignment_id;

-- Compatibility view app.assignments aliasing app.case_assignment_history
create or replace view app.assignments as
select
    id,
    case_id,
    to_analyst_id as assignee_id,
    assigned_at
from app.case_assignment_history;

-- Indexes for efficient simulation queries
create index if not exists idx_test_runs_status on test_runs(status);
create index if not exists idx_test_samples_run_id_step on test_samples(run_id, step_index);
create index if not exists idx_test_events_run_id on test_events(run_id);
create index if not exists idx_test_messages_run_id on test_messages(run_id);
create index if not exists idx_test_controls_run_id on test_controls(run_id);
create index if not exists idx_test_notifications_run_id on test_notifications(run_id);
create index if not exists idx_test_outbox_processed on test_outbox(processed) where not processed;
