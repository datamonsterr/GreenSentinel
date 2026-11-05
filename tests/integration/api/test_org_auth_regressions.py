"""Regression tests for verified tenant claims and database-owned grants."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid5

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.api import auth
from src.config import Settings
from src.services.access_control import bootstrap_clerk_organization, load_principal, sync_clerk_principal

pytestmark = pytest.mark.docker

ORG_A = "11111111-1111-4111-8111-111111111111"
ORG_B = "22222222-2222-4222-8222-222222222222"


def principal(org=ORG_A, roles=("analyst",), status="active"):
    return {"id": f"principal-{org}", "organization_id": org, "roles": list(roles), "status": status}


class Cursor:
    def __init__(self, rows, links=None):
        self.source = rows
        self.links = links or {}
        self.rows = iter(())

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def execute(self, query, params):
        if "app.organizations" in query:
            linked = self.links.get(params[0])
            self.rows = iter([{"id": linked}] if linked else [])
            return
        rows = self.source
        if "p.status = 'active'" in query:
            rows = [row for row in rows if row["status"] == "active"]
        if "p.organization_id = %s" in query:
            rows = [row for row in rows if row["organization_id"] == params[1]]
        self.rows = iter(rows)

    def fetchone(self):
        return next(self.rows, None)


class Connection:
    def __init__(self, rows, links=None):
        self.rows = rows
        self.links = links or {}

    def cursor(self):
        return Cursor(self.rows, self.links)

    def close(self):
        pass


async def authenticate(monkeypatch, rows, claims, links=None):
    monkeypatch.setattr(auth, "authenticate_request", lambda *_args: SimpleNamespace(is_signed_in=True, payload=claims))
    writes = Mock(return_value=principal(roles=("admin",)))
    monkeypatch.setattr(auth, "sync_clerk_principal", writes)
    settings = Settings(app_env="production", database_url="", clerk_secret_key="sk_test_unit", _env_file=None)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/me",
            "headers": [(b"authorization", b"Bearer verified-session")],
        }
    )
    service = SimpleNamespace(_get_db_connection=lambda: Connection(rows, links))
    return await auth.require_principal(request, settings, service), writes


async def test_stale_admin_claim_cannot_restore_database_role(monkeypatch):
    result, writes = await authenticate(
        monkeypatch, [principal()], {"sub": "user_shared", "org_id": ORG_A, "org_role": "org:admin"}
    )
    assert result.roles == frozenset({"analyst", "fraud_analyst"})
    writes.assert_not_called()


@pytest.mark.parametrize("organization", ["org_other", "invalid-org"])
async def test_unmapped_or_invalid_org_denies_existing_identity(monkeypatch, organization):
    with pytest.raises(HTTPException) as error:
        await authenticate(monkeypatch, [principal()], {"sub": "user_shared", "org_id": organization})
    assert error.value.status_code == 403


async def test_inactive_identity_is_not_reactivated_from_stale_role(monkeypatch):
    with pytest.raises(HTTPException) as error:
        await authenticate(
            monkeypatch,
            [principal(status="inactive")],
            {"sub": "user_shared", "org_id": ORG_A, "org_role": "org:admin"},
        )
    assert error.value.status_code == 403


async def test_uuid_claim_selects_correct_tenant_for_shared_subject(monkeypatch):
    result, writes = await authenticate(
        monkeypatch, [principal(roles=("admin",)), principal(ORG_B)], {"sub": "user_shared", "org_id": ORG_B}
    )
    assert result.organization_id == ORG_B
    assert "admin" not in result.roles
    writes.assert_not_called()


async def test_unscoped_duplicate_subject_denies_even_with_role_claim(monkeypatch):
    with pytest.raises(HTTPException) as error:
        await authenticate(
            monkeypatch, [principal(), principal(ORG_B)], {"sub": "user_shared", "org_role": "org:admin"}
        )
    assert error.value.status_code == 403


async def test_single_provisioned_personal_session_keeps_database_grant(monkeypatch):
    result, writes = await authenticate(monkeypatch, [principal()], {"sub": "user_shared"})
    assert result.organization_id == ORG_A
    assert "analyst" in result.roles
    writes.assert_not_called()


def test_database_unavailable_returns_503():
    with pytest.raises(HTTPException) as error:
        load_principal(lambda: None, "user_shared")
    assert error.value.status_code == 503


LINKED_ORG = "org_linked123"
LINKED_UUID = ORG_A


async def test_linked_native_org_keeps_database_grant(monkeypatch):
    result, writes = await authenticate(
        monkeypatch,
        [principal()],
        {"sub": "user_shared", "org_id": LINKED_ORG, "org_role": "org:member"},
        links={LINKED_ORG: LINKED_UUID},
    )
    assert result.organization_id == ORG_A
    assert "analyst" in result.roles
    writes.assert_not_called()


async def test_linked_native_org_provisions_new_member_with_mapped_role(monkeypatch):
    result, writes = await authenticate(
        monkeypatch,
        [],
        {"sub": "user_new", "org_id": LINKED_ORG, "org_role": "org:admin"},
        links={LINKED_ORG: LINKED_UUID},
    )
    assert result.organization_id == ORG_A
    assert writes.called
    synced = writes.call_args[0]
    assert synced[2] == LINKED_UUID
    assert synced[3] == "admin"


async def test_unlinked_native_org_stays_denied_for_members(monkeypatch):
    with pytest.raises(HTTPException) as error:
        await authenticate(
            monkeypatch, [principal()], {"sub": "user_shared", "org_id": "org_unknown999", "org_role": "org:member"}
        )
    assert error.value.status_code == 403
    assert error.value.detail == "Clerk organization is not provisioned"


async def test_unlinked_native_org_creator_bootstraps_owned_tenant(monkeypatch):
    created = {}

    def fake_bootstrap(*args):
        created["args"] = args[1:]
        return {"organization_id": ORG_B, "principal_id": "principal-new"}

    monkeypatch.setattr(auth, "bootstrap_clerk_organization", fake_bootstrap)
    result, writes = await authenticate(
        monkeypatch,
        [principal(org=ORG_B, roles=("admin",))],
        {"sub": "user_creator", "org_id": "org_brandnew1", "org_role": "org:admin"},
    )
    assert created["args"][0] == "org_brandnew1"
    assert created["args"][2] == "user_creator"
    assert result.organization_id == ORG_B
    assert "admin" in result.roles
    writes.assert_not_called()


class RecordingCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def execute(self, query, params):
        self.conn.statements.append(query)
        if "INSERT INTO app.organizations" in query:
            self.conn.queued = [{"id": "org-new-uuid"}]
        elif "INSERT INTO app.principals" in query:
            self.conn.queued = [{"id": "principal-new"}]
        elif "SELECT id FROM app.organizations" in query:
            self.conn.queued = []

    def fetchone(self):
        return (self.conn.queued or [None])[0]


class RecordingConnection:
    def __init__(self):
        self.statements = []
        self.queued = []
        self.committed = False

    def cursor(self):
        return RecordingCursor(self)

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        pass


def test_bootstrap_creates_tenant_and_admin_grant():
    conn = RecordingConnection()
    result = bootstrap_clerk_organization(lambda: conn, "org_new9", "Acme Corp", "user_y", "Y")
    assert result == {"organization_id": "org-new-uuid", "principal_id": "principal-new"}
    assert conn.committed
    assert any("clerk_organization_id" in s for s in conn.statements)
    assert any("INSERT INTO app.principal_roles" in s for s in conn.statements)


async def test_linked_native_org_claim_in_session_object_form_keeps_grant(monkeypatch):
    # Real session JWTs carry the org inside the `o` object (`o.id`/`o.rol`),
    # not as top-level org_id/org_role claims (Refs #336).
    result, writes = await authenticate(
        monkeypatch,
        [principal()],
        {"sub": "user_shared", "o": {"id": LINKED_ORG, "rol": "member", "slg": "linked"}},
        links={LINKED_ORG: LINKED_UUID},
    )
    assert result.organization_id == ORG_A
    assert "analyst" in result.roles
    writes.assert_not_called()


class SyncCursor:
    def __init__(self):
        self.statements: list = []
        self._queue: list = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def execute(self, query, params):
        q = " ".join(str(query).split())
        self.statements.append((q, params))
        if q.startswith("INSERT INTO app.principals"):
            self._queue.append({"id": "pid-1", "organization_id": params[0]})
        elif q.startswith("SELECT id, organization_id, external_ref FROM app.drivers"):
            pass
        elif q.startswith("SELECT id, organization_id, principal_id FROM app.drivers"):
            pass
        elif q.startswith("INSERT INTO app.drivers"):
            self._queue.append({"id": params[0]})

    def fetchone(self):
        return self._queue.pop(0) if self._queue else None

    def fetchall(self):
        return []


class SyncConnection:
    def __init__(self):
        self.cursor_obj = SyncCursor()
        self.committed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        pass


def test_sync_driver_creates_deterministic_driver_binding():
    conn = SyncConnection()
    expected_driver_id = str(uuid5(UUID(ORG_A), "user_driver_1"))
    row = sync_clerk_principal(lambda: conn, "user_driver_1", ORG_A, "driver", "Driver One")
    assert row is not None
    assert row["driver_id"] == expected_driver_id
    assert row["roles"] == ["driver"]
    assert conn.committed
    assert any(stmt[0].startswith("INSERT INTO app.drivers") for stmt in conn.cursor_obj.statements)
    assert not any("principal_id IS NULL" in stmt[0] for stmt in conn.cursor_obj.statements)


def test_sync_non_driver_returns_no_driver_link():
    conn = SyncConnection()
    row = sync_clerk_principal(lambda: conn, "user_analyst_1", ORG_A, "analyst", "Analyst One")
    assert row is not None
    assert row["driver_id"] is None
    assert not any("app.drivers" in stmt[0] for stmt in conn.cursor_obj.statements)


class StatefulAuthDB:
    def __init__(self, principal_row, existing_driver=None, collision_driver=None):
        if isinstance(principal_row, list):
            self.principal_rows = [dict(p) for p in principal_row]
            self.principal_row = self.principal_rows[0] if self.principal_rows else {}
        else:
            self.principal_row = dict(principal_row)
            self.principal_rows = [self.principal_row]
        self.drivers = {}
        if existing_driver:
            self.drivers[existing_driver["id"]] = existing_driver
        if collision_driver:
            self.drivers[collision_driver["id"]] = collision_driver
        self.statements = []
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return StatefulAuthCursor(self)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


class StatefulAuthCursor:
    def __init__(self, db: StatefulAuthDB):
        self.db = db
        self.results = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, query, params=None):
        clean_q = " ".join(str(query).split())
        self.db.statements.append((clean_q, params))

        if "FROM app.principals" in clean_q:
            # load_principal
            matched = []
            for p in self.db.principal_rows:
                if params and len(params) > 1 and params[1] and str(p.get("organization_id")) != str(params[1]):
                    continue
                # Find driver_id from db.drivers linked to this principal
                d_id = None
                for d in self.db.drivers.values():
                    if d.get("principal_id") == p.get("id") and str(d.get("organization_id")) == str(
                        p.get("organization_id")
                    ):
                        d_id = d.get("id")
                        break
                row = dict(p)
                row["driver_id"] = d_id
                matched.append(row)
            self.results = matched[:2]

        elif "SELECT id, organization_id, external_ref FROM app.drivers WHERE principal_id = %s" in clean_q:
            p_id = params[0]
            matched = [
                {"id": d["id"], "organization_id": d["organization_id"], "external_ref": d.get("external_ref")}
                for d in self.db.drivers.values()
                if d.get("principal_id") == p_id
            ]
            self.results = matched

        elif (
            "SELECT id, organization_id, principal_id FROM app.drivers WHERE id = %s OR (organization_id = %s AND external_ref = %s)"
            in clean_q
        ):
            d_id, org_id, ext_ref = params[0], params[1], params[2]
            matched = [
                {"id": d["id"], "organization_id": d["organization_id"], "principal_id": d.get("principal_id")}
                for d in self.db.drivers.values()
                if d["id"] == d_id or (str(d["organization_id"]) == str(org_id) and d.get("external_ref") == ext_ref)
            ]
            self.results = matched

        elif "INSERT INTO app.drivers" in clean_q:
            d_id, org_id, p_id, ext_ref, disp_name = params[0], params[1], params[2], params[3], params[4]
            new_d = {
                "id": d_id,
                "organization_id": org_id,
                "principal_id": p_id,
                "external_ref": ext_ref,
                "display_name": disp_name,
                "partner_type": "owner_driver",
                "account_status": "active",
                "is_synthetic": False,
            }
            self.db.drivers[d_id] = new_d
            self.results = [{"id": d_id}]

        elif "SELECT id, organization_id, principal_id FROM app.drivers WHERE id = %s" in clean_q:
            d_id = params[0]
            if d_id in self.db.drivers:
                d = self.db.drivers[d_id]
                self.results = [
                    {"id": d["id"], "organization_id": d["organization_id"], "principal_id": d.get("principal_id")}
                ]
            else:
                self.results = []

    def fetchone(self):
        return self.results.pop(0) if self.results else None

    def fetchall(self):
        res = list(self.results)
        self.results = []
        return res


async def _run_require_principal(monkeypatch, db: StatefulAuthDB, claims: dict):
    monkeypatch.setattr(auth, "authenticate_request", lambda *_args: SimpleNamespace(is_signed_in=True, payload=claims))
    sync_mock = Mock()
    monkeypatch.setattr(auth, "sync_clerk_principal", sync_mock)
    settings = Settings(app_env="production", database_url="", clerk_secret_key="sk_test_unit", _env_file=None)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/me",
            "headers": [(b"authorization", b"Bearer verified-session")],
        }
    )
    service = SimpleNamespace(_get_db_connection=lambda: db)
    return await auth.require_principal(request, settings, service), sync_mock


@pytest.mark.asyncio
async def test_require_principal_db_driver_stale_jwt_admin_prevented(monkeypatch):
    """Negative scenario 1: DBdriver + staleJWTadmin must never escalate to admin in Principal or DB."""
    subject = "user_driver_stale_admin"
    db = StatefulAuthDB({"id": "pid-driver-1", "organization_id": ORG_A, "roles": ["driver"], "status": "active"})
    claims = {"sub": subject, "org_id": ORG_A, "org_role": "admin"}

    result, sync_mock = await _run_require_principal(monkeypatch, db, claims)

    # Principal assertions
    assert result.roles == frozenset({"driver"})
    assert "admin" not in result.roles
    assert "fraud_analyst" not in result.roles
    expected_driver_id = str(uuid5(UUID(ORG_A), subject))
    assert result.driver_id == expected_driver_id

    # DB safety assertions
    sync_mock.assert_not_called()
    assert db.principal_row["roles"] == ["driver"]
    assert not any("INSERT INTO app.principal_roles" in stmt[0] for stmt in db.statements)


@pytest.mark.asyncio
async def test_require_principal_db_driver_stale_jwt_member_prevented(monkeypatch):
    """Negative scenario 2: DBdriver + staleJWTmember must never insert member/analyst grant."""
    subject = "user_driver_stale_member"
    db = StatefulAuthDB({"id": "pid-driver-2", "organization_id": ORG_A, "roles": ["driver"], "status": "active"})
    claims = {"sub": subject, "org_id": ORG_A, "org_role": "member"}

    result, sync_mock = await _run_require_principal(monkeypatch, db, claims)

    assert result.roles == frozenset({"driver"})
    assert "fraud_analyst" not in result.roles
    assert "analyst" not in result.roles
    sync_mock.assert_not_called()
    assert db.principal_row["roles"] == ["driver"]
    assert not any("INSERT INTO app.principal_roles" in stmt[0] for stmt in db.statements)


@pytest.mark.asyncio
async def test_require_principal_db_driver_global_admin_metadata_prevented(monkeypatch):
    """Negative scenario 3: DBdriver + no-org/globaladminmetadata must never grant admin."""
    subject = "user_driver_global_admin"
    db = StatefulAuthDB({"id": "pid-driver-3", "organization_id": ORG_A, "roles": ["driver"], "status": "active"})
    claims = {"sub": subject, "public_metadata": {"role": "admin"}}

    result, sync_mock = await _run_require_principal(monkeypatch, db, claims)

    assert result.roles == frozenset({"driver"})
    assert "admin" not in result.roles
    assert result.organization_id == ORG_A
    sync_mock.assert_not_called()
    assert db.principal_row["roles"] == ["driver"]


@pytest.mark.asyncio
async def test_require_principal_db_admin_and_driver_multi_role_preserved(monkeypatch):
    """Negative scenario 4: DBadmin+driver multi-role missing profile preserves all roles without loss."""
    subject = "user_multi_role_1"
    db = StatefulAuthDB(
        {"id": "pid-multi-1", "organization_id": ORG_A, "roles": ["admin", "driver"], "status": "active"}
    )
    claims = {"sub": subject, "org_id": ORG_A, "org_role": "driver"}

    result, sync_mock = await _run_require_principal(monkeypatch, db, claims)

    expected_driver_id = str(uuid5(UUID(ORG_A), subject))
    assert result.driver_id == expected_driver_id
    assert "admin" in result.roles
    assert "driver" in result.roles
    sync_mock.assert_not_called()
    assert set(db.principal_row["roles"]) == {"admin", "driver"}


@pytest.mark.asyncio
async def test_require_principal_another_org_claim_mismatch_denied(monkeypatch):
    """Negative scenario 5: anotherorg claim without verified active role raises 403 and does not mutate driver profile."""
    subject = "user_driver_org_mismatch"
    db = StatefulAuthDB({"id": "pid-driver-5", "organization_id": ORG_A, "roles": ["driver"], "status": "active"})
    claims = {"sub": subject, "org_id": ORG_B}

    with pytest.raises(HTTPException) as exc_info:
        await _run_require_principal(monkeypatch, db, claims)

    assert exc_info.value.status_code == 403
    assert len(db.drivers) == 0


@pytest.mark.asyncio
async def test_require_principal_verified_multi_org_membership_provisions_in_second_org(monkeypatch):
    """Positive multi-org: same Clerk subject provisions in second org without copying principal ID or roles."""
    subject = "user_multi_org_member"
    db = StatefulAuthDB({"id": "pid-org-a", "organization_id": ORG_A, "roles": ["driver"], "status": "active"})
    claims = {"sub": subject, "org_id": ORG_B, "org_role": "admin"}

    monkeypatch.setattr(auth, "authenticate_request", lambda *_args: SimpleNamespace(is_signed_in=True, payload=claims))
    sync_mock = Mock(
        return_value={
            "id": "pid-org-b",
            "organization_id": ORG_B,
            "roles": ["admin"],
            "status": "active",
            "driver_id": None,
        }
    )
    monkeypatch.setattr(auth, "sync_clerk_principal", sync_mock)
    settings = Settings(app_env="production", database_url="", clerk_secret_key="sk_test_unit", _env_file=None)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/me",
            "headers": [(b"authorization", b"Bearer verified-session")],
        }
    )
    service = SimpleNamespace(_get_db_connection=lambda: db)

    result = await auth.require_principal(request, settings, service)

    assert result.organization_id == ORG_B
    assert result.id == "pid-org-b"
    assert "admin" in result.roles
    sync_mock.assert_called_once()
    assert sync_mock.call_args[0][1] == subject
    assert sync_mock.call_args[0][2] == ORG_B
    assert sync_mock.call_args[0][3] == "admin"
    assert db.principal_row["id"] == "pid-org-a"
    assert db.principal_row["organization_id"] == ORG_A
    assert db.principal_row["roles"] == ["driver"]


@pytest.mark.asyncio
async def test_require_principal_disabled_principal_in_second_org_remains_denied(monkeypatch):
    """Negative multi-org: if subject is active in Org A but disabled in Org B, accessing Org B is denied 403."""
    subject = "user_multi_org_disabled"
    principals = [
        {"id": "pid-org-a", "organization_id": ORG_A, "roles": ["driver"], "status": "active"},
        {"id": "pid-org-b", "organization_id": ORG_B, "roles": ["driver"], "status": "disabled"},
    ]
    db = StatefulAuthDB(principals)
    claims = {"sub": subject, "org_id": ORG_B, "org_role": "driver"}

    with pytest.raises(HTTPException) as exc_info:
        await _run_require_principal(monkeypatch, db, claims)

    assert exc_info.value.status_code == 403
    assert "no active assigned role" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_require_principal_profile_collision_fails_closed(monkeypatch):
    """Negative scenario 6: profile collision fails closed with HTTP 409."""
    subject = "user_driver_collision"
    deterministic_id = str(uuid5(UUID(ORG_A), subject))
    collision_driver = {
        "id": deterministic_id,
        "organization_id": ORG_A,
        "principal_id": "other-principal-uuid",
        "external_ref": f"clerk:{subject}",
        "display_name": "Colliding Profile",
        "partner_type": "owner_driver",
        "account_status": "active",
        "is_synthetic": False,
    }
    db = StatefulAuthDB(
        {"id": "pid-driver-6", "organization_id": ORG_A, "roles": ["driver"], "status": "active"},
        collision_driver=collision_driver,
    )
    claims = {"sub": subject, "org_id": ORG_A, "org_role": "driver"}

    with pytest.raises(HTTPException) as exc_info:
        await _run_require_principal(monkeypatch, db, claims)

    assert exc_info.value.status_code == 409
    assert "Driver profile collision" in exc_info.value.detail


@pytest.mark.asyncio
async def test_require_principal_stable_repeated_login(monkeypatch):
    """Negative scenario 7: stable repeated login does not re-insert driver profile."""
    subject = "user_driver_stable_repeat"
    db = StatefulAuthDB({"id": "pid-driver-7", "organization_id": ORG_A, "roles": ["driver"], "status": "active"})
    claims = {"sub": subject, "org_id": ORG_A, "org_role": "driver"}

    # First login provisions driver profile
    res1, sync1 = await _run_require_principal(monkeypatch, db, claims)
    driver_id = res1.driver_id
    assert driver_id is not None
    assert len(db.drivers) == 1
    insert_count_1 = sum(1 for stmt in db.statements if "INSERT INTO app.drivers" in stmt[0])
    assert insert_count_1 == 1

    # Second login reuses existing profile without executing another INSERT
    res2, sync2 = await _run_require_principal(monkeypatch, db, claims)
    assert res2.driver_id == driver_id
    insert_count_2 = sum(1 for stmt in db.statements if "INSERT INTO app.drivers" in stmt[0])
    assert insert_count_2 == 1  # No new INSERT statements executed!
