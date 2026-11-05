# ADR-012: Pull Request Deployment Previews and Approval Gates

## Status
Accepted

## Context
Pull requests need reproducible frontend and backend previews without sharing production resources. Backend and full-stack changes require an isolated `pr-N` Railway environment and exact commit verification. Frontend-only changes must provide a stable Dev preview without provisioning or waiting for Railway. Forks and documentation-only changes must skip deployment safely.

## Decision
Both deployment workflows trigger on every pull request. A shared paginated PR classifier excludes `src/webapp` from backend scope and classifies docs-only, frontend-only, backend, and full-stack changes. Forks and docs-only PRs skip deployment. Frontend-only PRs route immediately to the stable Dev backend; they do not provision or wait for Railway.

Backend and full-stack PRs provision isolated `pr-N` environments. Vercel waits 120 seconds for the exact PR/head Railway workflow and health endpoint, then fails closed. The successful Railway deployment ID is tracked and must match the submitted deployment. A Vercel preview is submitted only after this gate.

Vercel uses one token and one project for `/driver` and `/workplace` on the same domain. The driver product scope remains deferred. The preview origin is merged into the existing Dev allowlist as an exact serialized authorization rollout. This is separate from required authentication completion and never uses a wildcard. Vercel deployment failures propagate and readiness waits inspect `READY` state.

Staging and production remain selective dispatch paths. Production is main-only. Guards fail closed when required live reviewers are absent or production is not main-only. Current GitHub write access returns HTTP 404 for live rules `PUT`; live rules are therefore not documented as configured.

Migration and data scope are unchanged.

This ADR records the target contract for Issue #107/#111. Hosted implementation and manual evidence remain pending; this document does not claim a successful deployment run.

## Rationale & Alternatives Considered

| Option | Pros | Cons | Decision |
|---|---|---|---|
| Shared classifier plus exact PR/head gates | One policy, safe pagination, isolated backend previews, fast frontend previews | Requires exact deployment tracking and serialized authorization | Selected |
| Provision Railway for every PR | Uniform topology | Slow, wasteful, and unnecessary for frontend-only changes | Rejected |
| Shared backend fallback or wildcard CORS | Simple setup | Cross-PR contamination and unsafe origin authorization | Rejected |
| Configure live GitHub rules through current write token | Centralized enforcement | API returns HTTP 404; configuration would be unverified | Rejected |

## Consequences
Preview behavior is deterministic and fail-closed. Frontend-only feedback is fast. Backend/full-stack previews consume isolated Railway environments and wait for exact successful deployments and health. Live approval-rule configuration remains an explicit external gate. No schema, migration, or data behavior changes.
