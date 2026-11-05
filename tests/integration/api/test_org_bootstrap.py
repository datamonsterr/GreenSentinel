"""S4-ACTORS #295: per-org 100 drivers / 1000 customers bootstrap contracts.

Fake-DB suite: runs without Postgres. Covers exact counts, idempotent rerun,
concurrent replay, crash-resume, cross-org link denial, and NULL principal_id.
"""

from __future__ import annotations

import threading
import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.auth import Principal, require_principal
from src.api.routes import router
from src.config import Settings, get_settings
from src.services import org_bootstrap
from src.services.case_service import get_case_service
from src.services.org_bootstrap import (
    CUSTOMER_COUNT,
    DRIVER_COUNT,
    DatabaseUnavailableError,
    bootstrap_org_population,
    customer_id_for,
    driver_id_for,
    get_bootstrap_status,
    link_driver_principal,
)

ORG_A = "11111111-1111-4111-8111-111111111111"
ORG_B = "22222222-2222-4222-8222-222222222222"
PRIN_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
PRIN_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

TV = "v1"
SEED = "p063-s4-actors"


def _production_settings(**kwargs):
    return Settings(app_env="production", database_url="", clerk_secret_key="sk_test_unit", **kwargs)


class FakeDB:
    def __init__(self):
        self.lock = threading.RLock()
        self.drivers: dict = {}
        self.passengers: dict = {}
        self.state: dict = {}
        self.principals: dict = {}
        self.fail_after_inserts: int | None = None
        self.insert_count = 0


class FakeCursor:
    def __init__(self, db: FakeDB):
        self.db = db
        self._row = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def executemany(self, query, seq):
        for params in seq:
            self.execute(query, params)

    def execute(self, query, params=None):
        q = " ".join(str(query).split())
        params = params or ()
        db = self.db
        with db.lock:
            if q.startswith("SET "):
                self._row = None
                return
            if "app.org_bootstrap_state" in q:
                if q.startswith("INSERT"):
                    org, tv, seed = params[0], params[1], params[2]
                    db.state.setdefault(
                        (org, tv, seed), {"status": "running", "drivers_created": 0, "customers_created": 0}
                    )
                elif q.startswith("SELECT"):
                    org, tv, seed = params[0], params[1], params[2]
                    self._row = db.state.get((org, tv, seed))
                elif q.startswith("UPDATE"):
                    status, d, c = params[0], params[1], params[2]
                    org, tv, seed = params[4], params[5], params[6]
                    db.state[(org, tv, seed)] = {"status": status, "drivers_created": d, "customers_created": c}
                return
            if q.startswith("SELECT COUNT"):
                org, like = params[0], params[1]
                prefix = like.rstrip("%")
                store = db.drivers if "app.drivers" in q else db.passengers
                self._row = {"count": sum(1 for (o, ref) in store if o == org and ref.startswith(prefix))}
                return
            if "app.drivers" in q:
                if q.startswith("INSERT"):
                    db.insert_count += 1
                    if db.fail_after_inserts is not None and db.insert_count > db.fail_after_inserts:
                        raise RuntimeError("simulated crash mid-bootstrap")
                    _id, org, ref = params[0], params[1], params[2]
                    db.drivers.setdefault((org, ref), {"id": _id, "organization_id": org, "principal_id": None})
                elif q.startswith("SELECT"):
                    _id = params[0]
                    hit = next((r for r in db.drivers.values() if r["id"] == _id), None)
                    self._row = {"id": hit["id"], "organization_id": hit["organization_id"]} if hit else None
                elif q.startswith("UPDATE"):
                    pid, _id = params[0], params[1]
                    for r in db.drivers.values():
                        if r["id"] == _id:
                            r["principal_id"] = pid
                return
            if "app.passengers" in q and q.startswith("INSERT"):
                db.insert_count += 1
                if db.fail_after_inserts is not None and db.insert_count > db.fail_after_inserts:
                    raise RuntimeError("simulated crash mid-bootstrap")
                _id, org, ref = params[0], params[1], params[2]
                db.passengers.setdefault((org, ref), {"id": _id, "organization_id": org, "principal_id": None})
                return
            if "app.principals" in q and q.startswith("SELECT"):
                _id = params[0]
                hit = db.principals.get(_id)
                self._row = {"id": _id, "organization_id": hit} if hit else None
                return
            raise AssertionError(f"fake cannot handle: {q[:120]}")

    def fetchone(self):
        return self._row

    def fetchall(self):
        return []


class FakeConn:
    def __init__(self, db: FakeDB):
        self._db = db

    def cursor(self):
        return FakeCursor(self._db)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _factory(db):
    return lambda: FakeConn(db)


def test_exact_counts_and_deterministic_ids():
    db = FakeDB()
    result = bootstrap_org_population(ORG_A, _factory(db))
    assert result == {
        "organization_id": ORG_A,
        "template_version": TV,
        "seed": SEED,
        "drivers": DRIVER_COUNT,
        "customers": CUSTOMER_COUNT,
        "status": "ready",
        "ready": True,
    }
    assert len(db.drivers) == DRIVER_COUNT
    assert len(db.passengers) == CUSTOMER_COUNT
    assert db.drivers[(ORG_A, f"s4-{SEED}-drv-{TV}-0000")]["id"] == driver_id_for(
        ORG_A, 0, seed=SEED, template_version=TV
    )
    assert db.passengers[(ORG_A, f"s4-{SEED}-cus-{TV}-0000")]["id"] == customer_id_for(
        ORG_A, 0, seed=SEED, template_version=TV
    )


def test_two_orgs_isolated_and_distinct():
    db = FakeDB()
    bootstrap_org_population(ORG_A, _factory(db))
    bootstrap_org_population(ORG_B, _factory(db))
    assert len(db.drivers) == 2 * DRIVER_COUNT
    assert len(db.passengers) == 2 * CUSTOMER_COUNT
    assert driver_id_for(ORG_A, 0, seed=SEED, template_version=TV) != driver_id_for(
        ORG_B, 0, seed=SEED, template_version=TV
    )


def test_idempotent_rerun_no_dupes():
    db = FakeDB()
    first = bootstrap_org_population(ORG_A, _factory(db))
    second = bootstrap_org_population(ORG_A, _factory(db))
    assert first == second
    assert len(db.drivers) == DRIVER_COUNT
    assert len(db.passengers) == CUSTOMER_COUNT


def test_concurrent_replay_safe():
    db = FakeDB()
    errors: list = []

    def run():
        try:
            bootstrap_org_population(ORG_A, _factory(db))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(db.drivers) == DRIVER_COUNT
    assert len(db.passengers) == CUSTOMER_COUNT
    assert get_bootstrap_status(ORG_A, _factory(db))["status"] == "ready"


def test_crash_resume_completes():
    db = FakeDB()
    db.fail_after_inserts = 150  # crash partway through customers
    with pytest.raises(Exception):
        bootstrap_org_population(ORG_A, _factory(db))
    partial = get_bootstrap_status(ORG_A, _factory(db))
    assert partial["status"] == "running"  # partial run never claims ready
    assert len(db.drivers) + len(db.passengers) < DRIVER_COUNT + CUSTOMER_COUNT
    db.fail_after_inserts = None
    result = bootstrap_org_population(ORG_A, _factory(db))
    assert result["ready"] is True
    assert len(db.drivers) == DRIVER_COUNT
    assert len(db.passengers) == CUSTOMER_COUNT


def test_seeded_principal_id_null_and_no_mutable_copies():
    db = FakeDB()
    bootstrap_org_population(ORG_A, _factory(db))
    assert all(r["principal_id"] is None for r in db.drivers.values())
    assert all(r["principal_id"] is None for r in db.passengers.values())
    assert set(db.state.keys()) == {(ORG_A, TV, SEED)}


def test_unavailable_db_never_ready():
    def broken():
        raise ConnectionError("down")

    with pytest.raises(DatabaseUnavailableError):
        bootstrap_org_population(ORG_A, broken)
    with pytest.raises(DatabaseUnavailableError):
        get_bootstrap_status(ORG_A, broken)
    with pytest.raises(DatabaseUnavailableError):
        link_driver_principal(str(uuid.uuid4()), str(uuid.uuid4()), ORG_A, lambda: None)


def test_link_same_org_ok_foreign_denied():
    db = FakeDB()
    bootstrap_org_population(ORG_A, _factory(db))
    bootstrap_org_population(ORG_B, _factory(db))
    db.principals[PRIN_A] = ORG_A
    db.principals[PRIN_B] = ORG_B
    mine = driver_id_for(ORG_A, 0, seed=SEED, template_version=TV)
    foreign_driver = driver_id_for(ORG_B, 0, seed=SEED, template_version=TV)
    out = link_driver_principal(mine, PRIN_A, ORG_A, _factory(db))
    assert out == {"driver_id": mine, "principal_id": PRIN_A, "organization_id": ORG_A}
    from src.services.org_bootstrap import OrgMismatchError

    with pytest.raises(OrgMismatchError):
        link_driver_principal(foreign_driver, PRIN_A, ORG_A, _factory(db))
    with pytest.raises(OrgMismatchError):
        link_driver_principal(mine, PRIN_B, ORG_A, _factory(db))


def _app(principal, db):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_settings] = _production_settings
    app.dependency_overrides[require_principal] = lambda: principal
    service = SimpleNamespace(_get_db_connection=lambda: FakeConn(db))
    app.dependency_overrides[get_case_service] = lambda: service
    return app


def _admin(org):
    return Principal("admin-1", org, frozenset({"admin"}))


async def test_api_bootstrap_and_status_roundtrip():
    db = FakeDB()
    app = _app(_admin(ORG_A), db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/v1/admin/organizations/{ORG_A}/bootstrap")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["drivers"] == DRIVER_COUNT and body["customers"] == CUSTOMER_COUNT and body["ready"] is True
        response = await client.get(f"/api/v1/admin/organizations/{ORG_A}/bootstrap")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"


async def test_api_cross_org_bootstrap_forbidden():
    db = FakeDB()
    app = _app(_admin(ORG_A), db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post(f"/api/v1/admin/organizations/{ORG_B}/bootstrap")).status_code == 403
        assert (await client.get(f"/api/v1/admin/organizations/{ORG_B}/bootstrap")).status_code == 403
        assert len(db.drivers) == 0


async def test_api_non_admin_denied():
    db = FakeDB()
    app = _app(Principal("a-1", ORG_A, frozenset({"analyst"})), db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post(f"/api/v1/admin/organizations/{ORG_A}/bootstrap")).status_code == 403


async def test_api_link_same_org_ok_foreign_denied():
    db = FakeDB()
    bootstrap_org_population(ORG_A, _factory(db))
    bootstrap_org_population(ORG_B, _factory(db))
    db.principals[PRIN_A] = ORG_A
    app = _app(_admin(ORG_A), db)
    mine = driver_id_for(ORG_A, 1, seed=SEED, template_version=TV)
    foreign_driver = driver_id_for(ORG_B, 1, seed=SEED, template_version=TV)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ok = await client.post(f"/api/v1/admin/drivers/{mine}/link", json={"principal_id": PRIN_A})
        assert ok.status_code == 200, ok.text
        denied = await client.post(f"/api/v1/admin/drivers/{foreign_driver}/link", json={"principal_id": PRIN_A})
        assert denied.status_code == 403
        assert (await client.post(f"/api/v1/admin/drivers/{mine}/link", json={})).status_code == 422


async def test_api_unavailable_db_never_claims_ready():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_settings] = _production_settings
    app.dependency_overrides[require_principal] = lambda: _admin(ORG_A)
    app.dependency_overrides[get_case_service] = lambda: SimpleNamespace(_get_db_connection=lambda: None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post(f"/api/v1/admin/organizations/{ORG_A}/bootstrap")).status_code == 503
        assert (await client.get(f"/api/v1/admin/organizations/{ORG_A}/bootstrap")).status_code == 503


def test_no_route_accepts_client_organization_id():
    for route in router.routes:
        param_names = (
            [p.name for p in getattr(route, "dependant", {}).query_params] if hasattr(route, "dependant") else []
        )
        assert "organization_id" not in param_names, f"{route.path} trusts client organization_id"


def test_org_bootstrap_module_imports_cleanly():
    assert org_bootstrap.DRIVER_COUNT == 100
    assert org_bootstrap.CUSTOMER_COUNT == 1000
