-- Migration: 20261016160000_agent_context_clear_trigger.sql
-- Replace case_agent_messages append-only trigger with app.reject_agent_message_mutation()
-- Allows DELETE only when current_setting('app.agent_context_clear', true) = 'on'
-- Always rejects UPDATE.

create or replace function app.reject_agent_message_mutation()
returns trigger
language plpgsql
security definer
set search_path = app, extensions, pg_catalog
as $$
begin
    if tg_op = 'UPDATE' then
        raise exception '% is append-only', tg_table_name using errcode = '55000';
    elsif tg_op = 'DELETE' then
        if current_setting('app.agent_context_clear', true) is distinct from 'on' then
            raise exception '% is append-only', tg_table_name using errcode = '55000';
        end if;
        return old;
    end if;
    return new;
end;
$$;

drop trigger if exists case_agent_messages_append_only on app.case_agent_messages;

create trigger case_agent_messages_append_only
before update or delete on app.case_agent_messages
for each row execute function app.reject_agent_message_mutation();

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'service_role') then
        execute 'grant delete on app.case_agent_messages to service_role';
    end if;
end;
$$;
