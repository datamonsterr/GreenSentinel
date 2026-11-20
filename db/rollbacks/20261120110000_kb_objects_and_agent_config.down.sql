-- Rollback for 20261120110000_kb_objects_and_agent_config (PRD-K, ADR-032).
drop table if exists app.kb_proposal;
drop table if exists app.kb_policy_document;
drop table if exists app.agent_config_history;
drop table if exists app.agent_config;
drop table if exists app.kb_object;
