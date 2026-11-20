# ADR-033: Structured, versioned motivation assessment

Status: accepted · Scope: slice S-M of `docs/plans/2026-11-20-prd-features.md` (Decision 10). Migration `20261120100000_case_motivation_assessments.sql`.

## Context

Motivation existed only as an in-memory `forensic_brief.motivation_assessment` (`intent_profile`, reward, narrative). It was not persisted, had no motive catalogue and could not be edited or confirmed. The Overview "Motivation" card read `cockpit_evidence` (only populated for demo data), so it always showed "Not assessed" on real cases.

## Decision

- **Table** `app.case_motivation_assessments` (append-only versions per case, latest wins; `unique(case_id, version)`). Columns: `motive_category` (`reward_threshold|subsidy_surge|fare_inflation|platform_fault|unclear`), `signals jsonb`, `amount_at_stake_vnd`, `confidence` (0-1), `rationale`, `source` (`ai|rule|analyst`), `status` (`draft|confirmed`), `confirmed_by/at`. Only confirm updates a row in place (draft -> confirmed); edits and regenerations insert a new draft version.
- **Service** `src/services/case_motivation_service.py`. Category, signals, amount and confidence are computed in code from case evidence (`motivation_assessment_service._facts`). The rationale is rule text; when `generate_motivation_assessment` returns a validated LLM narrative that differs from the deterministic fallback, it replaces the rationale and `source` becomes `ai`. Timeouts/invalid output fall back to the rule text. Analyst edits cannot change the amount (system computed).
- **API** (prefix `/api/v1`): `GET /cases/{id}/motivation` (latest persisted, else an unsaved rule draft with `version: 0`, `persisted: false`), `POST .../motivation/generate`, `PUT .../motivation` (edit -> new version, optional `expected_version` -> 409), `POST .../motivation/confirm` (draft only, optional `expected_version`). Read: `CASE_READ_ROLES`. Write: `analyst`, `senior_analyst`, `admin` (reviewer/ops_director/marketplace_director read-only). Each write appends an `audit_events` row (`motivation_generated|edited|confirmed`) in the same transaction.
- **UI** `components/adjudication/motivation-card.tsx` renders inside the Overview Motivation section: category chip, status chip, signals, amount, confidence bar, rationale; Generate/Regenerate, Edit, Confirm for analyst-family roles. It fetches from the API, so the `cockpit_evidence` wiring bug no longer matters for this card.
- **Catalogue seam**: `MOTIVE_CATALOGUE` is a constant. When S-K publishes `kb_object(type='motive')`, `build_structured_assessment` should resolve categories and formulas from published objects and keep this catalogue as the fallback.

## Consequences

- Additive migration, no change to existing tables. Rollback drops the new table.
- The legacy `forensic_brief.motivation_assessment` (and the Finalization tab, which reveals it after a preliminary judgment) is unchanged.
- The structured card is visible on Overview before the preliminary judgment; the earlier anti-anchoring boundary applied only to the legacy narrative (open question for product).
