-- PRD-K policy analysis agent (ADR-033): analysis run status/counts on policy documents.
-- Additive + idempotent.
alter table app.kb_policy_document add column if not exists analysis_status text not null default 'pending';
alter table app.kb_policy_document add column if not exists analysis_error text;
alter table app.kb_policy_document add column if not exists analysis_counts jsonb not null default '{}'::jsonb;
alter table app.kb_policy_document add column if not exists analyzed_at timestamptz;
alter table app.kb_policy_document add column if not exists analyzed_by uuid references app.principals(id);
do $$
begin
    if not exists (select 1 from pg_constraint where conname = 'kb_policy_document_analysis_status_chk') then
        alter table app.kb_policy_document add constraint kb_policy_document_analysis_status_chk
            check (analysis_status in ('pending', 'running', 'done', 'failed'));
    end if;
end $$;
