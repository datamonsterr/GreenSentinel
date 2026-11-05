-- Rollback: 20261017100000_driver_trips_ratings.down.sql
-- Purpose: Cleanly drop trip_ratings and driver_trips tables (Issue #478).

DROP TABLE IF EXISTS app.trip_ratings CASCADE;
DROP TABLE IF EXISTS app.driver_trips CASCADE;
