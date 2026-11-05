-- S4-ACTORS #295: per-org actor bootstrap state + uniqueness guards (ADR-025 §4).
-- Idempotent: safe to re-run. Seeded drivers/passengers carry no principal;
-- principal_id stays NULL until an explicit Admin driver-link.

set search_path = app, extensions, public;

-- 1. Resumable bootstrap progress + seed lineage per (org, template, seed).
create table if not exists app.org_bootstrap_state (
    organization_id uuid not null references app.organizations(id),
    template_version text not null,
    seed text not null,
    status text not null default 'running'
        check (status in ('running', 'ready', 'failed')),
    drivers_created integer not null default 0 check (drivers_created >= 0),
    customers_created integer not null default 0 check (customers_created >= 0),
    detail jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (organization_id, template_version, seed)
);

-- 2. Row-level seed lineage for customers (drivers already have profile_provenance).
alter table app.passengers
    add column if not exists profile_provenance jsonb not null default '{}'::jsonb;

-- 3. Ensure deterministic-id convergence: unique per (organization_id, external_ref).
-- Base schema (0001) already declares these; the blocks below only fill the gap
-- when a backing unique constraint/index is missing.
do $$
begin
    if not exists (
        select 1 from pg_indexes
        where schemaname = 'app' and tablename = 'drivers'
          and indexdef like '%(organization_id, external_ref)%'
    ) then
        create unique index uq_drivers_org_external_ref
            on app.drivers (organization_id, external_ref);
    end if;
    if not exists (
        select 1 from pg_indexes
        where schemaname = 'app' and tablename = 'passengers'
          and indexdef like '%(organization_id, external_ref)%'
    ) then
        create unique index uq_passengers_org_external_ref
            on app.passengers (organization_id, external_ref);
    end if;
end
$$;
