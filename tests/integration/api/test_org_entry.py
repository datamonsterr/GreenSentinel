"""S4-ENTRY #296: routing matrix, invites, last-admin guard, pagination.

Fake-DB suite: runs without Postgres. Production Settings everywhere.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api import routes as routes_module
from src.api.auth import Principal, require_principal
from src.api.routes import router
from src.config import Settings, get_settings
from src.services.case_service import get_case_service

ORG_A = "11111111-1111-4111-8111-111111111111"


def _settings(**kwargs):
    return Settings(app_env="production", database_url="", clerk_secret_key="sk_test_unit", **kwargs)


def _app(principal, service, settings=None):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_settings] = lambda: settings or _settings()
    app.dependency_overrides[require_principal] = lambda: principal
    app.dependency_overrides[get_case_service] = lambda: service
    return app


def _service(**methods):
    return SimpleNamespace(**methods)


@pytest.fixture(autouse=True)
def clean_invites():
    routes_module._INVITATIONS.clear()
    yield
    routes_module._INVITATIONS.clear()


@pytest.mark.parametrize(
    ("roles", "route", "primary"),
    [
        ({"admin"}, "/organization", "admin"),
        ({"analyst"}, "/workspace", "analyst"),
        ({"fraud_analyst"}, "/workspace", "analyst"),
        ({"driver"}, "/driver", "driver"),
        ({"driver", "analyst"}, "/workspace", "analyst"),
    ],
)
async def test_route_matrix(roles, route, primary):
    app = _app(Principal("p1", ORG_A, frozenset(roles)), _service())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/account/route")
    assert res.status_code == 200
    assert res.json() == {"route": route, "primary_role": primary, "organization_id": ORG_A}


async def test_unauthorized_invite_denied():
    app = _app(Principal("analyst-1", ORG_A, frozenset({"analyst"})), _service())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/v1/admin/invitations", json={"email": "x@y.z", "role": "analyst"})
    assert res.status_code == 403


async def test_unsupported_role_rejected():
    app = _app(Principal("a1", ORG_A, frozenset({"admin"})), _service())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/v1/admin/invitations", json={"email": "x@y.z", "role": "superuser"})
    assert res.status_code == 422


async def test_invite_missing_secret_returns_501():
    no_secret = Settings(app_env="production", database_url="")
    app = _app(Principal("a1", ORG_A, frozenset({"admin"})), _service(), settings=no_secret)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/v1/admin/invitations", json={"email": "x@y.z", "role": "analyst"})
    assert res.status_code == 501


async def test_invite_roundtrip_revoke_resend():
    app = _app(Principal("a1", ORG_A, frozenset({"admin"})), _service())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/api/v1/admin/invitations", json={"email": "n@x.yz", "role": "driver"})
        assert created.status_code == 201
        inv_id = created.json()["id"]
        listed = await client.get("/api/v1/admin/invitations")
        assert listed.json()["total"] == 1
        revoked = await client.post(f"/api/v1/admin/invitations/{inv_id}/revoke")
        assert revoked.json()["status"] == "revoked"
        resend = await client.post(f"/api/v1/admin/invitations/{inv_id}/resend")
        assert resend.status_code == 422  # revoked cannot be resent


async def test_last_admin_demote_refused():
    roster = [{"id": "solo-admin", "display_name": "A", "roles": ["admin"], "status": "active"}]
    service = _service(
        list_principals=lambda organization_id=None: roster,
        update_principal_role=lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not reach persistence")),
    )
    app = _app(Principal("other-admin", ORG_A, frozenset({"admin"})), service)
    # other-admin granting admin to self is already 403; use distinct non-self admin target path:
    # demoting the sole admin (different id, non-admin target role) must fail safe.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.patch("/api/v1/account/users/solo-admin/role", json={"role": "analyst"})
    assert res.status_code == 403


async def test_roster_pagination():
    roster = [{"id": f"u{i}", "display_name": f"U{i}", "roles": ["analyst"], "status": "active"} for i in range(5)]
    service = _service(list_principals=lambda organization_id=None: roster)
    app = _app(Principal("a1", ORG_A, frozenset({"admin"})), service)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page = await client.get("/api/v1/account/users?limit=2&offset=2")
    assert page.status_code == 200
    assert [u["id"] for u in page.json()] == ["u2", "u3"]
