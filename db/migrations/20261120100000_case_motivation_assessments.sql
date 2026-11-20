-- S-M: structured, versioned motivation assessment per case (append-only versions, latest wins).
-- Additive and idempotent. Motive categories mirror MOTIVE_CATALOGUE in
-- src/services/case_motivation_service.py (later sourced from published kb motive objects).
create table if not exists app.case_motivation_assessments (
    id uuid primary key default gen_random_uuid(),
    case_id uuid not null references app.fraud_cases(id),
    organization_id uuid not null references app.organizations(id),
    version integer not null check (version >= 1),
    motive_category text not null
        check (motive_category in ('reward_threshold', 'subsidy_surge', 'fare_inflation', 'platform_fault', 'unclear')),
    signals jsonb not null default '[]'::jsonb,
    amount_at_stake_vnd numeric(14, 2) check (amount_at_stake_vnd is null or amount_at_stake_vnd >= 0),
    confidence numeric(4, 3) not null default 0 check (confidence >= 0 and confidence <= 1),
    rationale text not null default '',
    source text not null check (source in ('ai', 'rule', 'analyst')),
    status text not null default 'draft' check (status in ('draft', 'confirmed')),
    confirmed_by uuid references app.principals(id),
    confirmed_at timestamptz,
    created_by uuid references app.principals(id),
    created_at timestamptz not null default now(),
    unique (case_id, version)
);
create index if not exists case_motivation_assessments_case_idx
    on app.case_motivation_assessments (case_id, version desc);
create index if not exists case_motivation_assessments_org_idx
    on app.case_motivation_assessments (organization_id);
comment on table app.case_motivation_assessments is
    'Versioned structured motivation assessments; rows are only updated by confirm (status/confirmed_*).';
