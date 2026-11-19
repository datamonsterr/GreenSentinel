-- GSM workflow alignment (ADR-031): reviewer / ops_director / marketplace_director roles,
-- post-adjudication case statuses and an append-only workflow event log. Additive + idempotent.

alter table app.principal_roles drop constraint if exists principal_roles_role_check;
alter table app.principal_roles add constraint principal_roles_role_check
    check (role in ('analyst', 'fraud_analyst', 'senior_analyst', 'demo_operator', 'admin', 'manager', 'driver',
                    'reviewer', 'ops_director', 'marketplace_director'));

alter table app.fraud_cases drop constraint if exists fraud_cases_status_check;
alter table app.fraud_cases add constraint fraud_cases_status_check
    check (status in (
        'ingested', 'processing', 'ready', 'in_review', 'evidence_requested', 'escalated', 'resolved',
        'processing_failed', 'auto_dismissed', 'driver_disputed', 'pending_analyst_review',
        'report_issued', 'report_confirmed', 'need_ops_dir_approved', 'need_mkp_dir_approved', 'completed'
    ));

create table if not exists app.case_workflow_events (
    id uuid primary key default gen_random_uuid(),
    case_id uuid not null references app.fraud_cases(id),
    organization_id uuid not null references app.organizations(id),
    step text not null,
    from_status text not null,
    to_status text not null,
    actor_id uuid references app.principals(id),
    actor_role text not null,
    created_at timestamptz not null default now()
);
create index if not exists case_workflow_events_case_idx on app.case_workflow_events (case_id, created_at);
