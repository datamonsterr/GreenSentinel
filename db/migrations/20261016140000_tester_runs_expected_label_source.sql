-- Migration: 20261016140000_tester_runs_expected_label_source.sql
-- Purpose: Add expected_label and source columns to app.test_runs for issue #457.
set search_path = app, extensions, public;

alter table test_runs add column if not exists expected_label text;
alter table test_runs add column if not exists source text;
