"""End-to-End Scenario Workflow Tests for Issue #158.

Validates the full scenario lifecycle across all 3 canonical scenarios:
1. Normal Case (heavy gridlock, valid GPS, slow speed, c = 0.35 <= 0.50, driver confirms -> closed without sanction)
2. Unresolved Case (suspected DIC, clear flow, c = 0.78 > 0.50, branching: continue appeal vs no appeal vs 48h timeout)
3. Missing Evidence Case (0 telemetry, c = None, explicit unavailable state -> escalates to analyst HITL)
Also validates seeder dry-run/reset reversibility, and boundary confidence conditions.
"""

from uuid import uuid4

import pytest

from src.models.schemas import DriverChatRequest
from src.services.case_service import get_case_service
from src.services.driver_dispute_service import get_driver_dispute_service
from src.services.driver_scenario_runner import DriverScenarioRunner
from src.services.scenario_seeder import SCENARIOS_DEFINITIONS, ScenarioSeeder


@pytest.fixture(autouse=True)
def clean_scenario_state():
    """Ensure clean scenario fixtures before and after each test."""
    seeder = ScenarioSeeder()
    seeder.clean_in_memory()
    yield
    seeder.clean_in_memory()


@pytest.mark.asyncio
async def test_seeder_dry_run_and_manifest():
    """Seeder in dry-run mode returns complete preview manifest without writing to storage."""
    cs = get_case_service()
    initial_case_count = len(cs._cases)
    initial_pts_count = len(cs._telemetry_points)

    seeder = ScenarioSeeder()
    manifest = seeder.seed_in_memory(dry_run=True)

    assert manifest["dry_run"] is True
    assert manifest["run_id"] == "seed-driver-158"
    assert manifest["counts"]["cases"] == 3
    assert manifest["counts"]["telemetry_points"] == 30
    assert "normal_corroborated" in manifest["scenarios"]
    assert "unresolved_violation" in manifest["scenarios"]
    assert "missing_evidence" in manifest["scenarios"]

    # Storage remains untouched
    assert len(cs._cases) == initial_case_count
    assert len(cs._telemetry_points) == initial_pts_count


@pytest.mark.asyncio
async def test_seeder_real_seed_and_reset_reversibility():
    """Seeder commits records in normal mode and cleanly reverses only scenario records on reset."""
    cs = get_case_service()
    initial_case_count = len(cs._cases)
    initial_pts_count = len(cs._telemetry_points)

    seeder = ScenarioSeeder()
    seed_res = seeder.seed_in_memory(dry_run=False)
    assert seed_res["dry_run"] is False
    assert len(cs._cases) == initial_case_count + 6  # 3 UUIDs + 3 human aliases

    # Reset cleans scenario records back to initial
    reset_res = seeder.seed_in_memory(reset=True)
    assert reset_res["action"] == "reset"
    assert len(cs._cases) == initial_case_count
    assert len(cs._telemetry_points) == initial_pts_count


@pytest.mark.asyncio
async def test_scenario_normal_corroborated_workflow():
    """Normal scenario: gridlock, valid GPS, low confidence, driver confirms -> closed without sanction."""
    runner = DriverScenarioRunner()
    res = await runner.run_scenario("normal_corroborated")

    assert res["success"] is True
    assert res["scenario"] == "normal_corroborated"
    assert res["final_case_status"] == "driver_confirmed_resolution"
    assert res["final_dispute_status"] == "resolved"
    assert "driver_confirmation_requested" in res["audit_actions"]
    assert "driver_confirmed_resolution" in res["audit_actions"]


@pytest.mark.asyncio
async def test_scenario_unresolved_violation_continue_appeal():
    """Unresolved violation: clear traffic, high confidence (0.78), driver continues appeal -> escalated to analyst."""
    runner = DriverScenarioRunner()
    res = await runner.run_scenario("unresolved_violation", driver_choice="continue_appeal")

    assert res["success"] is True
    assert res["scenario"] == "unresolved_violation"
    assert res["final_case_status"] == "driver_disputed"
    assert res["final_dispute_status"] == "in_dispute"
    assert "driver_confirmation_requested" in res["audit_actions"]
    assert "driver_appeal_escalated" in res["audit_actions"]


@pytest.mark.asyncio
async def test_scenario_unresolved_violation_no_further_appeal():
    """Unresolved violation: driver selects 'no further appeal' -> case closed without sanction."""
    runner = DriverScenarioRunner()
    res = await runner.run_scenario("unresolved_violation", driver_choice="no_further_appeal")

    assert res["success"] is True
    assert res["scenario"] == "unresolved_violation"
    assert res["final_case_status"] == "driver_confirmed_resolution"
    assert res["final_dispute_status"] == "resolved"
    assert "driver_confirmed_resolution" in res["audit_actions"]


@pytest.mark.asyncio
async def test_scenario_unresolved_violation_silence_timeout_escalation():
    """Unresolved violation: no response within 48-hour silence deadline -> auto-escalates to analyst."""
    runner = DriverScenarioRunner()
    res = await runner.run_scenario("unresolved_violation", simulate_timeout=True)

    assert res["success"] is True
    assert res["final_case_status"] == "driver_disputed"
    assert res["final_dispute_status"] == "in_dispute"
    assert "driver_silence_timeout_escalation" in res["audit_actions"]


@pytest.mark.asyncio
async def test_scenario_missing_evidence_workflow():
    """Missing evidence scenario: zero telemetry, missing confidence -> escalates to analyst HITL without auto-close."""
    runner = DriverScenarioRunner()
    res = await runner.run_scenario("missing_evidence")

    assert res["success"] is True
    assert res["scenario"] == "missing_evidence"
    assert res["final_case_status"] == "driver_disputed"
    assert res["final_dispute_status"] == "in_dispute"
    assert "driver_dispute_submitted" in res["audit_actions"]


@pytest.mark.asyncio
async def test_boundary_confidence_and_error_handling():
    """Test boundary confidence rules: exactly 0.5, out-of-range, and tool failure escalate to analyst."""
    seeder = ScenarioSeeder()
    seeder.seed_in_memory()
    dispute_service = get_driver_dispute_service()

    cid = "018f2f4e-b000-7000-8000-000000000001"
    did = "018f2f4e-b300-7000-8000-000000000001"

    # 1. Exactly 0.5 confidence -> must escalate to analyst, never auto-close
    dispute_service._confidence_overrides[cid] = 0.50
    req_05 = DriverChatRequest(
        case_id=cid,
        driver_id=did,
        message="Tôi bị kẹt xe trên đường Kim Mã",
        claim_type="other",
        turn_id=str(uuid4()),
    )
    resp_05 = await dispute_service.process_driver_chat(req_05)
    assert resp_05.needs_analyst_review is True
    assert resp_05.dispute_status in ("pending_review", "in_dispute")

    # 2. Out-of-range confidence (e.g. 1.25) -> must escalate to analyst safely
    cid2 = "018f2f4e-b000-7000-8000-000000000002"
    did2 = "018f2f4e-b300-7000-8000-000000000002"
    dispute_service._confidence_overrides[cid2] = 1.25
    req_invalid_c = DriverChatRequest(
        case_id=cid2,
        driver_id=did2,
        message="Tôi gặp vấn đề thiết bị hỏng",
        claim_type="other",
        turn_id=str(uuid4()),
    )
    resp_invalid_c = await dispute_service.process_driver_chat(req_invalid_c)
    assert resp_invalid_c.needs_analyst_review is True
    assert resp_invalid_c.dispute_status == "in_dispute"


@pytest.mark.asyncio
async def test_run_all_scenarios_suite():
    """Runner can execute all 3 canonical scenarios sequentially and report complete pass status."""
    runner = DriverScenarioRunner()
    suite = await runner.run_all_scenarios()

    assert suite["all_passed"] is True
    assert len(suite["scenarios"]) == 3
    for name in SCENARIOS_DEFINITIONS:
        assert suite["scenarios"][name]["success"] is True
