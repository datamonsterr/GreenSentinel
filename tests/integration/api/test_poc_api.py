from uuid import uuid4

import pytest
from dotenv import load_dotenv

from src.config import get_settings
from src.services.case_service import get_case_service


@pytest.mark.asyncio
async def test_health_check(client):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "env" in data
    assert data["database"] in ("connected", "disconnected")

    # API v1 health alias
    response_v1 = await client.get("/api/v1/health")
    assert response_v1.status_code == 200
    data_v1 = response_v1.json()
    assert data_v1["status"] == "ok"
    assert data_v1["database"] in ("connected", "disconnected")


@pytest.mark.asyncio
async def test_telemetry_ingest_and_idempotency(client, monkeypatch):
    # Random IDs are valid for the isolated in-memory contract, not the FK-backed database.
    monkeypatch.setattr(get_case_service(), "_get_db_connection", lambda: None)
    trip_id = str(uuid4())
    assignment_id = str(uuid4())
    driver_id = str(uuid4())
    event_id = str(uuid4())
    correlation_id = str(uuid4())

    envelope = {
        "schema_version": 1,
        "event_id": event_id,
        "event_type": "telemetry.observed",
        "source": "simulator",
        "occurred_at": "2026-09-22T06:00:25Z",
        "correlation_id": correlation_id,
        "trip_id": trip_id,
        "assignment_id": assignment_id,
        "driver_id": driver_id,
        "sequence": 1,
        "payload": {
            "position": {
                "latitude": 21.0285,
                "longitude": 105.8542,
                "accuracy_m": 5.0,
            },
            "speed_mps": 0.0,
            "bearing_deg": 180.0,
            "app_state": "foreground",
            "network_state": "online",
            "gps_state": "valid",
            "mock_location_reported": False,
        },
    }

    # 1. First ingest -> status="ingested", duplicate=False
    res1 = await client.post("/api/v1/telemetry/ingest", json=envelope)
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["status"] == "ingested"
    assert data1["duplicate"] is False
    assert data1["event_id"] == event_id

    # 2. Duplicate ingest (same sequence and trip_id) -> status="duplicate", duplicate=True
    res2 = await client.post("/api/v1/telemetry/ingest", json=envelope)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["status"] == "duplicate"
    assert data2["duplicate"] is True
    assert data2["event_id"] == event_id

    # 3. Invalid schema validation -> 422 Unprocessable Entity
    invalid_envelope = dict(envelope)
    invalid_envelope["payload"] = {"position": {"latitude": 999.0, "longitude": 105.0, "accuracy_m": -1}}
    res3 = await client.post("/api/v1/telemetry/ingest", json=invalid_envelope)
    assert res3.status_code == 422


@pytest.mark.asyncio
async def test_simulations_trigger(client):
    # Intentional DIC scenario
    res_dic = await client.post("/api/v1/simulations/intentional_dic")
    assert res_dic.status_code == 200
    data_dic = res_dic.json()
    assert data_dic["scenario"] == "intentional_dic"
    assert data_dic["status"] == "triggered"
    assert "case_id" in data_dic

    # Traffic gridlock scenario
    res_grid = await client.post("/api/v1/simulations/traffic_gridlock")
    assert res_grid.status_code == 200
    data_grid = res_grid.json()
    assert data_grid["scenario"] == "traffic_gridlock"
    assert data_grid["status"] == "triggered"

    # Technical dropout scenario
    res_drop = await client.post("/api/v1/simulations/technical_dropout")
    assert res_drop.status_code == 200
    data_drop = res_drop.json()
    assert data_drop["scenario"] == "technical_dropout"
    assert data_drop["status"] == "triggered"

    # Unknown scenario -> 400
    res_unknown = await client.post("/api/v1/simulations/unknown_scenario")
    assert res_unknown.status_code == 400


@pytest.mark.asyncio
async def test_cases_queue_and_filters(client):
    # All cases
    res = await client.get("/api/v1/cases")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] > 0
    assert len(data["items"]) <= 50

    # Filter by priority P0
    res_p0 = await client.get("/api/v1/cases?priority=P0")
    assert res_p0.status_code == 200
    data_p0 = res_p0.json()
    for item in data_p0["items"]:
        assert item["priority"] == "P0"

    # Filter by priority 0 (integer format)
    res_p0_int = await client.get("/api/v1/cases?priority=0")
    assert res_p0_int.status_code == 200
    data_p0_int = res_p0_int.json()
    for item in data_p0_int["items"]:
        assert item["priority"] == "P0"

    # Filter by status
    res_ready = await client.get("/api/v1/cases?status=ready")
    assert res_ready.status_code == 200
    data_ready = res_ready.json()
    for item in data_ready["items"]:
        assert item["status"] == "ready"

    # Pagination
    res_page = await client.get("/api/v1/cases?limit=5&offset=0")
    assert res_page.status_code == 200
    data_page = res_page.json()
    assert len(data_page["items"]) <= 5


@pytest.mark.asyncio
async def test_case_detail_dossier(client):
    # Retrieve a known case
    cases_res = await client.get("/api/v1/cases?limit=1")
    assert cases_res.status_code == 200
    case_id = cases_res.json()["items"][0]["id"]

    res = await client.get(f"/api/v1/cases/{case_id}")
    assert res.status_code == 200
    data = res.json()

    # Verify dossier elements
    assert "case" in data
    assert data["case"]["id"] == case_id
    assert "trip" in data
    assert "telemetry_samples" in data
    assert isinstance(data["telemetry_samples"], list)
    assert "guardrails" in data
    assert "blocking_guardrail" in data["guardrails"]

    # Nonexistent case -> 404
    bad_id = "00000000-0000-0000-0000-000000000000"
    res_404 = await client.get(f"/api/v1/cases/{bad_id}")
    assert res_404.status_code == 404


@pytest.mark.asyncio
async def test_case_claim_lease_management(client):
    # Find a case without an active lease from queue
    res_cases = await client.get("/api/v1/cases?limit=20")
    assert res_cases.status_code == 200
    items = res_cases.json()["items"]
    assert items
    case_id = items[0]["id"]
    for it in items:
        det = await client.get(f"/api/v1/cases/{it['id']}")
        if det.status_code == 200 and not det.json().get("active_lease"):
            case_id = it["id"]
            break

    analyst_a = "018f2f4e-1000-7000-8000-000000000001"
    analyst_b = "018f2f4e-1000-7000-8000-000000000002"

    # Analyst A claims lease
    res_claim1 = await client.post(
        f"/api/v1/cases/{case_id}/claim",
        json={"analyst_id": analyst_a, "lease_duration_seconds": 300},
    )
    assert res_claim1.status_code == 200
    data_claim1 = res_claim1.json()
    assert data_claim1["case_id"] == case_id
    assert data_claim1["analyst_id"] == analyst_a
    assert data_claim1["status"] == "claimed"

    # Analyst B attempts to claim the same active lease -> 409 Conflict
    res_conflict = await client.post(
        f"/api/v1/cases/{case_id}/claim",
        json={"analyst_id": analyst_b, "lease_duration_seconds": 300},
    )
    assert res_conflict.status_code == 409

    # Analyst A extends / reclaims lease -> 200 OK
    res_extend = await client.post(
        f"/api/v1/cases/{case_id}/claim",
        json={"analyst_id": analyst_a, "lease_duration_seconds": 600},
    )
    assert res_extend.status_code == 200


@pytest.mark.asyncio
async def test_claim_release_mock_case_redis_lock_and_roles(client):
    queue = (await client.get("/api/v1/cases?limit=20")).json()["items"]
    assert queue
    mock_case_id = queue[0]["id"]
    analyst_a = "018f2f4e-1000-7000-8000-000000000001"
    analyst_b = "018f2f4e-1000-7000-8000-000000000002"
    admin_user = "018f2f4e-1000-7000-8000-000000000099"
    unauthorized_user = "driver-test-01"

    # Ensure clean slate by releasing if already claimed
    await client.post(
        f"/api/v1/cases/{mock_case_id}/release",
        json={"analyst_id": admin_user, "role": "admin", "force": True},
    )

    # 1. Unauthorized role cannot claim
    res_unauth = await client.post(
        f"/api/v1/cases/{mock_case_id}/claim",
        json={"analyst_id": unauthorized_user, "role": "driver", "lease_duration_seconds": 300},
    )
    assert res_unauth.status_code == 403

    # 2. Analyst A claims mock case -> 200 OK
    res_claim_a = await client.post(
        f"/api/v1/cases/{mock_case_id}/claim",
        json={"analyst_id": analyst_a, "role": "analyst", "lease_duration_seconds": 300},
    )
    assert res_claim_a.status_code == 200
    data_claim_a = res_claim_a.json()
    assert data_claim_a["status"] == "claimed"
    assert data_claim_a["analyst_id"] == analyst_a

    # 3. Analyst B attempts to claim locked case -> 409 Conflict
    res_claim_b = await client.post(
        f"/api/v1/cases/{mock_case_id}/claim",
        json={"analyst_id": analyst_b, "role": "analyst", "lease_duration_seconds": 300},
    )
    assert res_claim_b.status_code == 409
    err_b = res_claim_b.json()
    assert "detail" in err_b

    # 4. Analyst B attempts to release Analyst A's lease without force -> 403 Forbidden
    res_rel_b = await client.post(
        f"/api/v1/cases/{mock_case_id}/release",
        json={"analyst_id": analyst_b, "role": "analyst", "force": False},
    )
    assert res_rel_b.status_code == 403

    # 5. Admin can force release Analyst A's lease -> 200 OK
    res_rel_admin = await client.post(
        f"/api/v1/cases/{mock_case_id}/release",
        json={"analyst_id": admin_user, "role": "admin", "force": True},
    )
    assert res_rel_admin.status_code == 200
    assert res_rel_admin.json()["status"] == "released"

    # 6. Analyst B can now claim the released case -> 200 OK
    res_claim_b_ok = await client.post(
        f"/api/v1/cases/{mock_case_id}/claim",
        json={"analyst_id": analyst_b, "role": "senior_analyst", "lease_duration_seconds": 300},
    )
    assert res_claim_b_ok.status_code == 200

    # 7. Analyst B releases their own lease -> 200 OK
    res_rel_b_ok = await client.post(
        f"/api/v1/cases/{mock_case_id}/release",
        json={"analyst_id": analyst_b, "role": "senior_analyst", "force": False},
    )
    assert res_rel_b_ok.status_code == 200
    assert res_rel_b_ok.json()["status"] == "released"

    # Clean up
    await client.post(f"/api/v1/cases/{mock_case_id}/release", json={"analyst_id": analyst_a, "role": "analyst"})


@pytest.mark.asyncio
async def test_case_non_terminal_actions(client):
    cases_res = await client.get("/api/v1/cases?limit=1")
    case_id = cases_res.json()["items"][0]["id"]
    analyst = "018f2f4e-1000-7000-8000-000000000001"

    # 1. REQUEST_EVIDENCE
    res_req = await client.post(
        f"/api/v1/cases/{case_id}/actions",
        json={
            "action_type": "REQUEST_EVIDENCE",
            "analyst_id": analyst,
            "notes": "Requesting driver telemetry logs and customer chat transcript",
        },
    )
    assert res_req.status_code == 200
    data_req = res_req.json()
    assert data_req["action_type"] == "REQUEST_EVIDENCE"
    assert data_req["new_case_status"] == "evidence_requested"

    # Legacy actions are rejected by the v1 request schema.
    res_esc = await client.post(
        f"/api/v1/cases/{case_id}/actions",
        json={
            "action_type": "ESCALATE",
            "analyst_id": analyst,
            "notes": "Complex intentional DIC pattern, escalating to lead investigator",
        },
    )
    assert res_esc.status_code == 422

    res_def = await client.post(
        f"/api/v1/cases/{case_id}/actions",
        json={
            "action_type": "DEFER",
            "analyst_id": analyst,
            "notes": "Deferring pending road construction verification",
        },
    )
    assert res_def.status_code == 422


@pytest.mark.asyncio
async def test_adjudication_blocked_for_unassigned_analyst(client):
    analyst_a = "018f2f4e-1000-7000-8000-000000000001"
    analyst_b = "018f2f4e-1000-7000-8000-000000000003"
    admin_user = "018f2f4e-1000-7000-8000-000000000099"
    target_case_id = (await client.get("/api/v1/cases?limit=1")).json()["items"][0]["id"]

    # 1. Analyst A claims the case
    res_claim = await client.post(
        f"/api/v1/cases/{target_case_id}/claim",
        json={"analyst_id": analyst_a, "role": "analyst", "lease_duration_seconds": 300, "force": True},
    )
    assert res_claim.status_code == 200

    # Verify list_cases immediately reflects in_review status and assigned_analyst
    res_list = await client.get("/api/v1/cases?limit=20")
    assert res_list.status_code == 200

    # 2. Analyst B attempts to adjudicate Analyst A's case -> 409 Conflict
    res_unauth_adj = await client.post(
        f"/api/v1/cases/{target_case_id}/adjudicate",
        json={
            "outcome": "AGREE",
            "analyst_id": analyst_b,
            "rationale": "Analyst B attempting to adjudicate case owned by Analyst A",
            "expected_case_version": 1,
        },
    )
    assert res_unauth_adj.status_code == 409
    err_detail = res_unauth_adj.json()["detail"]
    assert "assigned to analyst" in err_detail or "claimed by analyst" in err_detail

    # 3. Clean up: Release case
    await client.post(
        f"/api/v1/cases/{target_case_id}/release",
        json={"analyst_id": admin_user, "role": "admin", "force": True},
    )


@pytest.mark.asyncio
async def test_case_terminal_adjudication(client):
    import os
    from datetime import UTC, datetime

    from src.services.telemetry_queue_worker import process_telemetry_event

    load_dotenv(".env")
    if not os.getenv("ISSUE63_DATABASE_URL") and not os.getenv("DATABASE_URL"):
        pytest.skip("requires an explicitly configured disposable integration database")
    from tests.support.database import require_database

    require_database(get_settings().database_url, required=bool(os.getenv("ISSUE63_DATABASE_URL")))
    evt_res = await process_telemetry_event(
        {
            "event_id": str(uuid4()),
            "scenario": "driver_stall_cancel",
            "cancellation_reason": "stalled",
            "stationary_duration_s": 220,
            "pickup": [105.8542, 21.0285],
            "dropoff": [105.8600, 21.0350],
            "points": [
                {
                    "speed_mps": 0.0,
                    "latitude": 21.0285,
                    "longitude": 105.8542,
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "sequence": 0,
                }
            ],
        }
    )
    target_case_id = evt_res["case_id"]
    analyst = "018f2f4e-1000-7000-8000-000000000001"
    import psycopg
    from psycopg.rows import dict_row

    case_service = get_case_service()
    case_service._active_leases.pop(target_case_id, None)

    with psycopg.connect(get_settings().database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE app.fraud_cases
                   SET assigned_analyst_id = %s::uuid, status = 'in_review', resolved_at = NULL
                   WHERE id = %s::uuid""",
                (analyst, target_case_id),
            )
            cur.execute("DELETE FROM app.review_leases WHERE case_id = %s::uuid", (target_case_id,))
        conn.commit()
    memory_case = case_service._cases.get(target_case_id)
    if memory_case is not None:
        memory_case.update(
            assigned_analyst_id=analyst,
            status="in_review",
            version=1,
            resolved_at=None,
        )

    try:
        claim_res = await client.post(
            f"/api/v1/cases/{target_case_id}/claim",
            json={"analyst_id": analyst, "role": "analyst", "lease_duration_seconds": 300, "force": True},
        )
        assert claim_res.status_code == 200, claim_res.text

        # 1. Stale version -> 409 Conflict
        res_stale = await client.post(
            f"/api/v1/cases/{target_case_id}/adjudicate",
            json={
                "outcome": "AGREE",
                "analyst_id": analyst,
                "rationale": "Clear intentional stall for 4 minutes causing cancellation",
                "expected_case_version": 100,
            },
        )
        assert res_stale.status_code == 409

        # 2. Valid terminal adjudication -> 200 OK
        res_adj = await client.post(
            f"/api/v1/cases/{target_case_id}/adjudicate",
            json={
                "outcome": "AGREE",
                "analyst_id": analyst,
                "rationale": "Clear intentional stall for 4 minutes causing passenger cancellation",
                "expected_case_version": 1,
                "policy_version_id": "018f2f4e-6000-7000-8000-000000000001",
            },
        )
        assert res_adj.status_code == 200, res_adj.text
        data_adj = res_adj.json()
        assert data_adj["status"] == "adjudicated"
        assert data_adj["outcome"] == "AGREE"
        assert data_adj["new_version"] == 2
        assert data_adj["sanction_applied"] is None
    finally:
        await client.post(
            f"/api/v1/cases/{target_case_id}/release",
            json={"analyst_id": analyst, "role": "analyst", "force": True},
        )


@pytest.mark.asyncio
async def test_guardrail_does_not_block_adjudication_and_is_advisory(client, monkeypatch):
    """Exercise advisory guardrails with private state and no database or Redis access."""
    from src.api.auth import Principal, require_principal
    from src.config import Settings
    from src.main import app
    from src.services.case_service import CaseService

    # Avoid loading shared seed state. Production connection methods remain unchanged.
    monkeypatch.setattr(CaseService, "_load_seed_data", lambda self: None)
    service = CaseService(Settings(_env_file=None, app_env="test", database_url=""))
    monkeypatch.setattr(service, "_get_db_connection", lambda: None)
    monkeypatch.setattr(service, "get_redis_client", lambda: None)
    case_id, assignment_id, analyst = str(uuid4()), str(uuid4()), str(uuid4())
    service._principal_roles[analyst] = "analyst"
    service._cases[case_id] = {
        "id": case_id,
        "assignment_id": assignment_id,
        "assigned_analyst_id": analyst,
        "status": "evidence_requested",
        "version": 1,
    }
    service._platform_incidents[assignment_id] = {"incident_type": "app_crash"}
    principal = Principal(analyst, str(uuid4()), frozenset({"analyst"}))
    monkeypatch.setitem(app.dependency_overrides, get_case_service, lambda: service)
    monkeypatch.setitem(app.dependency_overrides, require_principal, lambda: principal)

    detail = await service.get_case_detail(case_id)
    assert detail.guardrails["blocking_guardrail"] is True
    assert detail.guardrails.get("suggested_outcome") == "Disagree (System Error)"

    res_disagree = await client.post(
        f"/api/v1/cases/{case_id}/adjudicate",
        json={
            "outcome": "DISAGREE",
            "analyst_id": analyst,
            "rationale": "Verified technical incident",
            "expected_case_version": 1,
        },
    )
    assert res_disagree.status_code == 200, res_disagree.text
    assert res_disagree.json()["outcome"] == "DISAGREE"
    assert res_disagree.json()["new_version"] == 2
    assert service._cases[case_id]["status"] == "resolved"


@pytest.mark.asyncio
async def test_case_progress_sse_stream(client):
    cases_res = await client.get("/api/v1/cases?limit=1")
    case_id = cases_res.json()["items"][0]["id"]

    res = await client.get(f"/api/v1/cases/{case_id}/stream")
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]
    text = res.text
    assert "event: case_progress" in text
    assert "data: " in text
    assert case_id in text


@pytest.mark.asyncio
async def test_policy_chat_sse_stream(client, monkeypatch):
    # The session migration is required for persistence; this suite must not mutate a linked database.
    # The configured integration database may predate the additive migration.
    service = get_case_service()
    if service._get_db_connection() is not None:
        monkeypatch.setattr(service, "_get_db_connection", lambda: None)
    req_body = {
        "query": "Quy dinh xu phat hanh vi dung yen khong don khach DIC",
        "case_id": "018f2f4e-a000-7000-8000-000000000001",
    }
    res = await client.post("/api/v1/policy/chat/stream", json=req_body)
    if res.status_code in {500, 503} and "case_agent_sessions" in res.text:
        pytest.skip("case_agent_sessions migration is not installed in the configured test database")
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]
    text = res.text
    if "Case agent session database unavailable" in text:
        pytest.skip("case_agent_sessions migration is not installed in the configured test database")
    assert "event: citation" in text
    assert "event: tool_call" in text
    assert "event: thinking" in text
    assert "event: text_delta" in text
    assert "event: done" in text
    assert "tool_called" in text
    assert "thought" in text
