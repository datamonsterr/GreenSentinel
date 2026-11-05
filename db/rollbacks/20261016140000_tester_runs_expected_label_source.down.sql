-- Rollback: 20261016140000_tester_runs_expected_label_source.down.sql
set search_path = app, extensions, public;

alter table test_runs drop column if exists expected_label;
alter table test_runs drop column if exists source;
