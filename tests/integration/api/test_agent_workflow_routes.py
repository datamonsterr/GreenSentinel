"""Behavioral RED→GREEN tests for workflow API routes (#86 / #60).

Tests public HTTP endpoints via ASGI transport. Auth overrides use
app.dependency_overrides with explicit fixture principals (no production auth).
No mock-only acceptance; routes must exercise real DB operations via the service.

API under test:
  POST /api/v1/workflows/questions/ask
  GET  /api/v1/workflows/questions/{id}
  POST /api/v1/workflows/questions/{id}/answer
  POST /api/v1/workflows/actions/request
  GET  /api/v1/workflows/actions/{id}

Unauthenticated requests must return 401.
Driver attempting analyst-only action must return 403.
Answer submission must never change action_request status.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.agent_workflow_routes import router as workflow_router
from src.api.auth import require_principal

if "APP_ENV" not in os.environ:
    os.environ["APP_ENV"] = "test"

pytestmark = pytest.mark.docker


def _make_test_app() -> FastAPI:
    """Test-local FastAPI app with workflow router. Does not edit main.py."""
    test_app = FastAPI(title="Test Workflow App")
    test_app.include_router(workflow_router, prefix="/api/v1")
    return test_app


_test_app = _make_test_app()


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def db_available() -> bool:
    """Check if isolated DB is available."""
    try:
        import psycopg

        url = os.getenv("DATABASE_URL", "postgresql://postgres:postgrespassword@127.0.0.1:32794/postgres")
        conn = psycopg.connect(url)
        conn.close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def seed_ids(db_available):
    """Fetch seeded IDs for test use."""
    if not db_available:
        pytest.skip("Database not available")
    try:
        import psycopg
        from psycopg.rows import dict_row

        url = os.getenv("DATABASE_URL", "postgresql://postgres:postgrespassword@127.0.0.1:32794/postgres")
        conn = psycopg.connect(url, row_factory=dict_row)
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            cur.execute(
                """
                SELECT fc.id, fc.organization_id
                FROM app.fraud_cases fc
                JOIN app.adjudications a ON a.case_id = fc.id
                WHERE fc.assigned_analyst_id IS NOT NULL
                  AND EXISTS (
                    SELECT 1 FROM app.route_snapshots r
                    WHERE r.assignment_id = fc.assignment_id
                      AND r.provider = 'osrm'
                      AND r.provenance->>'status' = 'ok'
                  )
                  AND (SELECT count(*) FROM app.telemetry_points tp
                       WHERE tp.assignment_id = fc.assignment_id
                         AND tp.position IS NOT NULL) >= 2
                ORDER BY fc.id
                LIMIT 1
                """
            )
            case_row = cur.fetchone()
            if not case_row:
                conn.close()
                if os.getenv("ISSUE63_DATABASE_URL"):
                    pytest.fail("Required workflow fixture has no adjudicated road-evidence case")
                pytest.skip("No adjudicated road-evidence case in optional database")

            cur.execute(
                """
                SELECT p.id
                FROM app.fraud_cases fc
                JOIN app.principals p ON p.id = fc.assigned_analyst_id
                JOIN app.principal_roles pr ON pr.principal_id = p.id
                WHERE fc.id = %s::uuid AND pr.role IN ('analyst', 'senior_analyst')
                LIMIT 1
                """,
                (case_row["id"],),
            )
            analyst_row = cur.fetchone()
            if not analyst_row:
                conn.close()
                pytest.skip("No analyst principal in DB")

            cur.execute(
                """
                SELECT d.id, d.principal_id
                FROM app.fraud_cases fc
                JOIN app.trip_assignments ta ON ta.id = fc.assignment_id
                JOIN app.drivers d ON d.id = ta.driver_id
                WHERE fc.id = %s::uuid
                LIMIT 1
                """,
                (case_row["id"],),
            )
            driver_row = cur.fetchone()
            if not driver_row:
                pytest.fail("Isolated DB must contain a driver fixture")
            driver_id = str(driver_row["id"])
            driver_principal_id = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO app.principals (id, organization_id, external_subject, display_name)
                VALUES (%s::uuid, %s::uuid, %s, %s)
                ON CONFLICT (organization_id, external_subject) DO UPDATE
                SET display_name = EXCLUDED.display_name
                RETURNING id
                """,
                (
                    driver_principal_id,
                    case_row["organization_id"],
                    f"workflow-test-{driver_id}",
                    "Workflow Test Driver",
                ),
            )
            driver_principal_id = str(cur.fetchone()["id"])
            cur.execute(
                "UPDATE app.drivers SET principal_id = %s::uuid WHERE id = %s::uuid",
                (driver_principal_id, driver_id),
            )
            cur.execute(
                "INSERT INTO app.principal_roles (principal_id, role) VALUES (%s::uuid, 'driver') ON CONFLICT DO NOTHING",
                (driver_principal_id,),
            )
            conn.commit()

        conn.close()
        return {
            "case_id": str(case_row["id"]),
            "organization_id": str(case_row["organization_id"]),
            "analyst_id": str(analyst_row["id"]),
            "driver_id": driver_id,
            "driver_principal_id": driver_principal_id,
        }
    except Exception:
        if os.getenv("ISSUE63_DATABASE_URL"):
            pytest.fail("Required workflow seed fixture is unavailable", pytrace=False)
        pytest.skip("Optional workflow seed fixture is unavailable")


def _make_analyst_principal(seed: dict[str, Any]):
    from src.api.auth import Principal

    return Principal(
        id=seed["analyst_id"],
        organization_id=seed["organization_id"],
        roles=frozenset({"analyst"}),
    )


def _make_driver_principal(seed: dict[str, Any]):
    from types import SimpleNamespace

    return SimpleNamespace(
        id=seed["driver_principal_id"],
        organization_id=seed["organization_id"],
        roles=frozenset({"driver"}),
        driver_id=seed["driver_id"],
    )


@pytest_asyncio.fixture
async def analyst_client(seed_ids):
    """ASGI client authenticated as analyst via dependency override.
    Creates a fresh app instance to avoid cross-fixture override conflicts.
    """
    app_instance = _make_test_app()
    principal = _make_analyst_principal(seed_ids)
    app_instance.dependency_overrides[require_principal] = lambda: principal
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def driver_client(seed_ids):
    """ASGI client authenticated as driver via dependency override.
    Creates a fresh app instance to avoid cross-fixture override conflicts.
    """
    app_instance = _make_test_app()
    principal = _make_driver_principal(seed_ids)
    app_instance.dependency_overrides[require_principal] = lambda: principal
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def unauth_client():
    """ASGI client with no auth override (tests 401 behaviour)."""
    app_instance = _make_test_app()
    # No principal override: require_principal will return None → 401
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ─── Unauthenticated 401 tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ask_question_requires_auth(unauth_client, seed_ids):
    """RED: unauthenticated POST /workflows/questions/ask → 401."""
    resp = await unauth_client.post(
        "/api/v1/workflows/questions/ask",
        params={"case_id": seed_ids["case_id"]},
        json={
            "question_id_stable": "unauth-q-001",
            "question_kind": "yes_no",
            "purpose": "clarification",
            "actor_target": "driver",
            "question_text": "Test?",
            "options": [],
        },
    )
    # require_principal returns None for unauthenticated → 401
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_question_requires_auth(unauth_client):
    """RED: unauthenticated GET /workflows/questions/{id} → 401."""
    resp = await unauth_client.get(f"/api/v1/workflows/questions/{uuid.uuid4()}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_submit_answer_requires_auth(unauth_client):
    """RED: unauthenticated POST /workflows/questions/{id}/answer → 401."""
    resp = await unauth_client.post(
        f"/api/v1/workflows/questions/{uuid.uuid4()}/answer",
        json={
            "submitted_value": True,
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_request_action_approval_requires_auth(unauth_client, seed_ids):
    """RED: unauthenticated POST /workflows/actions/request → 401."""
    resp = await unauth_client.post(
        "/api/v1/workflows/actions/request",
        params={"case_id": seed_ids["case_id"]},
        json={
            "action_kind": "test",
            "payload": {},
            "consequence_summary": "test",
        },
    )
    assert resp.status_code == 401


# ─── Role enforcement tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_driver_cannot_request_approval_via_api(driver_client, seed_ids):
    """RED: driver POST /workflows/actions/request → 403."""
    resp = await driver_client.post(
        "/api/v1/workflows/actions/request",
        params={"case_id": seed_ids["case_id"]},
        json={
            "action_kind": "send_minutes",
            "payload": {"test": "val"},
            "consequence_summary": "Gửi biên bản",
        },
    )
    assert resp.status_code == 403


# ─── Happy path tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ask_question_and_retrieve_via_api(analyst_client, seed_ids):
    """GREEN: analyst creates question, retrieves it by ID."""
    stable_id = f"api-q-{uuid.uuid4().hex[:8]}"
    create_resp = await analyst_client.post(
        "/api/v1/workflows/questions/ask",
        params={"case_id": seed_ids["case_id"]},
        json={
            "question_id_stable": stable_id,
            "question_kind": "single_choice",
            "purpose": "clarification",
            "actor_target": "driver",
            "question_text": "Vì sao tốc độ thấp bất thường?",
            "options": [
                {"id": "traffic", "label": "Kẹt xe"},
                {"id": "stop", "label": "Dừng xe theo yêu cầu khách"},
                {"id": "other", "label": "Lý do khác"},
            ],
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    data = create_resp.json()
    assert data["status"] == "pending"
    question_id = data["question_id"]

    # Retrieve
    get_resp = await analyst_client.get(f"/api/v1/workflows/questions/{question_id}")
    assert get_resp.status_code == 200, get_resp.text
    q_data = get_resp.json()
    assert q_data["question_id"] == question_id
    assert q_data["status"] == "pending"
    assert q_data["question_kind"] == "single_choice"


@pytest.mark.asyncio
async def test_action_approval_request_via_api(analyst_client, seed_ids):
    """GREEN: analyst requests action approval, gets pending status."""
    resp = await analyst_client.post(
        "/api/v1/workflows/actions/request",
        params={"case_id": seed_ids["case_id"]},
        json={
            "action_kind": "send_case_minutes",
            "payload": {
                "minutes_id": str(uuid.uuid4()),
                "recipient_driver_id": seed_ids["driver_id"],
            },
            "consequence_summary": "Gửi biên bản kết quả xử lý đến tài xế qua kênh tin nhắn",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "pending"
    assert "action_request_id" in data


@pytest.mark.asyncio
async def test_answer_submission_invariant_via_api(analyst_client, driver_client, seed_ids):
    """INVARIANT: Submitting an answer does NOT change action_request status.

    This verifies that ordinary yes/no answers — even to a driver question —
    cannot grant analyst-action approval through any API path.
    """
    # Create action approval request (analyst)
    action_resp = await analyst_client.post(
        "/api/v1/workflows/actions/request",
        params={"case_id": seed_ids["case_id"]},
        json={
            "action_kind": "approval_invariant_test",
            "payload": {"unique": uuid.uuid4().hex},
            "consequence_summary": "Must not be auto-approved",
        },
    )
    assert action_resp.status_code == 200
    action_id = action_resp.json()["action_request_id"]

    # Create a driver question (analyst creates it)
    q_resp = await analyst_client.post(
        "/api/v1/workflows/questions/ask",
        params={"case_id": seed_ids["case_id"]},
        json={
            "question_id_stable": f"inv-api-{uuid.uuid4().hex[:8]}",
            "question_kind": "yes_no",
            "purpose": "clarification",
            "actor_target": "driver",
            "question_text": "Xác nhận?",
            "options": [],
        },
    )
    assert q_resp.status_code == 200
    question_id = q_resp.json()["question_id"]

    # Driver answers the question
    ans_resp = await driver_client.post(
        f"/api/v1/workflows/questions/{question_id}/answer",
        json={
            "submitted_value": True,
            "idempotency_key": f"inv-{uuid.uuid4().hex}",
        },
    )
    assert ans_resp.status_code == 200
    ans_data = ans_resp.json()
    assert "note" in ans_data
    # Note must clearly state answer does not grant approval
    assert "approval" in ans_data["note"].lower() or "grant" in ans_data["note"].lower()

    # Action request must still be pending
    status_resp = await analyst_client.get(
        f"/api/v1/workflows/actions/{action_id}",
        params={"case_id": seed_ids["case_id"]},
    )
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["status"] == "pending", (
        f"INVARIANT VIOLATED: action_request is {status_data['status']!r} after answer submission"
    )


@pytest.mark.asyncio
async def test_approved_minutes_are_persisted_in_driver_session(analyst_client, seed_ids):
    """Real DB proof: send appends the approved document to the case conversation."""
    draft = await analyst_client.post(
        "/api/v1/workflows/minutes/draft",
        json={"case_id": seed_ids["case_id"], "map_ref": "caller-map-must-be-ignored"},
    )
    assert draft.status_code == 200, draft.text
    draft_data = draft.json()
    assert draft_data["minutes_id"], "missing=" + ",".join(draft_data["missing_fields"])
    assert not draft_data["missing_fields"], draft.text

    preview = await analyst_client.get(
        f"/api/v1/workflows/minutes/{draft_data['minutes_id']}/preview",
        params={"case_id": seed_ids["case_id"]},
    )
    assert preview.status_code == 200, preview.text
    preview_data = preview.json()
    assert preview_data["ready_to_approve"] is True, repr(preview_data["missing_required_fields"])
    assert preview_data["content"]["map_svg"].startswith("<svg")

    approved = await analyst_client.post(
        f"/api/v1/workflows/minutes/{draft_data['minutes_id']}/approve",
        params={"case_id": seed_ids["case_id"], "content_hash": preview_data["content_hash"]},
    )
    assert approved.status_code == 200, approved.text

    sent = await analyst_client.post(
        f"/api/v1/workflows/minutes/{draft_data['minutes_id']}/send",
        params={
            "case_id": seed_ids["case_id"],
            "recipient_driver_id": seed_ids["driver_id"],
        },
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["delivery_state"] == "stored"

    import psycopg
    from psycopg.rows import dict_row

    conn = psycopg.connect(
        os.getenv("DATABASE_URL", "postgresql://postgres:postgrespassword@127.0.0.1:32794/postgres"),
        row_factory=dict_row,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.content
                FROM app.case_agent_messages m
                JOIN app.case_agent_sessions s ON s.id = m.session_id
                WHERE s.case_id = %s::uuid AND m.role IN ('assistant', 'driver_agent')
                ORDER BY m.sequence DESC
                """,
                (seed_ids["case_id"],),
            )
            messages = cur.fetchall()
        import json

        delivered = []
        for message in messages:
            try:
                content = json.loads(message["content"])
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(content, dict) and content.get("minutes_id") == draft_data["minutes_id"]:
                delivered.append(content)
        # Match this idempotent delivery, independently of later conversation messages.
        assert len(delivered) == 1
        assert delivered[0]["content"]["map_svg"] == preview_data["content"]["map_svg"]
    finally:
        conn.close()
