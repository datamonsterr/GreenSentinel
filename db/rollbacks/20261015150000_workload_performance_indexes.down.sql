-- Rollback: 20261015150000_workload_performance_indexes.down.sql
-- Description: Rollback additive workload-supported indexes cleanly and idempotently.
-- Target: P-063 Database Performance Optimization (Parent #394, Child #399)

DROP INDEX IF EXISTS app.idx_trip_assignments_trip_id;
DROP INDEX IF EXISTS app.idx_fraud_cases_org_lower_status_queue;

-- Clean up any prior speculative test indexes for complete idempotence
DROP INDEX IF EXISTS app.idx_fraud_cases_org_queue;
DROP INDEX IF EXISTS app.idx_trip_assignments_vehicle_id;
DROP INDEX IF EXISTS app.idx_case_assignment_history_case_id;
DROP INDEX IF EXISTS app.idx_evidence_snapshots_case_version;
DROP INDEX IF EXISTS app.idx_passenger_feedback_assignment_id;
DROP INDEX IF EXISTS app.idx_platform_incidents_assignment_id;
DROP INDEX IF EXISTS app.idx_solved_case_contexts_assignment_id;
