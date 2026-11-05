-- Rollback SPEC-0130 tester simulation schema

drop view if exists app.assignments;
drop view if exists app.cases;

drop table if exists test_idempotency_keys cascade;
drop table if exists test_outbox cascade;
drop table if exists test_notifications cascade;
drop table if exists test_messages cascade;
drop table if exists test_events cascade;
drop table if exists test_samples cascade;
drop table if exists test_controls cascade;
drop table if exists test_runs cascade;
drop table if exists test_definition_revisions cascade;
drop table if exists test_plans cascade;
