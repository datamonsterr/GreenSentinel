# Issue 66 verification: durable solved-case context

## Scope and schema gap

The inherited `app.precedent_workflows` table is a read-only compatibility source, not an authoritative solved-case record. Its `case_id` is nullable and its JSON trace has no enforced tenant, assignment, driver submission, evidence snapshot, policy version, signed adjudication, publisher, or immutable trace hash. The inherited in-memory service could also invent policy calls and publish unsaved records. Those records remain readable through an explicit legacy adapter but are never eligible for reuse.

Migration [`20261003090000_durable_solved_case_precedents.sql`](../../db/migrations/20261003090000_durable_solved_case_precedents.sql) adds:

- `app.solved_case_contexts`: one append-only record per resolved case, linked through organization, assignment, driver submission and/or case session, evidence snapshot, policy version, signed human adjudication, and publishing analyst;
- `app.precedent_reuse_history`: append-only `viewed`/`applied` events carrying actor, current case, immutable precedent trace hash, retrieval model, matching factors, and the explicit `uncalibrated_case_similarity_not_adjudication` score semantics;
- validation triggers that reject cross-tenant links, mismatched evidence/policy/decision records, unsigned decisions, mutable history, and reuse of an ineligible precedent;
- a rollback script that removes only the new authoritative tables/functions and restores legacy-table mutability for compatibility.

The repository builds traces only from persisted driver submissions, analyst conversation messages, agent-runtime tool events, evidence/policy IDs, and the signed adjudication. Missing conversation state is explicit; it is not synthesized. Applying a retrieved precedent appends advisory history and does not update either adjudication.

## Definition-of-done evidence map

| Issue outcome | Implementation / proof | Evidence boundary |
|---|---|---|
| Assignment → case → conversation → evidence → policy → decision → workflow provenance | New FK-backed context table and [`precedent_repository.py`](../../src/services/precedent_repository.py) | Static/local code proof; migrated DB test pending local virtualization or CI |
| Who/what/when, immutability, tenant isolation | Publisher/actor/timestamps, trace hash, validation and append-only triggers; migrated-DB tests cover mutation and cross-tenant reuse | Test is tracked and included in integration runner; not yet observed locally |
| Retrieval provenance and honest score semantics | API/service schemas return `PrecedentProvenance` and score semantics; legacy fixtures are read-only/ineligible | 14 focused precedent/API tests pass |
| Dismissed, approved, incomplete, legacy appeal, reload and rollback | [`test_precedent_history_integration.py`](../../tests/test_services/test_precedent_history_integration.py) | Isolated migrated-Postgres test; local execution blocked because Windows Virtual Machine Platform is disabled |
| No automatic adjudication | Reuse records `viewed`/`applied`; no decision update exists; publication requires an existing explicit human approval | Unit contract plus migrated-DB before/after decision assertion |

## Observed verification

| Layer | Result | Reproduction |
|---|---|---|
| Python environment | Python 3.11.16, 96 locked packages installed | `uv sync --frozen`; `.venv/Scripts/python.exe --version` |
| Focused precedent/API/workspace tests | 24 passed | `APP_ENV=test DATABASE_URL=postgresql://...@127.0.0.1:1/postgres python -m pytest tests/test_services/test_jev_precedent_service.py tests/test_api/test_precedent_api.py tests/test_services/test_case_workspace.py -q` |
| Owned Python lint/compile | Pass | `ruff check` on changed Python/tests; `python -m compileall -q src tests` |
| Whitespace | Pass | `git diff --check` |
| Migrated PostgreSQL integration | Not run locally | Docker reports `Virtual Machine Platform not enabled / No virtualization available`; test is included in `scripts/test_integration.sh` for CI/isolated DB execution |
| Integration-test collection without DB | 4 skipped as designed | `python -m pytest tests/test_services/test_precedent_history_integration.py -q`; skips require `ISSUE66_DATABASE_URL` or a migrated `DATABASE_URL` |
| Hosted environment | Not run | No hosted deployment or authenticated hosted acceptance is claimed |

The repository-wide collection includes E2E tests that require a migrated/seeded backend; an offline attempt reaches `tests/e2e/test_driver_api_e2e.py` and fails because zero cases are seeded. That result is not presented as an S2-F09 regression.
