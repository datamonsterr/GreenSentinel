-- Link explicitly admin-provisioned native Clerk org ids to provisioned tenants.
-- Unlinked native org_ ids keep failing closed in require_principal; the link
-- itself is data (per-environment admin action), never synthesized in code.
-- Idempotent: safe to re-run.

set search_path = app, extensions, public;

alter table app.organizations
    add column if not exists clerk_organization_id text;

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'uq_organizations_clerk_org'
    ) then
        alter table app.organizations
            add constraint uq_organizations_clerk_org unique (clerk_organization_id);
    end if;
end
$$;
