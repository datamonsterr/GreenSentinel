-- S2-F09: durable solved-case context and precedent workflow history.
-- The PR #40 precedent_workflows table is retained only for explicit legacy
-- compatibility. Production retrieval uses solved_case_contexts.

set search_path = app, extensions, public;

create table app.solved_case_contexts (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references app.organizations(id),
    case_id uuid not null unique references app.fraud_cases(id) on delete restrict,
    assignment_id uuid not null references app.trip_assignments(id) on delete restrict,
    conversation_session_id uuid references app.case_agent_sessions(id) on delete restrict,
    driver_submission_id uuid references app.driver_submissions(id) on delete restrict,
    conversation_state text not null
        check (conversation_state in ('linked', 'not_available')),
    evidence_snapshot_id uuid not null references app.evidence_snapshots(id) on delete restrict,
    policy_version_id uuid not null references app.policy_versions(id) on delete restrict,
    adjudication_id uuid not null unique references app.adjudications(id) on delete restrict,
    published_by uuid not null references app.principals(id) on delete restrict,
    violation_code text,
    claim_type text,
    title text not null check (length(btrim(title)) > 0),
    driver_statement text,
    workflow_trace jsonb not null,
    workflow_trace_hash text not null check (workflow_trace_hash ~ '^[0-9a-f]{64}$'),
    trace_schema_version text not null default '2.0',
    source_kind text not null default 'finalized_case'
        check (source_kind = 'finalized_case'),
    read_only boolean not null default true check (read_only),
    eligible_for_reuse boolean not null default true,
    published_at timestamptz not null,
    created_at timestamptz not null default now()
);

create index solved_case_contexts_tenant_category_idx
    on app.solved_case_contexts (organization_id, violation_code, claim_type, published_at desc)
    where eligible_for_reuse;

create index solved_case_contexts_trace_gin_idx
    on app.solved_case_contexts using gin (workflow_trace);

create table app.precedent_reuse_history (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references app.organizations(id),
    current_case_id uuid not null references app.fraud_cases(id) on delete restrict,
    precedent_context_id uuid not null references app.solved_case_contexts(id) on delete restrict,
    actor_id uuid not null references app.principals(id) on delete restrict,
    action text not null check (action in ('viewed', 'applied')),
    similarity_score double precision not null check (similarity_score between 0 and 1),
    score_semantics text not null check (length(btrim(score_semantics)) > 0),
    retrieval_model text not null check (length(btrim(retrieval_model)) > 0),
    matching_factors jsonb not null default '[]'::jsonb,
    precedent_trace_hash text not null check (precedent_trace_hash ~ '^[0-9a-f]{64}$'),
    request_id uuid not null,
    created_at timestamptz not null default now(),
    unique (organization_id, current_case_id, actor_id, request_id, action)
);

create index precedent_reuse_history_case_idx
    on app.precedent_reuse_history (organization_id, current_case_id, created_at desc);

create or replace function app.validate_solved_case_context()
returns trigger
language plpgsql
as $$
declare
    case_row record;
    evidence_row record;
    decision_row record;
    session_row record;
    submission_row record;
begin
    select organization_id, assignment_id, status
      into case_row
      from app.fraud_cases
     where id = new.case_id;

    if case_row is null
       or case_row.organization_id <> new.organization_id
       or case_row.assignment_id <> new.assignment_id
       or case_row.status <> 'resolved' then
        raise exception 'solved context must bind to its resolved tenant case and assignment'
            using errcode = '23514';
    end if;

    select case_id, policy_version_id
      into evidence_row
      from app.evidence_snapshots
     where id = new.evidence_snapshot_id;

    if evidence_row is null
       or evidence_row.case_id <> new.case_id
       or evidence_row.policy_version_id <> new.policy_version_id then
        raise exception 'solved context evidence/policy linkage mismatch'
            using errcode = '23514';
    end if;

    select case_id, evidence_snapshot_id, policy_version_id, analyst_id,
           explicit_human_approval, approved_at
      into decision_row
      from app.adjudications
     where id = new.adjudication_id;

    if decision_row is null
       or decision_row.case_id <> new.case_id
       or decision_row.evidence_snapshot_id <> new.evidence_snapshot_id
       or decision_row.policy_version_id <> new.policy_version_id
       or decision_row.analyst_id <> new.published_by
       or not decision_row.explicit_human_approval
       or decision_row.approved_at <> new.published_at then
        raise exception 'solved context must bind to the signed human adjudication'
            using errcode = '23514';
    end if;

    if new.conversation_session_id is null then
        if new.driver_submission_id is null and new.conversation_state <> 'not_available' then
            raise exception 'missing conversation must be explicit'
                using errcode = '23514';
        end if;
    else
        select organization_id, case_id
          into session_row
          from app.case_agent_sessions
         where id = new.conversation_session_id;
        if session_row is null
           or session_row.organization_id <> new.organization_id
           or session_row.case_id <> new.case_id
           or new.conversation_state <> 'linked' then
            raise exception 'solved context conversation linkage mismatch'
                using errcode = '23514';
        end if;
    end if;

    if new.driver_submission_id is not null then
        select case_id into submission_row
          from app.driver_submissions
         where id = new.driver_submission_id;
        if submission_row is null
           or submission_row.case_id <> new.case_id
           or new.conversation_state <> 'linked' then
            raise exception 'solved context driver submission linkage mismatch'
                using errcode = '23514';
        end if;
    end if;

    return new;
end;
$$;

create trigger solved_case_contexts_validate
before insert on app.solved_case_contexts
for each row execute function app.validate_solved_case_context();

create trigger solved_case_contexts_append_only
before update or delete on app.solved_case_contexts
for each row execute function app.reject_mutation();

create or replace function app.validate_precedent_reuse_history()
returns trigger
language plpgsql
as $$
declare
    case_org uuid;
    precedent_row record;
    actor_org uuid;
begin
    select organization_id into case_org
      from app.fraud_cases where id = new.current_case_id;
    select organization_id, workflow_trace_hash, eligible_for_reuse
      into precedent_row
      from app.solved_case_contexts where id = new.precedent_context_id;
    select organization_id into actor_org
      from app.principals where id = new.actor_id;

    if case_org is distinct from new.organization_id
       or precedent_row.organization_id is distinct from new.organization_id
       or actor_org is distinct from new.organization_id
       or not precedent_row.eligible_for_reuse
       or precedent_row.workflow_trace_hash is distinct from new.precedent_trace_hash then
        raise exception 'precedent reuse tenant/provenance linkage mismatch'
            using errcode = '23514';
    end if;
    return new;
end;
$$;

create trigger precedent_reuse_history_validate
before insert on app.precedent_reuse_history
for each row execute function app.validate_precedent_reuse_history();

create trigger precedent_reuse_history_append_only
before update or delete on app.precedent_reuse_history
for each row execute function app.reject_mutation();

-- PR #40 records may be read by the explicit legacy adapter but cannot be
-- rewritten into apparently authoritative evidence.
create trigger precedent_workflows_append_only
before update or delete on app.precedent_workflows
for each row execute function app.reject_mutation();

alter table app.solved_case_contexts enable row level security;
alter table app.precedent_reuse_history enable row level security;

revoke all on app.solved_case_contexts, app.precedent_reuse_history from public;

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'anon') then
        execute 'revoke all on app.solved_case_contexts, app.precedent_reuse_history from anon';
    end if;
    if exists (select 1 from pg_roles where rolname = 'authenticated') then
        execute 'revoke all on app.solved_case_contexts, app.precedent_reuse_history from authenticated';
    end if;
    if exists (select 1 from pg_roles where rolname = 'service_role') then
        execute 'grant select, insert on app.solved_case_contexts, app.precedent_reuse_history to service_role';
    end if;
end;
$$;

comment on table app.solved_case_contexts is
    'Immutable finalized case context bound to real evidence, policy and signed adjudication.';
comment on table app.precedent_reuse_history is
    'Append-only advisory precedent views/applications; similarity never adjudicates a case.';
