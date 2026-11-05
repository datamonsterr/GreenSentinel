-- Issue #251 (migration part): benchmark dataset/run/prediction store.
-- Rollback: db/rollbacks/20261007100000_benchmark_store.down.sql
--
-- Vanilla-Postgres safe: float (double precision) + jsonb only.
-- Never geography/vector types: a fresh Railway service has NO PostGIS/pgvector.

create schema if not exists app;

create table if not exists app.benchmark_datasets (
    id uuid primary key default gen_random_uuid(),
    name text not null unique,
    version text,
    source text,
    license text,
    artifact_sha256 text,
    row_count integer check (row_count is null or row_count >= 0),
    fields jsonb not null default '{}'::jsonb,
    acquired_at timestamptz,
    provenance jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists app.benchmark_runs (
    id uuid primary key default gen_random_uuid(),
    dataset_id uuid not null references app.benchmark_datasets(id) on delete cascade,
    generator_version text,
    seed bigint,
    config jsonb not null default '{}'::jsonb,
    class_mix jsonb not null default '{}'::jsonb,
    trip_count integer check (trip_count is null or trip_count >= 0),
    started_at timestamptz,
    completed_at timestamptz,
    status text not null default 'queued'
        check (status in ('queued', 'running', 'completed', 'failed')),
    check (completed_at is null or started_at is null or completed_at >= started_at)
);

create table if not exists app.benchmark_predictions (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references app.benchmark_runs(id) on delete cascade,
    trip_ref text not null,
    label text check (label in ('ERR-01', 'ERR-02', 'ERR-03', 'ERR-04', 'ERR-05', 'no_violation', 'insufficient_evidence')),
    predicted_category text,
    confidence double precision check (confidence is null or (confidence >= 0 and confidence <= 1)),
    priority_tier integer check (priority_tier is null or (priority_tier >= 0 and priority_tier <= 2)),
    reason_codes jsonb not null default '[]'::jsonb,
    guardrail_blocked boolean not null default false,
    unique (run_id, trip_ref)
);

-- Lookup indexes: per-run prediction fetch by trip ref and by label.
create index if not exists idx_benchmark_predictions_run_trip on app.benchmark_predictions (run_id, trip_ref);
create index if not exists idx_benchmark_predictions_run_label on app.benchmark_predictions (run_id, label);

-- Mirror the 0001 tail: benchmark tables live in app, revoked from browser roles.
revoke all on all tables in schema app from public;

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'anon') then
        execute 'revoke all on all tables in schema app from anon';
    end if;
    if exists (select 1 from pg_roles where rolname = 'authenticated') then
        execute 'revoke all on all tables in schema app from authenticated';
    end if;
end;
$$;
