"""TDD Tests for DriverDisputeService (Slice 1).

Tests:
1. Retrieval of driver dispute context
2. Autonomous exoneration when traffic conditions are corroborated (speed < 5 km/h, ratio >= 2.0, valid GPS, 0 sanctions)
3. Escalation when traffic claim is uncorroborated
4. Escalation when claim is non-traffic (e.g. gps_issue, passenger_wait)
5. Past sanctions blocking autonomous exoneration (NFR-L06-02 safety invariant)
6. Invalid GPS / mock location blocking autonomous exoneration
7. Analyst inquiry delegation (deadline setting and transcript update)
8. Dispute dossier compilation for analyst HITL review
"""

from datetime import UTC, datetime, timedelta

import pytest

from src.models.schemas import AnalystDelegateInquiryRequest, DriverChatRequest, PolicyChatRequest
from src.services.case_service import get_case_service
from src.services.driver_dispute_service import get_driver_dispute_service


@pytest.fixture
def case_service(monkeypatch):
    service = get_case_service()
    monkeypatch.setattr(service, "_has_app_tables", False)
    if not service._cases:
        case_id = "018f2f4e-a000-7000-8000-000000000001"
        assignment_id = "018f2f4e-a000-7000-8000-000000000002"
        driver_id = "018f2f4e-a000-7000-8000-000000000003"
        service._drivers[driver_id] = {
            "id": driver_id,
            "display_name": "Tài xế kiểm thử",
            "account_status": "active",
        }
        service._assignments[assignment_id] = {
            "id": assignment_id,
            "driver_id": driver_id,
            "trip_id": "018f2f4e-a000-7000-8000-000000000004",
        }
        service._cases[case_id] = {
            "id": case_id,
            "assignment_id": assignment_id,
            "status": "ready",
            "dispute_status": "not_disputed",
            "suspected_category": "ERR-01",
            "priority_score": 60,
            "priority_tier": 1,
            "priority_rule_version": "v1",
            "version": 1,
        }
    return service


@pytest.fixture
def dispute_service():
    return get_driver_dispute_service()


@pytest.mark.asyncio
async def test_dispute_context_retrieval(case_service, dispute_service):
    """Verify get_driver_dispute_context fetches correct case and driver metadata."""
    case_ids = list(case_service._cases.keys())
    case_id = case_ids[0]
    case = case_service._cases[case_id]
    asgn = case_service._assignments.get(str(case.get("assignment_id")), {})
    driver_id = str(asgn.get("driver_id", ""))

    ctx = await dispute_service.get_driver_dispute_context(case_id, driver_id)

    assert ctx.case_id == case_id
    assert ctx.driver_id
    assert ctx.violation_code is not None
    assert ctx.dispute_status in ("not_disputed", "pending", "in_dispute", "auto_dismissed", "pending_confirmation")
    assert "traffic_gridlock" in ctx.allowed_claim_types


@pytest.mark.asyncio
async def test_corroborated_traffic_claim_awaits_analyst_review(case_service, dispute_service):
    """#73 fix: When driver disputes with traffic_gridlock and all deterministic conditions hold,
    the claim must NOT auto-dismiss. It must produce a pending_review recommendation for analyst.

    PRD FR-03: human-confirmed dismissal only. No autonomous closure is permitted.

    RED (before fix): test_autonomous_exoneration_on_corroborated_traffic asserted is_auto_dismissed=True.
    GREEN (after fix): corroborated claim yields pending_review, needs_analyst_review=True.
    """
    case_id = "test-corroborated-prd-001"
    driver_id = "drv-corroborated-001"
    asgn_id = "asgn-corroborated-001"

    case_service._drivers[driver_id] = {
        "id": driver_id,
        "display_name": "Phạm Văn Lái Xe",
        "account_status": "active",
    }
    case_service._assignments[asgn_id] = {
        "id": asgn_id,
        "driver_id": driver_id,
        "trip_id": "trip-corroborated-001",
    }
    case_service._cases[case_id] = {
        "id": case_id,
        "assignment_id": asgn_id,
        "status": "ready",
        "dispute_status": "not_disputed",
        "suspected_category": "ERR-01",
        "priority_score": 60,
        "priority_tier": 1,
        "priority_rule_version": "v1",
        "version": 1,
    }

    # Deterministic traffic data: speed 2.2 km/h (< 5.0), ratio 2.8 (>= 2.0), valid GPS, 0 sanctions
    dispute_service._traffic_overrides[case_id] = {
        "observed_speed": 2.2,
        "ratio": 2.8,
        "congestion_level": "heavy",
        "gps_valid": True,
        "prior_sanctions": 0,
    }

    chat_req = DriverChatRequest(
        case_id=case_id,
        driver_id=driver_id,
        message="Đoạn này ùn tắc tê liệt, không thể di chuyển được",
        claim_type="traffic_gridlock",
    )

    resp = await dispute_service.process_driver_chat(chat_req)

    # #73 invariants: no autonomous closure, needs analyst review
    assert resp.is_auto_dismissed is False, "REGRESSION: corroborated traffic claim must NOT auto-dismiss (PRD FR-03)"
    assert resp.needs_analyst_review is True, "Corroborated claim must flag needs_analyst_review=True"
    assert resp.exoneration_receipt is None, "No exoneration receipt before authorized analyst confirmation"
    assert resp.dispute_status in ("pending_review", "in_dispute"), (
        f"Expected pending_review or in_dispute, got {resp.dispute_status!r}"
    )

    # Verify case state transitioned to pending_analyst_review (not auto_dismissed)
    updated_case = case_service._cases.get(case_id, {})
    assert updated_case.get("status") != "auto_dismissed", "Case must not be auto_dismissed after corroborated claim"

    # Verify corroboration evidence preserved in audit (not erased)
    audit_events = dispute_service.get_audit_entries(case_id)
    assert len(audit_events) >= 1
    # Must NOT have autonomous_exoneration action
    auto_exon_events = [e for e in audit_events if e["action"] == "autonomous_exoneration"]
    assert len(auto_exon_events) == 0, "autonomous_exoneration audit event must not be recorded (PRD FR-03)"
    # Must have the pending review recommendation
    pending_events = [e for e in audit_events if "pending_review" in e["action"] or "corroboration" in e["action"]]
    assert len(pending_events) >= 1, "Corroboration evidence must be preserved in audit record"


@pytest.mark.asyncio
async def test_uncorroborated_traffic_claim_escalates(case_service, dispute_service):
    """When traffic data shows speed >= 5 km/h or ratio < 2.0:
    escalate to in_dispute for analyst review; zero automated sanction.
    """
    case_id = "test-uncorrob-002"
    driver_id = "drv-uncorrob-002"
    asgn_id = "asgn-uncorrob-002"

    case_service._drivers[driver_id] = {
        "id": driver_id,
        "display_name": "Lê Văn Tốc Độ",
        "account_status": "active",
    }
    case_service._assignments[asgn_id] = {
        "id": asgn_id,
        "driver_id": driver_id,
        "trip_id": "trip-uncorrob-002",
    }
    case_service._cases[case_id] = {
        "id": case_id,
        "assignment_id": asgn_id,
        "status": "ready",
        "dispute_status": "not_disputed",
        "suspected_category": "ERR-01",
        "priority_score": 60,
        "priority_tier": 1,
        "priority_rule_version": "v1",
        "version": 1,
    }

    # Speed 18 km/h, ratio 1.2 -> Uncorroborated
    dispute_service._traffic_overrides[case_id] = {
        "observed_speed": 18.0,
        "ratio": 1.2,
        "congestion_level": "clear",
        "gps_valid": True,
        "prior_sanctions": 0,
    }

    chat_req = DriverChatRequest(
        case_id=case_id,
        driver_id=driver_id,
        message="Tôi bị kẹt xe",
        claim_type="traffic_gridlock",
    )

    resp = await dispute_service.process_driver_chat(chat_req)

    assert resp.is_auto_dismissed is False
    assert resp.dispute_status == "in_dispute"
    assert resp.needs_analyst_review is True
    assert resp.exoneration_receipt is None

    # Case must transition to driver_disputed
    assert case_service._cases[case_id]["status"] == "driver_disputed"
    assert case_service._cases[case_id]["dispute_status"] == "in_dispute"


@pytest.mark.asyncio
async def test_non_traffic_claim_escalates(case_service, dispute_service):
    """Non-traffic claims (e.g. gps_issue, passenger_wait, other) require human review."""
    case_id = "test-other-claim-003"
    driver_id = "drv-other-003"
    asgn_id = "asgn-other-003"

    case_service._drivers[driver_id] = {
        "id": driver_id,
        "display_name": "Hoàng Văn Chờ",
        "account_status": "active",
    }
    case_service._assignments[asgn_id] = {
        "id": asgn_id,
        "driver_id": driver_id,
        "trip_id": "trip-other-003",
    }
    case_service._cases[case_id] = {
        "id": case_id,
        "assignment_id": asgn_id,
        "status": "ready",
        "dispute_status": "not_disputed",
        "suspected_category": "ERR-01",
        "priority_score": 60,
        "priority_tier": 1,
        "priority_rule_version": "v1",
        "version": 1,
    }

    chat_req = DriverChatRequest(
        case_id=case_id,
        driver_id=driver_id,
        message="Khách hàng yêu cầu đợi thêm 10 phút tại sảnh",
        claim_type="passenger_wait",
    )

    resp = await dispute_service.process_driver_chat(chat_req)

    assert resp.is_auto_dismissed is False
    assert resp.dispute_status == "in_dispute"
    assert resp.needs_analyst_review is True
    assert case_service._cases[case_id]["status"] == "driver_disputed"
    assert case_service._cases[case_id]["dispute_status"] == "in_dispute"


@pytest.mark.asyncio
async def test_past_sanctions_blocks_auto_exoneration(case_service, dispute_service):
    """Driver with prior sanctions (>0) cannot be autonomously exonerated (safety invariant)."""
    case_id = "test-prior-sanction-004"
    driver_id = "drv-prior-004"
    asgn_id = "asgn-prior-004"

    case_service._drivers[driver_id] = {
        "id": driver_id,
        "display_name": "Đỗ Văn Vi Phạm Cũ",
        "account_status": "active",
    }
    case_service._assignments[asgn_id] = {
        "id": asgn_id,
        "driver_id": driver_id,
        "trip_id": "trip-prior-004",
    }
    case_service._cases[case_id] = {
        "id": case_id,
        "assignment_id": asgn_id,
        "status": "ready",
        "dispute_status": "not_disputed",
        "suspected_category": "ERR-01",
        "priority_score": 60,
        "priority_tier": 1,
        "priority_rule_version": "v1",
        "version": 1,
    }

    # Traffic is slow and ratio >= 2.0, BUT prior_sanctions = 1
    dispute_service._traffic_overrides[case_id] = {
        "observed_speed": 1.5,
        "ratio": 3.0,
        "congestion_level": "heavy",
        "gps_valid": True,
        "prior_sanctions": 1,
    }

    chat_req = DriverChatRequest(
        case_id=case_id,
        driver_id=driver_id,
        message="Kẹt xe cứng nhắc ở đường Giải Phóng",
        claim_type="traffic_gridlock",
    )

    resp = await dispute_service.process_driver_chat(chat_req)

    assert resp.is_auto_dismissed is False
    assert resp.dispute_status == "in_dispute"
    assert resp.needs_analyst_review is True


@pytest.mark.asyncio
async def test_invalid_gps_blocks_auto_exoneration(case_service, dispute_service):
    """Driver with invalid/mock GPS telemetry cannot be autonomously exonerated."""
    case_id = "test-mock-gps-005"
    driver_id = "drv-mock-005"
    asgn_id = "asgn-mock-005"

    case_service._drivers[driver_id] = {
        "id": driver_id,
        "display_name": "Ngô Văn Fake GPS",
        "account_status": "active",
    }
    case_service._assignments[asgn_id] = {
        "id": asgn_id,
        "driver_id": driver_id,
        "trip_id": "trip-mock-005",
    }
    case_service._cases[case_id] = {
        "id": case_id,
        "assignment_id": asgn_id,
        "status": "ready",
        "dispute_status": "not_disputed",
        "suspected_category": "ERR-01",
        "priority_score": 60,
        "priority_tier": 1,
        "priority_rule_version": "v1",
        "version": 1,
    }

    dispute_service._traffic_overrides[case_id] = {
        "observed_speed": 1.0,
        "ratio": 3.5,
        "congestion_level": "heavy",
        "gps_valid": False,  # Mock/jitter detected
        "prior_sanctions": 0,
    }

    chat_req = DriverChatRequest(
        case_id=case_id,
        driver_id=driver_id,
        message="Kẹt xe nên đứng im",
        claim_type="traffic_gridlock",
    )

    resp = await dispute_service.process_driver_chat(chat_req)

    assert resp.is_auto_dismissed is False
    assert resp.needs_analyst_review is True


@pytest.mark.asyncio
async def test_delegate_analyst_inquiry(case_service, dispute_service):
    """Analyst delegates inquiry to driver: dispute_status -> 'pending', deadline set, instruction logged."""
    case_id = "018f2f4e-a000-7000-8000-000000000806"
    driver_id = "drv-delegate-006"
    asgn_id = "018f2f4e-a000-7000-8000-000000000807"

    case_service._drivers[driver_id] = {
        "id": driver_id,
        "display_name": "Vũ Văn Hỏi",
        "account_status": "active",
    }
    case_service._assignments[asgn_id] = {
        "id": asgn_id,
        "driver_id": driver_id,
        "trip_id": "trip-delegate-006",
    }
    case_service._cases[case_id] = {
        "id": case_id,
        "assignment_id": asgn_id,
        "status": "ready",
        "dispute_status": "not_disputed",
        "suspected_category": "ERR-01",
        "priority_score": 60,
        "priority_tier": 1,
        "priority_rule_version": "v1",
        "version": 1,
    }

    inquiry_req = AnalystDelegateInquiryRequest(
        case_id=case_id,
        analyst_id="analyst-01",
        instruction="Vui lòng cung cấp lý do dừng đón khách quá 5 phút tại điểm hẹn.",
        deadline_hours=48,
    )

    res = await dispute_service.delegate_analyst_inquiry(case_id, inquiry_req)

    assert res["dispute_status"] == "pending"
    assert "dispute_deadline" in res
    assert case_service._cases[case_id]["dispute_status"] == "pending"
    assert case_service._cases[case_id]["dispute_deadline"] is not None

    private_turn = PolicyChatRequest(query="nội bộ", case_id=case_id)
    case_service._begin_case_agent_turn(private_turn, organization_id=None, actor_id="analyst-private")
    session_id = case_service._agent_sessions[case_id]["session_id"]
    case_service._append_case_agent_reply(session_id, str(private_turn.turn_id), "ghi chú nội bộ")

    session = await dispute_service.get_driver_session(case_id)
    analyst_messages = [m for m in session["messages"] if m["role"] == "analyst"]
    assert len(analyst_messages) == 1
    assert analyst_messages[0]["content"] == (
        "[Yêu cầu từ Chuyên viên giám sát analyst-01]: Vui lòng cung cấp lý do dừng đón khách quá 5 phút tại điểm hẹn."
    )
    assert all(m["role"] not in {"user", "assistant"} for m in session["messages"])


@pytest.mark.asyncio
async def test_delegate_analyst_inquiry_is_idempotent_by_turn_id(case_service, dispute_service):
    case_id = "018f2f4e-a000-7000-8000-000000000808"
    driver_id = "drv-delegate-idempotent-008"
    asgn_id = "018f2f4e-a000-7000-8000-000000000809"
    case_service._drivers[driver_id] = {
        "id": driver_id,
        "display_name": "Tài xế Idempotent",
        "account_status": "active",
    }
    case_service._assignments[asgn_id] = {"id": asgn_id, "driver_id": driver_id, "trip_id": "trip-idempotent-008"}
    case_service._cases[case_id] = {
        "id": case_id,
        "assignment_id": asgn_id,
        "status": "ready",
        "dispute_status": "not_disputed",
        "suspected_category": "ERR-01",
        "priority_score": 60,
        "priority_tier": 1,
        "priority_rule_version": "v1",
        "version": 1,
    }
    request = AnalystDelegateInquiryRequest(
        case_id=case_id,
        analyst_id="analyst-idempotent",
        instruction="Xin xác nhận vị trí đón khách.",
        turn_id="stable-inquiry-turn-008",
    )

    await dispute_service.delegate_analyst_inquiry(case_id, request)
    await dispute_service.delegate_analyst_inquiry(case_id, request)

    session = await dispute_service.get_driver_session(case_id)
    matching = [m for m in session["messages"] if m["role"] == "analyst" and m["turn_id"] == "stable-inquiry-turn-008"]
    assert len(matching) == 1


@pytest.mark.asyncio
async def test_get_dispute_dossier(case_service, dispute_service):
    """Verify get_dispute_dossier returns complete evidence dossier for analyst review."""
    case_id = "test-dossier-007"
    driver_id = "drv-dossier-007"
    asgn_id = "asgn-dossier-007"

    case_service._drivers[driver_id] = {
        "id": driver_id,
        "display_name": "Bùi Văn Hồ Sơ",
        "account_status": "active",
    }
    case_service._assignments[asgn_id] = {
        "id": asgn_id,
        "driver_id": driver_id,
        "trip_id": "trip-dossier-007",
    }
    case_service._cases[case_id] = {
        "id": case_id,
        "assignment_id": asgn_id,
        "status": "ready",
        "dispute_status": "not_disputed",
        "suspected_category": "ERR-01",
        "priority_score": 60,
        "priority_tier": 1,
        "priority_rule_version": "v1",
        "version": 1,
    }

    # Driver chats first
    chat_req = DriverChatRequest(
        case_id=case_id,
        driver_id=driver_id,
        message="Tôi phải chờ đèn đỏ 3 nhịp và có va chạm giao thông phía trước",
        claim_type="traffic_gridlock",
    )
    dispute_service._traffic_overrides[case_id] = {
        "observed_speed": 12.0,
        "ratio": 1.4,
        "congestion_level": "moderate",
        "gps_valid": True,
        "prior_sanctions": 0,
    }
    await dispute_service.process_driver_chat(chat_req)

    # Fetch dossier
    dossier = await dispute_service.get_dispute_dossier(case_id)

    assert dossier.case_id == case_id
    assert dossier.driver_id == driver_id
    assert dossier.driver_name == "Bùi Văn Hồ Sơ"
    assert dossier.dispute_status == "in_dispute"
    assert dossier.claim_type == "traffic_gridlock"
    assert "ratio" in dossier.traffic_corroboration
    assert "observed_speed" in dossier.traffic_corroboration
    assert "congestion_level" in dossier.traffic_corroboration
    assert len(dossier.transcript) >= 1
    assert dossier.recommended_action is not None


@pytest.mark.asyncio
async def test_driver_chat_rejected_on_expired_deadline(case_service, dispute_service):
    """When dispute_deadline is in the past, process_driver_chat returns dispute_status='closed' with explanation message."""
    case_id = "test-expired-deadline-008"
    driver_id = "drv-expired-008"
    asgn_id = "asgn-expired-008"

    case_service._drivers[driver_id] = {
        "id": driver_id,
        "display_name": "Trần Văn Quá Hạn",
        "account_status": "active",
    }
    case_service._assignments[asgn_id] = {
        "id": asgn_id,
        "driver_id": driver_id,
        "trip_id": "trip-expired-008",
    }
    expired_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    case_service._cases[case_id] = {
        "id": case_id,
        "assignment_id": asgn_id,
        "status": "ready",
        "dispute_status": "pending",
        "dispute_deadline": expired_time,
        "suspected_category": "ERR-01",
        "priority_score": 60,
        "priority_tier": 1,
        "priority_rule_version": "v1",
        "version": 1,
    }

    chat_req = DriverChatRequest(
        case_id=case_id,
        driver_id=driver_id,
        message="Tôi muốn giải trình về chuyến xe này nhưng bị trễ",
        claim_type="traffic_gridlock",
    )

    resp = await dispute_service.process_driver_chat(chat_req)

    assert resp.dispute_status == "closed"
    assert "Thời hạn gửi khiếu nại" in resp.reply
    assert resp.is_auto_dismissed is False
    assert resp.needs_analyst_review is False


@pytest.mark.asyncio
async def test_driver_chat_on_already_resolved_case(case_service, dispute_service):
    """When case.status in ('resolved', 'auto_dismissed'), process_driver_chat informs that case is finalized without modifying case."""
    # Test case with status = resolved
    case_id_resolved = "test-resolved-009"
    driver_id_resolved = "drv-resolved-009"
    asgn_id_resolved = "asgn-resolved-009"

    case_service._drivers[driver_id_resolved] = {
        "id": driver_id_resolved,
        "display_name": "Lê Văn Đã Xong",
        "account_status": "active",
    }
    case_service._assignments[asgn_id_resolved] = {
        "id": asgn_id_resolved,
        "driver_id": driver_id_resolved,
        "trip_id": "trip-resolved-009",
    }
    case_service._cases[case_id_resolved] = {
        "id": case_id_resolved,
        "assignment_id": asgn_id_resolved,
        "status": "resolved",
        "dispute_status": "not_disputed",
        "suspected_category": "ERR-01",
        "priority_score": 60,
        "priority_tier": 1,
        "priority_rule_version": "v1",
        "version": 1,
    }

    chat_req_resolved = DriverChatRequest(
        case_id=case_id_resolved,
        driver_id=driver_id_resolved,
        message="Tôi muốn khiếu nại tiếp",
    )

    resp_resolved = await dispute_service.process_driver_chat(chat_req_resolved)
    assert resp_resolved.needs_analyst_review is False
    assert resp_resolved.is_auto_dismissed is False
    assert "Vụ việc đã được xử lý xong (Trạng thái: resolved)" in resp_resolved.reply
    # Case must not be modified
    assert case_service._cases[case_id_resolved]["status"] == "resolved"
    assert case_service._cases[case_id_resolved]["dispute_status"] == "not_disputed"

    # Test case with status = auto_dismissed
    case_id_dismissed = "test-dismissed-010"
    driver_id_dismissed = "drv-dismissed-010"
    asgn_id_dismissed = "asgn-dismissed-010"

    case_service._drivers[driver_id_dismissed] = {
        "id": driver_id_dismissed,
        "display_name": "Phạm Văn Miễn Trừ",
        "account_status": "active",
    }
    case_service._assignments[asgn_id_dismissed] = {
        "id": asgn_id_dismissed,
        "driver_id": driver_id_dismissed,
        "trip_id": "trip-dismissed-010",
    }
    fake_receipt = {"receipt_id": "rcpt-010", "verdict": "exonerated"}
    dispute_service._exoneration_receipts[case_id_dismissed] = fake_receipt
    case_service._cases[case_id_dismissed] = {
        "id": case_id_dismissed,
        "assignment_id": asgn_id_dismissed,
        "status": "auto_dismissed",
        "dispute_status": "auto_dismissed",
        "suspected_category": "ERR-01",
        "priority_score": 60,
        "priority_tier": 1,
        "priority_rule_version": "v1",
        "version": 1,
    }

    chat_req_dismissed = DriverChatRequest(
        case_id=case_id_dismissed,
        driver_id=driver_id_dismissed,
        message="Kiểm tra lại giúp tôi",
    )

    resp_dismissed = await dispute_service.process_driver_chat(chat_req_dismissed)
    assert resp_dismissed.needs_analyst_review is False
    assert resp_dismissed.is_auto_dismissed is True
    assert "Vụ việc đã được xử lý xong (Trạng thái: auto_dismissed)" in resp_dismissed.reply
    assert resp_dismissed.exoneration_receipt == fake_receipt
    # Case must not be modified
    assert case_service._cases[case_id_dismissed]["status"] == "auto_dismissed"
    assert case_service._cases[case_id_dismissed]["dispute_status"] == "auto_dismissed"


@pytest.mark.asyncio
async def test_autonomous_exoneration_blocked_by_prior_sanctions(case_service, dispute_service):
    """Driver with prior_sanctions = 2 submitting traffic gridlock is escalated (status='driver_disputed', dispute_status='in_dispute'), NOT auto-dismissed."""
    case_id = "test-prior-2-sanctions-011"
    driver_id = "drv-prior-2-011"
    asgn_id = "asgn-prior-2-011"

    case_service._drivers[driver_id] = {
        "id": driver_id,
        "display_name": "Hoàng Văn 2 Phạt",
        "account_status": "active",
    }
    case_service._assignments[asgn_id] = {
        "id": asgn_id,
        "driver_id": driver_id,
        "trip_id": "trip-prior-2-011",
    }
    case_service._cases[case_id] = {
        "id": case_id,
        "assignment_id": asgn_id,
        "status": "ready",
        "dispute_status": "not_disputed",
        "suspected_category": "ERR-01",
        "priority_score": 60,
        "priority_tier": 1,
        "priority_rule_version": "v1",
        "version": 1,
    }

    # Deterministic traffic data with speed < 5 km/h, ratio >= 2.0, valid GPS, but prior_sanctions = 2
    dispute_service._traffic_overrides[case_id] = {
        "observed_speed": 2.0,
        "ratio": 2.5,
        "congestion_level": "heavy",
        "gps_valid": True,
        "prior_sanctions": 2,
    }

    chat_req = DriverChatRequest(
        case_id=case_id,
        driver_id=driver_id,
        message="Tôi bị kẹt xe cứng nhắc ở đường Nguyễn Trãi",
        claim_type="traffic_gridlock",
    )

    resp = await dispute_service.process_driver_chat(chat_req)

    assert resp.is_auto_dismissed is False
    assert resp.dispute_status == "in_dispute"
    assert resp.needs_analyst_review is True
    assert case_service._cases[case_id]["status"] == "driver_disputed"
    assert case_service._cases[case_id]["dispute_status"] == "in_dispute"


@pytest.mark.asyncio
async def test_autonomous_exoneration_blocked_by_mock_location(case_service, dispute_service):
    """Telemetry with gps_valid=False submitting traffic gridlock is escalated, NOT auto-dismissed."""
    case_id = "test-mock-gps-012"
    driver_id = "drv-mock-gps-012"
    asgn_id = "asgn-mock-gps-012"

    case_service._drivers[driver_id] = {
        "id": driver_id,
        "display_name": "Đặng Văn Mock GPS",
        "account_status": "active",
    }
    case_service._assignments[asgn_id] = {
        "id": asgn_id,
        "driver_id": driver_id,
        "trip_id": "trip-mock-gps-012",
    }
    case_service._cases[case_id] = {
        "id": case_id,
        "assignment_id": asgn_id,
        "status": "ready",
        "dispute_status": "not_disputed",
        "suspected_category": "ERR-01",
        "priority_score": 60,
        "priority_tier": 1,
        "priority_rule_version": "v1",
        "version": 1,
    }

    dispute_service._traffic_overrides[case_id] = {
        "observed_speed": 1.5,
        "ratio": 3.0,
        "congestion_level": "heavy",
        "gps_valid": False,  # Mock location
        "prior_sanctions": 0,
    }

    chat_req = DriverChatRequest(
        case_id=case_id,
        driver_id=driver_id,
        message="Kẹt xe cả tiếng không nhúc nhích được",
        claim_type="traffic_gridlock",
    )

    resp = await dispute_service.process_driver_chat(chat_req)

    assert resp.is_auto_dismissed is False
    assert resp.dispute_status == "in_dispute"
    assert resp.needs_analyst_review is True
    assert case_service._cases[case_id]["status"] == "driver_disputed"
    assert case_service._cases[case_id]["dispute_status"] == "in_dispute"


@pytest.mark.asyncio
async def test_pending_analyst_review_case_blocks_resubmission(case_service, dispute_service):
    """#73: A case in pending_analyst_review must inform driver and not re-process claim.

    Prevents double-processing of claims while analyst is reviewing.
    Evidence state must not be modified.
    """
    case_id = "test-pending-review-013"
    driver_id = "drv-pending-013"
    asgn_id = "asgn-pending-013"

    case_service._drivers[driver_id] = {
        "id": driver_id,
        "display_name": "Nguyễn Văn Đợi Duyệt",
        "account_status": "active",
    }
    case_service._assignments[asgn_id] = {
        "id": asgn_id,
        "driver_id": driver_id,
        "trip_id": "trip-pending-013",
    }
    case_service._cases[case_id] = {
        "id": case_id,
        "assignment_id": asgn_id,
        "status": "pending_analyst_review",
        "dispute_status": "pending_review",
        "suspected_category": "ERR-02",
        "priority_score": 60,
        "priority_tier": 1,
        "priority_rule_version": "v1",
        "version": 1,
    }

    chat_req = DriverChatRequest(
        case_id=case_id,
        driver_id=driver_id,
        message="Xin hãy xem xét lại giúp tôi",
        claim_type="traffic_gridlock",
    )

    resp = await dispute_service.process_driver_chat(chat_req)

    assert resp.is_auto_dismissed is False
    assert resp.needs_analyst_review is True
    assert resp.exoneration_receipt is None
    assert resp.dispute_status == "pending_review"
    # Case state must not have changed
    assert case_service._cases[case_id]["status"] == "pending_analyst_review"
    assert case_service._cases[case_id]["dispute_status"] == "pending_review"


@pytest.mark.asyncio
async def test_err_taxonomy_uses_canonical_prd_labels(dispute_service):
    """ERR title map must match PRD taxonomy (not old inverted labels).

    PRD:
      ERR-01: off-platform cash (embezzlement)
      ERR-02: route deviation / stall-to-cancel
      ERR-03: incentive/policy exploitation
      ERR-04: phantom trip
      ERR-05: fake GPS / tech manipulation
    """
    from src.services.driver_dispute_service import VIOLATION_TITLE_MAP

    # ERR-02 must mention route/deviation/stall-to-cancel, not delay/GPS
    assert any(kw in VIOLATION_TITLE_MAP.get("ERR-02", "").lower() for kw in ["lệch", "stall", "deviation", "hủy"]), (
        f"ERR-02 title incorrect: {VIOLATION_TITLE_MAP.get('ERR-02')}"
    )

    # ERR-03 must mention incentive/policy exploitation, not GPS
    err03 = VIOLATION_TITLE_MAP.get("ERR-03", "").lower()
    assert any(kw in err03 for kw in ["khuyến mãi", "incentive", "exploitation", "gaming"]), (
        f"ERR-03 title incorrect: {VIOLATION_TITLE_MAP.get('ERR-03')}"
    )

    # ERR-04 must mention phantom/collusion, not GPS jitter
    err04 = VIOLATION_TITLE_MAP.get("ERR-04", "").lower()
    assert any(kw in err04 for kw in ["ảo", "phantom", "collusive", "virtual"]), (
        f"ERR-04 title incorrect: {VIOLATION_TITLE_MAP.get('ERR-04')}"
    )

    # ERR-05 must mention fake GPS / tech manipulation
    err05 = VIOLATION_TITLE_MAP.get("ERR-05", "").lower()
    assert any(kw in err05 for kw in ["giả", "fake", "manipulation", "spoofed"]), (
        f"ERR-05 title incorrect: {VIOLATION_TITLE_MAP.get('ERR-05')}"
    )
