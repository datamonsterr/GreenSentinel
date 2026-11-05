"""Public authorization regression contracts for issue #145."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.auth import Principal, require_principal
from src.api.routes import router
from src.config import Settings, get_settings
from src.services.case_service import get_case_service
from src.services.driver_dispute_service import get_driver_dispute_service


@pytest.mark.parametrize("environment", ["development", "staging", "production"])
@pytest.mark.parametrize("path", ["/me", "/driver/cases", "/cases"])
async def test_hosted_routes_reject_missing_identity_and_forged_headers(environment, path):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_settings] = lambda: Settings(app_env=environment, test_auth_enabled=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1" + path, headers={"X-Role": "analyst", "X-Driver-ID": "victim"})
    assert response.status_code == 401


@pytest.mark.parametrize("stored_roles", [["driver"]])
async def test_signed_metadata_cannot_restore_removed_or_privileged_roles(stored_roles):
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, query, params=None):
            assert not any(word in query for word in ("INSERT", "UPDATE", "DELETE"))

        def fetchone(self):
            return {"id": "principal", "organization_id": "org", "roles": stored_roles, "driver_id": "driver"}

    async def list_cases(**kwargs):
        return {"items": [], "total": 0, "limit": 50, "offset": 0}

    service = SimpleNamespace(
        _get_db_connection=lambda: SimpleNamespace(cursor=Cursor, close=lambda: None), list_cases=list_cases
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_settings] = lambda: Settings(app_env="production", clerk_secret_key="test")
    app.dependency_overrides[get_case_service] = lambda: service
    payload = {
        "sub": "subject",
        "role": "admin",
        "metadata": {"role": "analyst"},
        "public_metadata": {"role": "admin"},
    }
    with patch("src.api.auth.authenticate_request", return_value=SimpleNamespace(is_signed_in=True, payload=payload)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/cases", headers={"Authorization": "Bearer signed"})
    assert response.status_code == 403


async def test_unprovisioned_clerk_user_without_org_role_is_denied():
    """S4-CONTRACT #291: no fraud_analyst fallback for new users without a Clerk org role."""
    executed_queries = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, query, params=None):
            executed_queries.append((query, params))

        def fetchone(self):
            return None

    async def list_cases(**kwargs):
        raise AssertionError("denied request reached list_cases")

    service = SimpleNamespace(
        _get_db_connection=lambda: SimpleNamespace(cursor=Cursor, close=lambda: None, commit=lambda: None),
        list_cases=list_cases,
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_settings] = lambda: Settings(app_env="production", clerk_secret_key="test")
    app.dependency_overrides[get_case_service] = lambda: service
    payload = {
        "sub": "user_new_signup",
        "email": "analyst@vinuni.edu.vn",
    }
    with patch("src.api.auth.authenticate_request", return_value=SimpleNamespace(is_signed_in=True, payload=payload)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/cases", headers={"Authorization": "Bearer signed"})
    assert response.status_code == 403
    assert response.json()["detail"] == "Clerk user has no active assigned role"
    assert not any("INSERT INTO app.principals" in q[0] for q in executed_queries)


@pytest.mark.parametrize(
    "path,method,body",
    [
        ("/cases/case/release", "POST", {"analyst_id": "victim"}),
        ("/driver/cases", "GET", None),
        ("/driver/cases/case/session", "GET", None),
        ("/driver/cases/case/chat/stream", "POST", {"message": "hello", "driver_id": "victim"}),
    ],
)
async def test_driver_endpoints_require_explicit_driver_role(path, method, body):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_principal] = lambda: Principal("analyst", "org", frozenset({"analyst"}))
    service = SimpleNamespace(
        list_driver_cases=lambda **kwargs: pytest.fail("denied request reached list"),
        get_dispute_context=lambda *args, **kwargs: pytest.fail("denied request reached context"),
        release_case_lease=lambda *args, **kwargs: pytest.fail("forged identity reached release"),
    )
    app.dependency_overrides[get_case_service] = lambda: service
    app.dependency_overrides[get_driver_dispute_service] = lambda: service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, "/api/v1" + path, json=body)
    assert response.status_code == 403


async def test_analyst_cannot_self_grant_admin():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_principal] = lambda: Principal("analyst", "org", frozenset({"analyst"}))
    app.dependency_overrides[get_case_service] = lambda: SimpleNamespace(
        update_principal_role=lambda *args, **kwargs: pytest.fail("self grant reached persistence")
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch("/api/v1/account/users/analyst/role", json={"role": "admin"})
    assert response.status_code == 403


@pytest.mark.parametrize("roles", [{"driver"}, {"driver", "analyst"}])
@pytest.mark.parametrize(
    "row", [None, {"organization_id": "other", "driver_id": "driver"}, {"organization_id": "org", "driver_id": "other"}]
)
@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/driver/cases/case/session", None),
        ("GET", "/driver/cases/case/dispute", None),
        ("GET", "/driver/cases/case/chat/stream?message=hello", None),
        ("POST", "/driver/cases/case/chat", {"message": "hello"}),
        ("POST", "/driver/cases/case/chat/stream", {"message": "hello", "event_schema_version": "1.1"}),
    ],
)
async def test_driver_cannot_read_or_replay_other_case(roles, row, method, path, body):
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, query, params):
            assert params == ("case",)

        def fetchone(self):
            return row

    service = SimpleNamespace(_get_db_connection=lambda: SimpleNamespace(cursor=Cursor, close=lambda: None))
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_principal] = lambda: Principal("principal", "org", frozenset(roles), "driver")
    app.dependency_overrides[get_case_service] = lambda: service
    app.dependency_overrides[get_driver_dispute_service] = lambda: SimpleNamespace()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, "/api/v1" + path, json=body)
    assert response.status_code == 403
    assert "text/event-stream" not in response.headers.get("content-type", "")


async def test_driver_list_passes_trusted_organization_and_driver():
    from unittest.mock import AsyncMock

    listing = AsyncMock(return_value={"items": [], "total": 0})
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_principal] = lambda: Principal("principal", "org", frozenset({"driver"}), "driver")
    app.dependency_overrides[get_driver_dispute_service] = lambda: SimpleNamespace(list_driver_cases=listing)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/driver/cases?driver_id=victim&organization_id=other")
    assert response.status_code == 200
    listing.assert_awaited_once_with(driver_id="driver", organization_id="org", limit=50, offset=0)


async def test_clerk_denial_cannot_fall_back_to_accepted_jwks():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_settings] = lambda: Settings(app_env="production", clerk_secret_key="test")
    with (
        patch("src.api.auth.authenticate_request", return_value=SimpleNamespace(is_signed_in=False, reason="revoked")),
        patch("src.api.auth._verify_jwt_with_jwks") as fallback,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/me", headers={"Authorization": "Bearer signed"})
    assert response.status_code == 401
    fallback.assert_not_called()


@pytest.mark.parametrize(
    "error", [__import__("jwt").ExpiredSignatureError("expired"), __import__("jwt").InvalidSignatureError("forged")]
)
async def test_invalid_jwt_never_loads_principal(error):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_settings] = lambda: Settings(
        app_env="production", clerk_secret_key="", clerk_jwt_key=""
    )
    with patch("src.api.auth._verify_jwt_with_jwks", side_effect=error), patch("src.api.auth.load_principal") as lookup:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/me", headers={"Authorization": "Bearer signed"})
    assert response.status_code == 401
    lookup.assert_not_called()


@pytest.mark.parametrize("roles", [{"analyst"}, {"senior_analyst"}, {"admin"}])
async def test_legacy_chat_denies_cross_org_before_stream_headers(roles):
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, query, params):
            pass

        def fetchone(self):
            return {"organization_id": "other", "driver_id": "other"}

    service = SimpleNamespace(_get_db_connection=lambda: SimpleNamespace(cursor=Cursor, close=lambda: None))
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_principal] = lambda: Principal("principal", "org", frozenset(roles))
    app.dependency_overrides[get_case_service] = lambda: service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/policy/chat/stream",
            json={"query": "show case attachment", "case_id": "018f2f4e-5000-7000-8000-000000000001"},
        )
    assert response.status_code == 403
    assert "text/event-stream" not in response.headers.get("content-type", "")


async def test_driver_list_reads_only_database_org_and_never_appends_fixtures():
    from src.services.driver_dispute_service import DriverDisputeService

    queries = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, query, params=None):
            queries.append((query, params))

        def fetchall(self):
            return []

    settings = Settings(app_env="production")
    service = DriverDisputeService(
        case_service=SimpleNamespace(settings=settings, _cases={"secret": {}}, _assignments={})
    )
    with patch.object(service, "_get_db_connection", return_value=SimpleNamespace(cursor=Cursor, close=lambda: None)):
        result = await service.list_driver_cases(driver_id="driver", organization_id="org")
    assert result.items == []
    query, params = queries[-1]
    assert "a.driver_id::text = %s" in query
    assert "c.organization_id::text = %s" in query
    assert params == ("driver", "org", 50, 0)


async def test_driver_list_database_failure_never_returns_fixture_history():
    from fastapi import HTTPException

    from src.services.driver_dispute_service import DriverDisputeService

    settings = Settings(app_env="production")
    service = DriverDisputeService(case_service=SimpleNamespace(settings=settings, _cases={"secret": {}}))
    with patch.object(service, "_get_db_connection", return_value=None), pytest.raises(HTTPException) as denied:
        await service.list_driver_cases(driver_id="driver", organization_id="org")
    assert denied.value.status_code == 503
