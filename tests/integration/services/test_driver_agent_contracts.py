"""Comprehensive verification test suite for Issue #157: Driver Agent Contracts & Autonomous Exoneration.

Tests:
1. Classifier confidence boundaries:
   - c = 0.49 (c < 0.5): asks driver to confirm resolution before closing, does not escalate.
   - c = 0.50 (c == 0.5): boundary condition, escalates to Analyst, never auto-closes.
   - c = 0.51 (c > 0.5): strictly greater than 0.5, asks whether driver still wants to appeal.
   - c is None (missing): escalates to Analyst, never auto-closes.
   - c < 0.0 or c > 1.0 (out-of-range): escalates to Analyst, never auto-closes.
   - Tool execution failure: escalates to Analyst, never auto-closes.
2. Driver confirmation resolution:
   - "Không khiếu nại thêm" / "confirm_resolution" closes case as 'driver_confirmed_resolution'.
   - Zero automated sanction applied.
   - Driver confirmation is sufficient to close case even with missing/conflicting evidence.
3. Driver appeal continuation:
   - "Tiếp tục khiếu nại" / "continue_appeal" escalates case to Fraud Analyst.
4. 48-Hour silence deadline:
   - Unresponsive / offline driver after confirmation question for > 48h automatically escalates to Analyst.
5. Score alone never closes or sanctions:
   - Neither high confidence (0.95) nor low confidence (0.10) directly closes or sanctions.
6. Cross-driver access denial:
   - Service raises 403 Forbidden when Driver B accesses Case of Driver A.
   - Tools return structured status_code=403, error_type="FORBIDDEN".
   - Agent returns status_code=403, error="FORBIDDEN".
7. Tool catalog metadata:
   - DRIVER_SURFACE_NAMES declared and aligned with CATALOG_ENTRIES.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from src.agents.driver_agent import run_driver_support_agent
from src.agents.tools.driver_tools import get_driver_dispute_context as tool_get_context
from src.agents.tools.driver_tools import submit_driver_statement as tool_submit_statement
from src.models.schemas import DriverChatRequest
from src.services.case_service import get_case_service
from src.services.driver_dispute_service import get_driver_dispute_service
from src.services.tool_catalog import CATALOG_ENTRIES, DRIVER_SURFACE_NAMES


@pytest.fixture
def case_service():
    return get_case_service()


@pytest.fixture
def dispute_service():
    return get_driver_dispute_service()


def _setup_test_case(case_service, case_id: str, driver_id: str, confidence: float | None = None):
    asgn_id = f"asgn-{case_id}"
    case_service._drivers[driver_id] = {
        "id": driver_id,
        "display_name": f"Driver {driver_id}",
        "account_status": "active",
    }
    case_service._assignments[asgn_id] = {
        "id": asgn_id,
        "driver_id": driver_id,
        "trip_id": f"trip-{case_id}",
    }
    case_data = {
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
    if confidence is not None:
        case_data["confidence"] = confidence
    case_service._cases[case_id] = case_data
    return case_id, driver_id


# ---------------------------------------------------------------------------
# 1. Classifier Confidence Boundaries
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_confidence_strictly_less_than_half_asks_confirmation(case_service, dispute_service):
    """When confidence < 0.5 (c = 0.49), do NOT escalate; still ask Driver to confirm resolution before closing."""
    case_id, driver_id = _setup_test_case(case_service, "case-conf-049", "drv-049")
    dispute_service._confidence_overrides[case_id] = 0.49

    req = DriverChatRequest(
        case_id=case_id,
        driver_id=driver_id,
        message="Tôi bị tắc đường đột xuất trên đường Trần Duy Hưng",
        claim_type="traffic_gridlock",
    )
    resp = await dispute_service.process_driver_chat(req)

    assert resp.needs_analyst_review is False
    assert resp.dispute_status == "pending_confirmation"
    assert "Độ tin cậy vi phạm thấp" in resp.reply or "xác nhận kết thúc" in resp.reply
    assert case_service._cases[case_id]["status"] == "pending_driver_confirmation"
    assert case_service._cases[case_id]["dispute_deadline"] is not None


@pytest.mark.asyncio
async def test_confidence_reply_never_states_classifier_confidence_as_a_fact(case_service, dispute_service):
    """R2: the deterministic reply must only state measured telemetry (speed/
    ratio), never an unmeasured/model-derived confidence score presented as
    fact (no fabricated metric, no verdict)."""
    case_id, driver_id = _setup_test_case(case_service, "case-conf-051-no-fab", "drv-051-no-fab")
    dispute_service._confidence_overrides[case_id] = 0.51

    req = DriverChatRequest(
        case_id=case_id,
        driver_id=driver_id,
        message="Đường Nguyễn Trãi kẹt cứng giờ cao điểm",
        claim_type="traffic_gridlock",
    )
    resp = await dispute_service.process_driver_chat(req)

    assert "Độ tin cậy hệ thống" not in resp.reply
    assert "51%" not in resp.reply


@pytest.mark.asyncio
async def test_confidence_exactly_half_escalates_to_analyst(case_service, dispute_service):
    """Boundary Rule: Exactly 0.5 (c == 0.50) MUST escalate to Analyst and NEVER auto-close."""
    case_id, driver_id = _setup_test_case(case_service, "case-conf-050", "drv-050")
    dispute_service._confidence_overrides[case_id] = 0.50

    req = DriverChatRequest(
        case_id=case_id,
        driver_id=driver_id,
        message="Tôi giải trình về thời gian dừng đỗ",
        claim_type="passenger_wait",
    )
    resp = await dispute_service.process_driver_chat(req)

    assert resp.needs_analyst_review is True
    assert resp.dispute_status == "in_dispute"
    assert resp.is_auto_dismissed is False
    assert case_service._cases[case_id]["status"] == "driver_disputed"


@pytest.mark.asyncio
async def test_confidence_strictly_greater_than_half_asks_appeal(case_service, dispute_service):
    """When confidence > 0.5 (c = 0.51), ask whether Driver still wants to appeal (does not auto-sanction)."""
    case_id, driver_id = _setup_test_case(case_service, "case-conf-051", "drv-051")
    dispute_service._confidence_overrides[case_id] = 0.51

    req = DriverChatRequest(
        case_id=case_id,
        driver_id=driver_id,
        message="Đường Nguyễn Trãi kẹt cứng giờ cao điểm",
        claim_type="traffic_gridlock",
    )
    resp = await dispute_service.process_driver_chat(req)

    assert resp.needs_analyst_review is False
    assert resp.dispute_status == "pending_confirmation"
    assert "Bạn có muốn tiếp tục khiếu nại" in resp.reply
    assert case_service._cases[case_id]["status"] == "pending_driver_confirmation"


@pytest.mark.asyncio
async def test_missing_confidence_escalates_to_analyst(case_service, dispute_service):
    """Boundary Rule: Missing confidence (c = None) MUST escalate to Analyst and NEVER auto-close."""
    case_id, driver_id = _setup_test_case(case_service, "case-conf-none", "drv-none")
    dispute_service._confidence_overrides[case_id] = None

    req = DriverChatRequest(
        case_id=case_id,
        driver_id=driver_id,
        message="Đề nghị kiểm tra lại cuốc xe",
        claim_type="other",
    )
    resp = await dispute_service.process_driver_chat(req)

    assert resp.needs_analyst_review is True
    assert resp.dispute_status == "in_dispute"
    assert resp.is_auto_dismissed is False
    assert case_service._cases[case_id]["status"] == "driver_disputed"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_confidence", [-0.2, 1.4])
async def test_out_of_range_confidence_escalates_to_analyst(case_service, dispute_service, bad_confidence):
    """Boundary Rule: Out-of-range confidence (c < 0 or c > 1) MUST escalate to Analyst and NEVER auto-close."""
    case_id, driver_id = _setup_test_case(case_service, f"case-bad-conf-{bad_confidence}", f"drv-{bad_confidence}")
    dispute_service._confidence_overrides[case_id] = bad_confidence

    req = DriverChatRequest(
        case_id=case_id,
        driver_id=driver_id,
        message="Giải trình lý do chậm đón",
        claim_type="other",
    )
    resp = await dispute_service.process_driver_chat(req)

    assert resp.needs_analyst_review is True
    assert resp.dispute_status == "in_dispute"
    assert case_service._cases[case_id]["status"] == "driver_disputed"


@pytest.mark.asyncio
async def test_tool_failure_escalates_to_analyst(case_service, dispute_service):
    """Boundary Rule: Tool execution failure MUST escalate to Analyst and NEVER auto-close."""
    case_id, driver_id = _setup_test_case(case_service, "case-tool-fail", "drv-fail")
    dispute_service._confidence_overrides[case_id] = 0.80

    with patch.object(dispute_service, "corroborate_traffic_conditions", side_effect=RuntimeError("OSRM backend down")):
        req = DriverChatRequest(
            case_id=case_id,
            driver_id=driver_id,
            message="Kẹt xe đường Cầu Giấy",
            claim_type="traffic_gridlock",
        )
        resp = await dispute_service.process_driver_chat(req)

        assert resp.needs_analyst_review is True
        assert resp.dispute_status == "in_dispute"
        assert resp.is_auto_dismissed is False
        assert case_service._cases[case_id]["status"] == "driver_disputed"


# ---------------------------------------------------------------------------
# 2. Driver Confirmation Resolution (Zero Sanction, Closes Case)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "confirm_msg", ["confirm_resolution", "Không khiếu nại thêm", "Đồng ý kết thúc", "no_further_appeal"]
)
async def test_driver_confirmation_closes_case_without_sanction(case_service, dispute_service, confirm_msg):
    """Driver confirmation is sufficient to close case as driver_confirmed_resolution with zero sanction."""
    safe_slug = "".join(c for c in confirm_msg if c.isalnum()) or "confirm"
    case_id, driver_id = _setup_test_case(case_service, f"case-confirm-{safe_slug}", "drv-confirm")
    case_service._cases[case_id]["status"] = "pending_driver_confirmation"
    case_service._cases[case_id]["dispute_status"] = "pending_confirmation"

    req = DriverChatRequest(
        case_id=case_id,
        driver_id=driver_id,
        message=confirm_msg,
    )
    resp = await dispute_service.process_driver_chat(req)

    assert resp.needs_analyst_review is False
    assert resp.dispute_status == "resolved"
    assert case_service._cases[case_id]["status"] == "driver_confirmed_resolution"
    assert case_service._cases[case_id]["dispute_status"] == "resolved"

    # Verify zero sanction recorded in audit
    audit = dispute_service.get_audit_entries(case_id)
    confirm_entries = [e for e in audit if e["action"] == "driver_confirmed_resolution"]
    assert len(confirm_entries) >= 1
    assert confirm_entries[-1]["payload"].get("sanction_applied") is None


# ---------------------------------------------------------------------------
# 3. Driver Refusal / Continue Appeal
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("refuse_msg", ["continue_appeal", "Tiếp tục khiếu nại", "Tôi muốn khiếu nại tiếp"])
async def test_driver_continue_appeal_escalates_to_analyst(case_service, dispute_service, refuse_msg):
    """When Driver refuses resolution and continues appeal, escalate to Fraud Analyst."""
    safe_slug = "".join(c for c in refuse_msg if c.isalnum()) or "refuse"
    case_id, driver_id = _setup_test_case(case_service, f"case-refuse-{safe_slug}", "drv-refuse")
    case_service._cases[case_id]["status"] = "pending_driver_confirmation"
    case_service._cases[case_id]["dispute_status"] = "pending_confirmation"

    req = DriverChatRequest(
        case_id=case_id,
        driver_id=driver_id,
        message=refuse_msg,
    )
    resp = await dispute_service.process_driver_chat(req)

    assert resp.needs_analyst_review is True
    assert resp.dispute_status == "in_dispute"
    assert case_service._cases[case_id]["status"] == "driver_disputed"
    assert case_service._cases[case_id]["dispute_status"] == "in_dispute"


# ---------------------------------------------------------------------------
# 4. 48-Hour Silence Deadline Expiration
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_silence_timeout_after_confirmation_question_escalates(case_service, dispute_service):
    """If no response / offline after confirmation question for > 48 hours, automatically escalate to Analyst."""
    case_id, driver_id = _setup_test_case(case_service, "case-timeout-48h", "drv-timeout")
    expired_time = (datetime.now(UTC) - timedelta(hours=49)).isoformat()
    case_service._cases[case_id]["status"] = "pending_driver_confirmation"
    case_service._cases[case_id]["dispute_status"] = "pending_confirmation"
    case_service._cases[case_id]["dispute_deadline"] = expired_time

    req = DriverChatRequest(
        case_id=case_id,
        driver_id=driver_id,
        message="Xin chào hệ thống",
    )
    resp = await dispute_service.process_driver_chat(req)

    assert resp.needs_analyst_review is True
    assert resp.dispute_status == "in_dispute"
    assert "Thời hạn 48 giờ phản hồi đã kết thúc" in resp.reply
    assert case_service._cases[case_id]["status"] == "driver_disputed"


# ---------------------------------------------------------------------------
# 5. Score Alone Never Closes or Sanctions
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_score_alone_never_closes_or_sanctions(case_service, dispute_service):
    """High score (c = 0.95) does not sanction or close; low score (c = 0.10) does not auto-close without driver confirmation."""
    # Test High Score
    c_high = "case-score-high"
    _setup_test_case(case_service, c_high, "drv-high")
    dispute_service._confidence_overrides[c_high] = 0.95

    resp_high = await dispute_service.process_driver_chat(
        DriverChatRequest(
            case_id=c_high, driver_id="drv-high", message="Giải trình kẹt xe", claim_type="traffic_gridlock"
        )
    )
    assert resp_high.dispute_status == "pending_confirmation"
    assert case_service._cases[c_high]["status"] == "pending_driver_confirmation"

    # Test Low Score
    c_low = "case-score-low"
    _setup_test_case(case_service, c_low, "drv-low")
    dispute_service._confidence_overrides[c_low] = 0.10

    resp_low = await dispute_service.process_driver_chat(
        DriverChatRequest(case_id=c_low, driver_id="drv-low", message="Giải trình lý do khách huỷ", claim_type="other")
    )
    assert resp_low.dispute_status == "pending_confirmation"
    assert case_service._cases[c_low]["status"] == "pending_driver_confirmation"


# ---------------------------------------------------------------------------
# 6. Cross-Driver Access Denial
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cross_driver_access_denied_service(case_service, dispute_service):
    """Service strictly denies access when driver_id does not match case driver (404 anti-probing)."""
    case_id, owner_driver = _setup_test_case(case_service, "case-cross-service", "drv-owner")

    # get_driver_dispute_context with wrong driver
    with pytest.raises(HTTPException) as exc_ctx:
        await dispute_service.get_driver_dispute_context(case_id, "drv-intruder")
    assert exc_ctx.value.status_code == 404

    # process_driver_chat with wrong driver
    with pytest.raises(HTTPException) as exc_chat:
        await dispute_service.process_driver_chat(
            DriverChatRequest(case_id=case_id, driver_id="drv-intruder", message="Hacking case")
        )
    assert exc_chat.value.status_code == 404


@pytest.mark.asyncio
async def test_cross_driver_access_denied_tools(case_service):
    """Tools return structured 404 NOT_FOUND error response on cross-driver invocation (anti-probing)."""
    case_id, owner_driver = _setup_test_case(case_service, "case-cross-tool", "drv-owner")

    # Direct tool call get_driver_dispute_context
    ctx_res = await tool_get_context.ainvoke({"case_id": case_id, "driver_id": "drv-intruder"})
    assert ctx_res.get("status_code") == 404
    assert ctx_res.get("error_type") == "NOT_FOUND"

    # Direct tool call submit_driver_statement
    stmt_res = await tool_submit_statement.ainvoke(
        {
            "case_id": case_id,
            "driver_id": "drv-intruder",
            "reason": "Intruder explanation",
            "claim_type": "traffic_gridlock",
        }
    )
    assert stmt_res.get("status_code") == 404
    assert stmt_res.get("error_type") == "NOT_FOUND"


@pytest.mark.asyncio
async def test_cross_driver_access_denied_agent(case_service):
    """Agent returns structured 403 FORBIDDEN on cross-driver execution."""
    case_id, owner_driver = _setup_test_case(case_service, "case-cross-agent", "drv-owner")

    agent_res = await run_driver_support_agent(
        case_id=case_id,
        driver_id="drv-intruder",
        message="Intruder agent prompt",
    )
    assert agent_res.get("status_code") == 403
    assert agent_res.get("error") == "FORBIDDEN"


# ---------------------------------------------------------------------------
# 7. Tool Catalog Metadata Declaration
# ---------------------------------------------------------------------------
def test_driver_tool_catalog_declarations():
    """Verify tool catalog contains all driver tools with correct permission bounds and error codes."""
    expected_driver_tools = {
        "get_driver_dispute_context",
        "corroborate_traffic_conditions",
        "inspect_trip_telemetry",
        "verify_exoneration_rules",
        "submit_driver_statement",
        "query_driver_policy",
    }
    assert expected_driver_tools.issubset(DRIVER_SURFACE_NAMES)

    # Check that entries exist in CATALOG_ENTRIES
    all_surface_names = {name for entry in CATALOG_ENTRIES for name in entry.surface_names}
    for tool_name in expected_driver_tools:
        assert tool_name in all_surface_names, f"Tool {tool_name} missing from CATALOG_ENTRIES surface_names"

    # Specifically check submit_driver_statement is human-only (model_selectable=False)
    submit_entries = [e for e in CATALOG_ENTRIES if "submit_driver_statement" in e.surface_names]
    assert len(submit_entries) == 1
    assert submit_entries[0].model_selectable is False
    assert submit_entries[0].actor == "driver"
    assert "FORBIDDEN" in submit_entries[0].error_codes
