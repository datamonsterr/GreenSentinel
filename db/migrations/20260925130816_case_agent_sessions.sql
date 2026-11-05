-- One durable conversation per case. Messages are append-only and contain only
-- user input and the assistant's final, user-visible reply (never model CoT).
create table app.case_agent_sessions (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null references app.organizations(id),
    case_id uuid not null unique references app.fraud_cases(id),
    created_by uuid references app.principals(id),
    created_at timestamptz not null default now()
);

create table app.case_agent_messages (
    id uuid primary key default gen_random_uuid(),
    session_id uuid not null references app.case_agent_sessions(id),
    turn_id uuid not null,
    sequence bigint generated always as identity,
    role text not null check (role in ('user', 'assistant')),
    content text not null check (length(btrim(content)) > 0),
    created_at timestamptz not null default now(),
    unique (session_id, turn_id, role)
);

create index case_agent_messages_session_sequence_idx
    on app.case_agent_messages (session_id, sequence);

create trigger case_agent_messages_append_only
before update or delete on app.case_agent_messages
for each row execute function app.reject_mutation();

revoke all on app.case_agent_sessions, app.case_agent_messages from public;

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'anon') then
        execute 'revoke all on app.case_agent_sessions, app.case_agent_messages from anon';
    end if;
    if exists (select 1 from pg_roles where rolname = 'authenticated') then
        execute 'revoke all on app.case_agent_sessions, app.case_agent_messages from authenticated';
    end if;
    if exists (select 1 from pg_roles where rolname = 'service_role') then
        execute 'grant select, insert on app.case_agent_sessions to service_role';
        execute 'grant select, insert on app.case_agent_messages to service_role';
        execute 'grant usage, select on sequence app.case_agent_messages_sequence_seq to service_role';
    end if;
end;
$$;
