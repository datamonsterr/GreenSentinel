# ADR-023: Sequence preview deployments through a reusable workflow

## Status
Accepted — 2026-10-06. Relates to [issue #179](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/179).

## Context
Vercel's cross-workflow wait occupied the sole self-hosted runner while Railway provisioning queued. Moving the wait to a hosted runner failed before execution because GitHub reported account billing/spending limits in [run 37405954899](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/actions/runs/37405954899).

## Decision
Railway calls the reusable Vercel workflow after successful PR provisioning and health checks, through `needs: [deploy-pr-preview]` and `railway_ready: true`. No runner executes a cross-workflow wait. The independent Vercel pull-request path deploys only frontend-only changes. Both paths retain backend health checks; backend changes require the exact PR head and cannot fall back to a shared backend.

The relative workflow reference uses the caller's commit. The called workflow retains the caller's pull-request event and head SHA. Caller permissions match the callee; inherited secrets remain scoped to existing deployment steps. Neither workflow declares a shared concurrency group, avoiding caller cancellation by the callee. These semantics follow GitHub's [reuse guide](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows) and [reusable-workflow reference](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations).

## Rationale & Alternatives Considered

| Option | Benefit | Cost | Decision |
|---|---|---|---|
| Self-hosted polling | Existing configuration | Deadlocks with one runner | Rejected |
| Hosted polling | Frees the self-hosted runner | Cannot start under current account billing limits | Replaced |
| Reusable workflow after Railway | Scheduler enforces ordering without a waiting runner | Backend frontend checks appear under the Railway run | Selected |

## Consequences
Failed, cancelled, or skipped Railway provisioning prevents the dependent frontend call. Frontend-only PRs keep their direct dev-backend path. A backend preview retry starts from the Railway workflow; separate Vercel runs intentionally skip backend deployment. YAML contract tests cover scheduling and existing provisioning tests cover exact-head rejection. Current-head CI and deployed backend/frontend checks remain required evidence.

## Runtime boundaries and data flow
This deployment decision changes no TypedDict state, graph nodes, conditional edges, tool contracts, or application input validation. Client requests still pass from Next.js to FastAPI, service adapters, and LangGraph, with results streamed through the existing API. API, service, agent, and shared-model responsibilities retain their current boundaries. Secrets remain in GitHub secret storage and step environments; application authorization, sanitization, and rate limits are unchanged.
