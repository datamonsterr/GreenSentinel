# Plan: PRD features (driver explanation AI + knowledge base & agent config)

Sources: `docs/prd/prd-ai-driver-explanation.md` (PRD-A), `docs/prd/prd-knowledge-agent-config.md` (PRD-K), `docs/prd/gap-analysis.md`.
Branch: `so/gs-master-prd-3809e831`. Slices run as `master/<slice>` worktrees, merged by master.

## Goal / out of scope
Goal: ship a working, flag-guarded vertical of both PRDs: structured motivation per case, knowledge base + agent config (admin/analyst portal), driver explanation agent v2 (dynamic form, bounded loop, help request, summary confirm) and analyst provenance/feedback.
Out of scope this batch: monitoring agent scheduler (US8, PRD-K), TX history memory (PRD-A US5 layer 2, DPIA-gated), scenario cards from closed cases (PRD-K US5), golden-case evaluation harness, code-sandbox and drag-drop formula modes, email/other notification channels, real embeddings, deployment, prod data.

## Decisions (ambiguities resolved toward the PRD)
1. **Naming**: knowledge objects live in `kb_*` tables/`/knowledge` routes; "workflow" in PRD = `kb_workflow` (never the existing `workflow_*` analyst tables or `/cases/{id}/workflow` stepper).
2. **One generic object table** `kb_object(type in parameter|motive|behavior|scenario|workflow, code, version, status, scope, body jsonb, author, approver, ...)` with per-version rows; lifecycle Nháp → Sẵn sàng kiểm thử → Chạy thử → Đã phát hành → Ngưng. Agent reads only `published`.
3. **Roles (no new DB roles)**: KSGL = analyst/fraud_analyst/senior_analyst; VH = `manager`/`reviewer`; approver (4-eyes) = `senior_analyst`/`admin` and must differ from author; admin sees everything; PO bounds = code constants. Documented in ADR-032.
4. **Formulas**: Excel-style expression only (`=IF(a+1>=b, c-d, 0)`), evaluated by a safe AST evaluator over the parameter catalogue (no `eval`). Code/drag-drop modes deferred.
5. **Embeddings**: none live. Similarity = deterministic token-overlap/Jaccard behind a `SimilarityScorer` interface; indexing status for policy documents shows `not_indexed / embeddings_not_configured` unless a key is present. Tests mock the embedder.
6. **Status model**: no new `fraud_cases.status`. Explanation session state in new tables; "Đang kiểm tra giải trình" derives from session state.
7. **Notifications**: in-portal (poll badge count of open help requests); no email/push.
8. **LLM**: OpenRouter `z-ai/glm-5.3-flash`; every number (motive value, thresholds) computed in code; LLM output validated against pydantic schema, fallback to deterministic result on failure/timeout.
9. **Kill switch / config**: DB-backed `agent_config` (+history, bounds). Kill switch ⇒ agent v2 off ⇒ existing static form + current chat (default stays current behaviour; v2 on only when `explain_agent_enabled=true`).
10. **Motivation**: persisted per case as structured assessment (see S-M); Overview card reads it (fix existing wiring bug: card read `cockpit_evidence`, data lives in `forensic_brief.motivation_assessment`). Analyst can edit/confirm; generation is rule-based + optional LLM rationale.
11. **Test accounts**: no VH login exists; analyst stands in for VH in browser verification of help queue.

## Migrations (idempotent, additive, schema `app`, timestamps > 20261020000000)
- M1 `20261120100000_case_motivation_assessments.sql`
- M2 `20261120110000_kb_objects_and_agent_config.sql` (kb_object, kb_audit uses audit_events, agent_config, agent_config_history, kb_policy_document, kb_proposal)
- M3 `20261120120000_explain_sessions.sql` (explain_session, statement_version, assessment_round, explain_turn, help_request, vh_feedback)
Slices append their own file; only the controller applies to prod.

## Slices

### S-M — Structured motivation (independent) — worktree `master-s-m`, ports 3004/8104
- DB: `case_motivation_assessments(id, case_id, org_id, version, motive_category, signals jsonb, amount_at_stake_vnd, confidence, rationale, source ai|rule|analyst, status draft|confirmed, confirmed_by, confirmed_at, created_at)` (append versions, latest wins).
- Backend: extend `motivation_assessment_service` to emit the structured shape (category enum: reward_threshold, subsidy_surge, fare_inflation, platform_fault, unclear), `GET /cases/{id}/motivation`, `POST /cases/{id}/motivation/generate`, `PUT /cases/{id}/motivation` (analyst edit → new version), `POST .../confirm`. Role: analyst-family; audit event.
- UI: Overview Motivation card shows category chip, signals, amount, confidence bar, rationale, status; buttons Generate / Edit / Confirm; reads persisted else `forensic_brief`. Cyan tokens, vi/en.
- Acceptance: card never shows "Not assessed" for a case with forensic brief data; edit→confirm persists; unit tests for mapping, API, card rendering; browser verified on 2+ cases.

### S-K — Knowledge base + agent config view (foundation) — worktree `master-s-k`, ports 3005/8105
- Backend: M2; `kb_service` (CRUD, version, clone, retire, lifecycle transitions, 4-eyes publish with author≠approver, rollback to previous version, audit); safe formula evaluator + parameter catalogue seed (trip km, gps km, fare, surge, subsidy, trips_today, milestone…); validation (syntax, unknown param, div/0); preview on real case(s); `agent_config` service with bounds/history/revert + kill switch; routes `/knowledge/*`, `/agent-config/*`; policy document upload record + indexing status field (`not_indexed|indexed|embeddings_not_configured`).
- Frontend: new route `/knowledge` (top bar + left sub-nav + main panel) with tabs: Kho tri thức (list by type, filters, status chips, version history, editor with formula validation + preview), Tài liệu chính sách (upload/list/indexing status, which agents use it), Agent (which agent uses which knowledge, instruction version, model, tools, memory layers), Cấu hình (N_max, K, T, SLA, ceilings, thresholds, kill switch, history/revert, 30-day metrics placeholders), Hàng chờ duyệt (proposals, Accept/Edit/Reject with reason). Entry in portal top bar for analyst/admin. Seed a few demo knowledge objects (idempotent).
- Acceptance: create motive+behavior+scenario+workflow, publish via second user (author≠approver enforced, replay stub reports counts), kill switch + config change recorded with history; pytest/vitest per feature; browser verified as analyst and admin.

### S-D1 — Driver explanation agent v2 backend — worktree `master-s-d1`, ports 3006/8106 (after S-K)
- M3; session service: form versions (fixed questions per reason + ≤K dynamic from matched published workflow), `statement_version` (immutable v1, later versions), 4-state assessment round, flags (novel_scenario, statement_changed, ai_inconclusive, session_interrupted, asked_for_help, asked_for_help_skipped), bounded loop (think→tool→observe→ask) with N_max from config, tools `identify_behavior, list_motives, compute_motive, match_scenario, get_workflow, request_help, propose_knowledge` registered in tool catalog (read published only; log code+version), output guard (no fines/conclusions/thresholds/other drivers), prompt-injection flagging, summary confirm/edit (≤ edit limit), end-early, T-minute lazy auto-submit, fallback to static form when kill switch/LLM failure.
- Help: `help_request` create/claim/reply/expire (lazy), ceiling, proposal generation from VH reply.
- Routes under `/driver/cases/{id}/explain/*` and `/cases/{id}/explain/*` (analyst read + feedback + help queue). Existing chat/statement routes untouched.
- Acceptance: scripted simulation test (PRD-A §10 scenario) passes with mocked LLM; loop stops at N_max with ai_inconclusive; kill switch returns fallback; guard tests.

### S-D2 — Driver app UX + analyst provenance (after S-D1) — worktree `master-s-d2`, ports 3002/8102
- Driver: dynamic typed form (text/time/location/choice/amount/photo/ticket, required marks, draft by violation, highlight missing), "Đang kiểm tra giải trình", agent chat step with Kết thúc, summary Confirm/Sửa, bilingual, mobile 390x844. Hooks into `driver-explain-flow.tsx` behind config flag; legacy flow intact.
- Analyst: Overview/Driver-relay show assessment rounds, statement versions, flags, provenance (scenario/behavior/motive/workflow code+version), suggestion block, help request history; structured VH feedback (Agree / Disagree + error types + comment); help-request queue panel with badge, claim/reply (analyst stands in for VH).
- Acceptance: browser E2E driver submits explanation → analyst sees rounds/provenance → help reply → driver continues.

### S-P (stretch, only if time) — Policy analysis agent: upload → rule extraction with citation (LLM, schema-validated) → proposals with reuse/extend/new via token similarity → review queue (reuses S-K queue UI). Skipped if S-D2 not merged first.

## Ordering
Wave 1 (parallel): S-M ∥ S-K. Wave 2: S-D1 (needs S-K). Wave 3: S-D2 (needs S-D1). S-P stretch parallel with Wave 3 if capacity.
Merge discipline: each subagent runs `git merge so/gs-master-prd-3809e831` before final report; master reviews diff, merges, runs full checks, removes worktree.

## Test plan
Per slice TDD: failing pytest/vitest first. Backend `uv run pytest tests/unit -n 8 -k <area>`, `uv run ruff check src`; webapp `pnpm test`, `pnpm exec tsc --noEmit -p tsconfig.json`, eslint on touched files. Final: full suites + `pnpm build`. Browser verification per role (analyst, admin, driver) → `/home/dat/.claude/gs-shots/master/`.
