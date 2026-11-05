# System Prompt Fine-Tuning Plan: Reasoning Baseline, Prior Evidence First & HITL

## 1. Executive Summary & Purpose

This document defines the engineering plan and specifications for fine-tuning the **GreenSM Sentinel Copilot** system prompt based on the deterministic reasoning baseline and forensic benchmark (`eval/reasoning_baseline.py`).

The objective is to eliminate hallucination, prevent unauthorized autonomous sanctions, enforce evidence grounding, and guarantee that prompt updates are versioned and verifiable without regressing core benchmark cases.

---

## 2. Core Pillars & Design Invariants

```
                                  +-------------------------------------+
                                  |   Raw Telemetry & Trip Case Facts   |
                                  +------------------+------------------+
                                                     |
                                                     v
                                  +-------------------------------------+
                                  |  Guardrail & Degradation Check      |
                                  |  - Outage? GPS degraded? Pts < 2?   |
                                  +------------------+------------------+
                                           /                    \
                               (Degraded / Sparse)         (Clean & Grounded)
                                       /                            \
                                      v                              v
                    +-----------------------------+   +------------------------------+
                    |    insufficient_evidence    |   | Prior Evidence Evaluation    |
                    |   (Confidence: 0.0, Hold)   |   | - Mock Location -> ERR-05    |
                    +-----------------------------+   | - Stall >=180s + Psg-> ERR-02|
                                   \                  | - Completed -> no_violation  |
                                    \                 +--------------+---------------+
                                     \                              /
                                      \                            /
                                       v                          v
                                  +-------------------------------------+
                                  |     Advisory Copilot Summary        |
                                  |     (Category, Confidence, Refs)    |
                                  +------------------+------------------+
                                                     |
                                                     v
                                  +-------------------------------------+
                                  |  Human-in-the-Loop (HITL) Gateway   |
                                  |  ❌ ZERO AUTO-SANCTION               |
                                  |  ✅ Human Analyst Final Adjudication |
                                  +-------------------------------------+
```

### Pillar 1: Prior Evidence First (Bằng chứng đi trước)
- Every finding, classification, and recommended triage category must be strictly grounded in observable telemetry fields: `telemetry_points`, `stationary_duration_s`, `lifecycle_state`, `cancellation_actor`, `mock_location_reported`, `platform_outage`, `gps_degraded`.
- **Degradation / Outage Exception**: If `platform_outage == true`, `gps_degraded == true`, or `telemetry_points < 2`, the agent MUST abstain by classifying as `insufficient_evidence` with confidence `0.0` and holding for analyst review.
- **Core Decision Thresholds**:
  - `ERR-05` (Mock Location / Fake GPS): Confirmed `mock_location_reported == true` (Điều 15.3).
  - `ERR-02` (Driver Stalling / DIC): `stationary_duration_s >= 180`, `lifecycle_state == "cancelled"`, and `cancellation_actor == "passenger"` (Điều 14.2). If duration < 180s, classify as `insufficient_evidence`.
  - `no_violation`: `lifecycle_state == "completed"` with no supported violation rules triggered.
  - `insufficient_evidence`: Ambiguous, corrupted, or below-threshold evidence.

### Pillar 2: Zero Auto-Sanction & Mandatory Human-in-the-Loop (HITL)
- **Strict Prohibition on Autonomous Sanction**: Under no circumstances can the Copilot autonomously apply punitive sanctions, driver suspensions, account deactivations, contract terminations, or financial clawbacks.
- **Human Sole Authority**: The human fraud analyst retains 100% sole adjudication authority.
- **Advisory Role**: The Copilot provides structured forensic summaries, uncalibrated confidence scores (0.0 to 1.0), and non-binding advisory recommendations for human sign-off.
- **Sanction Request Rejection**: If a user or prompt instructs the Copilot to "ban driver", "suspend account immediately", or "execute sanction now", the Copilot must decline automatic execution, present grounded evidence, and defer the action to the analyst for HITL adjudication.

### Pillar 3: Prompt Versioning & Artifact Traceability
- Canonical prompt stored at [`src/agents/prompts/fraud_analyst_system_prompt.md`](file:///src/agents/prompts/fraud_analyst_system_prompt.md).
- Version identifier explicitly exposed as `SYSTEM_PROMPT_VERSION = "v1.2.0-forensic-hitl"` in [`src/agents/graph.py`](file:///src/agents/graph.py).
- Programmatic inspector `get_system_prompt_version() -> str` enables runtime traceability across audit logs and database assessments.

---

## 3. Acceptance Criteria & Verification Mapping

| Acceptance Criteria | Implementation Detail | Verification Test | Status |
|---|---|---|---|
| **Prompt Versioned** | Explicit `SYSTEM_PROMPT_VERSION`, versioned markdown file in repository, `get_system_prompt_version()` helper | [`test_system_prompt_versioning`](file:///tests/test_agents/test_graph.py) | ✅ Verified |
| **Prior Evidence First** | Grounded observations, outage/degraded GPS guardrails, quantitative thresholds (180s stall) | [`test_system_prompt_prior_evidence_first`](file:///tests/test_agents/test_graph.py) | ✅ Verified |
| **Not Auto-Sanction** | Mandatory HITL, zero auto-sanction directive, advisory-only outputs, sanction rejection guard | [`test_system_prompt_not_auto_sanction`](file:///tests/test_agents/test_graph.py) | ✅ Verified |
| **Zero Core Case Regression** | Benchmark evaluation on 10 synthetic core cases preserves 100% scores across all metrics | [`test_benchmark_no_regression_on_core_cases`](file:///tests/test_agents/test_graph.py), [`test_benchmark_core_cases_no_regression`](file:///tests/test_agents/test_forensic_baseline.py) | ✅ Verified |

---

## 4. Benchmark Regression Results

Running `.venv/bin/python -m eval.reasoning_baseline`:
```json
{
  "category_accuracy": 1.0,
  "schema_validity": 1.0,
  "evidence_grounding": 1.0,
  "required_evidence_recall": 1.0
}
```

All 10 golden benchmark mock cases pass with zero errors, zero drift, and full evidence schema compliance.

---

## 5. Reproducible Run & Verification Instructions

Execute the following commands from the repository root:

```bash
# 1. Run the deterministic reasoning baseline benchmark (evaluates 10 mock cases against ForensicOutput contract)
python -m eval.reasoning_baseline

# 2. Run unit and integration tests verifying prompt versioning, boundary rules, and non-regression
pytest tests/test_agents/test_graph.py tests/test_agents/test_forensic_baseline.py -v

# 3. Run full test suite across the repository
pytest tests/ -v

# 4. Run Ruff and ESLint checks
bash scripts/lint.sh
npm --prefix src/webapp run lint
```

