"""The hosted case API must not trust browser-supplied identity."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.routes import router
from src.config import Settings, get_settings
from src.services.case_service import get_case_service


async def test_production_cases_reject_missing_clerk_token():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_settings] = lambda: Settings(app_env="production", database_url="")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/cases")

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("roles", "expected_status"),
    [("analyst", 200), ("demo_operator", 403)],
)
async def test_signed_clerk_subject_uses_database_roles(roles, expected_status):
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def execute(self, _query, params):
            assert params == ("user_clerk_123",)

        def fetchone(self):
            if getattr(self, "exhausted", False):
                return None
            self.exhausted = True
            return {"id": "analyst-db-id", "organization_id": "org-db-id", "roles": [roles]}

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            pass

    class FakeService:
        def _get_db_connection(self):
            return FakeConnection()

        async def list_cases(self, **_kwargs):
            return {"items": [], "total": 0, "limit": 50, "offset": 0}

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_settings] = lambda: Settings(
        app_env="production", database_url="", clerk_secret_key="sk_test_unit"
    )
    app.dependency_overrides[get_case_service] = FakeService
    with patch(
        "src.api.auth.authenticate_request",
        return_value=SimpleNamespace(is_signed_in=True, payload={"sub": "user_clerk_123"}),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/cases", headers={"Authorization": "Bearer signed"})

    assert response.status_code == expected_status


async def test_invalid_clerk_session_is_rejected_before_database_lookup():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_settings] = lambda: Settings(
        app_env="production", database_url="", clerk_secret_key="sk_test_unit"
    )
    with patch("src.api.auth.authenticate_request", side_effect=ValueError("invalid")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/cases", headers={"Authorization": "Bearer forged"})

    assert response.status_code == 401


def test_require_role_production_unauthenticated():
    from fastapi import HTTPException

    from src.api.auth import require_role

    with patch("src.api.auth.get_settings", return_value=Settings(app_env="production")):
        with pytest.raises(HTTPException) as exc_info:
            require_role(None, "analyst")
        assert exc_info.value.status_code == 401


def test_require_analyst_identity_production_unauthenticated():
    from fastapi import HTTPException

    from src.api.auth import require_analyst_identity

    with patch("src.api.auth.get_settings", return_value=Settings(app_env="production")):
        with pytest.raises(HTTPException) as exc_info:
            require_analyst_identity(None, "user_123")
        assert exc_info.value.status_code == 401


async def test_cases_with_jwks_when_secret_key_absent():
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def execute(self, _query, params=None):
            pass

        def fetchone(self):
            if getattr(self, "exhausted", False):
                return None
            self.exhausted = True
            return {"id": "analyst-db-id", "organization_id": "org-db-id", "roles": ["analyst"]}

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            pass

    class FakeService:
        def _get_db_connection(self):
            return FakeConnection()

        async def list_cases(self, **_kwargs):
            return {"items": [], "total": 0, "limit": 50, "offset": 0}

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_settings] = lambda: Settings(
        app_env="production",
        database_url="",
        clerk_secret_key="",
        clerk_jwt_key="",
        clerk_jwks_url="https://fake-clerk.accounts.dev/.well-known/jwks.json",
    )
    app.dependency_overrides[get_case_service] = FakeService

    with patch(
        "src.api.auth._verify_jwt_with_jwks",
        return_value={"sub": "user_clerk_123", "azp": "https://p-063.vercel.app"},
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/cases", headers={"Authorization": "Bearer jwks_valid_token"})

    assert response.status_code == 200


async def test_cases_returns_503_when_no_clerk_verification_configured():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_settings] = lambda: Settings(
        app_env="production",
        database_url="",
        clerk_secret_key="",
        clerk_jwt_key="",
        clerk_jwks_url="",
        clerk_issuer="",
        clerk_publishable_key="",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/cases", headers={"Authorization": "Bearer test_token"})

    assert response.status_code == 503
    assert response.json()["detail"] == "Clerk verification is not configured"


async def test_unknown_clerk_user_without_org_role_is_denied_no_fallback():
    """S4-CONTRACT #291: unknown identity with no org gets 403, never a default role/org."""
    executed_queries = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def execute(self, query, params=None):
            executed_queries.append((query, params))

        def fetchone(self):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            pass

        def close(self):
            pass

    class FakeService:
        def _get_db_connection(self):
            return FakeConnection()

        async def list_cases(self, **_kwargs):
            raise AssertionError("denied request reached list_cases")

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_settings] = lambda: Settings(
        app_env="production",
        database_url="",
        clerk_jwks_url="https://fake-clerk.accounts.dev/.well-known/jwks.json",
    )
    app.dependency_overrides[get_case_service] = FakeService

    with patch(
        "src.api.auth._verify_jwt_with_jwks",
        return_value={"sub": "user_new_analyst_999", "email": "new_analyst@vinuni.edu.vn"},
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/cases", headers={"Authorization": "Bearer token"})

    assert response.status_code == 403
    assert response.json()["detail"] == "Clerk user has no active assigned role"
    assert not any("INSERT INTO app.principals" in q[0] for q in executed_queries)


async def test_org_member_jit_syncs_with_explicit_role_and_provisioned_org():
    """S4-CONTRACT #291: JIT sync only for Clerk org members with explicit role mapping."""
    executed_queries = []
    org_uuid = "11111111-1111-4111-8111-111111111111"

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def execute(self, query, params=None):
            executed_queries.append((query, params))

        def fetchone(self):
            for q, _ in reversed(executed_queries):
                if "SELECT p.id, p.organization_id" in q:
                    if len(executed_queries) > 2:
                        return {
                            "id": "new-principal-uuid",
                            "organization_id": org_uuid,
                            "roles": ["fraud_analyst"],
                            "driver_id": None,
                        }
                    return None
                if "INSERT INTO app.principals" in q:
                    assert _params_org(executed_queries[-1][1]) == org_uuid
                    return {"id": "new-principal-uuid", "organization_id": org_uuid}
                if "WHERE external_subject" in q:
                    return None
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            pass

        def close(self):
            pass

    class FakeService:
        def _get_db_connection(self):
            return FakeConnection()

        async def list_cases(self, **_kwargs):
            return {"items": [], "total": 0, "limit": 50, "offset": 0}

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_settings] = lambda: Settings(
        app_env="production",
        database_url="",
        clerk_jwks_url="https://fake-clerk.accounts.dev/.well-known/jwks.json",
    )
    app.dependency_overrides[get_case_service] = FakeService

    with patch(
        "src.api.auth._verify_jwt_with_jwks",
        return_value={"sub": "user_new_analyst_999", "org_id": org_uuid, "org_role": "org:member"},
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/cases", headers={"Authorization": "Bearer token"})

    assert response.status_code == 200
    assert any("INSERT INTO app.principals" in q[0] for q in executed_queries)


def _params_org(params):
    return params[0] if params else None


async def test_clerk_native_org_id_never_collapses_to_default_org():
    """S4-CONTRACT #291: org_* ids are not provisioned; sync must refuse, not default."""
    from fastapi import HTTPException

    from src.services.access_control import sync_clerk_principal

    with pytest.raises(HTTPException) as exc_info:
        await _call_sync(sync_clerk_principal, "org_123abc", "fraud_analyst")
    assert exc_info.value.status_code == 403


async def _call_sync(sync_fn, organization_id, role):
    import asyncio

    return await asyncio.to_thread(sync_fn, lambda: None, "user_x", organization_id, role, "X")


@pytest.mark.parametrize("subject", ["user_alice", "user_bob"])
async def test_provision_failure_never_assumes_another_analysts_identity(subject):
    from unittest.mock import MagicMock

    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [
        None,
        {"id": "org"},
        {"id": "shared-analyst", "organization_id": "org", "roles": ["analyst"]},
    ]

    def execute(query, params=None):
        if "INSERT INTO app.principals" in query:
            raise RuntimeError("database unavailable")

    cursor.execute.side_effect = execute
    service = MagicMock()
    service._get_db_connection.return_value = conn
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_settings] = lambda: Settings(
        app_env="production", database_url="", clerk_secret_key="sk_test_unit"
    )
    app.dependency_overrides[get_case_service] = lambda: service
    with patch(
        "src.api.auth.authenticate_request", return_value=SimpleNamespace(is_signed_in=True, payload={"sub": subject})
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/me", headers={"Authorization": "Bearer signed"})
    assert response.status_code in (403, 503)
    assert not any("WHERE p.status = 'active'" in call.args[0] for call in cursor.execute.call_args_list)


async def test_me_uses_authenticated_principal_and_persisted_name():
    from src.api.auth import Principal, require_principal

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_principal] = lambda: Principal("alice", "org", frozenset({"analyst"}))
    app.dependency_overrides[get_case_service] = lambda: SimpleNamespace(
        get_principal_display_name=lambda identifier: "Alice" if identifier == "alice" else None
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/me")
    assert response.json() == {"id": "alice", "display_name": "Alice", "roles": ["analyst"]}
