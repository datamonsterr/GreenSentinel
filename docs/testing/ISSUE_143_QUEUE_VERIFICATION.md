# Issue 143 queue verification

## Scope and environment

Issue: [#143](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/143). Branch: `fix/143-active-triage-terminal`. Verification date: 2026-10-05. The local PostgreSQL container `p063-issue143-postgres` holds the exclusively owned, migrated `issue143_queue` database. Hosted reproduction and authenticated preview acceptance remain separate.

## Reproduction and regression evidence

With only the production patch temporarily removed against the branch HEAD, `test_active_case_queue.py` reproduced two failures: both Available and My Cases reported total 8 instead of 4. `cockpit-live.test.tsx` reproduced a committed-dismissal queue refresh failure when detail retrieval rejected. Production changes were then restored.

- `.venv/bin/pytest tests/test_api/test_active_case_queue.py -q`: 8 passed. Covers filtering before pagination, organization scope, retained history, actual Dismiss/Approve/Suspend transitions, stale retries, failed submissions, Request Evidence, and rejection of unsupported Escalate.
- `ISSUE143_DATABASE_URL=<isolated database> .venv/bin/pytest tests/test_api/test_active_case_queue_persisted.py -q --tb=short`: 3 passed. Uses the real HTTP/service/PostgreSQL path with an authorized principal dependency override. Verifies actual Dismiss/Approve/Suspend persistence, one adjudication per stale-retried request, sanctions for Suspend, retained snapshots, and unchanged seeded historical audit rows.
- `pnpm test tests/cockpit-live.test.tsx`: client contract tests use mocked API responses; they do not prove persistence.
- `PORT=3143 pnpm exec playwright test e2e/active-queue.spec.ts`: Chromium fixture tests exercise Dismiss/Approve submit and reload. Fixture results do not prove persistence.
- The optional `ISSUE143_BROWSER_API` browser test forwards requests unchanged to an exclusively owned, PostgreSQL-backed API. It exercises claim, dismiss, reload, a second browser session, active queue exclusion, and retained detail. Authentication is a local principal override; Clerk/hosted authentication is not proven.

## Manual/hosted acceptance still required

1. Record deployed commit, URL, authenticated analyst, case ID, and before/after screenshots/API responses.
2. In two authenticated browser sessions, claim an eligible case; submit Dismiss and an approved sanction with rationale. Verify removal from Available and My Cases after refresh and reopening.
3. Submit a stale/failed decision; verify the active row remains and no decision persists.
4. Request Evidence; verify the case remains in its authorized work queue. Existing escalated records remain nonterminal; new Escalate remains unsupported by the current contract.
5. Independently inspect retained evidence, conversation, adjudication, sanction, and audit rows. Retry the same version; confirm no duplicate adjudication.

## Known boundaries

The baseline adjudication path does not create `app.audit_events` entries. This change preserves explicitly seeded historical audit bytes; it does not claim a new decision audit event. Comprehensive rollback, hosted authentication, and audit creation acceptance remain open. `bash scripts/check.sh` passes Ruff lint/format but stops on the baseline NumPy stub/Python-target mypy error: `Type statement is only supported in Python 3.12 and greater`. Baseline repair is tracked separately.
