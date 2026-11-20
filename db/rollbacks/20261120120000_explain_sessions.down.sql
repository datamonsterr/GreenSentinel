-- Rollback for 20261120120000_explain_sessions (PRD-A, ADR-034).
drop table if exists app.vh_feedback;
drop table if exists app.help_request;
drop table if exists app.explain_turn;
drop table if exists app.assessment_round;
drop trigger if exists statement_version_immutable_trg on app.statement_version;
drop table if exists app.statement_version;
drop function if exists app.statement_version_immutable();
drop table if exists app.explain_session;
