"""End-to-End API test for GreenSM Driver Application and GSupport Agent."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app
from src.services.driver_dispute_service import get_driver_dispute_service


@pytest.mark.asyncio
async def test_e2e_driver_flow_full_lifecycle():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. List driver cases
        resp_cases = await client.get("/api/v1/driver/cases", params={"limit": 100})
        assert resp_cases.status_code == 200
        data_cases = resp_cases.json()
        assert "items" in data_cases
        assert data_cases["total"] > 0
        case_ids = [item["case_id"] for item in data_cases["items"]]

        # Ensure flagship case 26 exists in list
        target_case_id = "018f2f4e-a000-7000-8000-000000000026"
        assert target_case_id in case_ids
        active_case_id = target_case_id

        # Ensure active test case is in 'ready'/'in_dispute' state for repeatable testing
        dispute_svc = get_driver_dispute_service()
        cs = dispute_svc.case_service
        if active_case_id in cs._cases:
            cs._cases[active_case_id]["status"] = "ready"
            cs._cases[active_case_id]["dispute_status"] = "in_dispute"
            cs._cases[active_case_id]["dispute_deadline"] = (datetime.now(UTC) + timedelta(days=2)).isoformat()
        conn = None
        try:
            conn = dispute_svc._get_db_connection()
            if conn:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    cur.execute(
                        "UPDATE app.fraud_cases SET status = 'ready', dispute_status = 'in_dispute', dispute_deadline = now() + interval '2 days' WHERE id::text = %s;",
                        (active_case_id,),
                    )
                conn.commit()
        except Exception:
            pass
        finally:
            if conn:
                conn.close()

        # 2. Get dispute context for active case
        resp_ctx = await client.get(f"/api/v1/driver/cases/{active_case_id}/dispute")
        assert resp_ctx.status_code == 200
        data_ctx = resp_ctx.json()
        assert data_ctx["case_id"] == active_case_id
        assert "violation_code" in data_ctx
        assert "dispute_deadline" in data_ctx
        assert "allowed_claim_types" in data_ctx
        assert "traffic_gridlock" in data_ctx["allowed_claim_types"]

        # 3. Check session history
        resp_sess = await client.get(f"/api/v1/driver/cases/{active_case_id}/session")
        assert resp_sess.status_code == 200
        data_sess = resp_sess.json()
        assert "session_id" in data_sess
        assert "messages" in data_sess

        # 4. Driver chats to explain traffic gridlock
        chat_payload = {
            "case_id": active_case_id,
            "driver_id": data_ctx["driver_id"],
            "message": "Tôi bị kẹt xe cứng nhắc ở ngã tư Kim Mã, xe không thể di chuyển.",
            "claim_type": "traffic_gridlock",
        }
        resp_chat = await client.post(
            f"/api/v1/driver/cases/{active_case_id}/chat",
            json=chat_payload,
        )
        assert resp_chat.status_code == 200
        data_chat = resp_chat.json()
        assert data_chat["case_id"] == active_case_id
        assert len(data_chat["reply"]) > 0

        # Issue #73: no automatic dismissal; corroborated claim awaits analyst confirmation.
        assert data_chat["is_auto_dismissed"] is False
        assert data_chat["dispute_status"] == "pending_review"
        assert data_chat["exoneration_receipt"] is None
        assert data_chat["needs_analyst_review"] is True

        # 5. Verify SSE token streaming endpoint
        stream_payload = {
            "case_id": active_case_id,
            "driver_id": data_ctx["driver_id"],
            "message": "Tôi muốn xác nhận lại kết quả miễn trừ.",
            "claim_type": "traffic_gridlock",
        }
        resp_stream = await client.post(
            f"/api/v1/driver/cases/{active_case_id}/chat/stream",
            json=stream_payload,
        )
        assert resp_stream.status_code == 200
        assert "text/event-stream" in resp_stream.headers.get("content-type", "")
        stream_text = resp_stream.text
        assert "event: token" in stream_text or "event: done" in stream_text

        # 6. Verify case status moved to pending analyst confirmation
        resp_ctx_updated = await client.get(f"/api/v1/driver/cases/{active_case_id}/dispute")
        assert resp_ctx_updated.status_code == 200
        assert resp_ctx_updated.json()["dispute_status"] == "pending_review"
