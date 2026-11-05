-- Case-bound observations retain provider/fixture provenance; notes are not verdicts.
ALTER TABLE app.fraud_cases
    ADD COLUMN IF NOT EXISTS cockpit_evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS workflow_draft jsonb NOT NULL DEFAULT '{}'::jsonb;
COMMENT ON COLUMN app.fraud_cases.cockpit_evidence IS
    'Source-labelled cockpit observations. Synthetic demo evidence must declare is_simulated.';
COMMENT ON COLUMN app.fraud_cases.workflow_draft IS
    'Analyst notes with optimistic version, actor and timestamp; distinct from adjudication.';
-- Rollback (only after exporting any analyst notes):
-- ALTER TABLE app.fraud_cases DROP COLUMN workflow_draft, DROP COLUMN cockpit_evidence;
