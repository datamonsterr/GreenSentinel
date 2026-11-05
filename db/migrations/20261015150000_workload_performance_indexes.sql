-- Migration: 20261015150000_workload_performance_indexes.sql
-- Description: Add justified, workload-measured indexes for trip assignment lookups and organization case queues.
-- Target: GreenSentinel Database Performance Optimization (Parent #394, Child #399)

-- 1. Trip assignments lookup by trip_id
-- Existing index (uq_trip_one_active_assignment) only covered active states (accepted, arrived, started).
-- Historical, completed, or general trip queries filtering by trip_id were forced into sequential scans.
CREATE INDEX IF NOT EXISTS idx_trip_assignments_trip_id
    ON app.trip_assignments (trip_id);

