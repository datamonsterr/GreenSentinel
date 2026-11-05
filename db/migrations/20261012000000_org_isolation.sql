-- S4-TENANT #294: organization isolation hardening (ADR-025).
-- Adds org-scoped indexes, cross-table ownership triggers, and a quarantine
-- table for ambiguous legacy rows. Ambiguous rows are quarantined and
-- documented, never auto-assigned to every org. Idempotent: safe to re-run.

set search_path = app, extensions, public;

-- 1. Org-scoped indexes for tenant-filtered reads (counts, lists, SSE scope checks).
create index if not exists fraud_cases_org_status_idx
    on app.fraud_cases (organization_id, status, created_at desc);
create index if not exists fraud_cases_org_assignee_idx
    on app.fraud_cases (organization_id, assigned_analyst_id);
create index if not exists trips_org_idx on app.trips (organization_id);
create index if not exists drivers_org_idx on app.drivers (organization_id);
create index if not exists principals_org_subject_idx
    on app.principals (organization_id, external_subject);
create index if not exists ingest_events_org_idx on app.ingest_events (organization_id);
create index if not exists audit_events_org_idx on app.audit_events (organization_id);

-- 2. Ownership triggers: child rows must belong to the same org as their parent.
create or replace function app.check_trip_assignment_org() returns trigger as $$
declare
    trip_org uuid;
    driver_org uuid;
begin
    select organization_id into trip_org from app.trips where id = new.trip_id;
    select organization_id into driver_org from app.drivers where id = new.driver_id;
    if trip_org is null or driver_org is null then
        raise exception 'trip_assignment references missing trip/driver (%)', new.id
            using errcode = 'foreign_key_violation';
    end if;
    if trip_org is distinct from driver_org then
        raise exception 'trip_assignment cross-org: trip % <> driver %', trip_org, driver_org
            using errcode = 'foreign_key_violation';
    end if;
    return new;
end;
$$ language plpgsql;

drop trigger if exists trip_assignment_org_match on app.trip_assignments;
create trigger trip_assignment_org_match
    before insert or update of trip_id, driver_id on app.trip_assignments
    for each row execute function app.check_trip_assignment_org();

create or replace function app.check_fraud_case_org() returns trigger as $$
declare
    assignment_org uuid;
begin
    select t.organization_id into assignment_org
    from app.trip_assignments a join app.trips t on t.id = a.trip_id
    where a.id = new.assignment_id;
    if assignment_org is null then
        raise exception 'fraud_case references missing assignment (%)', new.id
            using errcode = 'foreign_key_violation';
    end if;
    if assignment_org is distinct from new.organization_id then
        raise exception 'fraud_case cross-org: case % <> assignment %', new.organization_id, assignment_org
            using errcode = 'foreign_key_violation';
    end if;
    return new;
end;
$$ language plpgsql;

drop trigger if exists fraud_case_org_match on app.fraud_cases;
create trigger fraud_case_org_match
    before insert or update of assignment_id, organization_id on app.fraud_cases
    for each row execute function app.check_fraud_case_org();

create or replace function app.check_driver_principal_org() returns trigger as $$
declare
    principal_org uuid;
begin
    if new.principal_id is null then
        return new;
    end if;
    select organization_id into principal_org from app.principals where id = new.principal_id;
    if principal_org is null then
        raise exception 'driver references missing principal (%)', new.id
            using errcode = 'foreign_key_violation';
    end if;
    -- Invited Driver binds explicitly via Admin API driver link; the linked
    -- principal must belong to the same org. Seeded driver/customer entities
    -- carry no principal until that explicit bind.
    if principal_org is distinct from new.organization_id then
        raise exception 'driver cross-org: driver % <> principal %', new.organization_id, principal_org
            using errcode = 'foreign_key_violation';
    end if;
    return new;
end;
$$ language plpgsql;

drop trigger if exists driver_principal_org_match on app.drivers;
create trigger driver_principal_org_match
    before insert or update of principal_id, organization_id on app.drivers
    for each row execute function app.check_driver_principal_org();

-- 3. Quarantine for ambiguous legacy rows: documented, never auto-assigned.
create table if not exists app.org_quarantine (
    id uuid primary key default gen_random_uuid(),
    table_name text not null,
    row_id uuid not null,
    reason text not null,
    detail jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique (table_name, row_id)
);

-- Legacy trip_assignments whose trip and driver orgs disagree.
insert into app.org_quarantine (table_name, row_id, reason, detail)
select 'trip_assignments', a.id, 'trip_org_mismatch',
       jsonb_build_object('trip_org', t.organization_id, 'driver_org', d.organization_id)
from app.trip_assignments a
join app.trips t on t.id = a.trip_id
join app.drivers d on d.id = a.driver_id
where t.organization_id is distinct from d.organization_id
on conflict (table_name, row_id) do nothing;

-- Legacy fraud_cases whose org disagrees with the assignment's trip org.
insert into app.org_quarantine (table_name, row_id, reason, detail)
select 'fraud_cases', c.id, 'case_org_mismatch',
       jsonb_build_object('case_org', c.organization_id, 'trip_org', t.organization_id)
from app.fraud_cases c
join app.trip_assignments a on a.id = c.assignment_id
join app.trips t on t.id = a.trip_id
where c.organization_id is distinct from t.organization_id
on conflict (table_name, row_id) do nothing;

-- Legacy drivers linked to a principal from another org.
insert into app.org_quarantine (table_name, row_id, reason, detail)
select 'drivers', d.id, 'driver_principal_org_mismatch',
       jsonb_build_object('driver_org', d.organization_id, 'principal_org', p.organization_id)
from app.drivers d
join app.principals p on p.id = d.principal_id
where d.organization_id is distinct from p.organization_id
on conflict (table_name, row_id) do nothing;
