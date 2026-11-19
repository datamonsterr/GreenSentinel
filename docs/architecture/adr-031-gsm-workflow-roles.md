# ADR-031: GSM workflow roles and case stepper

Status: accepted · Scope: roles, case statuses, Overview stepper. Reference: GSM admin portal (ROLES / ST / STEPS).

## Role mapping

| Reference | Meaning | Our role | Clerk org role key | Badge |
|---|---|---|---|---|
| KSGL | Fraud analyst | `fraud_analyst` / `analyst` / `senior_analyst` | `org:fraud_analyst`, `org:member`, `org:analyst` | KSGL (#f0e6fb/#7b3ed6) |
| OPS | Operations | `manager` (DB only, no Clerk mapping; unchanged) | – | gap, not used by workflow |
| KSCL | Depot reviewer | **`reviewer`** (new) | `org:reviewer` | KSCL (#fbe9d6/#c8791e) |
| OPS_DIR | Ops director | **`ops_director`** (new) | `org:ops_director` | OPS_DIR (#e3ecfb/#3b6fd6) |
| MKP_DIR | Marketplace director | **`marketplace_director`** (new) | `org:marketplace_director` | MKP_DIR (#fde4e4/#e0484b) |
| TX | Driver | `driver` | `org:driver` | TX |
| System | automation | – (event `actor_role = 'System'` / `KSGL` actor recorded) | – | System |

`admin` may perform every workflow action. New roles route to `/workspace` (treated as non-driver staff).

## Status mapping (`app.fraud_cases.status`)

| Reference step | Our status |
|---|---|
| NEED_TO_EXPLAIN | `evidence_requested`, `driver_disputed` |
| UNDER_REVIEW | `ingested`, `processing`, `ready`, `in_review`, `escalated`, `pending_analyst_review` |
| REVIEWED | `resolved` (staged adjudication done) |
| REPORT_ISSUED | **`report_issued`** (new) |
| REPORT_CONFIRMED | **`report_confirmed`** (new; transient, recorded in history, case moves on immediately to ops approval) |
| NEED_OPS_DIR_APPROVED | **`need_ops_dir_approved`** (new) |
| NEED_MKP_DIR_APPROVED | **`need_mkp_dir_approved`** (new) |
| COMPLETED | **`completed`** (new) |
| CLOSED · no violation | `auto_dismissed` (stepper shows closed banner) |
| POST_CHECK | gap: not modelled |

## Transitions (`POST /api/v1/cases/{id}/workflow/{action}`)

`issue-report` resolved→report_issued (analyst/admin) · `confirm-report` report_issued→need_ops_dir_approved (reviewer/admin; records step REPORT_CONFIRMED) · `approve-ops` →need_mkp_dir_approved (ops_director/admin) · `approve-marketplace` →completed (marketplace_director/admin). Compare-and-set on status (409 otherwise), each written to append-only `app.case_workflow_events` (actor, role code, from/to, timestamp). `GET .../workflow` returns steps + next actor + caller's allowed actions. Existing adjudication / dispute flows untouched.

## Gaps

OPS role, POST_CHECK, fine-threshold routing (reference skips director steps for small cases), notifications to next actor, and UI for non-analyst roles beyond the Overview stepper.
