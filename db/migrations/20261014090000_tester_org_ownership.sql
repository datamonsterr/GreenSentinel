-- Plan is the immutable tenant anchor. Descendants inherit ownership by FK joins.
-- Legacy NULL ownership is intentionally invisible to every scoped API read.
set search_path = app, extensions, public;
alter table test_plans add column if not exists organization_id uuid;
alter table test_plans add column if not exists created_by text;
-- Older tester schema declared this audit actor as uuid; fixture principals may
-- be opaque external IDs, so preserve the value as text across upgrades.
alter table test_plans alter column created_by type text using created_by::text;
alter table test_definition_revisions add column if not exists messages jsonb not null default '[]'::jsonb;
create index if not exists idx_test_plans_org_created on test_plans(organization_id, created_at desc);
create index if not exists idx_test_runs_definition on test_runs(definition_revision_id);

-- Separate durable tenant/key identity preserves legacy unscoped key rows.
create table if not exists test_run_requests (
    organization_id uuid not null,
    key varchar(255) not null,
    run_id uuid not null references test_runs(id) on delete cascade,
    created_at timestamptz not null default now(),
    primary key (organization_id, key)
);
create table if not exists test_cases (
    id text primary key,
    run_id uuid not null references test_runs(id) on delete cascade,
    payload jsonb not null
);
create index if not exists idx_test_cases_run on test_cases(run_id);
