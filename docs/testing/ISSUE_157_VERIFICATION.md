# Issue #157 Verification: Driver Agent Contracts & Autonomous Exoneration

**Issue Reference:** [#157](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/157)  
**Task Type:** Feature (Backend, AI Agents & Contracts)  
**Date:** 2026-10-05  
**Author:** Dat Nguyen (@DatTienNguyenn), assisted by Antigravity  

---

## 1. Objectives & Scope

Implement and verify the full Driver Agent Contracts and Autonomous Exoneration state machine across Driver Dispute Service, Driver Support Agent (LangGraph), Driver Tools, and Kinematic Maneuver Parsing in accordance with confirmed stakeholder rules (2026-10-05):

1. **Step-by-Step Driver Interaction Flow:**
   - **Step 1:** Read case, summarize it, and present brief to Driver.
   - **Step 2:** Driver provides explanation or request (statement).
   - **Step 3:** Retrieve and present additional evidence (telemetry, traffic corroboration) and relevant policy (Điều 12.2).
   - **Step 4:** Evaluate classifier confidence $c \in [0.0, 1.0]$:
     - **Strictly greater than 0.5 ($c > 0.5$, not $\ge 0.5$):** Ask whether Driver still wants to appeal.
     - **No further appeal** ("Không khiếu nại thêm" / "Đồng ý kết thúc" / "confirm_resolution"): Close case as `driver_confirmed_resolution`. Driver confirmation is sufficient to close every case at that step, even if evidence remains missing or conflicting. Zero sanction applied.
     - **Continue appeal** ("Tiếp tục khiếu nại" / refusal): Escalate to Fraud Analyst (`driver_disputed` / `in_dispute`).
     - **Confidence < 0.5 ($c < 0.5$) after a reasonable appeal:** Do NOT escalate; still ask Driver to confirm before closing.
     - **Boundary Rule:** Exactly `0.5`, missing confidence ($c = None$), out-of-range ($c < 0$ or $c > 1$), or tool execution failure MUST escalate to Analyst and NEVER auto-close.
     - **48-Hour Silence Deadline:** If no response / offline after confirmation question for > 48 hours, automatically escalate to Analyst.
     - **Score alone never closes or sanctions.**

2. **Kinematic Maneuver Parser (`src/services/route_analytics.py`):**
   - Resilient turn-by-turn maneuver extraction covering straight segments, left turns, right turns, U-turns, stationary stops, and GPS anomalies.
   - Graceful handling of malformed input (missing coordinates, invalid string speeds, out-of-bound or non-finite values, empty lists).
   - Strict provenance invariant: 100% of maneuver coordinates originate from the recorded telemetry points (zero fabricated GPS points).

3. **Cross-Driver Access Denial:**
   - Enforced across HTTP API (`require_driver_identity` in `src/api/routes.py`), direct tool calls (`get_driver_dispute_context`, `submit_driver_statement` in `src/agents/tools/driver_tools.py`), and agent dispatch (`run_driver_support_agent` in `src/agents/driver_agent.py`).
   - Returns structured `status_code=403` and `error_type="FORBIDDEN"` on cross-driver invocation.

---

## 2. API Contract & Schemas

### Request
`POST /api/v1/driver/cases/{case_id}/chat`
```json
{
  "case_id": "018f2f4e-a000-7000-8000-000000000026",
  "driver_id": "drv-001",
  "message": "Không khiếu nại thêm",
  "claim_type": "traffic_gridlock"
}
```

### Response Model (`DriverChatResponse`)
```json
{
  "case_id": "018f2f4e-a000-7000-8000-000000000026",
  "driver_id": "drv-001",
  "reply": "Cảm ơn bạn đã xác nhận. Vụ việc đã được ghi nhận hoàn tất và đóng khiếu nại (driver_confirmed_resolution). Không có bất kỳ chế tài xử phạt nào được áp dụng theo quy chế bảo vệ đối tác tài xế.",
  "dispute_status": "resolved",
  "is_auto_dismissed": false,
  "exoneration_receipt": null,
  "needs_analyst_review": false
}
```

---

## 3. Verification Commands & Results

### 1. Dedicated Driver Agent Contracts Test Suite
```bash
uv run pytest tests/test_services/test_driver_agent_contracts.py -v
```
**Result:** 20 passed in 0.15s:
- `test_confidence_strictly_less_than_half_asks_confirmation`: $c = 0.49$ does not escalate, asks driver to confirm resolution before closing (`status="pending_driver_confirmation"`, `dispute_status="pending_confirmation"`).
- `test_confidence_exactly_half_escalates_to_analyst`: Boundary rule $c = 0.50$ escalates to Analyst (`status="driver_disputed"`, `dispute_status="in_dispute"`).
- `test_confidence_strictly_greater_than_half_asks_appeal`: $c = 0.51$ asks whether driver wants to appeal without auto-sanctioning.
- `test_missing_confidence_escalates_to_analyst`: Missing confidence ($c = None$) escalates to Analyst, never auto-closes.
- `test_out_of_range_confidence_escalates_to_analyst`: Out-of-range ($c = -0.2$, $c = 1.4$) escalates to Analyst.
- `test_tool_failure_escalates_to_analyst`: Tool exception escalates to Analyst, never auto-closes.
- `test_driver_confirmation_closes_case_without_sanction`: Parametrized across `confirm_resolution`, `Không khiếu nại thêm`, `Đồng ý kết thúc`, `no_further_appeal`; closes case as `driver_confirmed_resolution` with zero sanction.
- `test_driver_continue_appeal_escalates_to_analyst`: Parametrized across `continue_appeal`, `Tiếp tục khiếu nại`, `Tôi muốn khiếu nại tiếp`; escalates to Fraud Analyst.
- `test_silence_timeout_after_confirmation_question_escalates`: 48h silence deadline expiration automatically escalates to Analyst.
- `test_score_alone_never_closes_or_sanctions`: High score (0.95) and low score (0.10) both require driver confirmation turn.
- `test_cross_driver_access_denied_service`: Service raises 403 Forbidden on mismatched driver ID.
- `test_cross_driver_access_denied_tools`: Direct tool execution returns `{"status_code": 403, "error_type": "FORBIDDEN"}`.
- `test_cross_driver_access_denied_agent`: Direct agent execution returns `{"status_code": 403, "error": "FORBIDDEN"}`.
- `test_driver_tool_catalog_declarations`: Validates `DRIVER_SURFACE_NAMES` metadata, `CATALOG_ENTRIES`, actor permissions, and human-only command guards.

### 2. Kinematic Maneuver Parser Test Suite
```bash
uv run pytest tests/test_services/test_kinematic_maneuvers.py -v
```
**Result:** 11 passed in 0.08s:
- `test_haversine_and_bearing_helpers`: Bearing and distance calculations.
- `test_parse_trajectory_maneuvers_straight_and_turns`: Straight segments and right turns.
- `test_parse_trajectory_maneuvers_stationary_stall`: Stationary clustering and Điều 14.2 stall flag.
- `test_format_maneuvers_for_llm_narrative`: Concise forensic brief prompt narrative for LLM.
- `test_jev_assessment_agent_populates_maneuvers`: Dynamic maneuver narrative population in Jev assessment.
- `test_parse_trajectory_maneuvers_wrong_direction`: Moving away from pickup detection under Điều 16.1.
- `test_jev_assessment_agent_detects_wrong_direction_err03`: Dynamic classification of wrong direction trajectory.
- `test_parse_trajectory_maneuvers_left_turn`: Left turn detection with signed angle delta.
- `test_parse_trajectory_maneuvers_malformed_input`: Resilient handling of None coordinates, missing fields, string speeds, NaN, out-of-range lon/lat, and empty lists.
- `test_parse_trajectory_maneuvers_unavailable_telemetry`: Single point with 0 speed and 0 stall duration returns empty list (no fabricated movement).
- `test_parse_trajectory_maneuvers_zero_fabricated_points`: 100% of returned maneuver coordinates strictly originate from input stream.

### 3. Driver Dispute Service Test Suite
```bash
uv run pytest tests/test_services/test_driver_dispute_service.py -v
```
**Result:** 14 passed in 0.11s:
- Corroborated traffic claim recommendations, uncorroborated traffic claim escalations, non-traffic claim escalations, past sanction blocks, mock GPS blocks, analyst inquiry delegations, dispute dossier compilation, and deadline expiration handling.

### 4. Code Quality, Type Safety & Full Regression Gates
```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
uv run pytest
```
**Result:**
- `ruff check`: All checks passed!
- `ruff format`: 166 files checked, 0 unformatted files.
- `mypy src/`: Success: no issues found in 62 source files.
- `pytest`: 1004 passed, 52 skipped in 142.83s.

---

## 4. Conclusion & Hand-off

Issue #157 is 100% complete, verified with 45 unit/contract tests, and ready for PR merge into `feat/152-system-analytics`. This establishes the core driver contract and unlocks Issues #158 (Driver Dispute Timeline & Telemetry Review), #159 (Driver Voice/Audio Input), and #160 (Driver Precedent & Autonomous Exoneration Dossier).
