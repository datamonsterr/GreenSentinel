-- Migration: 20261016000000_test_store_schema_parity.sql
-- Purpose: Structural parity and unambiguous organization ownership propagation across dev, staging, and production.
-- Bounded ownership: test-store tables and ownership columns under issue #394 / child task #423.
-- Preserves all existing data; strictly additive; fail-closed on incompatible schema.

-- 1. Incompatible schema fail-closed validations
DO $$
DECLARE
    v_type text;
BEGIN
    -- Verify app.test_plans.created_by compatibility
    SELECT udt_name INTO v_type
    FROM information_schema.columns
    WHERE table_schema = 'app'
      AND table_name = 'test_plans'
      AND column_name = 'created_by';

    IF v_type IS NOT NULL AND v_type NOT IN ('text', 'uuid', 'varchar', 'bpchar') THEN
        RAISE EXCEPTION 'Incompatible type % on app.test_plans.created_by; expected uuid or text', v_type;
    END IF;

    -- Verify app.test_run_requests compatibility if pre-existing
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'app' AND table_name = 'test_run_requests') THEN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'app' AND table_name = 'test_run_requests' AND column_name = 'run_id' AND udt_name = 'uuid'
        ) THEN
            RAISE EXCEPTION 'Pre-existing app.test_run_requests differs incompatibly from contract (missing uuid run_id)';
        END IF;
    END IF;

    -- Verify app.test_cases compatibility if pre-existing
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'app' AND table_name = 'test_cases') THEN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'app' AND table_name = 'test_cases' AND column_name = 'run_id' AND udt_name = 'uuid'
        ) THEN
            RAISE EXCEPTION 'Pre-existing app.test_cases differs incompatibly from contract (missing uuid run_id)';
        END IF;
    END IF;
END $$;

-- 2. Additive nullable organization_id columns on test-store tables
ALTER TABLE app.test_plans ADD COLUMN IF NOT EXISTS organization_id uuid;
ALTER TABLE app.test_controls ADD COLUMN IF NOT EXISTS organization_id uuid;
ALTER TABLE app.test_definition_revisions ADD COLUMN IF NOT EXISTS organization_id uuid;
ALTER TABLE app.test_events ADD COLUMN IF NOT EXISTS organization_id uuid;
ALTER TABLE app.test_idempotency_keys ADD COLUMN IF NOT EXISTS organization_id uuid;
ALTER TABLE app.test_notifications ADD COLUMN IF NOT EXISTS organization_id uuid;
ALTER TABLE app.test_outbox ADD COLUMN IF NOT EXISTS organization_id uuid;
ALTER TABLE app.test_runs ADD COLUMN IF NOT EXISTS organization_id uuid;
ALTER TABLE app.test_samples ADD COLUMN IF NOT EXISTS organization_id uuid;

-- 3. Additive messages column on test_definition_revisions
ALTER TABLE app.test_definition_revisions ADD COLUMN IF NOT EXISTS messages jsonb NOT NULL DEFAULT '[]'::jsonb;

-- 4. Safe type conversion of app.test_plans.created_by from UUID to TEXT
ALTER TABLE app.test_plans ADD COLUMN IF NOT EXISTS created_by text;
DO $$
DECLARE
    v_type text;
BEGIN
    SELECT udt_name INTO v_type
    FROM information_schema.columns
    WHERE table_schema = 'app'
      AND table_name = 'test_plans'
      AND column_name = 'created_by';

    IF v_type IS NOT NULL AND v_type <> 'text' THEN
        ALTER TABLE app.test_plans ALTER COLUMN created_by TYPE text USING created_by::text;
    END IF;
END $$;

-- 5. Additive test-store contract tables
CREATE TABLE IF NOT EXISTS app.test_run_requests (
    organization_id uuid NOT NULL,
    key varchar(255) NOT NULL,
    run_id uuid NOT NULL REFERENCES app.test_runs(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, key)
);

CREATE TABLE IF NOT EXISTS app.test_cases (
    id text PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES app.test_runs(id) ON DELETE CASCADE,
    payload jsonb NOT NULL
);

-- 6. Workload-appropriate and foreign-key indexes
CREATE INDEX IF NOT EXISTS idx_test_plans_org_created ON app.test_plans(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_test_runs_definition ON app.test_runs(definition_revision_id);
CREATE INDEX IF NOT EXISTS idx_test_cases_run ON app.test_cases(run_id);
CREATE INDEX IF NOT EXISTS idx_test_run_requests_run ON app.test_run_requests(run_id);
CREATE INDEX IF NOT EXISTS idx_test_revisions_org ON app.test_definition_revisions(organization_id, plan_id);
CREATE INDEX IF NOT EXISTS idx_test_runs_org ON app.test_runs(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_test_controls_org_run ON app.test_controls(organization_id, run_id);
CREATE INDEX IF NOT EXISTS idx_test_samples_org_run ON app.test_samples(organization_id, run_id, step_index);
CREATE INDEX IF NOT EXISTS idx_test_events_org_run ON app.test_events(organization_id, run_id);
CREATE INDEX IF NOT EXISTS idx_test_notifications_org_run ON app.test_notifications(organization_id, run_id);

-- 7. Quarantine infrastructure
CREATE TABLE IF NOT EXISTS app.org_quarantine (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    table_name text NOT NULL,
    row_id uuid NOT NULL,
    reason text NOT NULL,
    detail jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (table_name, row_id)
);

-- 8. Safe organization ownership propagation
-- Rule: Backfill ONLY if unambiguous from validated parent in app.organizations;
--       Preserve existing child org; conflicting orgs quarantined, never overwritten;
--       Unowned legacy rows quarantined with NULL preserved.

-- 8.1 test_plans: quarantine invalid org reference or unowned
INSERT INTO app.org_quarantine (table_name, row_id, reason, detail)
SELECT 'test_plans', p.id, 'invalid_org_reference', jsonb_build_object('organization_id', p.organization_id)
FROM app.test_plans p
WHERE p.organization_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM app.organizations o WHERE o.id = p.organization_id)
ON CONFLICT (table_name, row_id) DO NOTHING;

INSERT INTO app.org_quarantine (table_name, row_id, reason, detail)
SELECT 'test_plans', p.id, 'unowned_plan', jsonb_build_object('plan_id', p.id)
FROM app.test_plans p
WHERE p.organization_id IS NULL
ON CONFLICT (table_name, row_id) DO NOTHING;

-- 8.2 test_definition_revisions: quarantine conflicts & unowned, backfill unambiguous
INSERT INTO app.org_quarantine (table_name, row_id, reason, detail)
SELECT 'test_definition_revisions', r.id, 'parent_child_org_conflict',
       jsonb_build_object('child_org', r.organization_id, 'parent_org', p.organization_id, 'plan_id', p.id)
FROM app.test_definition_revisions r
JOIN app.test_plans p ON p.id = r.plan_id
WHERE r.organization_id IS NOT NULL
  AND p.organization_id IS NOT NULL
  AND r.organization_id IS DISTINCT FROM p.organization_id
ON CONFLICT (table_name, row_id) DO NOTHING;

INSERT INTO app.org_quarantine (table_name, row_id, reason, detail)
SELECT 'test_definition_revisions', r.id, 'invalid_org_reference',
       jsonb_build_object('organization_id', r.organization_id)
FROM app.test_definition_revisions r
WHERE r.organization_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM app.organizations o WHERE o.id = r.organization_id)
ON CONFLICT (table_name, row_id) DO NOTHING;

UPDATE app.test_definition_revisions r
SET organization_id = p.organization_id
FROM app.test_plans p
WHERE r.plan_id = p.id
  AND r.organization_id IS NULL
  AND p.organization_id IS NOT NULL
  AND EXISTS (SELECT 1 FROM app.organizations o WHERE o.id = p.organization_id);

INSERT INTO app.org_quarantine (table_name, row_id, reason, detail)
SELECT 'test_definition_revisions', r.id, 'unowned_revision',
       jsonb_build_object('revision_id', r.id, 'plan_id', r.plan_id)
FROM app.test_definition_revisions r
WHERE r.organization_id IS NULL
ON CONFLICT (table_name, row_id) DO NOTHING;

-- 8.3 test_runs: quarantine conflicts & unowned, backfill unambiguous
INSERT INTO app.org_quarantine (table_name, row_id, reason, detail)
SELECT 'test_runs', run.id, 'parent_child_org_conflict',
       jsonb_build_object('child_org', run.organization_id, 'parent_revision_org', r.organization_id, 'revision_id', r.id)
FROM app.test_runs run
JOIN app.test_definition_revisions r ON r.id = run.definition_revision_id
WHERE run.organization_id IS NOT NULL
  AND r.organization_id IS NOT NULL
  AND run.organization_id IS DISTINCT FROM r.organization_id
ON CONFLICT (table_name, row_id) DO NOTHING;

INSERT INTO app.org_quarantine (table_name, row_id, reason, detail)
SELECT 'test_runs', run.id, 'invalid_org_reference',
       jsonb_build_object('organization_id', run.organization_id)
FROM app.test_runs run
WHERE run.organization_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM app.organizations o WHERE o.id = run.organization_id)
ON CONFLICT (table_name, row_id) DO NOTHING;

UPDATE app.test_runs run
SET organization_id = r.organization_id
FROM app.test_definition_revisions r
WHERE run.definition_revision_id = r.id
  AND run.organization_id IS NULL
  AND r.organization_id IS NOT NULL
  AND EXISTS (SELECT 1 FROM app.organizations o WHERE o.id = r.organization_id);

INSERT INTO app.org_quarantine (table_name, row_id, reason, detail)
SELECT 'test_runs', run.id, 'unowned_run',
       jsonb_build_object('run_id', run.id, 'definition_revision_id', run.definition_revision_id)
FROM app.test_runs run
WHERE run.organization_id IS NULL
ON CONFLICT (table_name, row_id) DO NOTHING;

-- 8.4 test_controls: quarantine conflicts & unowned, backfill unambiguous
INSERT INTO app.org_quarantine (table_name, row_id, reason, detail)
SELECT 'test_controls', c.id, 'parent_child_org_conflict',
       jsonb_build_object('child_org', c.organization_id, 'run_org', r.organization_id, 'run_id', r.id)
FROM app.test_controls c
JOIN app.test_runs r ON r.id = c.run_id
WHERE c.organization_id IS NOT NULL
  AND r.organization_id IS NOT NULL
  AND c.organization_id IS DISTINCT FROM r.organization_id
ON CONFLICT (table_name, row_id) DO NOTHING;

UPDATE app.test_controls c
SET organization_id = r.organization_id
FROM app.test_runs r
WHERE c.run_id = r.id
  AND c.organization_id IS NULL
  AND r.organization_id IS NOT NULL
  AND EXISTS (SELECT 1 FROM app.organizations o WHERE o.id = r.organization_id);

INSERT INTO app.org_quarantine (table_name, row_id, reason, detail)
SELECT 'test_controls', c.id, 'unowned_control',
       jsonb_build_object('control_id', c.id, 'run_id', c.run_id)
FROM app.test_controls c
WHERE c.organization_id IS NULL
ON CONFLICT (table_name, row_id) DO NOTHING;

-- 8.5 test_samples: quarantine conflicts & unowned, backfill unambiguous
INSERT INTO app.org_quarantine (table_name, row_id, reason, detail)
SELECT 'test_samples', s.id, 'parent_child_org_conflict',
       jsonb_build_object('child_org', s.organization_id, 'run_org', r.organization_id, 'run_id', r.id)
FROM app.test_samples s
JOIN app.test_runs r ON r.id = s.run_id
WHERE s.organization_id IS NOT NULL
  AND r.organization_id IS NOT NULL
  AND s.organization_id IS DISTINCT FROM r.organization_id
ON CONFLICT (table_name, row_id) DO NOTHING;

UPDATE app.test_samples s
SET organization_id = r.organization_id
FROM app.test_runs r
WHERE s.run_id = r.id
  AND s.organization_id IS NULL
  AND r.organization_id IS NOT NULL
  AND EXISTS (SELECT 1 FROM app.organizations o WHERE o.id = r.organization_id);

INSERT INTO app.org_quarantine (table_name, row_id, reason, detail)
SELECT 'test_samples', s.id, 'unowned_sample',
       jsonb_build_object('sample_id', s.id, 'run_id', s.run_id)
FROM app.test_samples s
WHERE s.organization_id IS NULL
ON CONFLICT (table_name, row_id) DO NOTHING;

-- 8.6 test_events: quarantine conflicts & unowned, backfill unambiguous
INSERT INTO app.org_quarantine (table_name, row_id, reason, detail)
SELECT 'test_events', e.id, 'parent_child_org_conflict',
       jsonb_build_object('child_org', e.organization_id, 'run_org', r.organization_id, 'run_id', r.id)
FROM app.test_events e
JOIN app.test_runs r ON r.id = e.run_id
WHERE e.organization_id IS NOT NULL
  AND r.organization_id IS NOT NULL
  AND e.organization_id IS DISTINCT FROM r.organization_id
ON CONFLICT (table_name, row_id) DO NOTHING;

UPDATE app.test_events e
SET organization_id = r.organization_id
FROM app.test_runs r
WHERE e.run_id = r.id
  AND e.organization_id IS NULL
  AND r.organization_id IS NOT NULL
  AND EXISTS (SELECT 1 FROM app.organizations o WHERE o.id = r.organization_id);

INSERT INTO app.org_quarantine (table_name, row_id, reason, detail)
SELECT 'test_events', e.id, 'unowned_event',
       jsonb_build_object('event_id', e.id, 'run_id', e.run_id)
FROM app.test_events e
WHERE e.organization_id IS NULL
ON CONFLICT (table_name, row_id) DO NOTHING;

-- 8.7 test_notifications: quarantine conflicts & unowned, backfill unambiguous
INSERT INTO app.org_quarantine (table_name, row_id, reason, detail)
SELECT 'test_notifications', n.id, 'parent_child_org_conflict',
       jsonb_build_object('child_org', n.organization_id, 'run_org', r.organization_id, 'run_id', r.id)
FROM app.test_notifications n
JOIN app.test_runs r ON r.id = n.run_id
WHERE n.organization_id IS NOT NULL
  AND r.organization_id IS NOT NULL
  AND n.organization_id IS DISTINCT FROM r.organization_id
ON CONFLICT (table_name, row_id) DO NOTHING;

UPDATE app.test_notifications n
SET organization_id = r.organization_id
FROM app.test_runs r
WHERE n.run_id = r.id
  AND n.organization_id IS NULL
  AND r.organization_id IS NOT NULL
  AND EXISTS (SELECT 1 FROM app.organizations o WHERE o.id = r.organization_id);

INSERT INTO app.org_quarantine (table_name, row_id, reason, detail)
SELECT 'test_notifications', n.id, 'unowned_notification',
       jsonb_build_object('notification_id', n.id, 'run_id', n.run_id)
FROM app.test_notifications n
WHERE n.organization_id IS NULL
ON CONFLICT (table_name, row_id) DO NOTHING;

-- 8.8 test_idempotency_keys: quarantine conflicts & unowned, backfill unambiguous
INSERT INTO app.org_quarantine (table_name, row_id, reason, detail)
SELECT 'test_idempotency_keys', r.id, 'parent_child_org_conflict',
       jsonb_build_object('key', k.key, 'child_org', k.organization_id, 'run_org', r.organization_id, 'run_id', r.id)
FROM app.test_idempotency_keys k
JOIN app.test_runs r ON r.id = k.run_id
WHERE k.organization_id IS NOT NULL
  AND r.organization_id IS NOT NULL
  AND k.organization_id IS DISTINCT FROM r.organization_id
ON CONFLICT (table_name, row_id) DO NOTHING;

UPDATE app.test_idempotency_keys k
SET organization_id = r.organization_id
FROM app.test_runs r
WHERE k.run_id = r.id
  AND k.organization_id IS NULL
  AND r.organization_id IS NOT NULL
  AND EXISTS (SELECT 1 FROM app.organizations o WHERE o.id = r.organization_id);

INSERT INTO app.org_quarantine (table_name, row_id, reason, detail)
SELECT 'test_idempotency_keys', k.run_id, 'unowned_idempotency_key',
       jsonb_build_object('key', k.key, 'run_id', k.run_id)
FROM app.test_idempotency_keys k
WHERE k.organization_id IS NULL
  AND k.run_id IS NOT NULL
ON CONFLICT (table_name, row_id) DO NOTHING;

-- 8.9 test_outbox: quarantine conflicts & unowned, backfill unambiguous
INSERT INTO app.org_quarantine (table_name, row_id, reason, detail)
SELECT 'test_outbox', o.id, 'parent_child_org_conflict',
       jsonb_build_object('child_org', o.organization_id, 'run_org', r.organization_id, 'run_id', r.id)
FROM app.test_outbox o
JOIN app.test_runs r ON r.id::text = o.aggregate_id
WHERE o.aggregate_type = 'test_run'
  AND o.organization_id IS NOT NULL
  AND r.organization_id IS NOT NULL
  AND o.organization_id IS DISTINCT FROM r.organization_id
ON CONFLICT (table_name, row_id) DO NOTHING;

UPDATE app.test_outbox o
SET organization_id = r.organization_id
FROM app.test_runs r
WHERE o.aggregate_type = 'test_run'
  AND o.aggregate_id = r.id::text
  AND o.organization_id IS NULL
  AND r.organization_id IS NOT NULL
  AND EXISTS (SELECT 1 FROM app.organizations org WHERE org.id = r.organization_id);

INSERT INTO app.org_quarantine (table_name, row_id, reason, detail)
SELECT 'test_outbox', o.id, 'unowned_outbox',
       jsonb_build_object('outbox_id', o.id, 'aggregate_type', o.aggregate_type, 'aggregate_id', o.aggregate_id)
FROM app.test_outbox o
WHERE o.organization_id IS NULL
ON CONFLICT (table_name, row_id) DO NOTHING;
