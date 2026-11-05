-- Migration: 20261019000000_driver_confirmations_drafts.sql
-- Purpose: Confirmation tokens and statement drafts for driver accept/reject flow (Issue #483).

CREATE SCHEMA IF NOT EXISTS app;
SET search_path = app, extensions, public;

CREATE TABLE IF NOT EXISTS app.driver_confirmation_tokens (
    token_hash TEXT PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES app.fraud_cases(id) ON DELETE CASCADE,
    driver_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('acknowledge', 'submit_statement')),
    draft_hash TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.driver_statement_drafts (
    case_id UUID NOT NULL,
    driver_id TEXT NOT NULL,
    draft JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (case_id, driver_id)
);
