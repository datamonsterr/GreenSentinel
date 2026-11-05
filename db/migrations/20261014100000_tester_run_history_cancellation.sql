-- Console History and participant-initiated cancellation for tester simulation runs.
-- The run keeps its tenant anchor through test_plans; these columns record the
-- operator-visible title and the canonical cancellation evidence. A run without
-- recorded cancellation stays NULL and is never reported as cancelled by default.
set search_path = app, extensions, public;

alter table test_runs add column if not exists title text;
alter table test_runs add column if not exists trip_id uuid;
alter table test_runs add column if not exists cancelled_at timestamptz;
alter table test_runs add column if not exists cancellation_actor text;
alter table test_runs add column if not exists cancellation_reason text;

create index if not exists idx_test_runs_created on test_runs(created_at desc);
