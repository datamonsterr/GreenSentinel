-- Migration: 20260926180000_poc_v2_driver_role_and_dispute.sql
-- Slice 1: POC v2 Driver Role, Dispute Management, and Autonomous Exoneration.

set search_path = app, extensions, public;

-- 1. Update app.principal_roles check constraint to include 'driver'
alter table app.principal_roles drop constraint if exists principal_roles_role_check;
alter table app.principal_roles add constraint principal_roles_role_check
    check (role in ('analyst', 'senior_analyst', 'demo_operator', 'admin', 'driver', 'fraud_analyst', 'manager'));

-- 2. Add dispute fields and support dispute statuses to app.fraud_cases
alter table app.fraud_cases
    add column if not exists dispute_status text not null default 'not_disputed'
        check (dispute_status in ('not_disputed', 'pending', 'in_dispute', 'auto_dismissed', 'analyst_escalated')),
    add column if not exists dispute_deadline timestamptz;

alter table app.fraud_cases drop constraint if exists fraud_cases_status_check;
alter table app.fraud_cases add constraint fraud_cases_status_check
    check (status in ('ingested', 'processing', 'ready', 'in_review', 'evidence_requested', 'escalated', 'resolved', 'processing_failed', 'auto_dismissed', 'driver_disputed'));

-- 3. Update app.case_agent_messages role check constraint to include driver roles
alter table app.case_agent_messages drop constraint if exists case_agent_messages_role_check;
alter table app.case_agent_messages add constraint case_agent_messages_role_check
    check (role in ('user', 'assistant', 'analyst', 'driver', 'driver_agent'));

-- 4. Seed synthetic driver principals for existing drivers in app.drivers
do $$
declare
    d record;
    new_principal_id uuid;
begin
    for d in select id, organization_id, external_ref, display_name from app.drivers where principal_id is null loop
        new_principal_id := gen_random_uuid();
        insert into app.principals (id, organization_id, external_subject, display_name, status)
        values (
            new_principal_id,
            d.organization_id,
            coalesce(d.external_ref, 'driver_' || d.id::text),
            coalesce(d.display_name, 'Driver ' || substring(d.id::text, 1, 8)),
            'active'
        )
        on conflict (organization_id, external_subject) do update
            set display_name = excluded.display_name
        returning id into new_principal_id;

        update app.drivers set principal_id = new_principal_id where id = d.id;

        insert into app.principal_roles (principal_id, role)
        values (new_principal_id, 'driver')
        on conflict (principal_id, role) do nothing;
    end loop;
end;
$$;

-- Ensure all drivers with principal_id also have the 'driver' role granted
insert into app.principal_roles (principal_id, role)
select principal_id, 'driver'
from app.drivers
where principal_id is not null
on conflict (principal_id, role) do nothing;
