"""
Backend Python E2E Lifecycle Suite for Issue #197 Sprint 3 UAT Runbook.

Verifies Sprint 3 deliverables (FEAT-S3-01 through FEAT-S3-07).
Features not yet fully implemented are marked with xfail.
"""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.services.case_service import get_case_service
from src.services.driver_dispute_service import get_driver_dispute_service

ANALYST_HEADERS = {"X-Analyst-ID": "analyst-1", "X-Role": "analyst", "X-Test-Context": "true"}


@pytest.fixture(autouse=True)
def isolate_test_db(monkeypatch):
    """Ensure E2E integration test suite runs in deterministic, isolated in-memory mode.

    CaseService and DriverDisputeService explicitly guard database execution via
    `if conn is not None:`. Returning None triggers their canonical in-memory fallback path
    without requiring external PostgreSQL connectivity.
    """
    cs = get_case_service()
    ds = get_driver_dispute_service()
    monkeypatch.setattr(cs, "_get_db_connection", lambda: None)
    monkeypatch.setattr(ds, "_get_db_connection", lambda: None)


@pytest.fixture
def setup_e2e_case():
    """Helper to seed the in-memory store for a test case."""
    created_cases = []
    created_drivers = []
    created_assignments = []

    def _setup(case_id: str, driver_id: str, suspected_category: str = "ERR-01") -> None:
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
            "conversation": [
                {"role": "driver", "text": "Traffic caused delay.", "occurred_at": "2026-09-25T08:02:00Z"}
            ],
        }
        created_cases.append(case_id)
        created_drivers.append(driver_id)
        created_assignments.append(asgn_id)

    yield _setup

    cs = get_case_service()
    for cid in created_cases:
        cs._cases.pop(cid, None)
    for did in created_drivers:
        cs._drivers.pop(did, None)
    for aid in created_assignments:
        cs._assignments.pop(aid, None)


@pytest.mark.asyncio
async def test_feat_s3_01_driver_motivation_assessment(client: AsyncClient, setup_e2e_case):
    """FEAT-S3-01: Verify get_forensic_brief returns expected fields."""
    case_id = f"case-{uuid4().hex[:8]}"
    driver_id = f"drv-{uuid4().hex[:8]}"
    setup_e2e_case(case_id, driver_id)

    res = await client.get(f"/api/v1/cases/{case_id}/forensic-brief", headers=ANALYST_HEADERS)
    assert res.status_code == 200, res.text
    data = res.json()

    assessment = data["motivation_assessment"]
    assert assessment["economic_incentive_reward"] == 0.0
    assert assessment["intent_profile"] == "unclear_insufficient_data"
    assert assessment["natural_vietnamese_narrative"]


@pytest.mark.asyncio
@pytest.mark.xfail(strict=False, reason="FEAT-S3-02: Traffic tool invocation not yet implemented")
async def test_feat_s3_02_traffic_tool_invocation(client: AsyncClient, setup_e2e_case):
    """FEAT-S3-02: Verify /api/v1/policy/chat/stream exposes traffic corroboration tools."""
    case_id = str(uuid4())
    driver_id = str(uuid4())
    setup_e2e_case(case_id, driver_id)

    payload = {"query": "Check traffic for this case", "case_id": case_id}
    res = await client.post("/api/v1/policy/chat/stream", json=payload, headers=ANALYST_HEADERS)
    assert res.status_code == 200, res.text

    # Will xpass when FEAT-S3-02 is implemented: response must reference traffic corroboration tools
    assert "fetch_corridor_historical_traffic" in res.text or "query_traffic_incident_feed" in res.text


@pytest.mark.asyncio
@pytest.mark.xfail(strict=False, reason="FEAT-S3-03: Case document upload seam not yet implemented")
async def test_feat_s3_03_case_document_upload(client: AsyncClient):
    """FEAT-S3-03: Verify /api/v1/cases/{case_id}/documents endpoint exists."""
    case_id = f"case-{uuid4().hex[:8]}"

    res_post = await client.post(
        f"/api/v1/cases/{case_id}/documents", json={"filename": "test.pdf"}, headers=ANALYST_HEADERS
    )

    assert res_post.status_code in [200, 201], res_post.text

    res_get = await client.get(f"/api/v1/cases/{case_id}/documents", headers=ANALYST_HEADERS)
    assert res_get.status_code == 200
    assert isinstance(res_get.json(), list)


@pytest.mark.asyncio
async def test_feat_s3_04_conversation_endpoint_is_readonly(client: AsyncClient, setup_e2e_case):
    """FEAT-S3-04 (part 1): GET works, analyst POST to conversation is blocked (read-only enforcement)."""
    case_id = str(uuid4())
    driver_id = str(uuid4())
    setup_e2e_case(case_id, driver_id)

    res = await client.get(f"/api/v1/cases/{case_id}", headers=ANALYST_HEADERS)
    assert res.status_code == 200, res.text
    data = res.json()
    assert "conversation" in data
    assert isinstance(data["conversation"], list)

    # Analyst POST to /conversation must be blocked (read-only — endpoint does not exist)
    res_post = await client.post(
        f"/api/v1/cases/{case_id}/conversation",
        json={"role": "analyst", "text": "Injected message"},
        headers=ANALYST_HEADERS,
    )
    assert res_post.status_code in [404, 405, 403], (
        f"Expected POST /conversation to be blocked (404/405/403), got {res_post.status_code}"
    )


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=False,
    reason=(
        "FEAT-S3-04 (part 2): In-memory CaseDetailResponse does not yet surface seeded "
        "conversation messages from _cases store. Will xpass once FEAT-S3-04 is implemented."
    ),
)
async def test_feat_s3_04_conversation_messages_non_empty(client: AsyncClient, setup_e2e_case):
    """FEAT-S3-04 (part 2): Case detail must return non-empty conversation with role/text fields."""
    case_id = str(uuid4())
    driver_id = str(uuid4())
    setup_e2e_case(case_id, driver_id)

    res = await client.get(f"/api/v1/cases/{case_id}", headers=ANALYST_HEADERS)
    assert res.status_code == 200, res.text
    data = res.json()

    assert len(data["conversation"]) > 0, "Expected seeded conversation messages"
    first_msg = data["conversation"][0]
    assert "role" in first_msg, f"Missing 'role' in message, got keys: {list(first_msg.keys())}"
    assert "text" in first_msg, f"Missing 'text' in message, got keys: {list(first_msg.keys())}"


@pytest.mark.asyncio
@pytest.mark.xfail(strict=False, reason="FEAT-S3-05: PostHog + LangSmith trace correlation not yet implemented")
async def test_feat_s3_05_trace_correlation(client: AsyncClient):
    """FEAT-S3-05: Verify /api/v1/telemetry/events exists."""
    res = await client.post("/api/v1/telemetry/events", json={"event": "test"}, headers=ANALYST_HEADERS)

    assert res.status_code == 200, res.text


@pytest.mark.asyncio
@pytest.mark.xfail(strict=False, reason="FEAT-S3-06: Telemetry beacon + analyst session not yet implemented")
async def test_feat_s3_06_telemetry_beacon(client: AsyncClient):
    """FEAT-S3-06: Verify /api/v1/telemetry/analyst-session endpoint exists."""
    res = await client.post("/api/v1/telemetry/analyst-session", json={"session_id": "123"}, headers=ANALYST_HEADERS)

    assert res.status_code == 200, res.text


@pytest.mark.asyncio
@pytest.mark.xfail(strict=False, reason="FEAT-S3-07: POST /test/api/v1/runs simulation execution not yet implemented")
async def test_feat_s3_07_test_dashboard_orchestrator(client: AsyncClient):
    """FEAT-S3-07: Verify /test/api/v1/... simulation endpoints respond correctly."""
    res = await client.get("/test/api/v1/plans", headers=ANALYST_HEADERS)
    assert res.status_code == 200, res.text
    assert isinstance(res.json(), list)

    res_run = await client.post(
        "/test/api/v1/runs", json={"definition_revision_id": str(uuid4()), "speed_factor": 1.0}, headers=ANALYST_HEADERS
    )
    assert res_run.status_code in [200, 201, 202], res_run.text
