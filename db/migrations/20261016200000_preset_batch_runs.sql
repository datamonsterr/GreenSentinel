set search_path = app, extensions, public;

create table if not exists preset_batch_runs (
    id uuid primary key default gen_random_uuid(),
    organization_id text not null,
    preset_id text not null,
    params jsonb not null default '{}'::jsonb,
    status text not null default 'QUEUED',
    counters jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    started_at timestamptz,
    completed_at timestamptz,
    cancelled_at timestamptz
);

create table if not exists preset_batch_trips (
    id uuid primary key default gen_random_uuid(),
    batch_id uuid not null references preset_batch_runs(id) on delete cascade,
    organization_id text not null,
    trip_ref text not null,
    trip_order integer not null,
    status text not null default 'QUEUED',
    expected_label text,
    predicted_label text,
    confidence double precision,
    case_id text,
    run_id uuid references test_runs(id) on delete set null,
    error text,
    snapshot jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    started_at timestamptz,
    completed_at timestamptz
);

create index if not exists idx_preset_batch_runs_org on preset_batch_runs(organization_id, created_at desc);
create index if not exists idx_preset_batch_trips_batch on preset_batch_trips(batch_id, trip_order);
create index if not exists idx_preset_batch_trips_org on preset_batch_trips(organization_id);
