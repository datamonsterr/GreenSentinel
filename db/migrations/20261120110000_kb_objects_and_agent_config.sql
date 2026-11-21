-- PRD-K foundation (ADR-032): generic versioned knowledge objects, agent config + history,
-- policy documents and the proposals queue. Additive + idempotent. Audit uses app.audit_events.

create table if not exists app.kb_object (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references app.organizations(id),
    type text not null check (type in ('parameter', 'motive', 'behavior', 'scenario', 'workflow')),
    code text not null check (code ~ '^[A-Za-z0-9_.-]{2,64}$'),
    version integer not null check (version >= 1),
    status text not null default 'draft'
        check (status in ('draft', 'ready_for_test', 'trial', 'published', 'retired')),
    name text not null default '',
    scope jsonb not null default '{}'::jsonb,
    body jsonb not null default '{}'::jsonb,
    change_reason text,
    author_id uuid references app.principals(id),
    author_name text,
    approver_id uuid references app.principals(id),
    approver_name text,
    replay jsonb,
    override_reason text,
    retired_reason text,
    history jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    published_at timestamptz,
    retired_at timestamptz,
    unique (organization_id, type, code, version)
);
create index if not exists kb_object_org_type_status_idx on app.kb_object (organization_id, type, status);
-- at most one published version per object code
create unique index if not exists kb_object_one_published_idx
    on app.kb_object (organization_id, type, code) where status = 'published';

create table if not exists app.agent_config (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references app.organizations(id),
    key text not null,
    scope text not null default 'global',
    value jsonb not null,
    updated_by uuid references app.principals(id),
    updated_at timestamptz not null default now(),
    unique (organization_id, key, scope)
);

create table if not exists app.agent_config_history (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references app.organizations(id),
    key text not null,
    scope text not null default 'global',
    old_value jsonb,
    new_value jsonb not null,
    reason text,
    kind text not null default 'change' check (kind in ('change', 'revert', 'kill_switch')),
    changed_by uuid references app.principals(id),
    changed_by_name text,
    created_at timestamptz not null default now()
);
create index if not exists agent_config_history_key_idx on app.agent_config_history (organization_id, key, created_at desc);

create table if not exists app.kb_policy_document (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references app.organizations(id),
    name text not null,
    code text not null,
    effective_from date,
    effective_to date,
    region text,
    service text,
    contract_type text,
    filename text,
    content_type text,
    size_bytes integer not null default 0,
    text_excerpt text,
    indexing_status text not null default 'not_indexed'
        check (indexing_status in ('not_indexed', 'indexed', 'embeddings_not_configured')),
    uploaded_by uuid references app.principals(id),
    uploaded_by_name text,
    created_at timestamptz not null default now()
);
create index if not exists kb_policy_document_org_idx on app.kb_policy_document (organization_id, created_at desc);

create table if not exists app.kb_proposal (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references app.organizations(id),
    source text not null check (source in ('policy_analysis', 'help_reply', 'closed_case', 'monitoring', 'manual')),
    type text not null check (type in ('parameter', 'motive', 'behavior', 'scenario', 'workflow')),
    title text not null,
    payload jsonb not null default '{}'::jsonb,
    source_excerpt text,
    source_ref text,
    mapping text not null default 'new' check (mapping in ('reuse', 'extend', 'new')),
    similarity numeric,
    matched_code text,
    status text not null default 'pending' check (status in ('pending', 'accepted', 'edited', 'rejected')),
    reason_code text,
    note text,
    decided_by uuid references app.principals(id),
    decided_at timestamptz,
    resulting_object_id uuid references app.kb_object(id),
    created_by text,
    created_at timestamptz not null default now()
);
create index if not exists kb_proposal_org_status_idx on app.kb_proposal (organization_id, status, created_at desc);
