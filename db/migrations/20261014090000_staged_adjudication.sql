-- Issue #236: durable analyst judgment gate and final decision context.
set search_path = app, extensions, public;

create table if not exists app.preliminary_judgments (
    id uuid primary key default gen_random_uuid(),
    case_id uuid not null unique references app.fraud_cases(id) on delete restrict,
    analyst_id uuid not null references app.principals(id) on delete restrict,
    judgment text not null check (judgment in (
        'Nghi ngờ vi phạm',
        'Nghi oan-bất khả kháng',
        'Chưa đủ cơ sở'
    )),
    note text,
    created_at timestamptz not null default now()
);

create index if not exists preliminary_judgments_analyst_idx
    on app.preliminary_judgments (analyst_id, created_at desc);

drop trigger if exists preliminary_judgments_append_only on app.preliminary_judgments;
create trigger preliminary_judgments_append_only
before update or delete on app.preliminary_judgments
for each row execute function app.reject_mutation();

alter table app.adjudications
    add column if not exists staged_context jsonb not null default '{}'::jsonb;

comment on column app.adjudications.staged_context is
    'Immutable snapshot of preliminary judgment, AI suggestion, and deterministic delta.';

alter table app.preliminary_judgments enable row level security;

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'service_role') then
        execute 'grant select, insert on app.preliminary_judgments to service_role';
    end if;
end;
$$;

