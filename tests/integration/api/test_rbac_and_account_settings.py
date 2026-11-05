"""Full test suite for Clerk & Database RBAC (fraud_analyst, driver, admin) and account settings."""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.auth import Principal, require_analyst_identity, require_driver_identity, require_role
from src.api.routes import router
from src.config import Settings, get_settings
from src.services.case_service import CaseService, get_case_service


@pytest.fixture
def test_app():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_settings] = lambda: Settings(app_env="test", database_url="")
    return app


@pytest.mark.asyncio
async def test_require_role_unit_logic():
    # fraud_analyst satisfies analyst
    p_analyst = Principal(
        id="usr-1",
        organization_id="org-1",
        roles=frozenset(["fraud_analyst"]),
    )
    require_role(p_analyst, "analyst")
    require_role(p_analyst, "fraud_analyst")

    # admin satisfies analyst and admin
    p_admin = Principal(
        id="usr-2",
        organization_id="org-1",
        roles=frozenset(["admin", "analyst", "fraud_analyst"]),
    )
    require_role(p_admin, "analyst")
    require_role(p_admin, "admin")

    # driver does NOT satisfy analyst
    p_driver = Principal(
        id="usr-3",
        organization_id="org-1",
        roles=frozenset(["driver"]),
        driver_id="usr-3",
    )
    require_role(p_driver, "driver")
    with pytest.raises(Exception) as exc_info:
        require_role(p_driver, "analyst")
    assert exc_info.value.status_code == 403

    # driver identity verification
    require_driver_identity(p_driver, "usr-3")
    with pytest.raises(Exception) as exc_driver_mismatch:
        require_driver_identity(p_driver, "other-driver")
    assert exc_driver_mismatch.value.status_code == 403

    # analyst identity verification
    require_analyst_identity(p_analyst, "usr-1")
    # admin can act as analyst or override
    with pytest.raises(Exception):
        require_analyst_identity(p_admin, "any-analyst-id")


@pytest.mark.asyncio
async def test_fraud_analyst_and_admin_can_adjudicate_approve_dismiss_reject(test_app):
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        # Test admin can adjudicate AGREE
        sim_res2 = await client.post(
            "/api/v1/simulations/driver_stall_cancel",
            headers={"x-role": "demo_operator,admin", "x-principal-id": "operator-001"},
        )
        case_id2 = sim_res2.json()["case_id"]

        await client.post(
            f"/api/v1/cases/{case_id2}/claim",
            headers={"x-role": "admin,analyst", "x-principal-id": "admin-001"},
            json={"analyst_id": "admin-001"},
        )

        case2_info = await client.get(
            f"/api/v1/cases/{case_id2}",
            headers={"x-role": "admin,analyst", "x-principal-id": "admin-001"},
        )
        current_ver = case2_info.json().get("case", {}).get("version", case2_info.json().get("version", 1))

        adj_approve = await client.post(
            f"/api/v1/cases/{case_id2}/adjudicate",
            headers={"x-role": "admin,analyst", "x-principal-id": "admin-001"},
            json={
                "outcome": "AGREE",
                "analyst_id": "admin-001",
                "rationale": "Administrator override confirming violation.",
                "expected_case_version": current_ver,
            },
        )
        assert adj_approve.status_code == 200
        assert adj_approve.json()["outcome"] == "AGREE"


@pytest.mark.asyncio
async def test_fraud_analyst_can_approve_dismiss_reject_and_request_case(test_app):
    """Verify that fraud_analyst can perform AGREE, DISAGREE, claim, and inquiry request."""
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        # 1. AGREE as fraud_analyst
        sim1 = await client.post(
            "/api/v1/simulations/driver_stall_cancel",
            headers={"x-role": "demo_operator,admin", "x-principal-id": "operator-001"},
        )
        assert sim1.status_code == 200
        case1_id = sim1.json()["case_id"]

        claim1 = await client.post(
            f"/api/v1/cases/{case1_id}/claim",
            headers={"x-role": "fraud_analyst", "x-principal-id": "analyst-001"},
            json={"analyst_id": "analyst-001"},
        )
        assert claim1.status_code == 200
        assert claim1.json()["analyst_id"] == "analyst-001"

        c1_info = await client.get(
            f"/api/v1/cases/{case1_id}",
            headers={"x-role": "fraud_analyst", "x-principal-id": "analyst-001"},
        )
        v1 = c1_info.json().get("case", {}).get("version", 1)

        adj_approve = await client.post(
            f"/api/v1/cases/{case1_id}/adjudicate",
            headers={"x-role": "fraud_analyst", "x-principal-id": "analyst-001"},
            json={
                "outcome": "AGREE",
                "analyst_id": "analyst-001",
                "rationale": "Forensic evidence confirms breach.",
                "expected_case_version": v1,
            },
        )
        assert adj_approve.status_code == 200
        assert adj_approve.json()["outcome"] == "AGREE"
        assert adj_approve.json()["status"] == "adjudicated"

        # 2. DISAGREE as fraud_analyst
        sim2 = await client.post(
            "/api/v1/simulations/driver_stall_cancel",
            headers={"x-role": "demo_operator,admin", "x-principal-id": "operator-001"},
        )
        case2_id = sim2.json()["case_id"]

        await client.post(
            f"/api/v1/cases/{case2_id}/claim",
            headers={"x-role": "fraud_analyst", "x-principal-id": "analyst-002"},
            json={"analyst_id": "analyst-002"},
        )

        c2_info = await client.get(
            f"/api/v1/cases/{case2_id}",
            headers={"x-role": "fraud_analyst", "x-principal-id": "analyst-002"},
        )
        v2 = c2_info.json().get("case", {}).get("version", 1)

        adj_dismiss = await client.post(
            f"/api/v1/cases/{case2_id}/adjudicate",
            headers={"x-role": "fraud_analyst", "x-principal-id": "analyst-002"},
            json={
                "outcome": "DISAGREE",
                "analyst_id": "analyst-002",
                "rationale": "Dismissing case due to app network glitch.",
                "expected_case_version": v2,
            },
        )
        assert adj_dismiss.status_code == 200
        assert adj_dismiss.json()["outcome"] == "DISAGREE"
        assert adj_dismiss.json()["status"] == "adjudicated"

        # 3. REQUEST (delegate inquiry / request additional explanation) as fraud_analyst
        sim4 = await client.post(
            "/api/v1/simulations/driver_stall_cancel",
            headers={"x-role": "demo_operator,admin", "x-principal-id": "operator-001"},
        )
        case4_id = sim4.json()["case_id"]

        await client.post(
            f"/api/v1/cases/{case4_id}/claim",
            headers={"x-role": "fraud_analyst", "x-principal-id": "analyst-004"},
            json={"analyst_id": "analyst-004"},
        )

        req_inquiry = await client.post(
            f"/api/v1/cases/{case4_id}/delegate-inquiry",
            headers={"x-role": "fraud_analyst", "x-principal-id": "analyst-004"},
            json={
                "case_id": case4_id,
                "analyst_id": "analyst-004",
                "instruction": "Please clarify reasons for route detour.",
                "deadline_hours": 48,
            },
        )
        assert req_inquiry.status_code == 200
        assert req_inquiry.json()["dispute_status"] == "pending"


@pytest.mark.asyncio
async def test_driver_role_is_forbidden_from_cockpit_case_actions(test_app):
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        # Driver trying to list cockpit cases
        res = await client.get("/api/v1/cases", headers={"x-role": "driver", "x-driver-id": "driver-001"})
        assert res.status_code == 403
        assert "Insufficient role permissions" in res.json()["detail"]

        # Driver trying to claim a case
        claim_res = await client.post(
            "/api/v1/cases/test-case-id/claim",
            headers={"x-role": "driver", "x-driver-id": "driver-001"},
            json={"analyst_id": "driver-001"},
        )
        assert claim_res.status_code == 403

        # Driver trying to adjudicate a case
        adj_res = await client.post(
            "/api/v1/cases/test-case-id/adjudicate",
            headers={"x-role": "driver", "x-driver-id": "driver-001"},
            json={
                "outcome": "DISAGREE",
                "analyst_id": "driver-001",
                "rationale": "Driver dismissing own case.",
                "expected_case_version": 1,
            },
        )
        assert adj_res.status_code == 403


@pytest.mark.asyncio
async def test_account_settings_and_manager_role_configuration(test_app):
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        # 1. Fetch own account settings
        settings_res = await client.get(
            "/api/v1/account/settings",
            headers={"x-role": "fraud_analyst", "x-principal-id": "analyst-001"},
        )
        assert settings_res.status_code == 200
        settings_data = settings_res.json()
        assert settings_data["id"] == "analyst-001"
        assert settings_data["primary_role"] in ("analyst", "fraud_analyst")

        # 2. Update display name
        patch_res = await client.patch(
            "/api/v1/account/settings",
            headers={"x-role": "fraud_analyst", "x-principal-id": "analyst-001"},
            json={"display_name": "Lê Minh Tuấn Lead"},
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["display_name"] == "Lê Minh Tuấn Lead"

        # 3. Non-admin trying to list team users -> 403
        forbidden_users = await client.get(
            "/api/v1/account/users",
            headers={"x-role": "fraud_analyst", "x-principal-id": "analyst-001"},
        )
        assert forbidden_users.status_code == 403

        # 4. Admin listing team users -> 200
        admin_users = await client.get(
            "/api/v1/account/users",
            headers={"x-role": "admin", "x-principal-id": "admin-001"},
        )
        assert admin_users.status_code == 200
        users = admin_users.json()
        assert len(users) >= 1

        target_user = users[0]["id"]

        # 5. Admin configuring user role -> 200
        update_role_res = await client.patch(
            f"/api/v1/account/users/{target_user}/role",
            headers={"x-role": "admin", "x-principal-id": "admin-001"},
            json={"role": "analyst"},
        )
        assert update_role_res.status_code == 200
        assert update_role_res.json()["roles"] == ["analyst"]

        # Non-admin trying to update role -> 403
        blocked_role_update = await client.patch(
            f"/api/v1/account/users/{target_user}/role",
            headers={"x-role": "fraud_analyst", "x-principal-id": "analyst-001"},
            json={"role": "driver"},
        )
        assert blocked_role_update.status_code == 403


@pytest.mark.asyncio
async def test_unknown_clerk_subject_cannot_provision_privileged_roles():
    """Signed metadata cannot create a principal or privileged grant."""

    class FakeCursor:
        def __init__(self):
            self.executed = []
            self.calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def execute(self, query, params=None):
            self.executed.append((query, params))

        def fetchone(self):
            self.calls += 1
            if self.calls == 1:
                # First lookup: not found
                return None
            # RETURNING id, organization_id from INSERT
            return {
                "id": "018f2f4e-0000-7000-8000-000000000099",
                "organization_id": "018f2f4e-0000-7000-8000-000000000001",
            }

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            pass

        def close(self):
            pass

    class FakeService(CaseService):
        def __init__(self):
            super().__init__(settings=Settings(app_env="production"))

        def _get_db_connection(self):
            return FakeConnection()

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    fake_service = FakeService()
    app.dependency_overrides[get_case_service] = lambda: fake_service
    app.dependency_overrides[get_settings] = lambda: Settings(
        app_env="production",
        clerk_jwt_key="mock-key",
        database_url="postgresql://mock",
    )

    with patch("src.api.auth._verify_jwt_with_jwks") as mock_jwks, patch("src.api.auth.authenticate_request", None):
        mock_jwks.return_value = {
            "sub": "user_new_clerk_999",
            "name": "Tran New Analyst",
            "public_metadata": {"role": "admin"},
        }
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.get("/api/v1/me", headers={"Authorization": "Bearer fake.jwt.token"})
            assert res.status_code == 403

            settings_res = await client.get(
                "/api/v1/account/settings", headers={"Authorization": "Bearer fake.jwt.token"}
            )
            assert settings_res.status_code == 403
