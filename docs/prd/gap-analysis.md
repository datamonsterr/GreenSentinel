# Gap analysis: PRD-A (Driver explanation agent) and PRD-K (Knowledge base and agent config) vs current code

Branch `so/gs-master-prd-3809e831`, read-only investigation, 2026-11-20. Line refs are from this worktree (HEAD 1bdf1ed).
PRD-A = `docs/prd/prd-ai-driver-explanation.md` (US1-US6, section 8). PRD-K = `docs/prd/prd-knowledge-agent-config.md` (US1-US8, section 8).

Status legend: **exists** = usable as is; **partial** = something close exists, needs rework or extension; **missing** = nothing.
Headline: almost everything in both PRDs is **missing**. The repo has a free-form chat "GSupport" agent and an analyst precedent mechanism, but no structured explanation session, no knowledge store, no agent config, no help queue.

---

## 1. Architecture map of current code

### 1.1 Driver explain flow end to end (today)

1. **Notification / case list**: `GET /api/v1/driver/cases` (`src/api/routes.py:900`), context `GET /driver/cases/{id}/dispute` (`routes.py:958`), backed by `DriverDisputeService` (`src/services/driver_dispute_service.py:137`). Case has `dispute_status` (`not_disputed|pending|in_dispute|auto_dismissed|analyst_escalated`) and `dispute_deadline` (migration `20260926180000_poc_v2_driver_role_and_dispute.sql`).
2. **Driver App chat**: `src/webapp/components/driver/chat/driver-chat-view.tsx` (30 KB). Quick reply `explain` (line ~663) -> `handleRejectViolation` -> opens `DriverExplainFlow` (`driver-chat-view.tsx:684-692`).
3. **Form**: `src/webapp/components/driver/chat/driver-explain-flow.tsx`. Hard-coded 4-step wizard (`STEPS = 4`, line 9), 5 hard-coded reasons `NotDone|RealTrip|Tech|Customer|Other` (line 10), one free-text field (min 20 / max 500 chars, lines 7-8) plus one optional evidence text. It composes a single string `Lý do: ... / Chi tiết: ... / Bằng chứng: ...` and calls `onSubmit(summary)`. No per-reason question set, no typed fields, no required/optional per question, no photo/ticket fields, no form_version.
4. **Submit**: `handleConfirmBlock({action: "submit_statement"})` -> `POST /driver/cases/{id}/confirmations` (`routes.py:1178`, single-use token, 10 min) -> `POST /driver/cases/{id}/statement` (`routes.py:1220`) -> `DriverDisputeService.submit_statement_with_token` (`driver_dispute_service.py:2459`). It writes `app.driver_submissions` (insert is wrapped in try/except and silently skipped; note status literal `'submitted'` is not in the `0001` CHECK list `requested|present|late|rejected|quarantined|no_report`, so the insert likely fails without notice), sets case `status='driver_disputed'`, `dispute_status='analyst_escalated'` (line ~2540), writes an audit entry (`_record_audit_entry`, line 560, inserts into `app.audit_events` at ~611) and returns a canned Vietnamese reply. Drafts: `PUT/GET /driver/cases/{id}/statement-draft` (`routes.py:1240/1258`), table `app.driver_statement_drafts` (migration `20261019000000_driver_confirmations_drafts.sql`).
5. **Free chat (no N_max)**: `POST /driver/cases/{id}/chat/stream` (`routes.py:1102`) -> `DriverDisputeService.process_driver_chat` (`driver_dispute_service.py:1323`) -> LangGraph ReAct agent `src/agents/driver_agent.py` (`build_driver_support_agent` :207, `run_driver_support_agent` :239, model via `get_driver_chat_model` :74, `DRIVER_AGENT_MODEL` override). System prompt is a hard-coded Python string (`GSUPPORT_SYSTEM_PROMPT`, lines ~30-80). Tools in `src/agents/tools/driver_tools.py` (`ALL_DRIVER_TOOLS` / `MODEL_DRIVER_TOOLS` near line 960): dispute context, traffic corroboration, telemetry, weather, policy query, `assess_statement_completeness` (:861, only checks >=20 chars + corroboration), `suggest_dispute_path`, `get_appeal_options`, `submit_driver_statement` (not exposed to model; "never auto-submit"). Intent shortcut layer: `src/services/driver_intent.py` and `handle_driver_intent_transition` (`driver_dispute_service.py:1137`). Sessions/messages persisted in `app.case_agent_sessions`, `app.case_agent_messages` (+ `app.agent_runtime_turns`).
6. **Analyst side**: case lands in the workspace queue (`/workspace` = `app/workplace/page.tsx` -> `components/views/cockpit-view.tsx`), tabs in `components/adjudication/*` (`overview-tab`, `driver-relay-tab`, `conversation-tab`, `workflow-tab`, `finalization-tab`, `maps-tab`, `driver-info-tab`). Dispute transcript from `GET /cases/{id}/dispute-dossier` (`routes.py:1293`). Analyst copilot: `components/copilot/analyst-copilot-panel.tsx` (57 KB) + `src/rag/cockpit_agent.py` (99 KB) via `POST /cases/{id}/agent-runtime/stream` (`src/api/agent_runtime_routes.py:25`, `src/services/agent_runtime.py`). Policy chat: `POST /policy/chat/stream` (`routes.py:664`).
7. **Post-review**: ADR-031 stepper `src/services/case_workflow.py` (statuses `report_issued ... completed`, events in `app.case_workflow_events`). Existing "UNDER_REVIEW" maps to `ingested|processing|ready|in_review|escalated|pending_analyst_review` (ADR-031 `docs/architecture/adr-031-gsm-workflow-roles.md`).

### 1.2 Existing "workflow" and "precedent" concepts (name collision risk)

PRD "workflow" (approved question plan per scenario) is NOT the repo's `workflow`:
- `app.workflow_questions/answers/minutes/action_requests` (migration `20261001220000_workflow_questions_and_minutes.sql`, `src/services/agent_workflow_service.py`, `workflow_repository.py`, `src/api/agent_workflow_routes.py`) = analyst-asks-driver interactive questions and case minutes.
- `app.solved_case_contexts` + `precedent_reuse_history` (migration `20261003090000_durable_solved_case_precedents.sql`; `src/services/jev_precedent_service.py`, `precedent_repository.py`; routes `routes.py:1356-1414` `match-precedent`, `precedents`, `apply-precedent`) = immutable, tenant-scoped solved-case traces with advisory similarity match (heuristic + OpenRouter decision model). This is the closest thing to PRD-K "thẻ kịch bản" but it is analyst-facing, created at adjudication publish, not anonymised, no lifecycle/approval.
- `app.precedent_workflows` = legacy PR #40 table.

### 1.3 How motivation is computed and stored today

- Rule-based + optional LLM narrative: `src/services/motivation_assessment_service.py` (`assess_driver_motivation` :126 sync fallback; `generate_motivation_assessment` :160 async, 5 s timeout, 300 s in-process cache, org-scoped). Output model `DriverMotivationAssessment` (`src/models/schemas.py:272`): `economic_incentive_reward`, `intent_profile` in {possible_accidental, possible_intentional_exploit, unclear_insufficient_data}, `natural_vietnamese_narrative`. Inputs are only `fare_delta_vnd`, surge/subsidy increments, mock-GPS counts, platform incident flag. No motive catalogue, no formula engine, no policy link.
- Attached **in memory** to `forensic_brief.motivation_assessment`: `case_service.get_case_detail` (`case_service.py:2637`, sync fallback) and `get_forensic_brief` (`:3808`, LLM). Not persisted. Also pushed into the analyst copilot text via `src/agents/nodes/motivation_assessment.py` (`cockpit_agent.py:1357,1707`). Redacted for drivers in `driver_tools.py:741`.
- Finalization tab uses it: `finalization-tab.tsx:46,148` via `workspaceMotivation()` (`src/webapp/lib/workspace-data.ts:7`), and only when a saved preliminary judgment exists.
- **Overview "Motivation: Not assessed" card** (`src/webapp/components/adjudication/overview-tab.tsx:161` and `:215-221`, copy `:44` EN / `:57` VI "Chưa đánh giá: chưa có đánh giá động cơ", label `workspace-messages.ts:4,6`) reads a different source: `caseDetail.cockpit_evidence.motivation_assessment || .motivation` via `readAssessment` (`overview-tab.tsx:~75-86`, which looks for `narrative|label|assessment|value`, NOT `natural_vietnamese_narrative`). `cockpit_evidence` is a jsonb column (`app.fraud_cases.cockpit_evidence`, migration `20261019090000_analyst_cockpit_evidence.sql`) only populated by `scripts/enrich_demo_data.py:1045-1052` for demo data. For real cases it is `{}` so the card always shows "Not assessed", even though the structured assessment already exists in `forensic_brief`. Willingness card is the same pattern (`workspaceWillingness` is a constant `unavailable`, `workspace-data.ts:13`).
- Tests: `tests/test_services/test_motivation_assessment.py`, `tests/unit/services/test_motivation_org_cache.py`, `src/webapp/tests/unit/components/motivation-assessment.test.tsx`, `workspace-repair.test.tsx`.

### 1.4 RAG / Qdrant / LLM

- LLM: `src/services/llm.py` (`resolve_llm_config`, `get_llm`; providers gemini|openai|openrouter, `LLM_MODEL` picks provider). `src/config.py:171` default `openrouter_model = "z-ai/glm-5.3-flash"`; local `.env` has `LLM_MODEL=openrouter` with a real OpenRouter key, `DRIVER_AGENT_MODEL` empty. LangChain `ChatOpenAI` against `https://openrouter.ai/api/v1`.
- Embeddings: `src/rag/embedder.py`: `OpenAIEmbedder` (text-embedding-3-small, 1536) and `GeminiEmbedder`, selected by `RAG_EMBEDDING_PROVIDER` (default `openai`, `create_embedder` :112). Local `.env`: `RAG_EMBEDDING_PROVIDER=openai` but `OPENAI_API_KEY` and `GEMINI_API_KEY` are placeholders ("your-o...", "your-g..."). Result: `embed_text` raises `RuntimeError("OpenAI embedding service is not configured")`; `QdrantPolicyStore.search` (`src/rag/store.py:310`) catches it, sets `last_search_error="embedding_unavailable"` and falls back to `_fallback_local_search` (`:428`), a keyword search over `data/processed/manifest.json` that fails closed (returns `[]`) for org-scoped queries. No embedding via OpenRouter exists.
- Store: `QdrantPolicyStore` (`store.py:73`), policy ingest `src/rag/ingest.py`, chunker, crawler, `db_tools.py`, `driver_tools.py` (`src/rag`). `app.policy_versions` (draft|published|retired, `0001_poc_core.sql:252`) and `app.policy_chunks` (pgvector `embedding`, `:265`) exist but hold the fixed POC policy corpus (Điều 12.2 etc.), not uploaded payout policies. Qdrant in `docker-compose.yml:37`.

### 1.5 Admin / org / roles / nav

- Roles: `src/api/auth.py:424 require_role`, `WORKFLOW_ORG_ROLES` (`:95`); DB `app.principal_roles` CHECK = analyst, fraud_analyst, senior_analyst, demo_operator, admin, manager, driver, reviewer, ops_director, marketplace_director (migration `20261020000000_gsm_workflow_roles_statuses.sql`). Mapping in ADR-031: KSGL = fraud_analyst/analyst/senior_analyst; VH/OPS = `manager` ("DB only, gap"); admin allowed everything. There is no VH (Vận hành) role wired into UI or routing, and no "KSGL lead" / "VH lead" / "PO" distinction.
- Routing: `src/services/role_routing.py` mirrored by `src/webapp/lib/role-routing.ts` (admin -> `/organization`, driver -> `/driver`, others -> `/workspace`); server guard `lib/route-authorization.ts` (`protectedArea`: test, driver, organization, workspace, workplace).
- Admin portal today: `/organization` -> `components/organization/organization-management.tsx` (members, invitations, role change; API `/account/users`, `/admin/invitations`, `/admin/organizations/{id}/bootstrap`). Analyst portal nav is a dropdown in `components/portal/portal-top-bar.tsx` with 3 tabs `cockpit|analytics|profile` (`workplace/page.tsx:14`, labels `lib/navigation-messages.ts`). There is no sidebar and no place for Knowledge / Config / Help queue pages.
- i18n: only two big files `src/webapp/messages/en.json`, `vi.json` (next-intl, key `driver.explain.*`), plus ad-hoc inline dictionaries (`workspace-messages.ts`, `navigation-messages.ts`, `overview-tab.tsx` `copy`).
- Audit: `app.audit_events` (append-only, hash chained, `result in accepted|denied|failed`, redacted_payload) used from `driver_dispute_service.py:611` and `agent_runtime.py:1102`; `app.case_workflow_events`; `app.review_actions`; `app.agent_runtime_turns`. Tracing helper `src/services/agent_tracing.py`.
- Notifications: none in product code (no table, no push/email service; grep only hits tester simulation). Case queue has claim/release leases (`app.review_leases`, `routes.py:484/503`).
- Tool plumbing: `src/services/tool_catalog.py` (`ToolCatalogEntry`), `tool_execution.py`, `src/agents/tools/runtime_boundary.py`, `src/models/tool_contracts.py`: a canonical tool catalog with permissions/schemas that new agent tools can register in.
- Feature flags / config: only env-based `Settings` in `src/config.py` (e.g. `driver_formatter_enabled`, `fraud_classifier_enabled`). No DB-backed runtime config, no kill switch.

### 1.6 DB and migration convention

- Dir `db/migrations/*.sql`, rollbacks in `db/rollbacks/<same-name>.down.sql` (optional; several migrations only carry a trailing `-- Rollback:` comment instead). 36 migrations; baseline `0001_poc_core.sql`, newest `20261020000000_gsm_workflow_roles_statuses.sql`.
- Naming: `YYYYMMDDHHMMSS_snake_case.sql`, lexicographic order. New files must sort after `20261020000000`.
- Runner: `scripts/migrate_postgres.py` (`apply_migrations` :123; wrapper `scripts/migrate.sh`). Tracks applied files in `public.schema_migrations(version text pk, applied_at)`, executes each file in one `cur.execute`, and on an "already exists/duplicate" error marks the file as applied anyway. So migrations must be additive and idempotent: `create table if not exists`, `add column if not exists`, `create index if not exists`, `drop constraint if exists` + re-add, `drop trigger if exists`. Everything lives in schema `app`. Tenant tables carry `organization_id uuid references app.organizations(id)` and RLS is enabled on newer tables (`20261003090000`, `20261002070000`); append-only tables use `app.reject_mutation()` triggers.
- Related guards: `tests/unit/test_db_schema_parity.py`, `tests/integration/test_db_schema_parity_integration.py`; seeds `db/seed_cloud.sql`, `scripts/enrich_demo_data.py`, `scripts/seed/`.
- Existing tables relevant to PRDs: `fraud_cases` (status/dispute_status/dispute_deadline/cockpit_evidence/workflow_draft), `driver_submissions`, `driver_statement_drafts`, `driver_confirmation_tokens`, `case_agent_sessions/messages`, `agent_runtime_turns`, `adjudications`, `preliminary_judgments`, `solved_case_contexts`, `precedent_reuse_history`, `policy_versions/chunks`, `workflow_*`, `audit_events`, `case_workflow_events`, `principals/principal_roles/organizations`.
- Not present anywhere: any table for statement versions, assessment rounds, help requests, knowledge objects (motive/behavior/scenario/workflow), parameter catalogue, agent config / config history, proposals queue, monitoring reports, notifications.

### 1.7 Tests layout

Backend: `tests/unit/{agents,api,services,rag,models,scripts,...}` (pytest), `tests/integration/`, `tests/e2e/{backend,browser}`; frontend: `src/webapp/tests/unit/{components,lib,app,copilot}` (vitest), `tests/e2e/browser` (Playwright). Guide `docs/testing/README.md` (RED/GREEN, auto-discovery, `.venv/bin/python -m pytest`). Existing analogues to copy: `tests/unit/agents/test_driver_tools.py`, `test_driver_agent_*`, `tests/integration/test_driver_confirmations_483.py`, `tests/unit/rag/test_embedding_*`, `src/webapp/tests/unit/driver-accept-reject-483.test.tsx`.

---

## 2. Requirement matrix: PRD-A (driver explanation agent)

| Req | Summary | Status | Files / notes |
|---|---|---|---|
| US1 form per reason | Fixed question set per reason, typed fields (text, time, place, single choice, amount, photo, ticket code), required flag | **missing** | Wizard is hard-coded: `driver-explain-flow.tsx:9-10`. No question-set storage. Only one free-text + one evidence text. |
| US1 dynamic K questions | Up to K "ask-first" questions from approved workflow, always optional, never reveal origin | **missing** | Needs knowledge store (PRD-K US3/US6) + K config. |
| US1 form_version, workflow_id+version saved | Versioned form snapshot | **missing** | No column/table. |
| US1 reasons without form (resigned, wants to meet VH) | Free text + photo only | **partial** | Current flow always shows same text form; `Other` reason roughly equals this. |
| US1 block submit on missing required, highlight | | **partial** | Only min-20-chars check on detail (`driver-explain-flow.tsx:30-44`). |
| US1 draft by violation_id, SLA keeps running | | **exists** | `app.driver_statement_drafts`, `PUT/GET statement-draft` (`routes.py:1240/1258`), `resume-draft-banner.tsx`. Form-level answers are not stored structurally (free `draft` dict). |
| US1 no telemetry shown on form | | **exists** | Form shows none. |
| US2 statement_v1 immutable, supplements as versions | | **missing** | `driver_submissions` single row, no version column; insert likely failing silently (see 1.1 step 4). |
| US2 SLA timestamp = submit time; TX sees "Đang kiểm tra giải trình" | | **partial** | `dispute_deadline` exists; submit time stored in `driver_submissions.received_at` (if insert works). UI text not present. |
| US2 investigate: identify_behavior, list_motives/compute_motive, match_scenario | | **missing** | No tools; motive code is the single heuristic in `motivation_assessment_service.py`. |
| US2 `novel_scenario` flag | | **missing** | No such field anywhere. |
| US2 read <=TOP_K scenario cards + TX history | | **partial** | Analyst-side precedent retrieval exists (`jev_precedent_service.py`, `solved_case_contexts`), driver agent has `list_my_cases` etc. but not as memory. Not wired to driver agent. |
| US2 four assessment states (đợt 1/đợt 2) | Đủ điều kiện / Không đủ / Cần bổ sung / Thiếu thông tin nội bộ | **missing** | `assess_statement_completeness` (`driver_tools.py:861`) is a length check. No assessment-round table. |
| US2 plan of questions (hidden from TX), dynamic, logged | | **missing** | |
| US2 TX sees no agent result; shows "Đã gửi giải trình, VH sẽ phản hồi trong Y giờ" | | **partial** | Canned reply in `submit_statement_with_token`; no Y config. |
| US2 question loop (think-tool-observe-ask 1 q/turn) with N_max | | **partial** | `driver_agent.py` is ReAct LangGraph chat, free-form, no turn counter, no plan, no stop condition. |
| US2 opening summary of statement 1 | | **missing** | |
| US2 `statement_changed` flag, re-match on new reason | | **missing** | |
| US2 `ai_inconclusive` on N >= N_max | | **missing** | Only mentioned in PRD text; `grep` finds nothing in src. |
| US2 close-out summary, Confirm/Edit (max SỐ_LẦN_SỬA), then round 2 -> UNDER_REVIEW | | **missing** | Existing flow goes straight to `driver_disputed` + `analyst_escalated`. Confirmation-token step (483) is a good base for "Xác nhận". |
| US2 chat text + photo + ticket code attachments | | **partial** | Chat text exists; photos/ticket codes not structured. |
| US2 "Kết thúc" any time; 2 consecutive non-answers -> offer end | | **missing** | Intent detection partly in `driver_intent.py` (escalate/accept). |
| US2 draft T minutes, auto-submit, `session_interrupted` | | **missing** | Drafts exist, no TTL job/worker, no flag. Background workers exist for telemetry queue (`telemetry_queue_worker.py`) as pattern. |
| US2 asking rules (polite, no fine, no other TX, 1 q per contradiction) | | **partial** | Prompt rules in `GSUPPORT_SYSTEM_PROMPT` (`driver_agent.py`), formatter `answer_formatter.py` + `prompts/answer_formatter_driver.md`, `guardrails.py` is for telemetry only (not output checks). No post-generation check. |
| US3 help conditions (novel, low confidence after M turns, evidence without tool, conflicting internal sources, accident/sensitive) | | **missing** | |
| US3 `request_help` tool + queue (top of VH queue, notify) | | **missing** | No queue, no notification system. |
| US3 waiting message, agent keeps talking, VH never chats with TX | | **missing** | |
| US3 VH answers (agent uses it, can state facts not who) | | **missing** | |
| US3 SLA expiry fallback, cap per session, `asked_for_help_skipped` | | **missing** | |
| US3 help log (time, condition, responder, content, wait) | | **missing** | `audit_events` can store the audit part. |
| US4 assessment history per round on violation page | | **missing** | Cockpit tabs: `overview-tab.tsx`, `driver-relay-tab.tsx` (transcript via dispute-dossier). No rounds. |
| US4 transcript + statement versions + flags display | | **partial** | Transcript yes (`driver-relay-tab`, `conversation-tab`); versions and flags no. |
| US4 provenance of suggestion (scenario/behavior/motive/workflow code+version, <=3 similar cards, help requests) | | **missing** | Closest: workflow trace + precedent match (`routes.py:1338,1356`, `workflow-tab.tsx`). |
| US4 suggestion block (reason code, confidence, motive, suggested questions, turns used / N_max) | | **partial** | `preliminary_judgments` + classifier advisory (`classifier_advisory.py`, `/cases/{id}/preliminary-assessment` `routes.py:538`) give a suggestion, not tied to rounds. |
| US4 structured VH feedback Agree/Disagree + error types + free text | | **missing** | `adjudications`/`preliminary_judgments` hold analyst verdict but no AI-error taxonomy. |
| US4 closed case -> draft scenario card | | **missing** | `solved_case_contexts` is created at publish but not a PRD-K draft card. |
| US5 session memory | Plan, answers, tool results, help answers; dies at close, saved to assessment history | **partial** | `case_agent_sessions/messages` + `agent_runtime_turns` persist chat; `case_context.py`/`context_budget.py` hold context. No plan or tool-result memory. |
| US5 TX history layer (own past statements, retention THỜI_GIAN_LƯU, DPIA) | | **missing** | `list_my_cases` tool lists cases only. No retention policy. |
| US5 never mention other TX/case | | **partial** | Prompt-level only. |
| US6 tools: identify_behavior | | **missing** | `inspect_trip_telemetry`, `match_trip_telemetry`, `forensic_baseline.py`, `feature_engineering.py`, fraud classifier `src/services/fraud_classifier/` give signals to build on. |
| US6 tools: list_motives / compute_motive | | **missing** | Only `assess_driver_motivation` (1 hard-coded motive). |
| US6 tools: match_scenario / get_workflow | | **missing** | `match_precedent` is analyst-only and heuristic. |
| US6 tools: request_help / propose_knowledge | | **missing** | |
| US6 read published only, log code+version | | **missing** | No lifecycle. Tool call tracing: `agent_tracing.py`, `tool_execution.py` give logging hook. |
| US6 formula errors -> "không tính được" | | **missing** | |
| US6 motive value hidden from TX | | **exists (policy)** | `driver_tools.py:741` redacts `motivation_assessment` from driver tools; keep when adding. |
| General: audit of every retrieval/tool/help/approval | | **partial** | `audit_events` infrastructure + `agent_tracing.py` exist; PRD events not emitted. |
| General: bilingual AI output for VH (vi+en) | | **partial** | `answer_formatter.py` / `prompts/answer_formatter_vi.md`; bilingual convention in UI via vi/en dicts. |
| 8.1 agent card | | **missing** | Doc only. |
| 8.2 versioned system instructions with eval gate | | **partial** | Prompt version for analyst prompt: `src/agents/graph.py:48 get_system_prompt_version`; driver prompt is an inline string, unversioned. |
| 8.2 structured output schema, reject malformed | | **missing** | |
| 8.3 model recorded per session | | **partial** | `app.agent_runtime_turns`/tracing may log model; not per explanation session. Model config via `llm.py`, `DRIVER_AGENT_MODEL`. |
| 8.3 numbers computed by system not model | | **partial** | Motivation reward is computed deterministically (`motivation_assessment_service.py`); LLM only narrates. |
| 8.4 reasoning loop table | | **missing** | |
| 8.6 prompt injection flagged | | **partial** | `copilot_decision_service.py` classifies `adversarial_attack` for analyst copilot; nothing for driver text. |
| 8.6 per-message output check (no fine, verdict, thresholds, motive, other TX) | | **partial** | `answer_formatter.py` driver formatter + `driver_formatter_enabled`; no hard validator. |
| 8.6 accident/safety -> help | | **missing** | |
| 8.7 golden-case eval, simulated TX personas | | **partial** | `tests/unit/eval`, `eval/`, `scripts/benchmark/`, `driver_scenario_runner.py`, tester simulation (`src/models/test_simulation.py`, `/test` console) are reusable. |
| 8.8 monitoring (latency, cost, error rates, weekly drift), auto fallback to form | | **partial** | `observability_metrics.py`, `GET /observability/summary` (`routes.py:106`). Fallback to form on model failure is not implemented; note the form is the current default, so degraded mode is trivial. |

## 3. Requirement matrix: PRD-K (knowledge base and agent config)

| Req | Summary | Status | Files / notes |
|---|---|---|---|
| US1 policy intake (docx/pdf/xlsx upload or paste, metadata, effective dates, region, service, contract type) | | **missing** | `src/rag/crawler.py`, `chunker.py`, `ingest.py` ingest fixed policy docs; MarkItDown MCP exists in `.agents/mcp_config.json`. No upload API, no storage. `app.policy_versions` could hold metadata but has `action_matrix` not-null and is a fixed POC policy. |
| US1 extract payout rules with source citation | | **exists (S-P)** | `policy_analysis_service.py`: LLM extraction, items without a verbatim citation are dropped (ADR-040). |
| US1 propose motives / behaviors / reasons; map to existing store (reuse/extend/new + similarity) | | **exists (S-P)** | Token-overlap similarity vs published kb (embeddings unavailable); proposals `source=policy_analysis`. |
| US1 "cần tham số" -> request queue; never invent params; thresholds left as `<NGƯỠNG>` | | **missing** | |
| US1 analysis report, all drafts, notify on done, policy text treated as data | | **missing** | |
| US2 single review queue (sources: policy, help answers, case cards, monitoring) with filters | | **missing** | |
| US2 side-by-side compare, Accept/Edit/Reject(+reason), bulk accept >= threshold, feedback recorded | | **missing** | UI pattern base: `workflow-tab.tsx`, `case-queue-filters.tsx`, `finalization-tab.tsx`. |
| US2 accept/edit -> "Sẵn sàng kiểm thử" | | **missing** | |
| US3 Studio: CRUD+clone+retire for 4 object types, code/version/author/scope | | **missing** | |
| US3 formulas (Excel-like, sandboxed code, drag-drop) -> one expression form | | **missing** | No expression engine in repo (grep finds none). Recommend a safe AST evaluator over parameter catalogue; PRD Q8 says decide Excel vs code vs UI first. |
| US3 case parameter catalogue (name, desc, unit, source, owner, latency) | | **missing** | Candidate sources already in code: `src/services/feature_engineering.py`, `fare_economics_from_record`, `_facts` in `motivation_assessment_service.py:60`, `app.feature_sets`, `app.fare_quotes`, `app.platform_incidents`, telemetry/trip tables. |
| US3 validation on edit (syntax, unknown param, div by 0, units) | | **missing** | |
| US3 preview on real closed cases | | **missing** | Closed cases are in `adjudications`, `solved_case_contexts`. |
| US3 workflow can only call tools in the tool catalogue; no penalties/remedies | | **partial** | `tool_catalog.py` is a reusable registry; new KSGL-facing tools need catalogue entries. |
| US3 Excel import with duplicate/line errors | | **missing** | PRD Q9. |
| US3 permission to see formulas/thresholds, audit of view/edit/release | | **missing** | RBAC primitives exist (`require_role`, `access_control.py`); no per-object permission. |
| US4 forward case to top of VH queue labelled "AI cần hỗ trợ" with countdown | | **missing** | Queue = `GET /cases` + `case-queue.ts` / `case-queue-filters.tsx`; priority fields `priority_tier/priority_score` on `fraud_cases` (see `case_service.py:1221`). |
| US4 notify VH on shift/region (portal + KÊNH_THÔNG_BÁO) | | **missing** | No notification infra; no shift/region assignment model (check `app.case_assignment_history`, `review_leases`). |
| US4 help card contents (summary, transcript, stuck point, trigger, facts, scenario/workflow, 2-3 options) | | **missing** | |
| US4 claim/lock/transfer | | **partial** | Claim/release leases exist for cases (`routes.py:484/503`, `app.review_leases`, `docs/CASE_REVIEW_LOCK_GUIDE.md`); reuse for help cards. |
| US4 VH reply 4 ways (option, instruction, hand-checked result, request end) | | **missing** | |
| US4 expiry -> "Quá hạn", ceiling per shift, `asked_for_help_skipped` | | **missing** | |
| US4 reply -> draft knowledge proposal into US2 queue | | **missing** | |
| US4 log of each help request | | **missing** | |
| US5 auto-draft scenario card on REPORT_CONFIRMED / COMPLETED / closed-no-violation | | **partial** | Status machine and `case_workflow_events` (`case_workflow.py`) give the trigger point; `solved_case_contexts` is a precedent snapshot with a different trigger (analyst publish) and no anonymisation. |
| US5 card structure (rule, contract, region, motive, behavior, statement/will, helpful Q+tools, VH conclusion, VH feedback) | | **missing** | `workflow_trace` jsonb in `solved_case_contexts` is the nearest content source. |
| US5 map to existing scenario (reuse/extend/new); anonymise (no name/phone/plate/trip id/location) | | **missing** | Needs PII scrubber. |
| US5 card -> "Cần xem lại" if verdict overturned on complaint; only published cards retrievable | | **missing** | No complaint/appeal-overturn event model found. |
| US6 lifecycle Nháp -> Sẵn sàng kiểm thử -> Chạy thử -> Đã phát hành -> Ngưng for all objects | | **missing** | Only analogue: `policy_versions.status draft|published|retired`. |
| US6 replay on <SỐ_CASE_THỬ> closed cases, metrics (match VH conclusion, changed scenario count, est. turns, "không tra được" count) | | **missing** | Replay harness base: `scripts/benchmark/`, `src/models/test_simulation.py`, `src/services/test_simulation_runner.py`, `driver_scenario_runner.py`, `app.benchmark_*`, `evaluation_runs`. |
| US6 pass gate with override reason | | **missing** | |
| US6 4-eyes release (approver != author, role VAI_TRÒ_DUYỆT), version stores author/approver/date/reason/replay | | **missing** | Base: `case_workflow` role-transition pattern + `app.case_workflow_events` append-only; roles `reviewer` etc. exist (ADR-031) but are case-workflow roles. |
| US6 publish applies to new sessions only; revoke in 1 action; retire takes effect immediately (even running sessions -> default questions) | | **missing** | |
| US7 config catalogue (N_max/rule, K/rule, T global, help SLA/ceiling/max per session per region, similarity & confidence thresholds/rule, scenario-card memory toggle, kill switch/rule or global) | | **missing** | `Settings` env only (`src/config.py`). Need DB-backed config + audit + history/revert + bounds. |
| US7 min/max bounds set by PO; reject out-of-range | | **missing** | |
| US7 effective on new sessions; kill switch immediate | | **missing** | Safe default exists: today's explain flow is form-only, so "kill switch -> form + default questions" = current behaviour. |
| US7 change log (who, old/new, reason), revert | | **missing** | |
| US7 30-day metrics panel per rule | | **missing** | Needs data from sessions (does not exist yet). |
| US8 monitoring agent: scheduled weekly, read-only, detections, tool proposals, same-day alerts for asking-rule violations, dedupe | | **missing** | No scheduler in repo (only telemetry queue worker, `preset_batch_scheduler` for tester). Could be a script + cron/Railway job initially. |
| 8.1 three agents (analysis, driver, monitoring) | | **missing** | Only driver GSupport and analyst copilot exist. |
| 8.2 versioned instructions, structured JSON output | | **missing** | |
| 8.3 formula engine computes, model reads result | | **partial** | See US3. |
| 8.4 tools: extract_payout_rules, search_knowledge, list_parameters, replay_cases, propose_knowledge (+ driver tools) | | **missing** | |
| 8.5 memory layers, proposal queue, TX history | | **missing** | |
| 8.6 injection flag, output check, permission, anonymised cards, no automated decisions | | **partial** | Redaction patterns exist (`driver_tools.py:741`, `model_input_projection.py`, `answer_formatter.py`); need dedicated validators. |
| 8.7 golden cases per scenario (SỐ_CASE_VÀNG) | | **missing** | `eval/`, `tests/eval`, benchmark corpus as seed (`.agents/rules/benchmark.md`). |
| 8.8 monitoring (latency, cost, tool errors, schema errors, drift alerts, fallback) | | **partial** | See PRD-A 8.8. |
| 8.9 audit of analysis/tool/proposal/approval/publish/revoke/config/help with versions and model | | **partial** | `audit_events` (append-only, hash chained, requires `request_id`, `organization_id`) is a good sink; `result` limited to accepted/denied/failed. |
| Overview card "Motivation: Not assessed" -> structured motivation assessment | Show structured assessment in the Overview card | **partial** | Data exists in `forensic_brief.motivation_assessment` (see 1.3) but the card reads `cockpit_evidence`. Cheapest fix: in `overview-tab.tsx:161` fall back to `caseDetail.forensic_brief?.motivation_assessment` and map `natural_vietnamese_narrative`/`intent_profile`/`economic_incentive_reward` into `readAssessment`'s shape; no migration. Fuller fix later: replace heuristic with PRD motive catalogue (`list_motives`/`compute_motive`) and persist per case. |
| Admin/KSGL UI: Knowledge, Review queue, Config, Help queue pages and nav | | **missing** | Admin = `/organization` only; analyst portal = 3-tab dropdown in `portal-top-bar.tsx`. New route guard entries needed in `lib/route-authorization.ts` and `src/services/role_routing.py` / `role-routing.ts`. |
| Roles KSGL lead / VH / VH lead / PO | | **partial** | See 1.5: VH has no role; `manager` is "DB only, gap". Decision needed (ADR). |

---

## 4. Reusable foundations

- `app.audit_events` append-only hash chain + `_record_audit_entry` (`driver_dispute_service.py:560`) and `agent_tracing.py` for the PRD audit requirement.
- Confirmation-token + draft machinery (`driver_confirmation_tokens`, `driver_statement_drafts`, `/confirmations`, `/statement`) for "TX xác nhận bản tổng hợp" and draft/T-minutes work.
- `driver_agent.py` LangGraph ReAct runtime, `driver_tools.py` tool style, `tool_catalog.py` / `tool_execution.py` / `runtime_boundary.py` tool registry and boundary tests (`tests/unit/agents/test_driver_tool_allowlist_b12.py`, `test_runtime_tool_boundary.py`).
- `llm.py` provider layer (OpenRouter `z-ai/glm-5.3-flash` live key available locally), `DRIVER_AGENT_MODEL` override, `copilot_decision_service.py` (intent/adversarial classification) and `answer_formatter.py` (driver output filter) as guardrail starting points.
- `motivation_assessment_service.py` (deterministic economics + narrative with timeout/cache) as seed for `compute_motive`; `DriverMotivationAssessment` schema (`models/schemas.py:272`) and `forensic_brief` plumbing already reach the UI.
- Precedent stack (`solved_case_contexts`, `jev_precedent_service.py`, `workflow_trace`, `routes.py:1338-1414`, `workflow-tab.tsx`) as raw material for scenario cards and for replay corpora.
- Case claim/lease and queue UI (`review_leases`, `case-queue*.ts(x)`, `routes.py:484/503`) for the help-request queue.
- Role/permission helpers (`require_role`, ADR-031 roles, `case_workflow.py` compare-and-set transitions + `case_workflow_events`) for 4-eyes release.
- `QdrantPolicyStore` + local fallback, pgvector column on `policy_chunks`, docker Qdrant.
- Test/eval infra: tester simulation (`src/models/test_simulation.py`, `/test` console), `driver_scenario_runner.py`, benchmark scripts, `tests/unit/eval`.
- Frontend: shadcn UI kit, cyan tokens, `SectionCard`/`MetricCard`/`EmptyState` in `components/cockpit`, next-intl vi/en, driver chat components in `components/driver/chat/*`.

## 5. Risks and constraints

1. **No usable embeddings locally**: `RAG_EMBEDDING_PROVIDER=openai` with placeholder OpenAI/Gemini keys; search silently degrades to keyword fallback that returns `[]` for org-scoped queries. "Map to existing knowledge / similarity / TOP_K cards / `search_knowledge`" cannot rely on vectors. Options: (a) similarity by deterministic features + trigram/keyword (Postgres `pg_trgm` or simple token overlap) with a clean `Similarity` interface, (b) add an OpenRouter embeddings provider to `embedder.py`, (c) use the LLM to rank a short candidate list. Must work offline for tests (mock). Do not store vectors in a new column until the dimension/provider is decided.
2. **Naming collisions**: "workflow" (PRD) vs `workflow_questions/minutes/action_requests` and `/cases/{id}/workflow` (ADR-031 stepper); "precedent" vs "scenario card"; "policy" (`policy_versions`, fixed POC corpus) vs payout policy documents. Use distinct names (e.g. `knowledge_*`, `kb_workflow`, `agent_config`) and a CONTEXT.md/ADR entry.
3. **Migration conventions** (see 1.6): idempotent, additive, schema `app`, timestamp > `20261020000000`, `organization_id` + RLS, optional `.down.sql` in `db/rollbacks/`. The runner swallows "already exists" errors, so a half-failed migration can be marked applied; keep each migration small and re-runnable. Do not edit existing migration files. The shared local DB (localhost:15432) is used by parallel sessions: prefer new tables, avoid altering shared constraints; if you must touch `fraud_cases_status_check` or `principal_roles_role_check`, re-state the full current lists (see `20261020000000`) to avoid dropping statuses.
4. **Status model**: PRD uses UNDER_REVIEW etc.; code statuses are the ADR-031 set. Prefer NOT adding new `fraud_cases.status` values; track explanation session state in a new table and map "need explanation" via existing `evidence_requested`/`driver_disputed`.
5. **`driver_submissions` silent failure** (status `'submitted'` vs CHECK) means current statements may not reach the table; confirm in a DB before building statement versioning on it. A new `driver_statement_versions` table avoids depending on it.
6. **Role gaps**: no VH, KSGL lead, VH lead, PO, or approver role; `/organization` is admin-only; nav has no space for new pages. Needs an ADR (ADR-031 follow-up) before building review/4-eyes/config permissions. Quick pragmatic mapping: KSGL = analyst/fraud_analyst/senior_analyst; VH = `manager` (+`reviewer`); approver = `senior_analyst`/`admin`; PO bounds = static code constants.
7. **Prompt/behaviour regression risk**: the existing driver chat (`driver-chat-view.tsx`, 30 KB, many tests: `driver-accept-reject-483.test.tsx`, `tests/unit/api/test_driver_case_chat_ownership.py`, `test_driver_agent_*`) is shared by parallel sessions. Add the explanation agent behind a flag/kill switch and a new route set; do not rewrite the chat view.
8. **LLM cost/latency and model quality**: `glm-5.3-flash` via OpenRouter has no structured-output guarantee; need JSON-schema validation + retry and deterministic fallbacks; every PRD number (motive value, thresholds) must be computed in code.
9. **PII / DPIA**: card anonymisation, TX history retention, and "no training on case data" need Legal; model hosting region is open (PRD-A Q5). Scope tests to anonymiser correctness only.
10. **Scheduling and notifications do not exist**: US8 weekly agent, T-minute auto-submit, help SLA expiry, and VH notifications all need a scheduler/worker or lazy evaluation (compute-on-read) and a notification channel (start with in-portal polling/SSE; `GET /cases/{id}/stream` at `routes.py:631` shows an SSE pattern).
11. **Secret hygiene / test accounts**: Clerk dev accounts only (driver/analyst/admin); there is no VH test login, so E2E of the VH reply path needs an analyst account standing in.
12. **Prod data / deployment out of scope**; seeds: update `scripts/enrich_demo_data.py` and not `db/seed_cloud.sql` (2.5 MB generated).

## 6. Suggested slice cut

Dependencies in brackets. Each slice is shippable behind a flag, defaults to current behaviour.

- **S0 Quick win (no dependencies)**: Overview Motivation card reads `forensic_brief.motivation_assessment` (fix `overview-tab.tsx:161`, `readAssessment` mapping, update `motivation-assessment.test.tsx` / `workspace-repair.test.tsx`). Optionally persist per-case assessment later (S3).
- **S1 Foundations**: ADR/CONTEXT (names, roles, statuses), migration #1 (`agent_config` + `agent_config_history`, bounds table or code constants, `kill switch` row), config service + `GET/PUT /admin/agent-config` with audit, admin page `Cấu hình AI` under nav, role mapping. (PRD-K US7; unblocks N_max/K/T everywhere). [none]
- **S2 Knowledge store core**: migration #2 (`kb_parameter`, `kb_motive`, `kb_behavior`, `kb_scenario`, `kb_workflow`, shared version/lifecycle columns `Nháp..Ngưng`, author/approver, scope, `kb_proposal` queue, `kb_audit` via `audit_events`), safe expression evaluator over parameter catalogue, CRUD API, minimal Studio UI (Excel-style formula only), 4-eyes publish with replay stub, revoke/retire. (PRD-K US3, US6 minus replay metrics). [S1 for roles/config, ADR]
- **S3 Driver agent v2 core (backend)**: migration #3 (`explain_session`, `statement_version`, `assessment_round`, `explain_turn`, flags columns: novel_scenario, statement_changed, ai_inconclusive, session_interrupted, asked_for_help, asked_for_help_skipped), tools `identify_behavior`, `list_motives`, `compute_motive`, `match_scenario`, `get_workflow` (read published only, log code+version), bounded loop with N_max, 4 assessment states, structured-output validation, output guard, fallback to default question set, kill switch. Reuse `driver_agent.py` runtime in a new module, not editing GSupport chat. (PRD-A US2, US5 session, US6, section 8). [S1, S2]
- **S4 Driver app UX**: dynamic form (typed fields per reason, K dynamic questions, form_version), Confirm/Edit summary, "Kết thúc", T-draft/auto-submit (lazy on read plus a sweeper), new states copy. (PRD-A US1, US2 UI). [S2 for questions; S3 for loop; can ship static question sets first]
- **S5 Help loop**: `help_request` table, `request_help` tool, VH help queue page + card + claim/reply, SLA expiry (lazy), ceiling, notifications via portal polling, help answers -> proposals. (PRD-A US3, PRD-K US4). [S2 (proposals), S3]
- **S6 Cockpit provenance and feedback**: assessment rounds, flags, statement versions, provenance, suggestion block, structured VH feedback (Agree/Disagree + error types) in Overview/Relay/Finalization tabs. (PRD-A US4). [S3]
- **S7 Policy analysis agent + review queue**: policy upload, rule extraction with citations, proposals with reuse/extend/new (similarity without embeddings first), review queue with Accept/Edit/Reject, bulk accept. (PRD-K US1, US2). [S2; embeddings decision]
- **S8 Scenario cards from closed cases**: trigger on REPORT_CONFIRMED/COMPLETED/closed, anonymiser, card -> proposals, "Cần xem lại" on overturn. (PRD-K US5, PRD-A US4 tail). [S2, S6, S7 mapping]
- **S9 Replay, gate, evaluation**: `replay_cases` on closed cases, pass gate with override reason, golden cases, metrics panel on config (30-day), eval gate on instruction/model change. (PRD-K US6 full, US7 metrics, 8.7). [S2, S3, S8 for corpus]
- **S10 Monitoring agent**: weekly scheduled job reading sessions/help/feedback, detections, tool proposals with dedupe, same-day asking-rule alerts, drift alerts. (PRD-K US8, 8.8). [S3, S5, S6]
- **S11 TX history/memory with DPIA gating** (PRD-A US5 layer 2): last, feature-flagged off by default. [S3]

Open decisions needed before S1/S2: role mapping for VH/KSGL lead/PO; formula authoring mode for pilot (PRD-K Q8); source of case parameter catalogue (Q7); embedding strategy; notification channel (Q2).
