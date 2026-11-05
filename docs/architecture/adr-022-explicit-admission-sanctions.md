# ADR-022: Explicit Driver Admission Sanction Boundary

## Status
Accepted for synthetic test/dev scenarios; production mapping remains pending policy publication.

## Context
An explicit authenticated Driver admission may authorize autonomous handling. Exoneration evidence and generic confirmation do not. Production sanction amounts and durations must come from a published policy source.

## Decision
Persist an immutable `app.driver_admission_sanctions` outcome keyed by case, admission hash and policy version. The `greensentinel-demo-admission-v1` mapping is explicitly demo-only and maps ERR-02 to WARN without an invented amount. Unmapped or non-demo cases remain `pending_policy` and require analyst review.

## Rationale & Alternatives Considered
| Option | Pros | Cons | Decision |
|---|---|---|---|
| Explicit typed admission + published mapping | Auditable, idempotent, fail-closed | Requires policy versioning | Selected |
| Infer sanction from confidence/evidence | Simple | Silently authorizes adverse action | Rejected |
| Generic confirmation closes | Easy UX | Confirmation is not admission | Rejected |

## Consequences
The database enforces tenant ownership, immutable outcomes, idempotency and positive sanction bounds. The demo mapping is limited to synthetic test/dev data; production requires a non-demo published policy before application.

## Boundaries
FastAPI validates authenticated Driver ownership before creating an outcome. Audit records include the admission hash and policy version. Analyst adjudication remains the fallback for denial, missing policy, conflicting evidence or unsupported categories.
