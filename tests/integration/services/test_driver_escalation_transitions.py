"""Integration tests for driver escalation transitions, intent routing, and ownership checks (Issue #573 item 4).

TDD test suite verifying:
1. When driver explicitly asks to escalate (with/without diacritics, English), dispute_status moves to 'in_dispute',
   case status moves to 'driver_disputed', audit event is recorded, and reply confirms without repeating the question.
2. Escalation works from any initial state (not_disputed, pending_confirmation, etc.).
3. When driver accepts closure ('dong y ket thuc', 'confirm_resolution'), case closes as resolved with zero sanctions.
4. Stop re-issuing identical canned paragraph every turn when driver provides follow-up info during pending confirmation.
5. Tenant and driver identity mismatch checks reject unauthorized access (403
   for tenant/org scope checks; 404 anti-probing for cross-driver case access
   via `process_driver_chat`, per the driver-app redesign hardening).
"""

import pytest
from fastapi import HTTPException

from src.models.schemas import DriverChatRequest
from src.services.case_service import get_case_service
from src.services.driver_dispute_service import get_driver_dispute_service


@pytest.fixture
def case_service():
    return get_case_service()


@pytest.fixture
def dispute_service():
    return get_driver_dispute_service()


def _setup_test_case(
    case_service,
    case_id: str,
    driver_id: str,
    status: str = "ready",
    dispute_status: str = "not_disputed",
    organization_id: str = "018f2f4e-0000-7000-8000-000000000001",
    confidence: float | None = 0.75,
):
    asgn_id = f"asgn-{case_id}"
    case_service._drivers[driver_id] = {
        "id": driver_id,
        "display_name": f"Driver {driver_id}",
        "account_status": "active",
        "organization_id": organization_id,
    }
    case_service._assignments[asgn_id] = {
        "id": asgn_id,
        "driver_id": driver_id,
        "trip_id": f"trip-{case_id}",
    }
    case_data = {
        "id": case_id,
        "assignment_id": asgn_id,
        "driver_id": driver_id,
        "status": status,
        "dispute_status": dispute_status,
        "suspected_category": "ERR-01",
        "priority_score": 75,
        "priority_tier": 1,
        "priority_rule_version": "v1",
        "version": 1,
        "organization_id": organization_id,
    }
    if confidence is not None:
        case_data["confidence"] = confidence
    case_service._cases[case_id] = case_data
    return case_id, driver_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "escalate_msg",
    [
        "Toi muon tiep tuc khieu nai len chuyen vien giam sat",
        "Tôi muốn tiếp tục khiếu nại lên chuyên viên giám sát",
        "Tôi muốn khiếu nại lên chuyên viên",
        "Chuyển cho chuyên viên giúp tôi",
        "I want to escalate to a fraud analyst",
    ],
)
async def test_explicit_escalation_transitions_case_to_in_dispute(case_service, dispute_service, escalate_msg):
    """When driver explicitly asks to escalate, dispute_status moves to 'in_dispute',
    status moves to 'driver_disputed', audit event is recorded, and reply does not repeat the question.
    """
    case_id, driver_id = _setup_test_case(case_service, f"case-esc-{hash(escalate_msg)}", "drv-esc-001")

    req = DriverChatRequest(
        case_id=case_id,
        driver_id=driver_id,
        message=escalate_msg,
    )
    resp = await dispute_service.process_driver_chat(req)

    # 1. State transition
    assert resp.dispute_status == "in_dispute"
    assert resp.needs_analyst_review is True
    assert case_service._cases[case_id]["status"] == "driver_disputed"
    assert case_service._cases[case_id]["dispute_status"] == "in_dispute"

    # 2. Reply does not repeat the canned question
    assert "Bạn có muốn tiếp tục khiếu nại" not in resp.reply
    assert "hay Đồng ý kết thúc vụ việc" not in resp.reply
    assert "chuyên viên" in resp.reply.lower() or "analyst" in resp.reply.lower()

    # 3. Audit trail
    audit = dispute_service.get_audit_entries(case_id)
    escalate_events = [e for e in audit if e["action"] == "driver_appeal_escalated"]
    assert len(escalate_events) >= 1
    assert escalate_events[-1]["result"] in ("escalated", "accepted")


@pytest.mark.asyncio
async def test_escalation_from_pending_confirmation_reproduces_and_fixes_573(case_service, dispute_service):
    """Exact reproduction of issue #573 item 4:
    Turn 1 asks whether to appeal or close.
    Turn 2 driver sends 'Toi muon tiep tuc khieu nai len chuyen vien giam sat'.
    Must transition to in_dispute, not repeat canned text, and update dispute context.
    """
    case_id, driver_id = _setup_test_case(case_service, "case-c2c8309b-test", "drv-gmail-001", confidence=0.78)

    # Turn 1: Initial driver explanation
    t1_req = DriverChatRequest(
        case_id=case_id,
        driver_id=driver_id,
        message="Tôi bị kẹt xe trên đường Kim Mã",
        claim_type="traffic_gridlock",
    )
    resp_t1 = await dispute_service.process_driver_chat(t1_req)
    assert resp_t1.dispute_status == "pending_confirmation"
    assert "Bạn có muốn tiếp tục khiếu nại" in resp_t1.reply

    # Turn 2: Driver escalates
    t2_req = DriverChatRequest(
        case_id=case_id,
        driver_id=driver_id,
        message="Toi muon tiep tuc khieu nai len chuyen vien giam sat",
    )
    resp_t2 = await dispute_service.process_driver_chat(t2_req)

    assert resp_t2.dispute_status == "in_dispute"
    assert resp_t2.needs_analyst_review is True
    assert case_service._cases[case_id]["status"] == "driver_disputed"
    assert case_service._cases[case_id]["dispute_status"] == "in_dispute"
    assert "Bạn có muốn tiếp tục khiếu nại" not in resp_t2.reply

    # Verify GET dispute context reflects updated dispute_status
    ctx = await dispute_service.get_dispute_context(case_id, driver_id=driver_id)
    assert ctx.dispute_status == "in_dispute"


@pytest.mark.asyncio
@pytest.mark.parametrize("closure_msg", ["dong y ket thuc", "Đồng ý kết thúc", "no_further_appeal"])
async def test_acceptance_of_closure_closes_case_without_sanction(case_service, dispute_service, closure_msg):
    """When driver accepts closure, case is closed with status=driver_confirmed_resolution, dispute_status=resolved."""
    case_id, driver_id = _setup_test_case(
        case_service,
        f"case-close-{hash(closure_msg)}",
        "drv-close-001",
        status="pending_driver_confirmation",
        dispute_status="pending_confirmation",
    )

    req = DriverChatRequest(
        case_id=case_id,
        driver_id=driver_id,
        message=closure_msg,
    )
    resp = await dispute_service.process_driver_chat(req)

    assert resp.dispute_status == "resolved"
    assert resp.needs_analyst_review is False
    assert case_service._cases[case_id]["status"] == "driver_confirmed_resolution"
    assert case_service._cases[case_id]["dispute_status"] == "resolved"

    audit = dispute_service.get_audit_entries(case_id)
    close_events = [e for e in audit if e["action"] == "driver_confirmed_resolution"]
    assert len(close_events) >= 1
    assert close_events[-1]["payload"].get("sanction_applied") is None


@pytest.mark.asyncio
async def test_stop_reissuing_same_canned_paragraph_every_turn(case_service, dispute_service):
    """When driver provides follow-up remarks during pending confirmation without escalating or closing,
    system does NOT re-issue the initial canned paragraph containing speed/ratio/confidence metrics.
    """
    case_id, driver_id = _setup_test_case(case_service, "case-canned-test", "drv-canned-001", confidence=0.75)

    # Turn 1: Initial traffic explanation -> receives canned confirmation question with metrics
    t1_req = DriverChatRequest(
        case_id=case_id,
        driver_id=driver_id,
        message="Đường tắc nghẽn nặng",
        claim_type="traffic_gridlock",
    )
    resp_t1 = await dispute_service.process_driver_chat(t1_req)
    assert resp_t1.dispute_status == "pending_confirmation"
    first_reply = resp_t1.reply
    assert "Điều 12.2" in first_reply

    # Turn 2: Follow-up statement that is neither escalation nor closure
    t2_req = DriverChatRequest(
        case_id=case_id,
        driver_id=driver_id,
        message="Tôi có gửi thêm hình ảnh chụp công trường lúc đó",
    )
    resp_t2 = await dispute_service.process_driver_chat(t2_req)

    # Must NOT repeat the exact same canned paragraph
    assert resp_t2.reply != first_reply
    # Must acknowledge additional info
    assert "bổ sung" in resp_t2.reply.lower() or "ghi nhận" in resp_t2.reply.lower()
    # Must NOT invent new metrics or sanctions
    assert "vận tốc tb:" not in resp_t2.reply.lower()
    assert "tỷ lệ thời gian:" not in resp_t2.reply.lower()


@pytest.mark.asyncio
async def test_driver_identity_mismatch_rejected(case_service, dispute_service):
    """Cross-driver authorization: a driver cannot dispute another driver's case.

    Driver-app redesign (Issue #157) hardened `process_driver_chat` to an
    anti-probing 404 ("Case not found") for any cross-driver access, instead
    of a 403 that would leak case existence to a non-owner. See
    test_driver_agent_contracts.py::test_cross_driver_access_denied_service
    for the authoritative contract this aligns with.
    """
    case_id, driver_id = _setup_test_case(case_service, "case-cross-driver", "drv-authorized-001")

    req = DriverChatRequest(
        case_id=case_id,
        driver_id="drv-attacker-999",
        message="Toi muon tiep tuc khieu nai len chuyen vien giam sat",
    )
    with pytest.raises(HTTPException) as exc_info:
        await dispute_service.process_driver_chat(req)

    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_tenant_and_driver_ownership_checks(case_service, dispute_service):
    """Tenant/driver ownership checks enforce case boundaries."""
    from unittest.mock import MagicMock, patch

    from src.services.access_control import require_case_scope

    org_a = "11111111-1111-4111-8111-111111111111"
    org_b = "22222222-2222-4222-8222-222222222222"
    case_id, driver_id = _setup_test_case(case_service, "case-tenant-check", "drv-owner-001")
    case_service._cases[case_id]["organization_id"] = org_a

    # 1. require_case_scope checks with DB cursor
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"organization_id": org_a, "driver_id": driver_id}
    mock_db = MagicMock()
    mock_db.cursor.return_value.__enter__.return_value = mock_cursor

    with patch.object(case_service, "_get_db_connection", return_value=mock_db):
        # Matching tenant and driver succeeds
        require_case_scope(case_service, case_id, organization_id=org_a, driver_id=driver_id)

        # Cross-tenant access is rejected
        with pytest.raises(HTTPException) as exc_org:
            require_case_scope(case_service, case_id, organization_id=org_b, driver_id=driver_id)
        assert exc_org.value.status_code == 403

        # Wrong driver is rejected
        with pytest.raises(HTTPException) as exc_drv:
            require_case_scope(case_service, case_id, organization_id=org_a, driver_id="drv-intruder-999")
        assert exc_drv.value.status_code == 403
        assert exc_drv.value.detail == "Driver is not assigned to this case"

    # 2. dispute_service list_driver_cases tenant and driver scoping
    dispute_service.settings.test_auth_enabled = False
    with pytest.raises(HTTPException) as exc_list_org:
        await dispute_service.list_driver_cases(driver_id=driver_id, organization_id=None)
    assert exc_list_org.value.status_code == 403

    with pytest.raises(HTTPException) as exc_list_drv:
        await dispute_service.list_driver_cases(driver_id=None, organization_id=org_a)
    assert exc_list_drv.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("closure_msg", ["đồng ý kết thúc", "dong y ket thuc", "confirm_resolution"])
async def test_generic_confirmation_on_non_pending_case_routes_to_analyst(case_service, dispute_service, closure_msg):
    """Safeguard: Generic confirmation/denial on a non-pending case is NOT an admission of fraud.
    It routes to analyst review (status=driver_disputed, dispute_status=in_dispute),
    records driver_denial_escalated audit action, and does NOT resolve the case.
    """
    case_id, driver_id = _setup_test_case(
        case_service,
        f"case-safeguard-{hash(closure_msg)}",
        "drv-safeguard-001",
        status="ready",
        dispute_status="not_disputed",
    )

    req = DriverChatRequest(
        case_id=case_id,
        driver_id=driver_id,
        message=closure_msg,
    )
    resp = await dispute_service.process_driver_chat(req)

    # 1. State must NOT be resolved
    assert resp.dispute_status == "in_dispute"
    assert resp.needs_analyst_review is True
    assert case_service._cases[case_id]["status"] == "driver_disputed"
    assert case_service._cases[case_id]["dispute_status"] == "in_dispute"

    # 2. Reply clarifies confirmation is not fraud admission
    assert "thừa nhận gian lận" in resp.reply.lower() or "chuyên viên" in resp.reply.lower()

    # 3. Audit records denial escalation, not resolution
    audit = dispute_service.get_audit_entries(case_id)
    assert any(e["action"] == "driver_denial_escalated" for e in audit)
    assert not any(e["action"] == "driver_confirmed_resolution" for e in audit)


@pytest.mark.asyncio
async def test_stream_path_escalation_transitions_case_and_records_audit(case_service, dispute_service):
    """Proves stream-path escalation (stream_agent_turn and stream_driver_chat)
    transitions the case to driver_disputed/in_dispute, records driver_appeal_escalated audit,
    and streams reply without repeating the canned question.
    """
    from unittest.mock import patch
    from uuid import uuid4

    from src.api.auth import Principal
    from src.services.agent_runtime import stream_agent_turn

    case_uuid = str(uuid4())
    driver_id = "drv-stream-001"
    org_id = "018f2f4e-0000-7000-8000-000000000001"
    _setup_test_case(
        case_service, case_uuid, driver_id, status="ready", dispute_status="not_disputed", organization_id=org_id
    )

    # A. Test DriverDisputeService stream_driver_chat
    chunks = [
        chunk
        async for chunk in dispute_service.stream_driver_chat(
            case_id=case_uuid,
            message="tiếp tục khiếu nại",
            driver_id=driver_id,
        )
    ]
    full_stream = "".join(chunks)
    assert "chuyên viên" in full_stream.lower()
    assert case_service._cases[case_uuid]["status"] == "driver_disputed"
    assert case_service._cases[case_uuid]["dispute_status"] == "in_dispute"

    audit = dispute_service.get_audit_entries(case_uuid)
    escalate_events = [e for e in audit if e["action"] == "driver_appeal_escalated"]
    assert len(escalate_events) >= 1
    assert escalate_events[-1]["result"] in ("escalated", "accepted")

    # B. Test agent_runtime.stream_agent_turn (v1.1 stream path)
    case_uuid_2 = str(uuid4())
    _setup_test_case(
        case_service, case_uuid_2, driver_id, status="ready", dispute_status="not_disputed", organization_id=org_id
    )
    principal = Principal("p-drv-stream", org_id, frozenset({"driver"}), driver_id=driver_id)
    prepared_row = {"session_id": str(uuid4()), "run_id": str(uuid4())}

    with (
        patch(
            "src.services.agent_runtime.authorize_case",
            return_value={"driver_id": driver_id, "organization_id": org_id},
        ),
        patch("src.services.agent_runtime._finish", return_value=None),
    ):
        events = [
            chunk
            async for chunk in stream_agent_turn(
                principal=principal,
                case_id=case_uuid_2,
                query="tôi muốn tiếp tục khiếu nại lên chuyên viên",
                turn_id=str(uuid4()),
                prepared=(prepared_row, True),
            )
        ]
    event_str = "".join(events)
    assert "chuyên viên" in event_str.lower()
    assert case_service._cases[case_uuid_2]["status"] == "driver_disputed"
    assert case_service._cases[case_uuid_2]["dispute_status"] == "in_dispute"

    audit_2 = dispute_service.get_audit_entries(case_uuid_2)
    assert any(e["action"] == "driver_appeal_escalated" for e in audit_2)


@pytest.mark.asyncio
async def test_driver_ownership_other_driver_gets_403(case_service):
    """Proves other driver gets 403 'Driver is not assigned to this case'."""
    from unittest.mock import MagicMock, patch

    from src.services.access_control import require_case_scope

    org_id = "018f2f4e-0000-7000-8000-000000000001"
    case_id, owner_driver_id = _setup_test_case(case_service, "case-ownership-test", "drv-owner-42")

    # 1. Test with DB mock
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"organization_id": org_id, "driver_id": owner_driver_id}
    mock_db = MagicMock()
    mock_db.cursor.return_value.__enter__.return_value = mock_cursor

    with patch.object(case_service, "_get_db_connection", return_value=mock_db):
        with pytest.raises(HTTPException) as exc_info:
            require_case_scope(case_service, case_id, organization_id=org_id, driver_id="drv-other-99")
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Driver is not assigned to this case"

    # 2. Test in test environment with in-memory case state
    with patch.object(case_service, "_get_db_connection", return_value=None):
        case_service.settings.app_env = "test"
        case_service.settings.test_auth_enabled = True
        with pytest.raises(HTTPException) as exc_info_test:
            require_case_scope(case_service, case_id, organization_id=org_id, driver_id="drv-other-99")
        assert exc_info_test.value.status_code == 403
        assert exc_info_test.value.detail == "Driver is not assigned to this case"
