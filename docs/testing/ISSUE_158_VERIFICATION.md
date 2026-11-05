# Issue #158 Verification: Real Driver Tools & Seeded Scenario Workflow

**Issue Reference:** [#158](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/158)  
**Task Type:** Feature (Backend, Driver Tools, Seeder & Scenario Workflows)  
**Date:** 2026-10-05  
**Author:** Dat Nguyen (@DatTienNguyenn), assisted by Antigravity  

---

## 1. Objectives & Definition of Done

Issue #158 provides real Driver tools, an idempotent and reversible scenario seeder, and an automated scenario workflow runner that proves the end-to-end lifecycle:
$$\text{detection} \longrightarrow \text{driver intake} \longrightarrow \text{tool execution} \longrightarrow \text{persisted response/event} \longrightarrow \text{pending or escalation state}$$

### Acceptance Criteria Checklist
- [x] **Scenario Seeder (`scripts/seed_driver_scenarios.py` / `src/services/scenario_seeder.py`):** Creates isolated, reversible scenario data with stable UUIDs and source metadata. Supports `--dry-run`, `--reset`, and `--target in-memory|database`.
- [x] **Driver Tools Authorization & Security (`tests/test_services/test_driver_tools_authorization.py`):** Passes tests for owned data, foreign driver rejection (HTTP 403, `error_type="FORBIDDEN"`), missing case handling (404), and malformed input.
- [x] **End-to-End Scenario Runner (`scripts/run_driver_scenario.py` / `src/services/driver_scenario_runner.py`):** Exercises all 3 canonical scenarios:
  1. `normal_corroborated`: Heavy gridlock, valid telemetry, slow speeds ($3.4 \text{ km/h} < 5.0 \text{ km/h}$), low confidence ($c = 0.35 \le 0.50$), driver confirmation closes case with zero sanctions.
  2. `unresolved_violation`: Suspected DIC stall, clear traffic ($35.1 \text{ km/h}$), high confidence ($c = 0.78 > 0.50$), branching on appeal choice ("continue appeal" escalates to analyst HITL; "no further appeal" closes case; 48h silence timeout auto-escalates).
  3. `missing_evidence`: Technical dropout, zero telemetry points, missing confidence ($c = None$), explicit unavailable state escalates directly to analyst HITL without auto-closure.
- [x] **Idempotency Invariant:** Replayed identical statements/chat requests return cached identical responses and never duplicate durable turns or audit log records.
- [x] **Honest Tool Contracts:** Tools expose evidence references, timestamps, error types, and explicit unavailable states without fabricating GPS or defaulting unknown traffic to clear.
- [x] **Inherited Ticket Preview Truthfulness (`write_ticket_for_driver`):** Retains `status="ISSUED"` for UI widget compatibility while explicitly reporting `durable_persisted=False`, `sanction_authorized=False`, and `requires_human_approval=True` until backed by an approved human action contract and durable audit proof.
- [x] **API Smoke Script (`scripts/smoke_driver_scenarios.py`):** End-to-end ASGI/HTTP smoke test validating seeded scenarios, cross-driver security, 404 handling, and idempotent replays.
- [x] **100% Quality Gates:** Ruff check, Ruff format, Mypy (`src/`), and full Pytest suite (1020 passed, 0 failed).

---

## 2. Seeded Scenario Definitions & Stable Identifiers

| Scenario Name | Case ID / Alias | Driver ID / Alias | Violation Code | Telemetry Points | Confidence $c$ | Traffic Corroboration | Resolution Behavior |
|---|---|---|---|---|---|---|---|
| `normal_corroborated` | `018f2f4e-b000-7000-8000-000000000001`<br>`case-scn-normal-01` | `018f2f4e-b300-7000-8000-000000000001`<br>`drv-scn-normal-01` | `ERR-01` (Late Pickup) | 15 points (avg 3.4 km/h) | `0.35` ($\le 0.50$) | `True` (Congestion $> 2.0\times$) | Driver confirms $\to$ Closed (`driver_confirmed_resolution`), 0 sanction |
| `unresolved_violation` | `018f2f4e-b000-7000-8000-000000000002`<br>`case-scn-unresolved-02` | `018f2f4e-b300-7000-8000-000000000002`<br>`drv-scn-unresolved-02` | `ERR-02` (Intentional Stall DIC) | 15 points (avg 35.1 km/h) | `0.78` ($> 0.50$) | `False` (Clear flow) | Ask appeal: "continue appeal" $\to$ Escalates to Analyst HITL; "no appeal" $\to$ Closes; 48h timeout $\to$ Auto-escalates |
| `missing_evidence` | `018f2f4e-b000-7000-8000-000000000003`<br>`case-scn-missing-03` | `018f2f4e-b300-7000-8000-000000000003`<br>`drv-scn-missing-03` | `ERR-05` (Dropout / No Signal) | 0 points | `None` (Missing assessment) | `unavailable` (No fake data) | Boundary rule: Escalates to Analyst HITL (`in_dispute`), zero auto-close |

---

## 3. Verification Commands & Outputs

### 1. Seeder CLI Preview and Reset Verification
```bash
uv run python3 scripts/seed_driver_scenarios.py --dry-run
```
Output:
```json
{
  "run_id": "seed-driver-158",
  "version": "1.0",
  "scenarios": {
    "normal_corroborated": {
      "case_id": "018f2f4e-b000-7000-8000-000000000001",
      "case_alias": "case-scn-normal-01",
      "driver_id": "018f2f4e-b300-7000-8000-000000000001",
      "driver_name": "Nguyễn Văn Bình",
      "category": "ERR-01",
      "confidence": 0.35,
      "points_count": 15
    },
    "unresolved_violation": {
      "case_id": "018f2f4e-b000-7000-8000-000000000002",
      "case_alias": "case-scn-unresolved-02",
      "driver_id": "018f2f4e-b300-7000-8000-000000000002",
      "driver_name": "Lê Hoàng Long",
      "category": "ERR-02",
      "confidence": 0.78,
      "points_count": 15
    },
    "missing_evidence": {
      "case_id": "018f2f4e-b000-7000-8000-000000000003",
      "case_alias": "case-scn-missing-03",
      "driver_id": "018f2f4e-b300-7000-8000-000000000003",
      "driver_name": "Phạm Minh Quang",
      "category": "ERR-05",
      "confidence": null,
      "points_count": 0
    }
  },
  "counts": {
    "cases": 3,
    "drivers": 3,
    "trips": 3,
    "assignments": 3,
    "telemetry_points": 30
  },
  "dry_run": true
}
```

### 2. End-to-End Scenario Runner Execution
```bash
uv run python3 scripts/run_driver_scenario.py --scenario all
```
Output:
```json
{
  "run_id": "driver-scenarios-run",
  "timestamp": "2026-10-05T02:37:59.101849+00:00",
  "scenarios": {
    "normal_corroborated": {
      "scenario": "normal_corroborated",
      "case_id": "018f2f4e-b000-7000-8000-000000000001",
      "final_case_status": "driver_confirmed_resolution",
      "final_dispute_status": "resolved",
      "audit_actions": [
        "driver_confirmation_requested",
        "driver_confirmed_resolution"
      ],
      "success": true
    },
    "unresolved_violation": {
      "scenario": "unresolved_violation",
      "case_id": "018f2f4e-b000-7000-8000-000000000002",
      "final_case_status": "driver_disputed",
      "final_dispute_status": "in_dispute",
      "audit_actions": [
        "driver_confirmation_requested",
        "driver_appeal_escalated"
      ],
      "success": true
    },
    "missing_evidence": {
      "scenario": "missing_evidence",
      "case_id": "018f2f4e-b000-7000-8000-000000000003",
      "final_case_status": "driver_disputed",
      "final_dispute_status": "in_dispute",
      "audit_actions": [
        "driver_dispute_submitted"
      ],
      "success": true
    }
  },
  "all_passed": true
}
```

### 3. API Smoke Test Execution
```bash
uv run python3 scripts/smoke_driver_scenarios.py
```
Output:
```json
{
  "status": "ALL_PASS",
  "scenarios_tested": {
    "normal_corroborated": {
      "status": "PASS",
      "case_id": "018f2f4e-b000-7000-8000-000000000001",
      "final_dispute_status": "resolved",
      "is_auto_dismissed": false
    },
    "unresolved_violation": {
      "status": "PASS",
      "case_id": "018f2f4e-b000-7000-8000-000000000002",
      "final_dispute_status": "in_dispute",
      "needs_analyst_review": true
    },
    "missing_evidence": {
      "status": "PASS",
      "case_id": "018f2f4e-b000-7000-8000-000000000003",
      "final_dispute_status": "in_dispute",
      "needs_analyst_review": true
    }
  },
  "authorization_checks": {
    "foreign_driver_403": "PASS",
    "missing_case_404": "PASS"
  },
  "idempotency_checks": {
    "retry_identical_response": "PASS"
  }
}
```

### 4. Dedicated Test Suites Execution
```bash
uv run pytest tests/test_services/test_driver_tools_authorization.py tests/test_services/test_driver_scenario_workflow.py -v
```
Output:
```
tests/test_services/test_driver_tools_authorization.py::test_owned_data_access_passes PASSED
tests/test_services/test_driver_tools_authorization.py::test_foreign_driver_access_rejected_403 PASSED
tests/test_services/test_driver_tools_authorization.py::test_missing_case_handling_404 PASSED
tests/test_services/test_driver_tools_authorization.py::test_malformed_input_handling PASSED
tests/test_services/test_driver_tools_authorization.py::test_idempotent_driver_chat_retries PASSED
tests/test_services/test_driver_tools_authorization.py::test_missing_telemetry_honest_semantics PASSED
tests/test_services/test_driver_tools_authorization.py::test_write_ticket_for_driver_truthful_preview PASSED
tests/test_services/test_driver_scenario_workflow.py::test_seeder_dry_run_and_manifest PASSED
tests/test_services/test_driver_scenario_workflow.py::test_seeder_real_seed_and_reset_reversibility PASSED
tests/test_services/test_driver_scenario_workflow.py::test_scenario_normal_corroborated_workflow PASSED
tests/test_services/test_driver_scenario_workflow.py::test_scenario_unresolved_violation_continue_appeal PASSED
tests/test_services/test_driver_scenario_workflow.py::test_scenario_unresolved_violation_no_further_appeal PASSED
tests/test_services/test_driver_scenario_workflow.py::test_scenario_unresolved_violation_silence_timeout_escalation PASSED
tests/test_services/test_driver_scenario_workflow.py::test_scenario_missing_evidence_workflow PASSED
tests/test_services/test_driver_scenario_workflow.py::test_boundary_confidence_and_error_handling PASSED
tests/test_services/test_driver_scenario_workflow.py::test_run_all_scenarios_suite PASSED

============================== 16 passed in 0.28s ===============================
```

### 5. Static Code Quality Gates
```bash
uv run ruff check src/ tests/ scripts/
# All checks passed!

uv run ruff format --check src/ tests/ scripts/
# 203 files already formatted

uv run mypy src/
# Success: no issues found in 64 source files
```

### 6. Full Repository Regression Suite
```bash
uv run pytest
# ========== 1020 passed, 52 skipped, 10 warnings in 147.42s (0:02:27) ===========
```

---

## 4. Key Files Delivered

- [`src/services/scenario_seeder.py`](file:///home/dat/dev/vinuni_aia/GreenSentinel/src/services/scenario_seeder.py): Idempotent seeding and reversible cleanup of 3 canonical scenarios for both in-memory test stores and PostgreSQL databases.
- [`src/services/driver_scenario_runner.py`](file:///home/dat/dev/vinuni_aia/GreenSentinel/src/services/driver_scenario_runner.py): End-to-end scenario runner verifying detection, intake, tool execution, branching, and audit persistence.
- [`src/agents/tools/driver_tools.py`](file:///home/dat/dev/vinuni_aia/GreenSentinel/src/agents/tools/driver_tools.py): Real driver tools with cross-driver authorization, structured error handling, and honest telemetry availability.
- [`src/agents/tools/analyst_tools.py`](file:///home/dat/dev/vinuni_aia/GreenSentinel/src/agents/tools/analyst_tools.py): Truthful preview semantics on `write_ticket_for_driver` without unauthorized durable writes.
- [`scripts/seed_driver_scenarios.py`](file:///home/dat/dev/vinuni_aia/GreenSentinel/scripts/seed_driver_scenarios.py): CLI tool for scenario seeding, preview, and reset.
- [`scripts/run_driver_scenario.py`](file:///home/dat/dev/vinuni_aia/GreenSentinel/scripts/run_driver_scenario.py): CLI tool for automated scenario execution and audit verification.
- [`scripts/smoke_driver_scenarios.py`](file:///home/dat/dev/vinuni_aia/GreenSentinel/scripts/smoke_driver_scenarios.py): API smoke test exercising live endpoints.
- [`tests/test_services/test_driver_tools_authorization.py`](file:///home/dat/dev/vinuni_aia/GreenSentinel/tests/test_services/test_driver_tools_authorization.py): Unit tests for tool authorization, error types, idempotency, and ticket preview.
- [`tests/test_services/test_driver_scenario_workflow.py`](file:///home/dat/dev/vinuni_aia/GreenSentinel/tests/test_services/test_driver_scenario_workflow.py): Workflow tests for all 3 scenarios, timeout escalation, and boundary conditions.
