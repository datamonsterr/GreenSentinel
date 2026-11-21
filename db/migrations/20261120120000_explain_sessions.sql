-- PRD-A (ADR-034): driver explanation sessions v2. Additive + idempotent, schema app.
-- explain_session (1 per case), statement_version (immutable), assessment_round, explain_turn,
-- help_request (VH queue) and vh_feedback (structured Agree/Disagree).

create table if not exists app.explain_session (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references app.organizations(id),
    case_id uuid not null references app.fraud_cases(id),
    driver_id text not null,
    reason text not null,
    state text not null default 'draft'
        check (state in ('draft', 'investigating', 'asking', 'summary', 'submitted')),
    mode text not null default 'agent' check (mode in ('agent', 'fallback')),
    form_version text not null,
    form_schema jsonb not null default '{}'::jsonb,
    answers jsonb not null default '{}'::jsonb,
    workflow_code text,
    workflow_version integer,
    scenario_code text,
    scenario_version integer,
    novel_scenario boolean not null default false,
    statement_changed boolean not null default false,
    ai_inconclusive boolean not null default false,
    session_interrupted boolean not null default false,
    asked_for_help boolean not null default false,
    asked_for_help_skipped boolean not null default false,
    turns_used integer not null default 0,
    n_max integer not null default 6,
    edits_used integer not null default 0,
    help_count integer not null default 0,
    plan jsonb not null default '[]'::jsonb,
    memory jsonb not null default '{}'::jsonb,
    provenance jsonb not null default '[]'::jsonb,
    open_points jsonb not null default '[]'::jsonb,
    summary text,
    model text,
    instruction_version text,
    started_at timestamptz not null default now(),
    last_interaction_at timestamptz not null default now(),
    submitted_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (organization_id, case_id)
);
create index if not exists explain_session_state_idx on app.explain_session (organization_id, state);

create table if not exists app.statement_version (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references app.organizations(id),
    session_id uuid not null references app.explain_session(id),
    version integer not null check (version >= 1),
    source text not null check (source in ('form', 'chat', 'edit', 'summary', 'auto')),
    reason text,
    content jsonb not null default '{}'::jsonb,
    text text not null default '',
    created_at timestamptz not null default now(),
    unique (session_id, version)
);

-- statement versions are immutable (statement_v1 especially): no update, no delete.
create or replace function app.statement_version_immutable() returns trigger as $$
begin
    raise exception 'statement_version rows are immutable';
end;
$$ language plpgsql;
drop trigger if exists statement_version_immutable_trg on app.statement_version;
create trigger statement_version_immutable_trg
    before update or delete on app.statement_version
    for each row execute function app.statement_version_immutable();

create table if not exists app.assessment_round (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references app.organizations(id),
    session_id uuid not null references app.explain_session(id),
    round integer not null check (round >= 1),
    source text not null check (source in ('form', 'chat')),
    state text not null check (state in ('eligible', 'not_eligible', 'needs_driver', 'missing_internal')),
    matched_evidence jsonb not null default '[]'::jsonb,
    contradictions jsonb not null default '[]'::jsonb,
    open_points jsonb not null default '[]'::jsonb,
    missing_internal jsonb not null default '[]'::jsonb,
    statement_change text,
    confidence double precision not null default 0,
    suggested_reason_code text,
    suggested_questions jsonb not null default '[]'::jsonb,
    motive jsonb,
    provenance jsonb not null default '[]'::jsonb,
    turns_used integer not null default 0,
    n_max integer not null default 0,
    llm_used boolean not null default false,
    created_at timestamptz not null default now(),
    unique (session_id, round)
);

create table if not exists app.explain_turn (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references app.organizations(id),
    session_id uuid not null references app.explain_session(id),
    seq integer not null,
    kind text not null check (kind in ('agent_message', 'agent_question', 'driver_answer', 'tool_call',
                                       'plan_update', 'help', 'guard', 'flag', 'system')),
    visible_to_driver boolean not null default false,
    content text not null default '',
    payload jsonb not null default '{}'::jsonb,
    tool text,
    kb_code text,
    kb_version integer,
    created_at timestamptz not null default now(),
    unique (session_id, seq)
);

create table if not exists app.help_request (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references app.organizations(id),
    session_id uuid not null references app.explain_session(id),
    case_id uuid not null references app.fraud_cases(id),
    status text not null default 'open' check (status in ('open', 'claimed', 'answered', 'expired')),
    trigger text not null,
    summary text not null default '',
    stuck_point text not null default '',
    facts jsonb not null default '[]'::jsonb,
    options jsonb not null default '[]'::jsonb,
    claimed_by text,
    claimed_by_name text,
    claimed_at timestamptz,
    reply text,
    reply_facts jsonb not null default '[]'::jsonb,
    replied_by text,
    replied_by_name text,
    replied_at timestamptz,
    wait_seconds integer,
    consumed boolean not null default false,
    proposal_id text,
    expires_at timestamptz not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index if not exists help_request_queue_idx on app.help_request (organization_id, status, created_at);

create table if not exists app.vh_feedback (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references app.organizations(id),
    session_id uuid not null references app.explain_session(id),
    case_id uuid not null references app.fraud_cases(id),
    verdict text not null check (verdict in ('agree', 'disagree')),
    error_types jsonb not null default '[]'::jsonb,
    comment text,
    author_id text,
    author_name text,
    created_at timestamptz not null default now()
);
create index if not exists vh_feedback_session_idx on app.vh_feedback (session_id, created_at);
