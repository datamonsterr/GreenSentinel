-- Migration: 20261017100000_driver_trips_ratings.sql
-- Purpose: Schema for driver app trips history and trip ratings seeded from HF 40k corpus (Issue #478).
-- Rollback: db/rollbacks/20261017100000_driver_trips_ratings.down.sql

CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.driver_trips (
    trip_id UUID PRIMARY KEY,
    driver_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    pickup_label TEXT NOT NULL,
    pickup_lat DOUBLE PRECISION,
    pickup_lng DOUBLE PRECISION,
    dropoff_label TEXT NOT NULL,
    dropoff_lat DOUBLE PRECISION,
    dropoff_lng DOUBLE PRECISION,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    distance_km NUMERIC(10, 2) NOT NULL DEFAULT 0.0,
    duration_min NUMERIC(10, 2) NOT NULL DEFAULT 0.0,
    fare_vnd BIGINT NOT NULL DEFAULT 0,
    -- payment_method is synthesized (not present in raw benchmark trips corpus)
    payment_method TEXT NOT NULL DEFAULT 'wallet',
    payment_method_synthetic BOOLEAN NOT NULL DEFAULT true,
    status TEXT NOT NULL DEFAULT 'completed',
    fraud_label TEXT,
    case_id UUID
);

CREATE TABLE IF NOT EXISTS app.trip_ratings (
    trip_id UUID PRIMARY KEY REFERENCES app.driver_trips(trip_id) ON DELETE CASCADE,
    stars SMALLINT CHECK (stars BETWEEN 1 AND 5),
    comment TEXT,
    locale TEXT,
    source TEXT NOT NULL DEFAULT 'seed',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS idx_driver_trips_driver_started
    ON app.driver_trips (driver_id, started_at DESC);

-- Used by Driver App History flagged-trip link to quickly look up trips by case_id
CREATE INDEX IF NOT EXISTS idx_driver_trips_case_id
    ON app.driver_trips (case_id)
    WHERE case_id IS NOT NULL;

