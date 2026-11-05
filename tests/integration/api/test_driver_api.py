"""TDD Tests for Driver API, SSE Streaming, and A2A Delegation (Slice 2).

Endpoints:
1. GET /api/v1/driver/cases/{case_id}/dispute - Driver dispute context retrieval
2. POST /api/v1/driver/cases/{case_id}/chat - Driver dispute chat submission
3. GET /api/v1/driver/cases/{case_id}/chat/stream - SSE token streaming and completion
4. POST /api/v1/cases/{case_id}/delegate-inquiry - Analyst delegation inquiry
5. GET /api/v1/cases/{case_id}/dispute-dossier - Dispute dossier compilation
6. Unknown case 404 handling across all endpoints
7. Role and driver identity access control verification
"""

import json
from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.services.case_service import get_case_service
from src.services.driver_dispute_service import get_driver_dispute_service


def _setup_test_case(case_id: str, driver_id: str, suspected_category: str = "ERR-01"):
    """Helper to register a deterministic case in case_service."""
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
        "priority_score": 65,
        "priority_tier": 1,
        "priority_rule_version": "v1",
        "version": 1,
    }


def _parse_sse_blocks(text: str) -> list[tuple[str, dict]]:
    """Parse raw SSE body into (event_type, json_data) pairs."""
    events = []
    for block in text.strip().split("\n\n"):
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


@pytest.mark.asyncio
async def test_get_driver_dispute_context(client: AsyncClient):
    """1. Driver dispute context retrieval with valid case."""
    case_id = f"case-ctx-{uuid4().hex[:6]}"
    driver_id = f"drv-ctx-{uuid4().hex[:6]}"
    _setup_test_case(case_id, driver_id, suspected_category="ERR-01")

    # Call with driver header matching identity (both prefixed and un-prefixed)
    res = await client.get(
        f"/api/v1/driver/cases/{case_id}/dispute",
        headers={"X-Driver-ID": driver_id, "X-Role": "driver"},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["case_id"] == case_id
    assert data["driver_id"] == driver_id
    assert data["violation_code"] == "ERR-01"
    assert "traffic_gridlock" in data["allowed_claim_types"]
    assert data["dispute_status"] in ("not_disputed", "pending", "in_dispute")

    # Unprefixed root path check
    res_root = await client.get(
        f"/driver/cases/{case_id}/dispute",
        headers={"X-Driver-ID": driver_id, "X-Role": "driver"},
    )
    assert res_root.status_code == 200, res_root.text
    assert res_root.json()["case_id"] == case_id


@pytest.mark.asyncio
async def test_driver_identity_mismatch_forbidden(client: AsyncClient):
    """Driver attempting to access another driver's dispute must receive 403."""
    case_id = f"case-mismatch-{uuid4().hex[:6]}"
    owner_driver_id = f"drv-owner-{uuid4().hex[:6]}"
    attacker_driver_id = f"drv-attacker-{uuid4().hex[:6]}"
    _setup_test_case(case_id, owner_driver_id)

    res = await client.get(
        f"/api/v1/driver/cases/{case_id}/dispute",
        headers={"X-Driver-ID": attacker_driver_id, "X-Role": "driver"},
    )
    assert res.status_code == 403
    assert "Driver identity" in res.json()["detail"]


@pytest.mark.asyncio
async def test_driver_chat_response_in_dispute(client: AsyncClient):
    """2. Driver chat response when claim is non-traffic or uncorroborated -> status in_dispute, escalates to HITL."""
    case_id = f"case-chat-{uuid4().hex[:6]}"
    driver_id = f"drv-chat-{uuid4().hex[:6]}"
    _setup_test_case(case_id, driver_id)

    payload = {
        "message": "Tôi phải đợi khách đổi điểm đón 15 phút",
        "claim_type": "passenger_wait",
    }
    res = await client.post(
        f"/api/v1/driver/cases/{case_id}/chat",
        json=payload,
        headers={"X-Driver-ID": driver_id, "X-Role": "driver"},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["case_id"] == case_id
    assert data["dispute_status"] == "in_dispute"
    assert data["is_auto_dismissed"] is False
    assert data["needs_analyst_review"] is True
    assert data["exoneration_receipt"] is None
    assert "chuyển tiếp" in data["reply"] or "ghi nhận" in data["reply"]


@pytest.mark.asyncio
async def test_driver_chat_response_corroborated_claim(client: AsyncClient):
    """3. Driver chat response with corroborated traffic (speed < 5, ratio > 2, valid GPS, 0 sanctions)
    -> pending_review: recommendation for analyst confirmation, no automatic dismissal.
    """
    case_id = f"case-dismiss-{uuid4().hex[:6]}"
    driver_id = f"drv-dismiss-{uuid4().hex[:6]}"
    _setup_test_case(case_id, driver_id)

    dispute_service = get_driver_dispute_service()
    dispute_service._traffic_overrides[case_id] = {
        "observed_speed": 3.1,  # < 5.0 km/h
        "ratio": 2.5,  # >= 2.0x
        "congestion_level": "heavy",
        "gps_valid": True,
        "prior_sanctions": 0,
    }

    payload = {
        "message": "Đường tắc nghẽn nghiêm trọng không thể di chuyển nhanh",
        "claim_type": "traffic_gridlock",
    }
    res = await client.post(
        f"/api/v1/driver/cases/{case_id}/chat",
        json=payload,
        headers={"X-Driver-ID": driver_id, "X-Role": "driver"},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["case_id"] == case_id
    assert data["dispute_status"] == "pending_review"
    assert data["is_auto_dismissed"] is False
    assert data["needs_analyst_review"] is True
    assert data["exoneration_receipt"] is None


@pytest.mark.asyncio
async def test_driver_chat_sse_stream(client: AsyncClient):
    """4. Driver chat SSE stream streaming token chunks and final done event."""
    case_id = f"case-stream-{uuid4().hex[:6]}"
    driver_id = f"drv-stream-{uuid4().hex[:6]}"
    _setup_test_case(case_id, driver_id)

    res = await client.get(
        f"/api/v1/driver/cases/{case_id}/chat/stream",
        params={"message": "Tôi xin giải trình lý do chậm trễ", "claim_type": "passenger_wait"},
        headers={"X-Driver-ID": driver_id, "X-Role": "driver"},
    )
    assert res.status_code == 200, res.text
    assert "text/event-stream" in res.headers["content-type"]

    events = _parse_sse_blocks(res.text)
    token_events = [data for evt, data in events if evt == "token"]
    done_events = [data for evt, data in events if evt == "done"]
    blocks_events = [data for evt, data in events if evt == "blocks"]

    assert len(token_events) > 0, f"Expected token events in stream, got {events}"
    assert len(blocks_events) == 1, f"Expected exactly one blocks event in stream, got {events}"
    assert len(done_events) == 1, f"Expected exactly one done event, got {events}"

    # Verify event ordering: tokens appear before blocks event, blocks event appears before done
    event_names = [evt for evt, _ in events]
    assert event_names[-2] == "blocks"
    assert event_names[-1] == "done"

    # Verify token payload
    assert "token" in token_events[0] or "delta" in token_events[0]

    # Verify blocks payload
    blocks_data = blocks_events[0]
    assert "blocks" in blocks_data
    assert isinstance(blocks_data["blocks"], list)

    # Verify done payload
    done_data = done_events[0]
    assert done_data.get("status") == "completed"
    assert done_data.get("case_id") == case_id
    assert done_data.get("dispute_status") in ("in_dispute", "auto_dismissed")


@pytest.mark.asyncio
async def test_driver_chat_sse_stream_uses_real_agent_reply(client: AsyncClient):
    """Issue #482 review finding: the stream must surface the REAL agent reply
    (previously `run_driver_support_agent` was fired via `asyncio.create_task`
    and its result discarded; the driver only ever saw the deterministic
    policy-engine template). The streamed token text and the `done.reply`
    field must now equal the agent's real reply when the agent succeeds.
    """
    from unittest.mock import AsyncMock, patch

    case_id = f"case-real-reply-{uuid4().hex[:6]}"
    driver_id = f"drv-real-reply-{uuid4().hex[:6]}"
    _setup_test_case(case_id, driver_id)

    agent_reply = "GSupport đã đối soát trực tiếp với dữ liệu vệ tinh và xác nhận vị trí hợp lệ."
    agent_result = {"reply": agent_reply, "blocks": [], "error": None}

    with patch(
        "src.agents.driver_agent.run_driver_support_agent",
        new=AsyncMock(return_value=agent_result),
    ):
        res = await client.get(
            f"/api/v1/driver/cases/{case_id}/chat/stream",
            params={"message": "Tôi xin giải trình", "claim_type": "passenger_wait"},
            headers={"X-Driver-ID": driver_id, "X-Role": "driver"},
        )

    assert res.status_code == 200, res.text
    events = _parse_sse_blocks(res.text)
    token_text = "".join(data.get("token", data.get("delta", "")) for evt, data in events if evt == "token")
    done_data = [data for evt, data in events if evt == "done"][0]

    assert token_text.strip() == agent_reply
    assert done_data["reply"] == agent_reply


@pytest.mark.asyncio
async def test_driver_chat_sse_stream_post_with_locale(client: AsyncClient):
    """POST /driver/cases/{case_id}/chat/stream accepts locale and emits blocks event."""
    case_id = f"case-strm-post-{uuid4().hex[:6]}"
    driver_id = f"drv-strm-post-{uuid4().hex[:6]}"
    _setup_test_case(case_id, driver_id)

    res = await client.post(
        f"/api/v1/driver/cases/{case_id}/chat/stream",
        json={
            "message": "Heavy traffic gridlock on the road",
            "claim_type": "traffic_gridlock",
            "locale": "en",
        },
        headers={"X-Driver-ID": driver_id, "X-Role": "driver"},
    )
    assert res.status_code == 200, res.text
    assert "text/event-stream" in res.headers["content-type"]

    events = _parse_sse_blocks(res.text)
    blocks_events = [data for evt, data in events if evt == "blocks"]
    done_events = [data for evt, data in events if evt == "done"]

    assert len(blocks_events) == 1
    assert "blocks" in blocks_events[0]
    assert len(done_events) == 1


@pytest.mark.asyncio
async def test_analyst_delegation_inquiry(client: AsyncClient):
    """5. Analyst delegation inquiry updates case to evidence_requested / pending."""
    case_id = f"case-delegate-{uuid4().hex[:6]}"
    driver_id = f"drv-del-{uuid4().hex[:6]}"
    analyst_id = "analyst-senior-007"
    _setup_test_case(case_id, driver_id)

    payload = {
        "case_id": case_id,
        "analyst_id": analyst_id,
        "instruction": "Yêu cầu tài xế tải lên ảnh chụp màn hình ứng dụng dẫn đường",
        "deadline_hours": 36,
    }
    # Analyst role allowed
    res = await client.post(
        f"/api/v1/cases/{case_id}/delegate-inquiry",
        json=payload,
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["case_id"] == case_id
    assert data["dispute_status"] == "pending"
    assert "instruction" in data
    assert data["instruction"] == payload["instruction"]


@pytest.mark.asyncio
async def test_analyst_delegation_rejects_driver_role(client: AsyncClient):
    """Driver role must be forbidden from calling analyst delegation inquiry."""
    case_id = f"case-del-perm-{uuid4().hex[:6]}"
    driver_id = f"drv-no-perm-{uuid4().hex[:6]}"
    _setup_test_case(case_id, driver_id)

    payload = {
        "instruction": "Tự phê duyệt yêu cầu",
    }
    res = await client.post(
        f"/api/v1/cases/{case_id}/delegate-inquiry",
        json=payload,
        headers={"X-Driver-ID": driver_id, "X-Role": "driver"},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_analyst_dispute_dossier_retrieval(client: AsyncClient):
    """6. Analyst retrieves compiled dispute dossier for HITL adjudication."""
    case_id = f"case-dossier-{uuid4().hex[:6]}"
    driver_id = f"drv-dos-{uuid4().hex[:6]}"
    _setup_test_case(case_id, driver_id)

    # First add a chat turn so dossier has statement
    await client.post(
        f"/api/v1/driver/cases/{case_id}/chat",
        json={"message": "Tôi bị mất sóng định vị một đoạn", "claim_type": "gps_issue"},
        headers={"X-Driver-ID": driver_id, "X-Role": "driver"},
    )

    res = await client.get(f"/api/v1/cases/{case_id}/dispute-dossier")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["case_id"] == case_id
    assert data["driver_id"] == driver_id
    assert data["driver_statement"] == "Tôi bị mất sóng định vị một đoạn"
    assert data["claim_type"] == "gps_issue"
    assert "traffic_corroboration" in data
    assert "recommended_action" in data
    assert isinstance(data["transcript"], list)
    assert len(data["transcript"]) >= 1


@pytest.mark.asyncio
async def test_analyst_dispute_dossier_rejects_driver_role(client: AsyncClient):
    """Driver role must be forbidden from accessing analyst dispute dossier."""
    case_id = f"case-dos-perm-{uuid4().hex[:6]}"
    driver_id = f"drv-no-dos-{uuid4().hex[:6]}"
    _setup_test_case(case_id, driver_id)

    res = await client.get(
        f"/api/v1/cases/{case_id}/dispute-dossier",
        headers={"X-Driver-ID": driver_id, "X-Role": "driver"},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_unknown_case_handling_404(client: AsyncClient):
    """7. Unknown case returns 404 across all endpoints."""
    unknown_id = f"case-unknown-{uuid4().hex[:8]}"

    # 1. Dispute context
    res = await client.get(f"/api/v1/driver/cases/{unknown_id}/dispute")
    assert res.status_code == 404, f"Dispute context expected 404, got {res.status_code}"

    # 2. Driver chat
    res = await client.post(
        f"/api/v1/driver/cases/{unknown_id}/chat",
        json={"message": "Khiếu nại"},
    )
    assert res.status_code == 404, f"Driver chat expected 404, got {res.status_code}"

    # 3. Driver chat SSE stream
    res = await client.get(f"/api/v1/driver/cases/{unknown_id}/chat/stream")
    assert res.status_code == 404, f"Driver chat stream expected 404, got {res.status_code}"

    # 4. Delegate inquiry
    res = await client.post(
        f"/api/v1/cases/{unknown_id}/delegate-inquiry",
        json={"instruction": "Yêu cầu giải trình"},
    )
    assert res.status_code == 404, f"Delegate inquiry expected 404, got {res.status_code}"

    # 5. Dispute dossier
    res = await client.get(f"/api/v1/cases/{unknown_id}/dispute-dossier")
    assert res.status_code == 404, f"Dispute dossier expected 404, got {res.status_code}"


@pytest.mark.asyncio
async def test_driver_api_rbac_rejects_unauthorized_driver(client: AsyncClient):
    """When principal is Driver B (e.g. X-Driver-ID: drv-intruder-002, X-Role: driver),
    querying GET /driver/cases/{case_id}/dispute or posting POST /driver/cases/{case_id}/chat
    for Driver A's case raises HTTP 403 Forbidden.
    """
    case_id = f"case-rbac-{uuid4().hex[:6]}"
    driver_a = f"drv-owner-{uuid4().hex[:6]}"
    driver_b = "drv-intruder-002"
    _setup_test_case(case_id, driver_a)

    headers_b = {"X-Driver-ID": driver_b, "X-Role": "driver"}

    # 1. GET /driver/cases/{case_id}/dispute (and /api/v1/driver/cases/{case_id}/dispute)
    res_get = await client.get(f"/api/v1/driver/cases/{case_id}/dispute", headers=headers_b)
    assert res_get.status_code == 403

    res_get_root = await client.get(f"/driver/cases/{case_id}/dispute", headers=headers_b)
    assert res_get_root.status_code == 403

    # 2. POST /driver/cases/{case_id}/chat (and /api/v1/driver/cases/{case_id}/chat)
    chat_payload = {"message": "Tôi là tài xế lạ muốn can thiệp vụ việc"}
    res_post = await client.post(
        f"/api/v1/driver/cases/{case_id}/chat",
        json=chat_payload,
        headers=headers_b,
    )
    assert res_post.status_code == 403

    res_post_root = await client.post(
        f"/driver/cases/{case_id}/chat",
        json=chat_payload,
        headers=headers_b,
    )
    assert res_post_root.status_code == 403


@pytest.mark.asyncio
async def test_driver_api_empty_message_validation(client: AsyncClient):
    """Posting {"message": "   "} or {"message": ""} returns HTTP 422."""
    case_id = f"case-empty-msg-{uuid4().hex[:6]}"
    driver_id = f"drv-empty-{uuid4().hex[:6]}"
    _setup_test_case(case_id, driver_id)

    headers = {"X-Driver-ID": driver_id, "X-Role": "driver"}

    # Whitespace only
    res_spaces = await client.post(
        f"/api/v1/driver/cases/{case_id}/chat",
        json={"message": "   "},
        headers=headers,
    )
    assert res_spaces.status_code == 422

    # Empty string
    res_empty = await client.post(
        f"/api/v1/driver/cases/{case_id}/chat",
        json={"message": ""},
        headers=headers,
    )
    assert res_empty.status_code == 422


@pytest.mark.asyncio
async def test_driver_cases_list_and_session(client: AsyncClient):
    """GET /api/v1/driver/cases lists driver sessions and GET session returns conversation."""
    case_id = str(uuid4())
    driver_id = f"drv-sess-{uuid4().hex[:6]}"
    _setup_test_case(case_id, driver_id, "ERR-01")

    # 1. List cases
    headers = {"X-Driver-ID": driver_id, "X-Role": "driver"}
    res = await client.get("/api/v1/driver/cases", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert "total" in data
    assert any(c["case_id"] == case_id for c in data["items"])

    # 2. Get session
    res_sess = await client.get(f"/api/v1/driver/cases/{case_id}/session", headers=headers)
    assert res_sess.status_code == 200
    sess_data = res_sess.json()
    assert "messages" in sess_data
