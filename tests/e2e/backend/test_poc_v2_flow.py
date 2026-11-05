"""Full End-to-End Integration Suite for POC v2 (Slice 4).

Covers:
1. Flow A: Driver Mobile Dispute & Autonomous Exoneration
   - Driver dispute context retrieval
   - Corroborated traffic claim (observed speed < 5 km/h, delay ratio >= 2.0x, 0 past sanctions)
   - Deterministic corroboration by Driver Agent -> auto_dismissed with digital exoneration receipt
   - Verification of case dismissal, audit log, and queue reflection

2. Flow B: Multi-Agent A2A Handoff & Human-in-the-Loop (HITL) Adjudication
   - Uncorroborated traffic claim -> Driver Agent escalates to 'driver_disputed' / 'in_dispute'
   - Analyst claims exclusive review lease
   - Analyst queries dispute dossier (driver statement, traffic corroboration, transcript)
   - Analyst delegates inquiry to Driver Agent with specific deadline
   - Driver provides follow-up clarification
   - Analyst reviews updated dossier and submits final adjudication
   - Case resolves with terminal status 'resolved' and version increment

3. Flow C: Server-Sent Events (SSE) Driver Chat Streaming End-to-End
   - Stream token chunks ('event: token') and terminal event ('event: done')
   - Token reassembly and completion verification
   - Autonomous exoneration receipt delivery over SSE stream
"""

import json
from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.services.case_service import get_case_service
from src.services.driver_dispute_service import get_driver_dispute_service


def _setup_e2e_case(
    case_id: str,
    driver_id: str,
    suspected_category: str = "ERR-01",
    priority_score: int = 65,
    priority_tier: int = 1,
) -> None:
    """Register deterministic test entities in case_service."""
    cs = get_case_service()
    asgn_id = f"asgn-{case_id}"
    cs._drivers[driver_id] = {
        "id": driver_id,
        "display_name": f"Driver {driver_id}",
        "account_status": "active",
    }
    cs._assignments[asgn_id] = {
        "id": asgn_id,
        "driver_id": driver_id,
        "trip_id": f"trip-{case_id}",
    }
    cs._cases[case_id] = {
        "id": case_id,
        "assignment_id": asgn_id,
        "status": "ready",
        "dispute_status": "not_disputed",
        "suspected_category": suspected_category,
        "priority_score": priority_score,
        "priority_tier": priority_tier,
        "priority_rule_version": "v1",
        "version": 1,
    }


def _parse_sse_events(raw_sse_text: str) -> list[tuple[str, dict]]:
    """Parse raw SSE text into a list of (event_type, json_data) tuples."""
    events = []
    for block in raw_sse_text.strip().split("\n\n"):
        if not block.strip():
            continue
        event_name = "message"
        data_str = ""
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_str = line[5:].strip()
        if data_str:
            try:
                events.append((event_name, json.loads(data_str)))
            except json.JSONDecodeError:
                events.append((event_name, {"raw": data_str}))
    return events


@pytest.fixture(autouse=True)
def isolate_test_db(monkeypatch):
    """Ensure E2E integration test suite runs in deterministic, isolated in-memory mode."""
    cs = get_case_service()
    ds = get_driver_dispute_service()
    monkeypatch.setattr(cs, "_get_db_connection", lambda: None)
    monkeypatch.setattr(ds, "_get_db_connection", lambda: None)


# ---------------------------------------------------------------------------
# Flow A: Autonomous Exoneration
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_flow_a_autonomous_exoneration_e2e(client: AsyncClient):
    """Flow A: Corroborated Claim Pending Analyst Confirmation E2E Integration Test.
    1. Driver fetches dispute context.
    2. Driver submits traffic gridlock claim with high congestion.
    3. Driver Agent corroborates traffic deterministically; issue #73 requires analyst confirmation.
    4. Verify case status is pending_analyst_review, no automatic dismissal receipt,
       audit log is recorded, and queue reflects the pending review state.
    """
    case_id = f"case-flow-a-{uuid4().hex[:8]}"
    driver_id = f"drv-flow-a-{uuid4().hex[:8]}"
    _setup_e2e_case(case_id, driver_id, suspected_category="ERR-01")

    driver_headers = {"X-Driver-ID": driver_id, "X-Role": "driver"}

    # 1. Driver dispute context retrieval
    res_ctx = await client.get(
        f"/api/v1/driver/cases/{case_id}/dispute",
        headers=driver_headers,
    )
    assert res_ctx.status_code == 200, res_ctx.text
    ctx_data = res_ctx.json()
    assert ctx_data["case_id"] == case_id
    assert ctx_data["driver_id"] == driver_id
    assert ctx_data["violation_code"] == "ERR-01"
    assert ctx_data["dispute_status"] == "not_disputed"
    assert "traffic_gridlock" in ctx_data["allowed_claim_types"]

    # 2. Configure deterministic traffic corroboration (observed speed 3.2 km/h < 5.0, ratio 2.7x >= 2.0x)
    dispute_service = get_driver_dispute_service()
    dispute_service._traffic_overrides[case_id] = {
        "observed_speed": 3.2,
        "ratio": 2.7,
        "congestion_level": "heavy",
        "gps_valid": True,
        "prior_sanctions": 0,
    }

    # Driver sends chat with traffic_gridlock claim
    chat_payload = {
        "case_id": case_id,
        "driver_id": driver_id,
        "message": "Đường Kim Mã kẹt xe nghiêm trọng do có sự cố giao thông, xe không thể di chuyển nhanh",
        "claim_type": "traffic_gridlock",
    }
    res_chat = await client.post(
        f"/api/v1/driver/cases/{case_id}/chat",
        json=chat_payload,
        headers=driver_headers,
    )
    assert res_chat.status_code == 200, res_chat.text
    chat_data = res_chat.json()

    # 3. Verify corroborated claim awaits analyst confirmation (#73)
    assert chat_data["case_id"] == case_id
    assert chat_data["dispute_status"] == "pending_review"
    assert chat_data["is_auto_dismissed"] is False
    assert chat_data["needs_analyst_review"] is True
    assert chat_data["exoneration_receipt"] is None

    # 4. Verify case detail status and dispute_status
    res_detail = await client.get(f"/api/v1/cases/{case_id}")
    assert res_detail.status_code == 200, res_detail.text
    detail = res_detail.json()
    assert detail["case"]["status"] == "pending_analyst_review"
    assert detail["case"]["dispute_status"] == "pending_review"

    # 5. Verify queue listing reflects pending analyst review
    res_list = await client.get("/api/v1/cases?status=pending_analyst_review")
    assert res_list.status_code == 200, res_list.text
    items = res_list.json()["items"]
    matching_case = next((item for item in items if item["id"] == case_id), None)
    assert matching_case is not None
    assert matching_case["status"] == "pending_analyst_review"
    assert matching_case["dispute_status"] == "pending_review"

    # 6. Verify audit entry was logged (#73: corroboration recommendation, not autonomous exoneration)
    audit_entries = dispute_service.get_audit_entries(case_id)
    assert any(
        entry["action"] == "traffic_corroboration_pending_review" and entry["result"] == "accepted"
        for entry in audit_entries
    )


# ---------------------------------------------------------------------------
# Flow B: Multi-Agent A2A Handoff & Human Adjudication
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_flow_b_multi_agent_handoff_and_adjudication_e2e(client: AsyncClient):
    """Flow B: Multi-Agent A2A Handoff and Human Adjudication E2E Integration Test.
    1. Driver submits uncorroborated traffic claim (normal speed 28 km/h).
    2. Driver Agent escalates -> status='driver_disputed', dispute_status='in_dispute'.
    3. Analyst claims case lease -> lease claimed.
    4. Analyst queries dispute dossier -> verifies driver statement, signals, and transcript.
    5. Analyst delegates inquiry to Driver Agent with deadline.
    6. Driver Agent records analyst inquiry; driver provides follow-up answer.
    7. Analyst reviews updated dossier and submits final adjudication (APPROVE / DISMISS).
    8. Case resolves with terminal status 'resolved' and version incremented.
    """
    case_id = f"case-flow-b-{uuid4().hex[:8]}"
    driver_id = f"drv-flow-b-{uuid4().hex[:8]}"
    analyst_id = "018f2f4e-1000-7000-8000-000000000001"
    _setup_e2e_case(case_id, driver_id, suspected_category="ERR-01")

    cs = get_case_service()
    cs._principal_roles[analyst_id] = "analyst"
    dispute_service = get_driver_dispute_service()

    driver_headers = {"X-Driver-ID": driver_id, "X-Role": "driver"}
    analyst_headers = {"X-Principal-ID": analyst_id, "X-Role": "analyst"}

    # 1. Driver sends chat with uncorroborated traffic conditions
    dispute_service._traffic_overrides[case_id] = {
        "observed_speed": 28.5,
        "ratio": 1.08,
        "congestion_level": "clear",
        "gps_valid": True,
        "prior_sanctions": 0,
    }
    chat_payload = {
        "case_id": case_id,
        "driver_id": driver_id,
        "message": "Đường đông đúc bất thường vào giờ cao điểm nên tôi bị trễ vài phút",
        "claim_type": "traffic_gridlock",
    }
    res_chat = await client.post(
        f"/api/v1/driver/cases/{case_id}/chat",
        json=chat_payload,
        headers=driver_headers,
    )
    assert res_chat.status_code == 200, res_chat.text
    chat_data = res_chat.json()

    # 2. Driver Agent escalates to Human Analyst
    assert chat_data["case_id"] == case_id
    assert chat_data["dispute_status"] == "in_dispute"
    assert chat_data["is_auto_dismissed"] is False
    assert chat_data["needs_analyst_review"] is True
    assert chat_data["exoneration_receipt"] is None

    # Verify case status transitioned to driver_disputed
    detail_res1 = await client.get(f"/api/v1/cases/{case_id}")
    assert detail_res1.json()["case"]["status"] == "driver_disputed"
    assert detail_res1.json()["case"]["dispute_status"] == "in_dispute"

    # 3. Analyst claims case lease
    claim_payload = {
        "analyst_id": analyst_id,
        "role": "analyst",
        "lease_duration_seconds": 300,
        "force": True,
    }
    res_claim = await client.post(
        f"/api/v1/cases/{case_id}/claim",
        json=claim_payload,
        headers=analyst_headers,
    )
    assert res_claim.status_code == 200, res_claim.text
    claim_data = res_claim.json()
    assert claim_data["status"] == "claimed"
    assert claim_data["analyst_id"] == analyst_id

    # 4. Analyst queries dispute dossier
    res_dossier = await client.get(
        f"/api/v1/cases/{case_id}/dispute-dossier",
        headers=analyst_headers,
    )
    assert res_dossier.status_code == 200, res_dossier.text
    dossier = res_dossier.json()
    assert dossier["case_id"] == case_id
    assert dossier["driver_id"] == driver_id
    assert dossier["driver_statement"] == "Đường đông đúc bất thường vào giờ cao điểm nên tôi bị trễ vài phút"
    assert dossier["claim_type"] == "traffic_gridlock"
    assert dossier["traffic_corroboration"]["observed_speed"] == 28.5
    assert dossier["traffic_corroboration"]["corroborated"] is False
    assert len(dossier["transcript"]) >= 2

    # 5. Analyst delegates inquiry to Driver Agent
    inquiry_payload = {
        "case_id": case_id,
        "analyst_id": analyst_id,
        "instruction": "Tài xế vui lòng cung cấp địa điểm cụ thể và hình ảnh phương tiện bị kẹt",
        "deadline_hours": 24,
    }
    res_inquiry = await client.post(
        f"/api/v1/cases/{case_id}/delegate-inquiry",
        json=inquiry_payload,
        headers=analyst_headers,
    )
    assert res_inquiry.status_code == 200, res_inquiry.text
    inquiry_data = res_inquiry.json()
    assert inquiry_data["dispute_status"] == "pending"
    assert inquiry_data["instruction"] == inquiry_payload["instruction"]

    # Verify case status updated to evidence_requested
    detail_res2 = await client.get(f"/api/v1/cases/{case_id}")
    assert detail_res2.json()["case"]["status"] == "evidence_requested"
    assert detail_res2.json()["case"]["dispute_status"] == "pending"

    # 6. Driver Agent records inquiry; driver provides follow-up answer
    followup_payload = {
        "case_id": case_id,
        "driver_id": driver_id,
        "message": "Tôi bị kẹt tại lối rẽ Nguyễn Chí Thanh - Đê La Thành do xe buýt gặp sự cố chết máy chắn ngang đường",
        "claim_type": "traffic_gridlock",
    }
    res_followup = await client.post(
        f"/api/v1/driver/cases/{case_id}/chat",
        json=followup_payload,
        headers=driver_headers,
    )
    assert res_followup.status_code == 200, res_followup.text
    assert res_followup.json()["dispute_status"] == "in_dispute"

    # 7. Analyst reviews updated dispute dossier
    res_dossier2 = await client.get(
        f"/api/v1/cases/{case_id}/dispute-dossier",
        headers=analyst_headers,
    )
    assert res_dossier2.status_code == 200, res_dossier2.text
    dossier2 = res_dossier2.json()
    assert "xe buýt gặp sự cố" in dossier2["driver_statement"]
    # Transcript now contains driver turn 1, agent reply 1, analyst inquiry, driver turn 2, agent reply 2
    assert len(dossier2["transcript"]) >= 4

    # Analyst submits final adjudication
    case_detail = (await client.get(f"/api/v1/cases/{case_id}")).json()
    target_version = case_detail["case"]["version"]

    adjudicate_payload = {
        "outcome": "APPROVE",
        "analyst_id": analyst_id,
        "rationale": "Xác nhận sự cố giao thông cục bộ từ phản hồi của tài xế. Không áp dụng chế tài xử phạt.",
        "expected_case_version": target_version,
    }
    res_adj = await client.post(
        f"/api/v1/cases/{case_id}/adjudicate",
        json=adjudicate_payload,
        headers=analyst_headers,
    )
    assert res_adj.status_code == 200, res_adj.text
    adj_data = res_adj.json()
    assert adj_data["status"] == "adjudicated"
    assert adj_data["outcome"] == "APPROVE"
    assert adj_data["new_version"] == target_version + 1

    # 8. Case resolves with terminal status
    final_detail = (await client.get(f"/api/v1/cases/{case_id}")).json()
    assert final_detail["case"]["status"] == "resolved"
    assert final_detail["case"]["version"] == target_version + 1


# ---------------------------------------------------------------------------
# Flow C: SSE Driver Chat Streaming End-to-End
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_flow_c_sse_driver_chat_stream_e2e(client: AsyncClient):
    """Flow C: SSE Driver Chat Stream End-to-End Test.
    1. Driver connects to GET /api/v1/driver/cases/{id}/chat/stream.
    2. Verifies incoming token events and streaming payload.
    3. Reassembles tokens into full response and checks terminal 'done' event.
    """
    case_id = f"case-flow-c-{uuid4().hex[:8]}"
    driver_id = f"drv-flow-c-{uuid4().hex[:8]}"
    _setup_e2e_case(case_id, driver_id, suspected_category="ERR-01")

    driver_headers = {"X-Driver-ID": driver_id, "X-Role": "driver"}

    res = await client.get(
        f"/api/v1/driver/cases/{case_id}/chat/stream",
        params={
            "message": "Tôi xin giải trình về việc đón khách muộn do trời mưa to và đường ngập nước",
            "claim_type": "weather",
        },
        headers=driver_headers,
    )
    assert res.status_code == 200, res.text
    assert "text/event-stream" in res.headers["content-type"]

    events = _parse_sse_events(res.text)
    token_events = [data for evt, data in events if evt == "token"]
    done_events = [data for evt, data in events if evt == "done"]

    assert len(token_events) > 0, f"Expected token events, received {events}"
    assert len(done_events) == 1, f"Expected 1 done event, received {events}"

    # Verify token payload structure
    for t in token_events:
        assert "delta" in t or "token" in t
        assert t.get("case_id") == case_id

    # Verify reassembled reply matches the done event reply
    assembled_reply = "".join(t.get("delta") or t.get("token") for t in token_events).strip()
    done_payload = done_events[0]
    assert done_payload["status"] == "completed"
    assert done_payload["case_id"] == case_id
    assert done_payload["driver_id"] == driver_id
    assert done_payload["dispute_status"] == "in_dispute"
    assert done_payload["is_auto_dismissed"] is False
    assert done_payload["reply"].strip() == assembled_reply


@pytest.mark.asyncio
async def test_flow_c_corroborated_claim_over_sse_stream(client: AsyncClient):
    """Flow C Variant: Corroborated claim delivered over SSE stream.
    Verifies that when conditions satisfy corroboration, the terminal done event
    contains is_auto_dismissed=False and pending analyst confirmation (#73).
    """
    case_id = f"case-flow-c-auto-{uuid4().hex[:8]}"
    driver_id = f"drv-flow-c-auto-{uuid4().hex[:8]}"
    _setup_e2e_case(case_id, driver_id, suspected_category="ERR-01")

    dispute_service = get_driver_dispute_service()
    dispute_service._traffic_overrides[case_id] = {
        "observed_speed": 2.8,
        "ratio": 2.9,
        "congestion_level": "heavy",
        "gps_valid": True,
        "prior_sanctions": 0,
    }

    driver_headers = {"X-Driver-ID": driver_id, "X-Role": "driver"}

    res = await client.get(
        f"/api/v1/driver/cases/{case_id}/chat/stream",
        params={
            "message": "Đường Trần Duy Hưng ùn tắc không di chuyển được",
            "claim_type": "traffic_gridlock",
        },
        headers=driver_headers,
    )
    assert res.status_code == 200, res.text

    events = _parse_sse_events(res.text)
    done_events = [data for evt, data in events if evt == "done"]
    assert len(done_events) == 1

    done_payload = done_events[0]
    assert done_payload["dispute_status"] == "pending_review"
    assert done_payload["is_auto_dismissed"] is False
    assert done_payload["exoneration_receipt"] is None
    assert done_payload["needs_analyst_review"] is True


# ---------------------------------------------------------------------------
# Safety Invariant & Boundary Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_safety_invariant_prior_sanctions_block_auto_exoneration(client: AsyncClient):
    """Safety Invariant (NFR-L06-02): Drivers with prior sanctions cannot be auto-exonerated.
    Must escalate to human analyst review.
    """
    case_id = f"case-prior-sanc-{uuid4().hex[:8]}"
    driver_id = f"drv-prior-sanc-{uuid4().hex[:8]}"
    _setup_e2e_case(case_id, driver_id, suspected_category="ERR-01")

    dispute_service = get_driver_dispute_service()
    dispute_service._traffic_overrides[case_id] = {
        "observed_speed": 3.0,
        "ratio": 2.5,
        "congestion_level": "heavy",
        "gps_valid": True,
        "prior_sanctions": 1,  # Non-zero prior sanction!
    }

    driver_headers = {"X-Driver-ID": driver_id, "X-Role": "driver"}
    res = await client.post(
        f"/api/v1/driver/cases/{case_id}/chat",
        json={"message": "Kẹt xe cứng ngắc", "claim_type": "traffic_gridlock"},
        headers=driver_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_auto_dismissed"] is False
    assert data["dispute_status"] == "in_dispute"
    assert data["needs_analyst_review"] is True
