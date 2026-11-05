set search_path = app, extensions, public;

create table if not exists test_run_submissions (
    run_id uuid primary key references test_runs(id) on delete cascade,
    organization_id text not null,
    result jsonb not null,
    created_at timestamptz not null default now()
);

create index if not exists idx_test_run_submissions_org on test_run_submissions(organization_id);
