-- Explicit-admission sanctions are test/dev-only until a production policy is published.
create table if not exists app.driver_admission_sanctions (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references app.organizations(id),
    case_id uuid not null references app.fraud_cases(id),
    driver_id uuid not null references app.drivers(id),
    driver_submission_id uuid not null references app.driver_submissions(id),
    policy_version_id uuid not null references app.policy_versions(id),
    admission_hash bytea not null,
    action text not null check (action in ('WARN', 'FINE', 'SUSPEND')),
    amount_vnd integer check (amount_vnd is null or amount_vnd > 0),
    duration_days integer check (duration_days is null or duration_days > 0),
    status text not null check (status in ('applied', 'pending_policy', 'analyst_review')),
    idempotency_key text not null unique,
    created_at timestamptz not null default now(),
    unique (case_id, admission_hash, policy_version_id)
);

alter table app.driver_admission_sanctions enable row level security;
do $$
begin
    if exists (select 1 from pg_roles where rolname = 'authenticated') then
        execute $policy$
            create policy driver_admission_sanctions_org_read on app.driver_admission_sanctions
                for select to authenticated using (exists (
                    select 1 from app.principals p
                    where p.organization_id = driver_admission_sanctions.organization_id
                      and p.external_subject = (select auth.uid())::text
                      and p.status = 'active'
                ))
        $policy$;
    end if;
end
$$;
comment on table app.driver_admission_sanctions is
    'Immutable explicit-driver-admission outcomes; production mappings must use a published non-demo policy.';

insert into app.policy_versions
    (version, status, effective_from, source_hash, action_matrix, is_demo_policy)
values
    ('p063-demo-admission-v1', 'published', now(), extensions.digest('p063-demo-admission-v1', 'sha256'),
     '{"ERR-02":{"default_sanction":"WARN"}}'::jsonb, true)
on conflict (version) do nothing;

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'authenticated') then
        execute 'revoke update, delete on app.driver_admission_sanctions from authenticated';
    end if;
end
$$;
