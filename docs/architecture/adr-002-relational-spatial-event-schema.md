# ADR-002: Relational, Spatial, and Event Schema

## Status

Proposed

## Context

The PoC must represent an Uber-like trip lifecycle, high-frequency telemetry, reproducible fraud assessments, analyst assignment, human adjudication, and a tamper-evident audit trail. It must run locally and on Supabase without adding a separate event broker, spatial database, or analytics warehouse.

The model must preserve several distinctions: a trip can contain several driver pickup episodes; raw observations differ from derived features; an analyst assignment differs from a short review lease; a model assessment differs from a human adjudication; and a missing driver report differs from a technical fault. Decisions must record exactly which evidence and policy version the analyst reviewed.

## Decision

Use PostgreSQL as the PoC system of record with PostGIS for routes and points and pgvector for policy retrieval. Store normalized operational entities and append-only evidence, assessment, decision, and audit records in one database. Store raw producer envelopes in JSONB alongside typed columns used for validation, joins, and indexes.

Use one suspected-fraud case per accepted trip assignment, not one per trip. Preserve immutable evidence snapshots and versioned derived feature sets. Late evidence increments the case version and invalidates any review lease bound to an older snapshot.

Use a PostgreSQL jobs table with leases, retries, and `FOR UPDATE SKIP LOCKED`. Use a transactional outbox for internal domain events. Do not add Kafka, Redis, Celery, TimescaleDB, or a warehouse for the PoC.

Implement the schema through [`db/migrations/0001_poc_core.sql`](../../db/migrations/0001_poc_core.sql). Validate producer contracts against [`telemetry-event.schema.json`](schemas/telemetry-event.schema.json) and [`domain-event.schema.json`](schemas/domain-event.schema.json).

## Rationale and alternatives considered

| Option | Benefits | Costs | Decision |
|---|---|---|---|
| PostgreSQL + PostGIS + pgvector | One transactional boundary; relational integrity; spatial queries; local/cloud parity; enough analytics for PoC | Requires careful indexes and retention as telemetry grows | Selected |
| PostgreSQL plus Chroma | Familiar vector PoC and isolated retrieval | Adds persistence, backup, deployment, and consistency work | Rejected for PoC |
| Kafka plus stream processor plus warehouse | Strong high-volume streaming and analytical separation | Large operational surface; no MVP acceptance criterion needs it | Deferred |
| JSON document store | Flexible producer payloads | Weak cross-entity constraints and harder atomic adjudication | Rejected |
| Full event sourcing | Complete replay semantics | More projections, versioning rules, and developer overhead than needed | Rejected |

## Required architecture questions

| Question | Answer |
|---|---|
| System topology | Simulator, FastAPI, worker, LangGraph, and Next.js use one PostgreSQL system of record. Only FastAPI and worker connect directly. |
| State and graph lifecycle | Raw events create durable jobs. The worker builds a snapshot and feature set before invoking the bounded detection graph. Case states are persisted independently from graph memory. |
| Tool contracts | Repositories accept typed IDs and return typed domain objects. Agent nodes receive snapshot data through services and never issue SQL. |
| Data flow | Ingest raw event; commit job; preprocess; freeze snapshot; assess; compute priority; claim; adjudicate atomically; append audit and outbox records. |
| Trade-offs | One database minimizes PoC operations. Durable jobs trade peak throughput for transactional reliability and easy testing. |
| Security boundaries | The `app` schema is not browser-accessible. FastAPI verifies Clerk JWTs. Separate database roles restrict workers from adjudication and sanction writes. Append-only tables reject update/delete. |

## Consequences

The schema supports the deployed cockpit and synthetic operations without implementing passenger, driver, payment, or appeals applications. SQL transactions can enforce idempotency, stale-version rejection, and human approval.

PostgreSQL is not an immutable storage service. Update/delete rejection and a hash chain protect against ordinary application mutation; independently retained checkpoints are required to detect a privileged database-owner rewrite. Telemetry volume must be monitored. Partitioning and archival remain later decisions.
