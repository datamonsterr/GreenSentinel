-- Rollback for 20261014090000_staged_adjudication.sql.
set search_path = app, extensions, public;

drop trigger if exists preliminary_judgments_append_only on app.preliminary_judgments;
drop table if exists app.preliminary_judgments;
alter table app.adjudications drop column if exists staged_context;

