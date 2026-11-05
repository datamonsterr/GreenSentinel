# ADR-009: Precedent Workflow Mining, Jev Similarity Engine, and Post-Adjudication Workflow Synthesis

## Release authority and runtime boundary

The strict Phase 1 [PRD](../ba/PRD.md), adopted **2026-09-30 by @datamonsterr**, governs release scope. Recommendations and corroboration wait for **authorized analyst confirmation with written rationale**. No automatic dismissal is approved. All adverse sanctions, including warnings, require confirmation and rationale; blocking guardrails keep adverse sanctions blocked. Driver UI/mobile and appeal expansion are **deferred**.

[PR #40](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/40) is **MERGED historical runtime divergence**, commit `586caec05ddb7626a1f47066b55154e74d245cc0`, not accepted release scope. That baseline let traffic corroboration write `auto_dismissed` and return `needs_analyst_review=False`. Accepted upstream [PR #93](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/93), merged on 2026-10-02 at `16c1ad6bdc910badbe852418bc5de5b456759156`, removes the new automatic-dismissal transition and returns a recommendation awaiting analyst review. Legacy `auto_dismissed` records remain readable; this preserves history rather than authorizing a new autonomous outcome. [Issue #73](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/73) remains open for its independently accepted full DoD; merging #60/#86 does not close it by inference. Existing driver interfaces remain inherited baseline and do not approve driver/mobile/appeal expansion. This documentation correction changes no runtime and claims no separate hosted or database conformance proof.

## Status

Historical V2 decision; conflicting release authorization superseded by the strict Phase 1 PRD adopted 2026-09-30 by @datamonsterr. Inherited precedent interfaces are baseline; new driver/mobile and appeal expansion are deferred.

## Context

The historical GreenSM POC v2 design ([ADR-008](adr-008-poc-v2-async-driver-agent-and-a2a-collaboration.md)) paired `/driver/dispute/[caseId]` with analyst review in `/workplace`. Driver UI/mobile and appeal expansion remain deferred under the approved release; inherited interfaces do not change that boundary.

In high-volume ride-hailing operations, many contested cases share identical root causes across different drivers:
1. **Recurring Road Conditions:** Traffic gridlocks on major Hanoi commuter corridors (e.g. Kim Ma, Nguyen Chi Thanh, Ring Road 3) during peak hours.
2. **Infrastructure Anomalies:** GPS signal dropouts in underground parking basements (e.g. Vincom Royal City, Times City) or dense urban canyons.
3. **Operational Precedents:** Vehicle EV battery sudden depletion or passenger no-show with cancellation fee disputes.

When a Fraud Analyst investigates a case, they perform an investigation procedure: calling specific tools (corroborating traffic, querying policy, checking telemetry), reviewing human actions, and applying policy leeways. Repeating these investigative steps manually for identical situations creates cognitive fatigue and inflates dispute resolution MTTR.

To solve this, we need:
1. A matcher to rank situation similarity with a raw uncalibrated relevance score between incoming disputes and past adjudicated cases.
2. A structured JSON schema to record the complete execution workflow (tools called, human actions, policy citations, driver responses, final decision).
3. A post-adjudication synthesis view in the Cockpit displaying the full workflow and publishing it to a searchable Precedent Bank.

---

## Decision

Retain the historical **Precedent Workflow Mining & Jev Similarity Engine** design as implementation context. The sections below describe inherited/proposed structures, not newly authorized schema or product work. Advisory reuse always waits for analyst confirmation with written rationale.

### 1. Jev Precedent Similarity Engine

- **Model Specification:** We employ the TypeSafe Jev decision model (`~typesafe/jev-latest` hosted on OpenRouter via `OPENROUTER_API_KEY`).
- **Structured Schema Conformance:** Jev evaluates dispute context against indexed precedents, returning:
  - `similarity_score`: Raw uncalibrated relevance float `[0.0, 1.0]`, not calibrated fraud confidence or probability. It ranks contextual matches and carries model/fallback provenance; it is not a verdict.
  - `matched_precedent_case_id`: UUID of the top-matching past case.
  - `matching_factors`: List of matching evidence vectors (e.g. `["Same violation ERR-02", "Corroborated corridor congestion < 5 km/h", "Identical Kim Ma location"]`).
  - `recommended_procedure`: Step-by-step tool and verification sequence (e.g. `["corroborate_traffic_conditions", "query_driver_policy", "request_analyst_confirmation"]`).
  - `precedent_verdict`: Terminal verdict of the matched precedent (`exonerated`, `warning`, `penalty_applied`).
  - `confidence_rationale`: Transparent natural language explanation.
- **Heuristic fallback (inherited design):** Provider failures may use a deterministic matcher with explicit fallback provenance. Its relevance score has different origins from the model score; neither has demonstrated calibration. Failed retrieval/matching must remain visible. No operational uptime or equivalent accuracy guarantee is established.

Top-k ROUTE alternatives are optional pending product scope. They are distinct from RAG retrieval top-k, which limits retrieved policy/precedent context (see [`store.search`](../../src/rag/store.py)); neither controls classifier confidence or the number of analyst outcomes.

### 2. Standardized Workflow Trace Schema

We define the `WorkflowTrace` schema capturing the end-to-end investigation lifecycle:

```json
{
  "agent_tools_called": [
    {
      "tool_name": "corroborate_traffic_conditions",
      "input_summary": "case_id=018f2f4e-..., corridor=Kim Ma",
      "output_summary": "speed=1.08 km/h, ratio=2.2x, congestion=heavy",
      "executed_at": "2026-09-26T14:14:20Z",
      "status": "success"
    }
  ],
  "human_actions_performed": [
    {
      "actor_role": "driver",
      "action_type": "dispute_statement",
      "summary": "Driver reported severe traffic jam on Kim Ma street",
      "timestamp": "2026-09-26T14:14:15Z"
    },
    {
      "actor_role": "analyst",
      "action_type": "delegate_inquiry",
      "summary": "Analyst requested vehicle breakdown proof",
      "timestamp": "2026-09-26T14:16:00Z"
    }
  ],
  "driver_response_summary": "Xe buýt chết máy chắn lối rẽ Kim Mã khiến toàn tuyến tê liệt",
  "related_policies": [
    {
      "policy_code": "GSM-POL-042",
      "clause": "3.2 (Bất khả kháng do giao thông đô thị)",
      "rationale": "Miễn trừ chế tài trễ đón khách khi vận tốc dưới 5 km/h và tỷ lệ vượt trên 2.0x",
      "relevance_score": 0.95
    }
  ],
  "final_decision": {
    "verdict": "exonerated",
    "penalty_amount": 0,
    "rationale": "Xác thực kẹt xe Kim Mã từ viễn thông thực tế. Miễn trừ toàn bộ chế tài.",
    "decided_by": "018f2f4e-1000-7000-8000-000000000001",
    "decided_at": "2026-09-26T14:18:00Z"
  }
}
```

### 3. Database Persistence & Migration

1. **Dedicated Precedent Index Table (`app.precedent_workflows`):**
   Stores curated, indexable workflow templates:
   - `id`: UUID PRIMARY KEY
   - `case_id`: UUID REFERENCES `app.fraud_cases(id)`
   - `violation_code`: VARCHAR(32) NOT NULL
   - `claim_type`: VARCHAR(64) NOT NULL
   - `district`: VARCHAR(64)
   - `title`: VARCHAR(255) NOT NULL
   - `driver_statement_summary`: TEXT
   - `workflow_trace`: JSONB NOT NULL
   - `verdict`: VARCHAR(64) NOT NULL
   - `confidence_score`: NUMERIC(4,3) DEFAULT 1.0 (legacy field/default retained in this historical schema; not calibrated confidence or evidence of a correct verdict)
   - `created_at`: TIMESTAMPTZ DEFAULT now()
   - GIN index on `workflow_trace` and composite B-tree on `(violation_code, claim_type)`.
2. **Case Execution History:**
   Add `workflow_trace JSONB` to `app.fraud_cases` storing the exact runtime execution trace.

### 4. Cockpit Precedent Reuse & Post-Adjudication View

1. **Pre-Adjudication Precedent Recommendation Card:**
   When an analyst inspects a disputed case, the Cockpit Dossier evaluates precedent similarity. If `similarity_score >= 0.75`, the card displays:
   - Match label (e.g. `Raw relevance 0.92 — Jev`; never a fraud probability/accuracy percentage). The historical `>= 0.75` display threshold is ranking configuration, not a calibrated decision threshold.
   - Matching factors and precedent case link.
   - **"Áp dụng quy trình án lệ (Apply Precedent)"** button: Pre-fills an editable draft rationale/procedure only. It neither submits nor confirms a verdict; the analyst must review and confirm with written rationale.
2. **Post-Adjudication Workflow Synthesis Card:**
   Immediately following decision submission:
   - Replaces the generic success banner with the interactive **Case Workflow Synthesis**:
     - 🛠️ Tools Called (badges with execution status).
     - 👤 Human Actions (chronological timeline of driver replies and analyst delegations).
     - 💬 Driver Response summary.
     - 📜 Relevant Policy citations.
     - ⚖️ Final Decision verdict and rationale.
     - Precedent Bank publication status indicator.

### 5. Safety Invariant Check (`NFR-L06-02`)

Precedent workflows are advisory. Similarity and telemetry corroboration cannot dismiss a case or trigger an adverse sanction. Both dismissal and adverse sanctions require authorized analyst confirmation with written rationale. A blocking technical guardrail keeps adverse sanctions blocked; applying a precedent cannot override it. The former `auto_dismissed` branch is historical PR #40 divergence; PR #93 supplies the upstream correction while #73 full acceptance remains separate.

## Historical decision record

Originally accepted as V2 design, this ADR proposed asynchronous driver disputes, a precedent index/workflow trace, and one-click procedure reuse. Its original relief exception stated:

> Autonomous exoneration remains restricted to deterministic physical evidence corroborated by telemetry.

The original score wording also called `similarity_score` a “calibrated confidence float” without held-out calibration evidence. That assertion is corrected to raw uncalibrated relevance; the old label records historical intent only.

That release authorization is superseded by the strict PRD adopted 2026-09-30. Preserve the design and merged PR #40 history without treating the relief exception or new driver/mobile/appeal features as accepted Phase 1 scope.

## Rationale & Alternatives Considered

| Option | Pros | Cons | Decision |
|---|---|---|---|
| Advisory precedent reuse with human confirmation | Supports consistency and attributable rationale | Requires analyst review | Current release boundary |
| Similarity or corroboration decides the outcome | Historical automation proposal | Conflicts with no-auto-dismiss and sanction safeguards | Superseded authorization |
| Manual lookup or static matching | Fewer model dependencies | Less contextual ranking | Historical alternative; no performance conclusion |

## Required architecture questions

| Question | Answer |
|---|---|
| System topology | Inherited precedent services retrieve past workflows for the analyst cockpit; Jev/OpenRouter is an external matcher, not an adjudicator. See [release topology](POC_DESIGN.md#system-topology). |
| State and graph lifecycle | `WorkflowTrace` records tool and human actions, policy references, and an analyst decision; it is not a TypedDict graph state. Inherited [`AgentState`](../../src/agents/state.py) and [`graph.py`](../../src/agents/graph.py) keep `agent`/`tools` routing separate from case status. A match never resolves a case. |
| Tool contracts | Match inputs must be scoped to permitted evidence; output contains a score, factors, and procedure. Provider/schema failures remain explicit and any fallback provenance must be retained. See [failure requirements](POC_DESIGN.md#tool-contracts-and-failure-behavior); no uptime guarantee is established here. |
| Data flow | Retrieve authorized precedents, compute advisory relevance, show factors, optionally prefill a draft, then wait for analyst confirmation with written rationale. Only a validated human decision may populate the terminal trace. Existing REST/SSE streams return reply/tool status, not hidden reasoning. |
| Trade-offs | Contextual matching aids reuse but adds an external dependency and storage; deterministic fallback gives a different score, not evidence of calibration or equivalent accuracy. |
| Security boundaries | [Security requirements](POC_DESIGN.md#security-and-operations) keep provider keys server-side, sanitize text, and bound requests/rate limits. Precedent access needs authorization; blocked adverse sanctions cannot be unblocked by matching. Enforcement/deployment is not proven by this ADR. |

---

## Consequences

### Positive
- **MTTR hypothesis:** Procedure reuse may reduce repetitive lookup, but it does not resolve a case in one click. No MTTR improvement is measured here.
- **Consistency goal:** Contextual examples may support analyst reasoning; similarity alone proves neither comparable cases nor correct rulings.
- **Auditability & Traceability:** Every tool invocation, human message, and policy citation is preserved in a durable JSON workflow trace.

### Negative / Trade-Offs
- External dependency on OpenRouter Jev API; fallback is advisory with explicit provenance and failure states, never autonomous adjudication.
- Additional database storage for JSONB workflow traces and precedent indexes.
