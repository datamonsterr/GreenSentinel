-- Safe Rollback Guidance for 20261016000000_test_store_schema_parity.sql
-- Bounded ownership: test-store tables under issue #394 / child task #423.
--
-- IMPORTANT SAFETY POLICY:
-- Destructive 'DROP TABLE' or 'DROP COLUMN' operations MUST NOT be executed here.
-- Rationale:
-- 1. The 8 organization_id columns on child tables (test_controls, test_definition_revisions,
--    test_events, test_idempotency_keys, test_notifications, test_outbox, test_runs, test_samples)
--    pre-existed on Railway dev and staging environments before this migration.
-- 2. Any newly authored simulation runs, test plans, or test cases created after this migration
--    would suffer silent data loss if tables or columns were dropped.
-- 3. The schema changes in 20261016000000_test_store_schema_parity.sql are strictly additive:
--    all new columns are nullable or have safe defaults ('[]'::jsonb), and existing application
--    services (e.g. TestSimulationRepository) tolerate both pre- and post-migration states.
--
-- RECOMMENDED ROLLBACK STRATEGY:
-- - In-place: Keep additive columns and tables intact. Remove the migration record from the ledger
--   if necessary for runner re-execution:
--     DELETE FROM public.schema_migrations WHERE version = '20261016000000_test_store_schema_parity.sql';
--
-- - Full Environment Restore:
--   If a complete return to the exact pre-migration byte snapshot is required, perform a clean restore
--   from the restore-tested full backups verified in /tmp/p063-restore-verification.json:
--     - Dev: ca1b85fbf900de8c5187e68dfac251ea5cd7ef04fc1096b35b7d85401d34b166 (dev.dump)
--     - Staging: 71133c4f5020bcbd2066708a4dd4d761607a54ce9311c4d280cc9410670b82f2 (staging.dump)
--     - Production: f72331f9085c5f87ce0d91ebeb018228dfcc84f4205833ca02690fc62a8cc321 (production.dump)
--   Command:
--     pg_restore -U postgres -d <target_db> --clean --if-exists <backup_path>

DO $$
BEGIN
    RAISE NOTICE '20261016000000_test_store_schema_parity is strictly additive and non-destructive. No tables or columns were dropped to preserve pre-existing dev/staging schemas and runtime data.';
END $$;
