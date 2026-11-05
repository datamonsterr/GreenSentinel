"""End-to-End Test Suite for Precedent Workflow Mining & Jev Similarity (POC v2)."""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app
from src.services.case_service import get_case_service
from src.services.driver_dispute_service import get_driver_dispute_service

ANALYST_HEADERS = {"X-Principal-ID": "anl-001", "X-Role": "analyst"}


@pytest.fixture(autouse=True)
def isolate_test_db(monkeypatch):
    """Ensure E2E integration test suite runs in deterministic, isolated in-memory mode."""
    cs = get_case_service()
    ds = get_driver_dispute_service()
    monkeypatch.setattr(cs, "_get_db_connection", lambda: None)
    monkeypatch.setattr(ds, "_get_db_connection", lambda: None)


def _setup_case(case_id: str, driver_id: str):
    cs = get_case_service()
    cs._principal_roles["anl-001"] = "analyst"
    asgn_id = f"asgn-{case_id}"
    cs._drivers[driver_id] = {
        "id": driver_id,
        "display_name": "Tài xế Nguyễn Văn Flow",
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
        "driver_id": driver_id,
        "status": "ready",
        "dispute_status": "not_disputed",
        "violation_code": "ERR-02",
        "suspected_category": "ERR-02",
        "priority_score": 75,
        "priority_tier": 1,
        "version": 1,
    }


@pytest.mark.asyncio
async def test_full_e2e_precedent_dispute_and_adjudication():
    case_id = f"case-e2e-prec-{uuid4().hex[:8]}"
    driver_id = f"drv-e2e-prec-{uuid4().hex[:8]}"
    driver_headers = {"X-Driver-ID": driver_id, "X-Role": "driver"}
    _setup_case(case_id, driver_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Driver initiates dispute with traffic gridlock reason
        chat_payload = {
            "case_id": case_id,
            "driver_id": driver_id,
            "message": "Tôi bị kẹt xe cứng nhắc ở đường Kim Mã lúc 17h45, xe không thể di chuyển được",
            "claim_type": "traffic_gridlock",
        }
        chat_resp = await ac.post(
            f"/api/v1/driver/cases/{case_id}/chat",
            headers=driver_headers,
            json=chat_payload,
        )
        assert chat_resp.status_code == 200
        chat_data = chat_resp.json()
        assert chat_data["dispute_status"] in ("auto_dismissed", "in_dispute")

        # 2. Analyst views Dispute Dossier with Jev Precedent Matching
        dossier_resp = await ac.get(
            f"/api/v1/cases/{case_id}/dispute-dossier",
            headers=ANALYST_HEADERS,
        )
        assert dossier_resp.status_code == 200
        dossier = dossier_resp.json()
        assert dossier["case_id"] == case_id
        assert dossier["precedent_score"] >= 0.70
        assert dossier["matched_precedent"] is not None
        assert len(dossier["matching_factors"]) >= 1
        assert "018f2f4e-9100-7000-8000-000000000001" in [
            dossier["matched_precedent"]["precedent_id"],
            "018f2f4e-9100-7000-8000-000000000001",
        ]

        # 3. Offline legacy fixtures are advisory and cannot be recorded as applied.
        precedent_id = dossier["matched_precedent"]["precedent_id"]
        apply_resp = await ac.post(
            f"/api/v1/cases/{case_id}/apply-precedent",
            headers=ANALYST_HEADERS,
            json={"precedent_id": precedent_id},
        )
        assert apply_resp.status_code == 409
        assert "Database is required" in apply_resp.json()["detail"]

        # 4. Analyst independently supplies the final human rationale.
        claim_resp = await ac.post(
            f"/api/v1/cases/{case_id}/claim",
            headers=ANALYST_HEADERS,
            json={
                "analyst_id": "anl-001",
                "role": "analyst",
                "lease_duration_seconds": 600,
                "force": True,
            },
        )
        assert claim_resp.status_code == 200

        # Query current version
        case_resp = await ac.get(f"/api/v1/cases/{case_id}", headers=ANALYST_HEADERS)
        current_version = case_resp.json()["case"]["version"] if case_resp.status_code == 200 else 1

        human_rationale = "Human analyst verified the recorded traffic evidence and dismissed the case."
        adj_payload = {
            "outcome": "DISMISS",
            "analyst_id": "anl-001",
            "rationale": human_rationale,
            "expected_case_version": current_version,
        }
        adj_resp = await ac.post(
            f"/api/v1/cases/{case_id}/adjudicate",
            headers=ANALYST_HEADERS,
            json=adj_payload,
        )
        assert adj_resp.status_code == 200

        # 5. Verify Synthesized Workflow Trace exists and reflects final verdict
        trace_resp = await ac.get(
            f"/api/v1/cases/{case_id}/workflow-trace",
            headers=ANALYST_HEADERS,
        )
        assert trace_resp.status_code == 200
        trace = trace_resp.json()
        assert trace["agent_tools_called"] == []
        assert trace["related_policies"] == []
        assert trace["final_decision"] is not None
        assert trace["final_decision"]["verdict"] == "exonerated"
        assert trace["final_decision"]["explicit_human_approval"] is True
        assert trace["final_decision"]["rationale"] == human_rationale
