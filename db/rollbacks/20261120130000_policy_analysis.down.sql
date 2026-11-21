-- Rollback for 20261120130000_policy_analysis (ADR-033).
alter table app.kb_policy_document drop constraint if exists kb_policy_document_analysis_status_chk;
alter table app.kb_policy_document drop column if exists analyzed_by;
alter table app.kb_policy_document drop column if exists analyzed_at;
alter table app.kb_policy_document drop column if exists analysis_counts;
alter table app.kb_policy_document drop column if exists analysis_error;
alter table app.kb_policy_document drop column if exists analysis_status;
