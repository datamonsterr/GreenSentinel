-- Durable assistant turns are actor-scoped; no model may adjudicate a case.
create table if not exists app.agent_runtime_turns (
  run_id uuid primary key,
  case_id uuid not null references app.fraud_cases(id),
  actor_id uuid not null references app.principals(id),
  organization_id uuid not null references app.organizations(id),
  session_id uuid not null,
  turn_id text not null,
  request_hash text not null,
  query text not null,
  answer text,
  events jsonb not null default '[]'::jsonb,
  status text not null check (status in ('running','completed','waiting_for_user','failed','interrupted')),
  created_at timestamptz not null default now(),
  finished_at timestamptz,
  unique (case_id, actor_id, turn_id)
);
create index if not exists agent_runtime_turns_session_idx
  on app.agent_runtime_turns (session_id, created_at);
alter table app.agent_runtime_turns enable row level security;
revoke all on app.agent_runtime_turns from public;
