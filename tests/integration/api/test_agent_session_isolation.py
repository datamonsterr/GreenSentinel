"""Integration tests for Issue #572:
1. Driver session 403 fix (organization scope passed properly).
2. Analyst Copilot session isolation (driver messages never leaked to analyst copilot).
"""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.auth import Principal, require_principal
from src.main import app
from src.services.case_service import get_case_service


@pytest.fixture(autouse=True)
def clean_dependency_overrides():
    yield
    app.dependency_overrides.pop(require_principal, None)


@pytest.mark.asyncio
async def test_driver_session_org_scope_and_access_contracts():
    """Item 1: Driver session endpoint enforces proper org scope and access contracts."""
    cs = get_case_service()
    conn = cs._get_db_connection()
    if conn is None:
        pytest.skip("PostgreSQL database not available")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.id, c.organization_id, a.driver_id
            FROM app.fraud_cases c
            JOIN app.trip_assignments a ON a.id = c.assignment_id
            WHERE a.driver_id IS NOT NULL
            LIMIT 1;
            """
        )
        row = cur.fetchone()
        assert row is not None, "Seeded fraud case required for test"
        case_id = str(row["id"])
        org_id = str(row["organization_id"])
        owning_driver_id = str(row["driver_id"])
    conn.close()

    owning_principal = Principal(
        id=f"user-{owning_driver_id}",
        organization_id=org_id,
        roles=frozenset({"driver"}),
        driver_id=owning_driver_id,
    )

    non_owning_driver_id = str(uuid4())
    non_owning_principal = Principal(
        id=f"user-{non_owning_driver_id}",
        organization_id=org_id,
        roles=frozenset({"driver"}),
        driver_id=non_owning_driver_id,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Unknown case returns 403 "Case access denied"
        unknown_case_id = str(uuid4())
        app.dependency_overrides[require_principal] = lambda: owning_principal
        res = await client.get(f"/api/v1/driver/cases/{unknown_case_id}/session")
        assert res.status_code == 403
        assert res.json()["detail"] == "Case access denied"

        # 2. Non-owning driver returns 403 "Driver is not assigned to this case"
        app.dependency_overrides[require_principal] = lambda: non_owning_principal
        res = await client.get(f"/api/v1/driver/cases/{case_id}/session")
        assert res.status_code == 403
        assert res.json()["detail"] == "Driver is not assigned to this case"

        # 3. Owning driver returns 200 with session under production/development env
        # (where allow_unscoped is False, ensuring organization_id is passed down)
        app.dependency_overrides[require_principal] = lambda: owning_principal
        res_dispute = await client.get(f"/api/v1/driver/cases/{case_id}/dispute")
        assert res_dispute.status_code == 200

        # Temporarily simulate development/production environment where unscoped reads are rejected with 403
        orig_env = cs.settings.app_env
        try:
            cs.settings.app_env = "development"
            res_sess = await client.get(f"/api/v1/driver/cases/{case_id}/session")
            assert res_sess.status_code == 200, res_sess.text
            sess_data = res_sess.json()
            assert "messages" in sess_data
        finally:
            cs.settings.app_env = orig_env


@pytest.mark.asyncio
async def test_analyst_and_driver_session_isolation_on_same_case():
    """Item 2: Analyst Copilot session never leaks driver turns; driver session never leaks analyst turns."""
    cs = get_case_service()
    conn = cs._get_db_connection()
    if conn is None:
        pytest.skip("PostgreSQL database not available")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.id, c.organization_id, a.driver_id
            FROM app.fraud_cases c
            JOIN app.trip_assignments a ON a.id = c.assignment_id
            WHERE a.driver_id IS NOT NULL
            LIMIT 1;
            """
        )
        row = cur.fetchone()
        case_id = str(row["id"])
        org_id = str(row["organization_id"])
        owning_driver_id = str(row["driver_id"])

        # Find or create session
        cur.execute(
            """
            INSERT INTO app.case_agent_sessions (organization_id, case_id)
            VALUES (%s, %s)
            ON CONFLICT (case_id) DO UPDATE SET organization_id = EXCLUDED.organization_id
            RETURNING id;
            """,
            (org_id, case_id),
        )
        session_id = str(cur.fetchone()["id"])

        # Insert messages with different roles using valid UUID turn_ids
        t1, t2, t3 = str(uuid4()), str(uuid4()), str(uuid4())
        messages_to_insert = [
            (session_id, t1, "user", "Analyst copilot question"),
            (session_id, t1, "assistant", "Analyst copilot answer"),
            (session_id, t2, "driver", "Driver dispute claim text"),
            (session_id, t2, "driver_agent", "GSupport response to driver"),
            (session_id, t3, "analyst", "Analyst inquiry sent to driver"),
        ]
        for s_id, t_id, role, content in messages_to_insert:
            cur.execute(
                """
                INSERT INTO app.case_agent_messages (session_id, turn_id, role, content)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (session_id, turn_id, role) DO NOTHING;
                """,
                (s_id, t_id, role, content),
            )
        conn.commit()
    conn.close()

    analyst_principal = Principal(
        id=str(uuid4()),
        organization_id=org_id,
        roles=frozenset({"analyst"}),
    )

    driver_principal = Principal(
        id=f"user-{owning_driver_id}",
        organization_id=org_id,
        roles=frozenset({"driver"}),
        driver_id=owning_driver_id,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Analyst Copilot session contains ONLY user and assistant turns; NO driver turns
        app.dependency_overrides[require_principal] = lambda: analyst_principal
        res_analyst = await client.get(f"/api/v1/cases/{case_id}/agent-session")
        assert res_analyst.status_code == 200, res_analyst.text
        analyst_data = res_analyst.json()
        analyst_roles = [m["role"] for m in analyst_data.get("messages", [])]

        # Must not contain driver or driver_agent
        assert "driver" not in analyst_roles, f"Leaked driver messages into analyst copilot: {analyst_roles}"
        assert "driver_agent" not in analyst_roles, (
            f"Leaked driver_agent messages into analyst copilot: {analyst_roles}"
        )
        # All messages returned must only be user or assistant
        for m in analyst_data.get("messages", []):
            assert m["role"] in ("user", "assistant"), f"Invalid role in analyst copilot: {m['role']}"

        # 2. Driver session contains ONLY driver, driver_agent, analyst; NO private user or assistant turns
        app.dependency_overrides[require_principal] = lambda: driver_principal
        res_driver = await client.get(f"/api/v1/driver/cases/{case_id}/session")
        assert res_driver.status_code == 200, res_driver.text
        driver_data = res_driver.json()
        driver_roles = [m["role"] for m in driver_data.get("messages", [])]

        assert "user" not in driver_roles, f"Leaked analyst copilot user message into driver session: {driver_roles}"
        assert "assistant" not in driver_roles, (
            f"Leaked analyst copilot assistant message into driver session: {driver_roles}"
        )
        for m in driver_data.get("messages", []):
            assert m["role"] in ("driver", "driver_agent", "analyst"), f"Invalid role in driver session: {m['role']}"


@pytest.mark.asyncio
async def test_in_memory_session_isolation():
    """Verify in-memory fallback respects role isolation between analyst and driver sessions."""
    cs = get_case_service()
    case_id = str(uuid4())
    driver_id = f"drv-{uuid4().hex[:6]}"
    session_id = str(uuid4())
    org_id = "018f2f4e-0000-7000-8000-000000000001"

    # Set up in-memory fixture
    asgn_id = f"asgn-{case_id}"
    cs._drivers[driver_id] = {"id": driver_id, "display_name": "Test Driver", "account_status": "active"}
    cs._assignments[asgn_id] = {"id": asgn_id, "driver_id": driver_id, "trip_id": f"trip-{case_id}"}
    cs._cases[case_id] = {
        "id": case_id,
        "organization_id": org_id,
        "assignment_id": asgn_id,
        "status": "ready",
        "dispute_status": "not_disputed",
        "suspected_category": "ERR-01",
    }
    cs._agent_sessions[case_id] = {
        "session_id": session_id,
        "case_id": case_id,
        "organization_id": org_id,
    }
    cs._agent_messages[session_id] = [
        {
            "id": str(uuid4()),
            "turn_id": str(uuid4()),
            "role": "user",
            "content": "Analyst note",
            "created_at": "2026-10-19T10:00:00Z",
        },
        {
            "id": str(uuid4()),
            "turn_id": str(uuid4()),
            "role": "assistant",
            "content": "Agent analysis",
            "created_at": "2026-10-19T10:00:05Z",
        },
        {
            "id": str(uuid4()),
            "turn_id": str(uuid4()),
            "role": "driver",
            "content": "Driver rebuttal",
            "created_at": "2026-10-19T10:01:00Z",
        },
        {
            "id": str(uuid4()),
            "turn_id": str(uuid4()),
            "role": "driver_agent",
            "content": "Support ack",
            "created_at": "2026-10-19T10:01:05Z",
        },
    ]

    # Analyst session check
    analyst_sess = await cs.get_case_agent_session(case_id, organization_id=org_id)
    analyst_roles = [m["role"] for m in analyst_sess["messages"]]
    assert analyst_roles == ["user", "assistant"]

    # Driver session check
    from src.services.driver_dispute_service import get_driver_dispute_service

    dds = get_driver_dispute_service()
    driver_sess = await dds.get_driver_session(case_id, organization_id=org_id)
    driver_roles = [m["role"] for m in driver_sess["messages"]]
    assert driver_roles == ["driver", "driver_agent"]
