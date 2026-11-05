"""Driver Dispute Scenario Runner for Issue #158.

Orchestrates and proves end-to-end driver dispute workflows:
detection -> driver intake -> tool execution -> persisted response/event -> pending or escalation state.

Supports the 3 canonical scenarios:
1. normal_corroborated: Gridlock delay, valid GPS, slow speeds (< 5 km/h), c = 0.35 <= 0.5, driver confirms -> closed without sanction.
2. unresolved_violation: DIC stall, clear traffic (35 km/h), c = 0.78 > 0.5, ask appeal -> continue appeal escalates to analyst, no appeal closes case, timeout escalates.
3. missing_evidence: Zero telemetry, c = None, explicit unavailable state -> escalates to analyst HITL without auto-closure.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from src.models.schemas import DriverChatRequest, DriverChatResponse
from src.services.case_service import CaseService, get_case_service
from src.services.driver_dispute_service import DriverDisputeService, get_driver_dispute_service
from src.services.scenario_seeder import SCENARIOS_DEFINITIONS, ScenarioSeeder

logger = logging.getLogger(__name__)


class DriverScenarioRunner:
    """Automates scenario execution and verifies state machine transitions, audit proof, and tool contracts."""

    def __init__(
        self,
        case_service: CaseService | None = None,
        dispute_service: DriverDisputeService | None = None,
        seeder: ScenarioSeeder | None = None,
    ) -> None:
        self.case_service = case_service or get_case_service()
        self.dispute_service = dispute_service or get_driver_dispute_service()
        self.seeder = seeder or ScenarioSeeder(self.case_service, self.dispute_service)

    async def run_scenario(
        self,
        scenario_name: str,
        driver_choice: str | None = None,
        simulate_timeout: bool = False,
    ) -> dict[str, Any]:
        """Execute one canonical driver dispute scenario end-to-end and verify all DoD invariants."""
        if scenario_name not in SCENARIOS_DEFINITIONS:
            raise ValueError(f"Unknown scenario '{scenario_name}'. Valid: {list(SCENARIOS_DEFINITIONS.keys())}")

        spec = SCENARIOS_DEFINITIONS[scenario_name]
        case_id = spec["case_id"]
        driver_id = spec["driver_id"]
        case_alias = spec["case_alias"]

        # Ensure scenario data exists in-memory
        if case_id not in self.case_service._cases and case_alias not in self.case_service._cases:
            self.seeder.seed_in_memory()

        steps: list[dict[str, Any]] = []

        # -------------------------------------------------------------
        # Step 1: Driver Intake (Fetch violation context & summary)
        # -------------------------------------------------------------
        intake_context = await self.dispute_service.get_driver_dispute_context(
            case_id=case_id,
            driver_id=driver_id,
        )
        assert intake_context.case_id in (case_id, case_alias)
        assert intake_context.violation_code == spec["suspected_category"]

        intake_step = {
            "step": "driver_intake",
            "case_id": intake_context.case_id,
            "driver_id": intake_context.driver_id,
            "driver_name": intake_context.driver_name,
            "violation_code": intake_context.violation_code,
            "dispute_deadline": intake_context.dispute_deadline,
            "dispute_status": intake_context.dispute_status,
        }
        steps.append(intake_step)

        # -------------------------------------------------------------
        # Step 2: Driver Explanation & Tool Execution
        # -------------------------------------------------------------
        if scenario_name == "normal_corroborated":
            statement = "Tôi bị kẹt xe trên đường Kim Mã tắc cứng 15 phút, xe không thể di chuyển."
            claim_type = "traffic_gridlock"
        elif scenario_name == "unresolved_violation":
            statement = "Tôi gặp sự cố xe chết máy trên đường chờ cứu hộ."
            claim_type = "vehicle_breakdown"
        else:  # missing_evidence
            statement = "Điện thoại mất sóng 4G cả đoạn đường, ứng dụng không định vị được."
            claim_type = "technical_dropout"

        turn_1_id = f"turn-1-{scenario_name}-{uuid4().hex[:6]}"
        chat_req_1 = DriverChatRequest(
            case_id=case_id,
            driver_id=driver_id,
            message=statement,
            claim_type=claim_type,
            turn_id=turn_1_id,
        )

        resp_1: DriverChatResponse = await self.dispute_service.process_driver_chat(chat_req_1)

        # Step 2b: Tool Execution Direct Verification
        traffic_tool_res = await self.dispute_service.corroborate_traffic_conditions(
            case_id=case_id,
            driver_id=driver_id,
        )
        telemetry_tool_res = await self.dispute_service.inspect_trip_telemetry(
            case_id=case_id,
            driver_id=driver_id,
        )

        tool_verification = {
            "step": "tool_execution_verification",
            "traffic_corroboration": {
                "corroborated": traffic_tool_res.get("corroborated"),
                "status": traffic_tool_res.get("status"),
                "observed_speed": traffic_tool_res.get("observed_speed"),
                "evidence_references": traffic_tool_res.get("evidence_references", []),
            },
            "trip_telemetry": {
                "status": telemetry_tool_res.get("status"),
                "points_count": telemetry_tool_res.get("points_count"),
                "has_breadcrumbs": bool(telemetry_tool_res.get("breadcrumbs")),
                "evidence_references": telemetry_tool_res.get("evidence_references", []),
            },
        }
        steps.append(tool_verification)

        chat_step_1 = {
            "step": "driver_explanation_intake",
            "turn_id": turn_1_id,
            "statement": statement,
            "claim_type": claim_type,
            "agent_reply": resp_1.reply,
            "dispute_status": resp_1.dispute_status,
            "needs_analyst_review": resp_1.needs_analyst_review,
        }
        steps.append(chat_step_1)

        # -------------------------------------------------------------
        # Step 3: Branching & Resolution / Confirmation
        # -------------------------------------------------------------
        if scenario_name == "normal_corroborated":
            # Confidence is low (0.35 <= 0.50), traffic is corroborated.
            # State is pending_confirmation. Driver confirms resolution.
            assert resp_1.dispute_status == "pending_confirmation"
            assert not resp_1.needs_analyst_review

            turn_2_id = f"turn-2-{scenario_name}-{uuid4().hex[:6]}"
            chat_req_2 = DriverChatRequest(
                case_id=case_id,
                driver_id=driver_id,
                message="Tôi đồng ý xác nhận kết thúc khiếu nại, không khiếu nại thêm.",
                turn_id=turn_2_id,
                # A resolution confirmation is not an admission of fraud.
                admits_fraud=False,
            )
            resp_2 = await self.dispute_service.process_driver_chat(chat_req_2)
            assert resp_2.dispute_status == "resolved"
            assert not resp_2.needs_analyst_review

            steps.append(
                {
                    "step": "driver_confirmation",
                    "turn_id": turn_2_id,
                    "action": "confirm_resolution",
                    "agent_reply": resp_2.reply,
                    "final_dispute_status": resp_2.dispute_status,
                }
            )

        elif scenario_name == "unresolved_violation":
            # Confidence is high (0.78 > 0.50), traffic clear.
            # Agent asks if Driver wants to appeal.
            assert resp_1.dispute_status == "pending_confirmation"

            if simulate_timeout:
                # 48-hour timeout simulation
                canonical_id = self.case_service._case_aliases.get(case_id, case_id)
                case = self.case_service._cases[canonical_id]
                case["dispute_deadline"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()

                turn_timeout_id = f"turn-timeout-{scenario_name}-{uuid4().hex[:6]}"
                chat_req_timeout = DriverChatRequest(
                    case_id=case_id,
                    driver_id=driver_id,
                    message="Kiểm tra trạng thái khiếu nại sau thời gian dài.",
                    turn_id=turn_timeout_id,
                )
                resp_timeout = await self.dispute_service.process_driver_chat(chat_req_timeout)
                assert resp_timeout.needs_analyst_review
                assert resp_timeout.dispute_status == "in_dispute"
                steps.append(
                    {
                        "step": "timeout_auto_escalation",
                        "turn_id": turn_timeout_id,
                        "action": "driver_silence_timeout_escalation",
                        "agent_reply": resp_timeout.reply,
                        "final_dispute_status": resp_timeout.dispute_status,
                    }
                )

            elif driver_choice == "no_further_appeal":
                turn_2_id = f"turn-2-noappeal-{scenario_name}-{uuid4().hex[:6]}"
                chat_req_2 = DriverChatRequest(
                    case_id=case_id,
                    driver_id=driver_id,
                    message="Tôi chấp nhận kết quả, không khiếu nại thêm.",
                    turn_id=turn_2_id,
                    # Closing an appeal is not an admission of fraud.
                    # The system applies no automated sanctions.
                    admits_fraud=False,
                )
                resp_2 = await self.dispute_service.process_driver_chat(chat_req_2)
                assert resp_2.dispute_status == "resolved"
                steps.append(
                    {
                        "step": "driver_close_confirmation",
                        "turn_id": turn_2_id,
                        "action": "no_further_appeal",
                        "agent_reply": resp_2.reply,
                        "final_dispute_status": resp_2.dispute_status,
                    }
                )

            else:  # Default: continue_appeal
                turn_2_id = f"turn-2-appeal-{scenario_name}-{uuid4().hex[:6]}"
                chat_req_2 = DriverChatRequest(
                    case_id=case_id,
                    driver_id=driver_id,
                    message="Tôi không đồng ý và muốn tiếp tục khiếu nại lên Chuyên viên giám sát.",
                    turn_id=turn_2_id,
                )
                resp_2 = await self.dispute_service.process_driver_chat(chat_req_2)
                assert resp_2.needs_analyst_review
                assert resp_2.dispute_status == "in_dispute"
                steps.append(
                    {
                        "step": "driver_appeal_escalation",
                        "turn_id": turn_2_id,
                        "action": "continue_appeal",
                        "agent_reply": resp_2.reply,
                        "final_dispute_status": resp_2.dispute_status,
                    }
                )

        else:  # missing_evidence
            # Explicit unavailable state, confidence is None -> must escalate to analyst immediately, never auto-close
            assert resp_1.needs_analyst_review
            assert traffic_tool_res.get("status") == "unavailable"
            assert telemetry_tool_res.get("status") == "unavailable"
            steps.append(
                {
                    "step": "boundary_missing_evidence_escalation",
                    "reason": "unavailable_telemetry_or_missing_confidence",
                    "final_dispute_status": resp_1.dispute_status,
                }
            )

        # -------------------------------------------------------------
        # Step 4: Idempotent Retry Check
        # -------------------------------------------------------------
        prior_audit_count = len(self.dispute_service.get_audit_entries(case_id))
        retry_resp = await self.dispute_service.process_driver_chat(chat_req_1)
        post_audit_count = len(self.dispute_service.get_audit_entries(case_id))
        assert retry_resp.reply == resp_1.reply
        assert post_audit_count == prior_audit_count, "Duplicate audit entry created on idempotent retry!"
        steps.append(
            {
                "step": "idempotency_verification",
                "status": "PASS",
                "audit_entries_unchanged": True,
            }
        )

        canonical_id = self.case_service._case_aliases.get(case_id, case_id)
        final_case = self.case_service._cases[canonical_id]
        audit_entries = self.dispute_service.get_audit_entries(canonical_id)

        return {
            "scenario": scenario_name,
            "case_id": case_id,
            "driver_id": driver_id,
            "category": spec["suspected_category"],
            "initial_confidence": spec["confidence"],
            "final_case_status": final_case.get("status"),
            "final_dispute_status": final_case.get("dispute_status"),
            "audit_actions": [a.get("action") for a in audit_entries],
            "steps": steps,
            "success": True,
        }

    async def run_all_scenarios(self) -> dict[str, Any]:
        """Run all 3 canonical scenarios and return combined execution results."""
        results: dict[str, Any] = {}
        for sc_name in SCENARIOS_DEFINITIONS:
            # For unresolved_violation, execute continue_appeal branch
            results[sc_name] = await self.run_scenario(sc_name)
        return {
            "run_id": "driver-scenarios-run",
            "timestamp": datetime.now(UTC).isoformat(),
            "scenarios": results,
            "all_passed": all(r.get("success") for r in results.values()),
        }
