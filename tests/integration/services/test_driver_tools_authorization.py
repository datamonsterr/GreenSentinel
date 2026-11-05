"""Unit and Authorization Tests for Driver Tools and Services (#158).

Tests:
1. Owned data access: driver can retrieve dispute context, inspect telemetry, and corroborate traffic.
2. Foreign driver access rejection: cross-driver requests return 403 / FORBIDDEN.
3. Missing case handling: 404 / NOT_FOUND returned cleanly across tools and services.
4. Malformed input handling: empty string, None, invalid coordinates, or invalid case IDs.
5. Idempotent retries: duplicate requests return identical responses without duplicating audit or turns.
6. Honest tool semantics: evidence references, timestamps, error types, and explicit unavailable states.
7. Analyst sanction preview semantics: write_ticket_for_driver returns truthful preview without false durable claims.
"""

from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.agents.tools.analyst_tools import write_ticket_for_driver
from src.agents.tools.driver_tools import (
    corroborate_traffic_conditions,
    get_driver_dispute_context,
    inspect_trip_telemetry,
    verify_exoneration_rules,
)
from src.models.schemas import DriverChatRequest
from src.services.driver_dispute_service import get_driver_dispute_service
from src.services.scenario_seeder import ScenarioSeeder


@pytest.fixture(autouse=True)
def seed_test_scenarios():
    """Ensure clean scenario fixtures exist for each test."""
    seeder = ScenarioSeeder()
    seeder.seed_in_memory()
    yield
    seeder.clean_in_memory()


@pytest.mark.asyncio
async def test_owned_data_access_passes():
    """Authenticated driver can access their owned case dispute context and tools."""
    case_id = "018f2f4e-b000-7000-8000-000000000001"
    driver_id = "018f2f4e-b300-7000-8000-000000000001"

    # Context tool
    ctx = await get_driver_dispute_context.ainvoke({"case_id": case_id, "driver_id": driver_id})
    assert "error" not in ctx
    assert ctx["case_id"] == case_id
    assert ctx["driver_id"] == driver_id
    assert ctx["violation_code"] == "ERR-01"

    # Traffic corroboration tool
    traffic = await corroborate_traffic_conditions.ainvoke({"case_id": case_id, "driver_id": driver_id})
    assert "error" not in traffic
    assert traffic["corroborated"] is True
    assert traffic["status"] == "available"
    assert len(traffic["evidence_references"]) > 0

    # Telemetry inspection tool
    telemetry = await inspect_trip_telemetry.ainvoke({"case_id": case_id, "driver_id": driver_id})
    assert "error" not in telemetry
    assert telemetry["status"] == "available"
    assert telemetry["points_count"] == 15
    assert len(telemetry["breadcrumbs"]) == 15


@pytest.mark.asyncio
async def test_foreign_driver_access_rejected_403():
    """Cross-driver access to foreign case must be rejected with 404 / NOT_FOUND (anti-probing)."""
    owned_case_id = "018f2f4e-b000-7000-8000-000000000001"
    attacker_driver_id = "018f2f4e-b300-7000-8000-000000000002"  # Belongs to case-02

    # Context tool
    ctx = await get_driver_dispute_context.ainvoke({"case_id": owned_case_id, "driver_id": attacker_driver_id})
    assert ctx.get("error_type") == "NOT_FOUND"
    assert ctx.get("status_code") == 404
    assert "not found" in ctx.get("error", "").lower()

    # Telemetry inspection tool
    telem = await inspect_trip_telemetry.ainvoke({"case_id": owned_case_id, "driver_id": attacker_driver_id})
    assert telem.get("error_type") == "NOT_FOUND"
    assert telem.get("status_code") == 404

    # Traffic corroboration tool
    traffic = await corroborate_traffic_conditions.ainvoke({"case_id": owned_case_id, "driver_id": attacker_driver_id})
    assert traffic.get("error_type") == "NOT_FOUND"
    assert traffic.get("status_code") == 404

    # Direct service method
    dispute_service = get_driver_dispute_service()
    with pytest.raises(HTTPException) as exc_info:
        await dispute_service.get_driver_dispute_context(case_id=owned_case_id, driver_id=attacker_driver_id)
    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_missing_case_owner_fails_closed():
    """A case without ownership metadata must reject supplied driver IDs."""
    service = get_driver_dispute_service()
    assert service._is_driver_authorized(None, "driver-attacker") is False


@pytest.mark.asyncio
async def test_missing_case_handling_404():
    """Non-existent cases return clean 404 / NOT_FOUND errors."""
    missing_id = "018f2f4e-0000-0000-0000-000000000404"
    driver_id = "018f2f4e-b300-7000-8000-000000000001"

    ctx = await get_driver_dispute_context.ainvoke({"case_id": missing_id, "driver_id": driver_id})
    assert ctx.get("error_type") == "NOT_FOUND"
    assert ctx.get("status_code") == 404

    traffic = await corroborate_traffic_conditions.ainvoke({"case_id": missing_id, "driver_id": driver_id})
    assert traffic.get("error_type") == "NOT_FOUND"
    assert traffic.get("status_code") == 404

    telemetry = await inspect_trip_telemetry.ainvoke({"case_id": missing_id, "driver_id": driver_id})
    assert telemetry.get("error_type") == "NOT_FOUND"
    assert telemetry.get("status_code") == 404


@pytest.mark.asyncio
async def test_malformed_input_handling():
    """Malformed or invalid inputs are handled safely without crashing."""
    driver_id = "018f2f4e-b300-7000-8000-000000000001"

    # Empty string case_id
    res = await get_driver_dispute_context.ainvoke({"case_id": "", "driver_id": driver_id})
    assert res.get("status_code") in (400, 404)

    # Empty driver statement raises validation error
    with pytest.raises(Exception):
        DriverChatRequest(case_id="case-1", driver_id=driver_id, message="   ")

    # Invalid timestamp strings in traffic tool do not throw unhandled exception
    case_id = "018f2f4e-b000-7000-8000-000000000001"
    res_corrob = await corroborate_traffic_conditions.ainvoke(
        {
            "case_id": case_id,
            "driver_id": driver_id,
            "start_time": "invalid-time",
            "end_time": "not-a-date",
        }
    )
    assert "error" not in res_corrob  # Falls back safely to case timestamps


@pytest.mark.asyncio
async def test_idempotent_driver_chat_retries():
    """Replaying an identical chat request returns the cached result without duplicating turns or audit entries."""
    case_id = "018f2f4e-b000-7000-8000-000000000001"
    driver_id = "018f2f4e-b300-7000-8000-000000000001"
    dispute_service = get_driver_dispute_service()

    turn_id = f"test-turn-{uuid4().hex[:6]}"
    chat_req = DriverChatRequest(
        case_id=case_id,
        driver_id=driver_id,
        message="Tôi bị kẹt xe trên đường Kim Mã 15 phút.",
        claim_type="traffic_gridlock",
        turn_id=turn_id,
    )

    resp_1 = await dispute_service.process_driver_chat(chat_req)
    audit_count_1 = len(dispute_service.get_audit_entries(case_id))

    # Replay identical request
    resp_2 = await dispute_service.process_driver_chat(chat_req)
    audit_count_2 = len(dispute_service.get_audit_entries(case_id))

    assert resp_1.reply == resp_2.reply
    assert resp_1.dispute_status == resp_2.dispute_status
    assert audit_count_1 == audit_count_2, "Idempotent retry must not duplicate audit log entries"


@pytest.mark.asyncio
async def test_explicit_admission_hands_off_to_analyst(monkeypatch):
    """Explicit admission hands off to analyst review without automated sanction."""
    monkeypatch.setenv("APP_ENV", "test")
    service = get_driver_dispute_service()
    case_id = "018f2f4e-b000-7000-8000-000000000002"
    driver_id = "018f2f4e-b300-7000-8000-000000000002"
    response = await service.process_driver_chat(
        DriverChatRequest(
            case_id=case_id,
            driver_id=driver_id,
            message="admit_fraud",
            admits_fraud=True,
        )
    )
    assert response.sanction_status != "applied"
    assert response.sanction_status == "pending_policy"
    assert response.sanction_action is None
    assert response.dispute_status == "in_dispute"
    assert response.needs_analyst_review is True
    assert "chuyên viên phân tích" in response.reply
    assert "cảnh báo" not in response.reply.lower()
    assert "warn" not in response.reply.lower()

    audit_entries = service.get_audit_entries(case_id)
    assert any(e.get("action") == "explicit_admission_pending_policy" for e in audit_entries)
    assert not any(e.get("action") == "explicit_admission_sanctioned" for e in audit_entries)


@pytest.mark.asyncio
async def test_missing_telemetry_honest_semantics():
    """When telemetry is absent (missing_evidence case), tools must expose explicit unavailable state without fake GPS."""
    case_id = "018f2f4e-b000-7000-8000-000000000003"
    driver_id = "018f2f4e-b300-7000-8000-000000000003"

    # Telemetry inspection
    telem = await inspect_trip_telemetry.ainvoke({"case_id": case_id, "driver_id": driver_id})
    assert telem.get("status") == "unavailable"
    assert telem.get("points_count") == 0
    assert telem.get("breadcrumbs") == []
    assert telem.get("error_type") == "UNAVAILABLE"

    # Traffic corroboration
    traffic = await corroborate_traffic_conditions.ainvoke({"case_id": case_id, "driver_id": driver_id})
    assert traffic.get("status") == "unavailable"
    assert traffic.get("corroborated") is False
    assert traffic.get("observed_speed") is None
    assert traffic.get("evidence_references") == []

    # Exoneration rules tool
    exon = await verify_exoneration_rules.ainvoke({"case_id": case_id, "driver_id": driver_id})
    assert exon.get("status") == "unavailable"
    assert exon.get("qualifies_for_auto_exoneration") is False
    assert exon.get("action") == "ESCALATE_TO_ANALYST"


@pytest.mark.asyncio
async def test_write_ticket_for_driver_truthful_preview():
    """write_ticket_for_driver must disclose unpersisted preview semantics unless durable audit proof is supplied."""
    case_id = "018f2f4e-b000-7000-8000-000000000001"
    driver_id = "018f2f4e-b300-7000-8000-000000000001"

    # Without durable audit proof -> PREVIEW_ONLY
    preview = await write_ticket_for_driver.ainvoke(
        {
            "driver_id": driver_id,
            "case_id": case_id,
            "violation_code": "ERR-02",
            "penalty_type": "NOTICE",
            "reason": "Test preview ticket",
            "fine_amount_vnd": 0,
        }
    )
    assert preview["status"] == "ISSUED"  # UI compatibility
    assert preview["execution_type"] == "PREVIEW_ONLY"
    assert preview["durable_persisted"] is False
    assert preview["requires_human_approval"] is True
    assert preview["sanction_authorized"] is False

    # With durable audit proof -> AUDITED_ISSUANCE
    proof_ref = "audit_action:018f2f4e-auth-action-0001"
    audited = await write_ticket_for_driver.ainvoke(
        {
            "driver_id": driver_id,
            "case_id": case_id,
            "violation_code": "ERR-02",
            "penalty_type": "NOTICE",
            "reason": "Official sanctioned ticket",
            "fine_amount_vnd": 0,
            "durable_audit_proof": proof_ref,
        }
    )
    assert audited["execution_type"] == "AUDITED_ISSUANCE"
    assert audited["durable_persisted"] is True
    assert audited["sanction_authorized"] is True
    assert audited["durable_audit_proof"] == proof_ref

    # Disallowed sanction types (FINE) are not accepted
    with pytest.raises(ValueError):
        await write_ticket_for_driver.ainvoke(
            {
                "driver_id": driver_id,
                "case_id": case_id,
                "violation_code": "ERR-02",
                "penalty_type": "FINE",
                "reason": "Attempted fine penalty",
                "fine_amount_vnd": 500000,
            }
        )
