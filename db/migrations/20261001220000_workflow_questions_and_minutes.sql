-- Migration: 20261001220000_workflow_questions_and_minutes.sql
-- Issue #86 / #60: Durable workflow interactions and case minutes.
-- Adds four tables for interactive questions, human answers, case minutes,
-- and action-approval requests. All timestamps are UTC timestamptz.

set search_path = app, extensions, public;

-- ─── 1. Interactive workflow questions ────────────────────────────────────────
--
-- A question is persisted before the waiting-for-user result is emitted.
-- question_id_stable + revision form the idempotency key so duplicate
-- tool calls or replayed stream events reuse the same record.

create table if not exists app.workflow_questions (
    id                  uuid        primary key default gen_random_uuid(),
    -- stable identity assigned by the tool; revision increments on reissue
    question_id_stable  text        not null,
    revision            integer     not null default 1,
    case_id             uuid        not null references app.fraud_cases(id),
    organization_id     uuid        not null references app.organizations(id),
    -- who may answer: 'analyst' | 'driver' | 'both'
    actor_target        text        not null
                            check (actor_target in ('analyst', 'driver', 'both')),
    -- question_kind governs validation rules for answers
    question_kind       text        not null
                            check (question_kind in ('single_choice', 'multiple_choice', 'yes_no', 'text')),
    -- purpose distinguishes clarification from action-confirmation rendering
    purpose             text        not null default 'clarification'
                            check (purpose in ('clarification', 'action_confirmation')),
    -- full question payload: text, options[], max_selections, hint, etc.
    payload             jsonb       not null,
    status              text        not null default 'pending'
                            check (status in ('pending', 'answered', 'declined', 'cancelled', 'expired', 'superseded')),
    -- who created this question (tool context actor)
    created_by_actor_id uuid        references app.principals(id),
    created_at          timestamptz not null default now(),
    answered_at         timestamptz,
    expires_at          timestamptz,
    -- unique idempotency: same stable ID + revision → same record
    unique (case_id, question_id_stable, revision)
);

create index if not exists idx_wq_case_status
    on app.workflow_questions (case_id, status, created_at desc);

-- ─── 2. Human answers ────────────────────────────────────────────────────────
--
-- One answer per (question_id, respondent, idempotency_key).
-- idempotency_key is set by the client from its own submission token so
-- retried POSTs return the stored result without inserting a duplicate.

create table if not exists app.workflow_answers (
    id                      uuid        primary key default gen_random_uuid(),
    question_id             uuid        not null references app.workflow_questions(id),
    respondent_principal_id uuid        not null references app.principals(id),
    -- verbatim submitted value; array or scalar depending on kind
    submitted_value         jsonb       not null,
    -- optional free-text explanation preserved verbatim
    explanation             text,
    submitted_at            timestamptz not null default now(),
    -- client-supplied idempotency token; unique prevents double-write
    idempotency_key         text        not null unique,
    constraint fk_answer_question foreign key (question_id)
        references app.workflow_questions(id) on delete restrict
);

create index if not exists idx_wa_question
    on app.workflow_answers (question_id);

-- ─── 3. Case minutes ─────────────────────────────────────────────────────────
--
-- Final minutes are source-bound to a recorded adjudication and a frozen
-- evidence snapshot. Historical sent records are immutable; corrections
-- create a new revision linked to the same case.

create table if not exists app.workflow_minutes (
    id                  uuid        primary key default gen_random_uuid(),
    case_id             uuid        not null references app.fraud_cases(id),
    organization_id     uuid        not null references app.organizations(id),
    -- monotonic revision; corrections increment
    revision            integer     not null default 1,
    -- must reference an existing adjudication record
    decision_id         uuid        references app.adjudications(id),
    -- full Vietnamese minutes as structured JSON
    content             jsonb       not null,
    -- GIS map artifact reference (deterministic, not AI-generated)
    map_ref             text,
    -- frozen evidence snapshot this minutes is bound to
    evidence_snapshot_id uuid       references app.evidence_snapshots(id),
    status              text        not null default 'draft'
                            check (status in ('draft', 'preview', 'approved', 'sent')),
    -- principal who gave send approval
    approved_by         uuid        references app.principals(id),
    approved_at         timestamptz,
    -- the exact content/recipient hash that was approved
    approved_content_hash text,
    sent_at             timestamptz,
    delivery_state      text        check (delivery_state in ('stored', 'queued', 'sent', 'delivered', 'read', 'failed')),
    -- outbox event that triggered posting; nullable until send is attempted
    outbox_event_id     uuid        references app.outbox_events(id),
    -- who drafted this revision
    drafted_by          uuid        references app.principals(id),
    created_at          timestamptz not null default now(),
    unique (case_id, revision)
);

create index if not exists idx_wm_case_status
    on app.workflow_minutes (case_id, status, created_at desc);

-- ─── 4. Action-approval requests ─────────────────────────────────────────────
--
-- request_action_approval persists a pending card that the human case owner
-- must explicitly approve or deny via a signed endpoint. The model cannot
-- approve its own proposal.

create table if not exists app.workflow_action_requests (
    id              uuid        primary key default gen_random_uuid(),
    case_id         uuid        not null references app.fraud_cases(id),
    organization_id uuid        not null references app.organizations(id),
    -- canonical action kind from the catalog
    action_kind     text        not null,
    requested_by    uuid        not null references app.principals(id),
    -- full action payload including recipient, preview, consequence summary
    payload         jsonb       not null,
    -- content hash of the exact payload that must be approved
    payload_hash    text        not null,
    status          text        not null default 'pending'
                        check (status in ('pending', 'approved', 'denied', 'cancelled', 'expired')),
    approved_by     uuid        references app.principals(id),
    decided_at      timestamptz,
    denial_reason   text,
    created_at      timestamptz not null default now(),
    -- idempotency: same case + action + payload_hash → same request
    unique (case_id, action_kind, payload_hash)
);

create index if not exists idx_war_case_status
    on app.workflow_action_requests (case_id, status, created_at desc);

-- ─── 5. Status constraint extension for fraud_cases ──────────────────────────
--
-- Add 'pending_analyst_review' to support the #73 fix: corroborated claims
-- now await human confirmation instead of auto-dismissal.

do $$
begin
    alter table app.fraud_cases
        drop constraint if exists fraud_cases_status_check;
    alter table app.fraud_cases
        add constraint fraud_cases_status_check
        check (status in (
            'ingested', 'processing', 'ready', 'in_review',
            'evidence_requested', 'escalated', 'resolved',
            'processing_failed', 'auto_dismissed', 'driver_disputed',
            'pending_analyst_review'
        ));
exception when others then
    -- constraint may already include the new value from another migration
    null;
end $$;

do $$
begin
    alter table app.fraud_cases
        drop constraint if exists fraud_cases_dispute_status_check;
    alter table app.fraud_cases
        add constraint fraud_cases_dispute_status_check
        check (dispute_status in (
            'not_disputed', 'pending', 'in_dispute',
            'auto_dismissed', 'analyst_escalated', 'pending_review'
        ));
exception when others then
    null;
end $$;
