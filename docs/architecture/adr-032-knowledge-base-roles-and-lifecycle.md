# ADR-032: Knowledge base, agent config, roles and lifecycle

Status: Accepted · Scope: `/knowledge`, `/agent-config`, `app.kb_*`, `app.agent_config*` (PRD-K, plan Decisions 1-5, 7-9) · Slice S-K. Depends on [ADR-031](adr-031-gsm-workflow-roles.md) role mapping.

## Context

PRD-K lets fraud analysts (KSGL) teach the driver explanation agent (motives, behaviours, scenarios, workflows) in the portal, gate releases, configure agent limits and kill the agent. The repo has no knowledge store, config, or proposals queue. Names collide with existing concepts (`workflow_*` analyst tables, `/cases/{id}/workflow` stepper, "policy" corpus, "precedent").

## Decision

### 3-tier layering

1. **Routes** `src/api/knowledge_routes.py`: auth principal, request models, delegation only.
2. **Services** `kb_service.py` (lifecycle, validation, proposals, registry, seed), `agent_config_service.py` (bounds, history, kill switch), `kb_formula.py` (safe AST evaluator), `kb_similarity.py` (scorer interface).
3. **Persistence** `kb_store.py`: table-oriented `Store` protocol, `PgStore` (psycopg, schema `app`) and `MemoryStore` (tests). Services never write SQL.

### Naming

Knowledge lives in `kb_*` tables and `/knowledge` routes. "Workflow" in PRD = `kb_object.type = 'workflow'`, never `workflow_*`. Config is `agent_config` / `agent_config_history`.

### Data model (migration `20261120110000_kb_objects_and_agent_config.sql`)

- `kb_object(type parameter|motive|behavior|scenario|workflow, code, version, status, scope, body jsonb, author/approver, replay jsonb, override_reason, history jsonb, ...)`: one row per version. Unique `(org, type, code, version)`; partial unique index guarantees at most one `published` row per `(org, type, code)`.
- `agent_config(org, key, scope, value)` + `agent_config_history(old/new, reason, kind change|revert|kill_switch, actor)`.
- `kb_policy_document` (metadata + extracted text, `indexing_status not_indexed|indexed|embeddings_not_configured`).
- `kb_proposal(source, type, payload, mapping reuse|extend|new, similarity, status pending|accepted|edited|rejected, reason_code, ...)`.
- Audit: existing append-only `app.audit_events` (`kb.object.*`, `kb.proposal.*`, `kb.document.create`, `agent_config.*`, `kb.seed`).

### Roles (no new DB roles)

| Capability | Roles |
|---|---|
| Read and author knowledge, upload documents, accept/edit/reject proposals (KSGL) | `analyst`, `fraud_analyst`, `senior_analyst`, `admin` |
| Approve a release / roll back (4-eyes) | `senior_analyst`, `admin`, and **never the author** |
| Read config + agent registry | KSGL + VH (`manager`, `reviewer`) |
| Edit config: KSGL-owned keys (K, similarity, confidence, edit limit, card memory) | KSGL |
| Edit config: VH-owned keys (N_max, T, help SLA/ceiling) | `manager`, `reviewer`, `admin` |
| Kill switch (`explain_agent_enabled`) | `senior_analyst`, `manager`, `admin` |
| Seed demo data | `admin` |

Formulas and thresholds are real detection logic: drivers and workflow-only roles get 403 on `/knowledge/*`. PO bounds (min/max per key) are code constants in `agent_config_service.DEFINITIONS`; out-of-bounds writes return 422. Config scope is `global` or `rule:<code>`; reads fall back to global then default. Every write needs a reason and appends history; revert re-validates against current bounds.

### Lifecycle

`draft → ready_for_test → trial → published → retired`.

- `submit` (draft only) runs body validation (formula syntax/unknown parameter/units/division by zero, tool catalogue, forbidden words fine/clawback/handling direction). Invalid objects can be saved as draft but not submitted.
- `trial` runs the replay stub over up to 30 real cases (no driver contact) and stores counts: `cases_total, matched, changed_scenario, not_computable, est_turns, gate_passed`. Gate = computable ratio >= 0.5. Policy-constant parameters (incentives, estimates, pricing) assume the catalogue sample value; the result marks them `assumed`.
- `publish`: approver role, `approver != author`, compare-and-set on `trial`, scenario references must be published, failed gate needs an `override_reason` (>= 10 chars). The previously published version becomes `retired (superseded)`.
- `rollback` restores the most recently superseded version in one step; `retire` takes effect immediately (`get_published` stops returning it).
- Editing is allowed only in `draft`/`ready_for_test` (edit returns to draft); new versions come from `clone`.
- Agents read only `published` via `kb_service.get_published(org, type, code)` / `list_published(org, type)`.
- Proposals (`propose_knowledge`, policy analysis, help replies) accept/edit only up to `ready_for_test`; they never publish.

### Formula evaluator

Excel-style only (`=IF(a+1>=b, c-d, 0)`), hand-written tokenizer + recursive-descent parser to a tiny AST; whitelisted functions `IF AND OR NOT MIN MAX ABS ROUND SUM`; no `eval`/`exec`/attribute access; length and depth limits. Names resolve only against `PARAMETER_CATALOGUE` (each has unit, source, owner, latency, kind `case|policy`). Code and drag-drop modes are deferred.

### Similarity and embeddings

No embeddings key exists. `SimilarityScorer` interface with a deterministic `TokenOverlapScorer` (Jaccard); `EmbeddingScorer(Embedder)` exists for later and is tested with a mock embedder. Document indexing status is `embeddings_not_configured` unless `EMBEDDINGS_API_KEY` is set (then `not_indexed`). No vector column is added.

### Kill switch semantics

`explain_agent_enabled` defaults to `false` (plan Decision 9). Off means the existing static form and chat. The flag is checked by the explanation agent per session via `AgentConfigService.explain_agent_enabled(org)`; the S-K slice only stores and audits it.

## Alternatives

| Option | Decision |
|---|---|
| One table per knowledge type | Rejected: four near-identical lifecycles and versioning. |
| Python `eval` / sandboxed code for formulas | Rejected: security surface; PRD Q8 open. |
| New DB roles for KSGL lead / VH lead / PO | Rejected: role migrations across Clerk; reuse `senior_analyst`/`manager`/`admin`. |
| pgvector now | Rejected: no provider/dimension decision. |
| Separate audit table | Rejected: `audit_events` is already append-only and hash-capable. |

## Consequences

- S-D1 consumes `get_published`, `list_published`, `AgentConfigService` getters, `KbService.create_proposal`, and `default_scorer()`.
- Replay is a stub: no changed-conclusion rate against VH outcomes until closed-case corpora exist (S9 in the gap analysis).
- Local cases carry few case parameters (`trips_today`, duration); trials of other parameters report `not_computable` honestly.


## Decision (2026-11-20): Approvers stay senior_analyst/admin

Publish/approve remains limited to `senior_analyst` and `admin` with author != approver. No broader approver role is introduced.
