set search_path = app, extensions, public;

alter table if exists fraud_cases
    drop column if exists workflow_draft,
    drop column if exists cockpit_evidence;
