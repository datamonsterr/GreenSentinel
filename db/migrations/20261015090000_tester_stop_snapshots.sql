-- Preserve the user-selected initial, pickup and destination evidence.
set search_path = app, extensions, public;

alter table if exists test_definition_revisions
    add column if not exists stop_snapshots jsonb not null default '{}'::jsonb;
