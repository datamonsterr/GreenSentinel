# ADR-005: PoC Runtime and Deployment

## Status

Proposed

## Context

The PoC must run locally, deploy quickly, remain accessible online, stream analysis and policy responses, and keep long-running model work durable. The preferred services are Vercel, Railway, Supabase, Clerk, OpenRouter, and LangSmith.

## Decision

Build a modular monolith from one repository:

- Next.js 16 App Router, TypeScript, Tailwind, shadcn/ui, MapLibre, and Clerk deploy to Vercel.
- FastAPI and a separate worker process use one Python package managed by `uv`; both deploy to Railway from the same image.
- Supabase PostgreSQL hosts the relational, spatial, vector, job, outbox, and audit data.
- OpenRouter provides Jev; LangSmith records redacted traces.
- Docker Compose runs web, API, worker, and PostgreSQL locally. Local tests use the same SQL migrations.

The browser calls FastAPI directly with a Clerk session bearer token. FastAPI validates the JWT signature, issuer, audience, expiry, and principal status, then loads roles from PostgreSQL. CORS permits only configured frontend origins. The browser receives no database, OpenRouter, or Supabase secret.

Use REST for queue reads, claims, decisions, and simulation commands. Poll the queue while visible. Use SSE only for analysis progress and policy chat. Long model work runs through durable PostgreSQL jobs; do not use FastAPI in-process background tasks for durable work.

## Rationale and alternatives considered

| Option | Benefits | Costs | Decision |
|---|---|---|---|
| Vercel + Railway + Supabase | Matches preferred stack; fast managed deployment; clear component ownership | Three platforms, CORS, and secret coordination | Selected |
| All services on Railway | Simpler network and deployment model | Gives up Vercel frontend workflow and managed Supabase features | Viable fallback |
| Next.js backend-for-frontend proxy | Same-origin browser requests | Extra hop; more streaming and authorization code; serverless duration boundary | Rejected for PoC |
| Supabase browser access with RLS | Less API code for reads | Clerk integration and mixed authorization become harder; sensitive evidence should stay behind API | Rejected |
| Redis/Celery | Mature worker queue | Additional service and operational failure modes | Deferred |
| Kubernetes | Portable orchestration | Excessive for PoC scale and team capacity | Rejected |

## Required architecture questions

| Question | Answer |
|---|---|
| System topology | Vercel web calls Railway API; Railway API/worker connect to Supabase; worker calls OpenRouter, LangSmith, and optional OSRM. |
| State and graph lifecycle | PostgreSQL owns durable case/job state. LangGraph state exists only during a leased worker attempt and writes a terminal assessment before completion. |
| Tool contracts | External adapters use explicit timeouts, retry only idempotent calls, return typed errors, and attach correlation IDs. |
| Data flow | Commands use REST, read-only progress uses SSE, jobs persist before worker execution, and decisions commit with audit/outbox rows. |
| Trade-offs | Managed services maximize delivery speed. Direct API access requires narrow CORS and correct cross-origin Clerk token handling. |
| Security boundaries | Platform secret stores hold credentials. Clerk proves identity; PostgreSQL roles enforce service capabilities. Rate limits, payload limits, and redacted tracing apply at API boundaries. |

## Consequences

API and worker can scale independently without splitting the codebase. Docker Compose provides local parity for SQL and background execution. A local development identity adapter may exist only behind an explicit development environment setting; startup must fail if it is enabled in a deployed environment.

SSE connections stay on Railway rather than crossing a Vercel proxy. If PostgreSQL job contention or telemetry volume exceeds the PoC envelope, Redis or a managed message broker can replace the job repository behind the same service interface.
