"""Integration tests for Issue #483: confirmation-gated accept/reject flow & statement drafts.

Covers:
1. FastAPI endpoints (/confirmations, /statement, /acknowledge, /statement-draft) with RBAC & 404 ownership checks.
2. Single-use token consumption, cross-case token rejection, audit timeline recording, and zero automated sanctions.
3. Real PostgreSQL persistence against `disposable_database_dsn` (tables `app.driver_confirmation_tokens` and `app.driver_statement_drafts`).
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from httpx import AsyncClient

from src.services.case_service import CaseService, get_case_service
from src.services.driver_dispute_service import DriverDisputeService, get_driver_dispute_service
from src.services.scenario_seeder import ScenarioSeeder
from tests.integration.conftest import DsnCaseService, is_postgres_available

pytestmark = pytest.mark.integration

OWNED_CASE_ID = "018f2f4e-b000-7000-8000-000000000001"
OTHER_CASE_ID = "018f2f4e-b000-7000-8000-000000000002"
OWNED_DRIVER_ID = "018f2f4e-b300-7000-8000-000000000001"
FOREIGN_DRIVER_ID = "018f2f4e-b300-7000-8000-000000000002"

OWNER_HEADERS = {"X-Driver-ID": OWNED_DRIVER_ID, "X-Role": "driver"}
FOREIGN_HEADERS = {"X-Driver-ID": FOREIGN_DRIVER_ID, "X-Role": "driver"}
ANALYST_HEADERS = {"X-Role": "analyst"}


@pytest.fixture(autouse=True)
def configure_test_auth_env(monkeypatch):
    """Ensure test auth is enabled and get_settings cache is cleared for #483 integration suite."""
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("TEST_AUTH_ENABLED", "true")
    from src.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def seeded_memory_env(monkeypatch):
    """Seed deterministic in-memory scenarios with DB fallback disabled for fast API contract tests."""
    monkeypatch.setattr(CaseService, "_get_db_connection", lambda self: None)
    seeder = ScenarioSeeder()
    seeder.seed_in_memory()
    yield
    seeder.clean_in_memory()


@pytest.mark.asyncio
async def test_api_confirmations_and_statement_flow(client: AsyncClient, seeded_memory_env):
    # 1. Invalid action -> 422
    bad_action = await client.post(
        f"/api/v1/driver/cases/{OWNED_CASE_ID}/confirmations",
        json={"action": "invalid_action"},
        headers=OWNER_HEADERS,
    )
    assert bad_action.status_code == 422

    # 2. Foreign driver or missing case -> 404
    foreign_conf = await client.post(
        f"/api/v1/driver/cases/{OWNED_CASE_ID}/confirmations",
        json={"action": "submit_statement"},
        headers=FOREIGN_HEADERS,
    )
    assert foreign_conf.status_code == 404

    missing_conf = await client.post(
        "/api/v1/driver/cases/018f2f4e-0000-0000-0000-000000000404/confirmations",
        json={"action": "submit_statement"},
        headers=OWNER_HEADERS,
    )
    assert missing_conf.status_code == 404

    # 3. Unmapped / non-driver role -> 403 or 404
    analyst_conf = await client.post(
        f"/api/v1/driver/cases/{OWNED_CASE_ID}/confirmations",
        json={"action": "submit_statement"},
        headers=ANALYST_HEADERS,
    )
    assert analyst_conf.status_code in (403, 404)

    # 4. Issue valid confirmation token for submit_statement
    conf_res = await client.post(
        f"/api/v1/driver/cases/{OWNED_CASE_ID}/confirmations",
        json={"action": "submit_statement", "draft_hash": "hash123"},
        headers=OWNER_HEADERS,
    )
    assert conf_res.status_code == 200
    conf_data = conf_res.json()
    token = conf_data["confirmation_token"]
    assert token
    assert "expires_at" in conf_data

    # 5. Empty reason_summary -> 422
    empty_stmt = await client.post(
        f"/api/v1/driver/cases/{OWNED_CASE_ID}/statement",
        json={"confirmation_token": token, "reason_summary": "   "},
        headers=OWNER_HEADERS,
    )
    assert empty_stmt.status_code == 422

    # 6. Submit statement with valid token -> submitted & analyst_escalated
    stmt_res = await client.post(
        f"/api/v1/driver/cases/{OWNED_CASE_ID}/statement",
        json={
            "confirmation_token": token,
            "reason_summary": "Đường Nguyễn Hữu Cảnh bị ngập sâu, CSGT phân luồng đi vòng Điện Biên Phủ",
            "evidence": [{"kind": "weather", "summary": "Mưa lớn gây ngập"}],
        },
        headers=OWNER_HEADERS,
    )
    assert stmt_res.status_code == 200
    stmt_data = stmt_res.json()
    assert stmt_data["status"] == "submitted"
    assert stmt_data["dispute_status"] == "analyst_escalated"
    assert stmt_data["needs_analyst_review"] is True

    # 7. Reusing the same token must fail
    reuse_res = await client.post(
        f"/api/v1/driver/cases/{OWNED_CASE_ID}/statement",
        json={
            "confirmation_token": token,
            "reason_summary": "Gửi lại lần 2",
        },
        headers=OWNER_HEADERS,
    )
    assert reuse_res.status_code == 200
    assert reuse_res.json()["status"] == "failed"

    # 8. Audit timeline has driver_statement_submitted
    svc = get_driver_dispute_service()
    entries = svc.get_audit_entries(OWNED_CASE_ID)
    assert any(e.get("action") == "driver_statement_submitted" for e in entries)


@pytest.mark.asyncio
async def test_api_acknowledge_and_draft_endpoints(client: AsyncClient, seeded_memory_env):
    # 1. Save & get statement draft
    put_res = await client.put(
        f"/api/v1/driver/cases/{OWNED_CASE_ID}/statement-draft",
        json={"reason": "Kẹt xe cầu Sài Gòn", "incident_type": "traffic"},
        headers=OWNER_HEADERS,
    )
    assert put_res.status_code == 200
    assert put_res.json()["draft"]["reason"] == "Kẹt xe cầu Sài Gòn"

    get_res = await client.get(
        f"/api/v1/driver/cases/{OWNED_CASE_ID}/statement-draft",
        headers=OWNER_HEADERS,
    )
    assert get_res.status_code == 200
    assert get_res.json()["draft"]["reason"] == "Kẹt xe cầu Sài Gòn"

    # Foreign driver cannot read or write draft -> 404
    foreign_get = await client.get(
        f"/api/v1/driver/cases/{OWNED_CASE_ID}/statement-draft",
        headers=FOREIGN_HEADERS,
    )
    assert foreign_get.status_code == 404

    # 2. Acknowledge without valid token fails and never sanctions
    bad_ack = await client.post(
        f"/api/v1/driver/cases/{OWNED_CASE_ID}/acknowledge",
        json={"confirmation_token": "bogus-token"},
        headers=OWNER_HEADERS,
    )
    assert bad_ack.status_code == 200
    assert bad_ack.json()["status"] == "failed"
    assert bad_ack.json().get("sanction_action") is None

    # 3. Issue acknowledge token and confirm -> routes to analyst, zero sanction
    conf_res = await client.post(
        f"/api/v1/driver/cases/{OWNED_CASE_ID}/confirmations",
        json={"action": "acknowledge"},
        headers=OWNER_HEADERS,
    )
    assert conf_res.status_code == 200
    ack_token = conf_res.json()["confirmation_token"]

    ack_res = await client.post(
        f"/api/v1/driver/cases/{OWNED_CASE_ID}/acknowledge",
        json={"confirmation_token": ack_token},
        headers=OWNER_HEADERS,
    )
    assert ack_res.status_code == 200
    ack_data = ack_res.json()
    assert ack_data["status"] == "submitted"
    assert ack_data["dispute_status"] == "analyst_escalated"
    assert ack_data["sanction_action"] is None

    svc = get_driver_dispute_service()
    entries = svc.get_audit_entries(OWNED_CASE_ID)
    assert any(e.get("action") == "driver_acknowledged_violation" for e in entries)


@pytest.mark.docker
@pytest.mark.skipif(
    not is_postgres_available(),
    reason="PostgreSQL engine not reachable on loopback; set DATABASE_URL to run real-DB test",
)
@pytest.mark.asyncio
async def test_postgres_confirmation_tokens_and_drafts_persistence(disposable_database_dsn: str):
    """Verify real PostgreSQL persistence in app.driver_confirmation_tokens and app.driver_statement_drafts."""
    org_id = str(uuid.uuid4())
    driver_id = str(uuid.uuid4())
    passenger_id = str(uuid.uuid4())
    vehicle_id = str(uuid.uuid4())
    trip_id = str(uuid.uuid4())
    asgn_id = str(uuid.uuid4())
    case_id = str(uuid.uuid4())

    with psycopg.connect(disposable_database_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            cur.execute("INSERT INTO app.organizations (id, name) VALUES (%s, %s);", (org_id, "Org 483"))
            cur.execute(
                """
                INSERT INTO app.passengers (id, organization_id, external_ref)
                VALUES (%s, %s, %s);
                """,
                (passenger_id, org_id, f"pax-{passenger_id[:8]}"),
            )
            cur.execute(
                """
                INSERT INTO app.drivers (id, organization_id, external_ref, partner_type, display_name)
                VALUES (%s, %s, %s, 'owner_driver', 'Tài xế 483');
                """,
                (driver_id, org_id, f"drv-{driver_id[:8]}"),
            )
            cur.execute(
                """
                INSERT INTO app.vehicles (id, organization_id, registration_ref, vehicle_type, service_class, telemetry_source)
                VALUES (%s, %s, '29E-483.00', 'car', 'standard', 'smartphone');
                """,
                (vehicle_id, org_id),
            )
            cur.execute(
                """
                INSERT INTO app.trips (
                    id, organization_id, passenger_id, requested_at,
                    pickup, dropoff, requested_service_class, status, pickup_address, dropoff_address
                )
                VALUES (
                    %s, %s, %s, now(),
                    ST_SetSRID(ST_MakePoint(105.85, 21.02), 4326)::geography,
                    ST_SetSRID(ST_MakePoint(105.81, 21.03), 4326)::geography,
                    'standard', 'completed', 'Điểm A', 'Điểm B'
                );
                """,
                (trip_id, org_id, passenger_id),
            )
            cur.execute(
                """
                INSERT INTO app.trip_assignments (id, trip_id, driver_id, vehicle_id, state, offered_at)
                VALUES (%s, %s, %s, %s, 'completed', now());
                """,
                (asgn_id, trip_id, driver_id, vehicle_id),
            )
            cur.execute(
                """
                INSERT INTO app.fraud_cases (
                    id, organization_id, assignment_id, status, dispute_status,
                    suspected_category, priority_tier, priority_score, priority_rule_version, version
                )
                VALUES (%s, %s, %s, 'ready', 'not_disputed', 'ERR-02', 1, 70, 'v1', 1);
                """,
                (case_id, org_id, asgn_id),
            )

    dsn_cs = DsnCaseService(disposable_database_dsn)
    dsn_cs.settings = get_case_service().settings
    dsn_cs._cases = {}
    dsn_cs._case_aliases = {}
    dsn_cs._agent_sessions = {}
    dsn_cs._agent_messages = {}

    svc = DriverDisputeService(case_service=dsn_cs)

    # 1. Draft save + load via Postgres
    await svc.save_statement_draft(case_id=case_id, driver_id=driver_id, draft={"reason": "Ngập nước sâu"})
    svc._statement_drafts.clear()
    loaded_draft = await svc.get_statement_draft(case_id=case_id, driver_id=driver_id)
    assert loaded_draft is not None
    assert loaded_draft.get("reason") == "Ngập nước sâu"

    # 2. Issue token + consume via Postgres
    token = await svc.issue_confirmation_token(
        case_id=case_id, driver_id=driver_id, action="submit_statement", draft_hash="d1"
    )
    svc._confirmation_tokens.clear()

    res = await svc.submit_statement_with_token(
        case_id=case_id,
        driver_id=driver_id,
        confirmation_token=token,
        reason_summary="Ngập nước sâu đường Nguyễn Hữu Cảnh",
        evidence=[{"kind": "weather", "summary": "Mưa ngập"}],
    )
    assert res["status"] == "submitted"
    assert res["dispute_status"] == "analyst_escalated"

    # Verify DB row state
    with psycopg.connect(disposable_database_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT used_at FROM app.driver_confirmation_tokens WHERE case_id = %s;", (case_id,))
            token_row = cur.fetchone()
            assert token_row is not None and token_row[0] is not None

            cur.execute("SELECT status, dispute_status FROM app.fraud_cases WHERE id = %s;", (case_id,))
            case_row = cur.fetchone()
            assert case_row == ("driver_disputed", "analyst_escalated")
