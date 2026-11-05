-- Rollback for 20261003090000_durable_solved_case_precedents.sql.
-- Export both history tables before rollback if they contain accepted records.

set search_path = app, extensions, public;

drop trigger if exists precedent_workflows_append_only on app.precedent_workflows;
drop trigger if exists precedent_reuse_history_append_only on app.precedent_reuse_history;
drop trigger if exists precedent_reuse_history_validate on app.precedent_reuse_history;
drop trigger if exists solved_case_contexts_append_only on app.solved_case_contexts;
drop trigger if exists solved_case_contexts_validate on app.solved_case_contexts;
drop table if exists app.precedent_reuse_history;
drop table if exists app.solved_case_contexts;
drop function if exists app.validate_precedent_reuse_history();
drop function if exists app.validate_solved_case_context();
