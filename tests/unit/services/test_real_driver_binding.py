import uuid
from typing import Any

import pytest
from fastapi import HTTPException

import src.api.auth as auth_module
import src.services.access_control as access_control_module
from src.services.access_control import ensure_driver_profile, sync_clerk_principal

ORG_A = "018f2f4e-0000-7000-8000-000000000001"
ORG_B = "018f2f4e-0000-7000-8000-000000000002"
FORBIDDEN_FIXTURE_UUID = "018f2f4e-3000-7000-8000-000000000006"


class MockDriverDBConnection:
    """In-memory PostgreSQL mock preserving relational semantics for principals and drivers."""

    def __init__(self):
        self.principals: dict[tuple[str, str], dict[str, Any]] = {}  # (org_id, external_subject) -> dict
        self.principal_roles: list[dict[str, Any]] = []
        self.drivers: dict[str, dict[str, Any]] = {}  # driver_id -> dict
        self.statements: list[tuple[str, tuple]] = []
        self.committed = False
        self.rolled_back = False
        self.simulate_db_error = False

    def cursor(self):
        return MockDriverDBCursor(self)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


class MockDriverDBCursor:
    def __init__(self, db: MockDriverDBConnection):
        self.db = db
        self.last_result: list[dict[str, Any]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def execute(self, query: str, params: tuple = ()):
        if self.db.simulate_db_error:
            raise RuntimeError("Simulated database failure")

        clean_q = " ".join(query.split())
        self.db.statements.append((clean_q, params))

        if "INSERT INTO app.principals" in clean_q:
            org_id, ext_sub, disp_name = params[0], params[1], params[2]
            key = (org_id, ext_sub)
            if key not in self.db.principals:
                p_id = str(uuid.uuid5(uuid.UUID(org_id), f"principal:{ext_sub}"))
                self.db.principals[key] = {
                    "id": p_id,
                    "organization_id": org_id,
                    "external_subject": ext_sub,
                    "display_name": disp_name,
                    "status": "active",
                }
            self.last_result = [self.db.principals[key]]

        elif "INSERT INTO app.principal_roles" in clean_q:
            p_id, role = params[0], params[1]
            self.db.principal_roles.append({"principal_id": p_id, "role": role})
            self.last_result = []

        elif "SELECT id, organization_id, external_ref FROM app.drivers WHERE principal_id = %s" in clean_q:
            p_id = params[0]
            matched = [
                {"id": d["id"], "organization_id": d["organization_id"], "external_ref": d["external_ref"]}
                for d in self.db.drivers.values()
                if d.get("principal_id") == p_id
            ]
            self.last_result = matched

        elif (
            "SELECT id, organization_id, principal_id FROM app.drivers WHERE id = %s OR (organization_id = %s AND external_ref = %s)"
            in clean_q
        ):
            d_id, org_id, ext_ref = params[0], params[1], params[2]
            matched = [
                {"id": d["id"], "organization_id": d["organization_id"], "principal_id": d.get("principal_id")}
                for d in self.db.drivers.values()
                if d["id"] == d_id or (d["organization_id"] == org_id and d.get("external_ref") == ext_ref)
            ]
            self.last_result = matched

        elif "INSERT INTO app.drivers" in clean_q:
            d_id, org_id, p_id, ext_ref, disp_name = params[0], params[1], params[2], params[3], params[4]
            # Check unique constraint violations
            if d_id in self.db.drivers:
                self.last_result = []
            elif any(
                d["organization_id"] == org_id and d.get("external_ref") == ext_ref for d in self.db.drivers.values()
            ):
                self.last_result = []
            elif any(d.get("principal_id") == p_id for d in self.db.drivers.values()):
                self.last_result = []
            else:
                new_driver = {
                    "id": d_id,
                    "organization_id": org_id,
                    "principal_id": p_id,
                    "external_ref": ext_ref,
                    "display_name": disp_name,
                    "partner_type": "owner_driver",
                    "account_status": "active",
                    "is_synthetic": False,
                }
                self.db.drivers[d_id] = new_driver
                self.last_result = [{"id": d_id}]

        elif "SELECT id, organization_id, principal_id FROM app.drivers WHERE id = %s" in clean_q:
            d_id = params[0]
            if d_id in self.db.drivers:
                d = self.db.drivers[d_id]
                self.last_result = [
                    {"id": d["id"], "organization_id": d["organization_id"], "principal_id": d.get("principal_id")}
                ]
            else:
                self.last_result = []

        elif "UPDATE app.drivers" in clean_q:
            # Legacy branch if hit
            self.last_result = []

    def fetchone(self):
        return self.last_result[0] if self.last_result else None

    def fetchall(self):
        return list(self.last_result)


def test_no_fixture_uuid_referenced_in_source():
    """Ensure hardcoded fixture UUID is completely excised from access_control and auth source."""
    with open(access_control_module.__file__, encoding="utf-8") as f:
        ac_source = f.read()
    with open(auth_module.__file__, encoding="utf-8") as f:
        auth_source = f.read()

    assert FORBIDDEN_FIXTURE_UUID not in ac_source, f"{FORBIDDEN_FIXTURE_UUID} found in access_control.py"
    assert FORBIDDEN_FIXTURE_UUID not in auth_source, f"{FORBIDDEN_FIXTURE_UUID} found in auth.py"


def test_never_claims_arbitrary_seeded_driver():
    """sync_clerk_principal must never query or update unassigned/seeded drivers (principal_id IS NULL)."""
    db = MockDriverDBConnection()
    # Pre-populate an unbound seeded driver
    seeded_id = "018f2f4e-9999-7000-8000-000000000001"
    db.drivers[seeded_id] = {
        "id": seeded_id,
        "organization_id": ORG_A,
        "principal_id": None,
        "external_ref": "drv_seeded_001",
        "display_name": "Seeded Driver",
        "partner_type": "fleet",
        "account_status": "active",
        "is_synthetic": True,
    }

    result = sync_clerk_principal(lambda: db, "user_real_driver", ORG_A, "driver", "Real Driver")
    assert result is not None
    # Real driver must NOT claim the seeded driver's id
    assert result["driver_id"] != seeded_id
    # Seeded driver must remain unlinked
    assert db.drivers[seeded_id]["principal_id"] is None
    # Assert query does not search for principal_id IS NULL
    for stmt, _ in db.statements:
        assert "principal_id IS NULL" not in stmt, "Attempted to query/claim unlinked driver"


def test_real_driver_profile_deterministic_uuid5():
    """Deterministic profile creation derived from verified Clerk subject and UUID5(org, subject)."""
    db = MockDriverDBConnection()
    subject = "user_driver_clerk_123"
    expected_driver_id = str(uuid.uuid5(uuid.UUID(ORG_A), subject))

    result = sync_clerk_principal(lambda: db, subject, ORG_A, "driver", "Nguyen Driver")
    assert result is not None
    assert result["driver_id"] == expected_driver_id
    assert result["roles"] == ["driver"]
    assert db.committed

    driver = db.drivers[expected_driver_id]
    assert driver["organization_id"] == ORG_A
    assert driver["external_ref"] == f"clerk:{subject}"
    assert driver["is_synthetic"] is False
    assert driver["display_name"] == "Nguyen Driver"


def test_two_real_users_not_sharing_driver():
    """Two real users in same org must receive distinct deterministic driver profiles."""
    db = MockDriverDBConnection()
    res1 = sync_clerk_principal(lambda: db, "user_driver_alpha", ORG_A, "driver", "Alpha")
    res2 = sync_clerk_principal(lambda: db, "user_driver_beta", ORG_A, "driver", "Beta")

    assert res1 is not None and res2 is not None
    assert res1["driver_id"] != res2["driver_id"]
    assert len(db.drivers) == 2


def test_two_org_isolation():
    """Driver profile is strictly tenant-scoped; same subject in different orgs gets different profiles."""
    db = MockDriverDBConnection()
    subject = "user_multi_org_driver"
    res_a = sync_clerk_principal(lambda: db, subject, ORG_A, "driver", "Multi Org Driver")
    res_b = sync_clerk_principal(lambda: db, subject, ORG_B, "driver", "Multi Org Driver")

    assert res_a is not None and res_b is not None
    assert res_a["driver_id"] != res_b["driver_id"]
    assert db.drivers[res_a["driver_id"]]["organization_id"] == ORG_A
    assert db.drivers[res_b["driver_id"]]["organization_id"] == ORG_B


def test_existing_binding_stable():
    """Repeated sync calls for already bound driver remain stable and do not mutate or duplicate."""
    db = MockDriverDBConnection()
    subject = "user_stable_driver"
    res1 = sync_clerk_principal(lambda: db, subject, ORG_A, "driver", "Stable Driver")
    driver_id = res1["driver_id"]

    # Re-sync
    res2 = sync_clerk_principal(lambda: db, subject, ORG_A, "driver", "Stable Driver Updated Name")
    assert res2["driver_id"] == driver_id
    assert len(db.drivers) == 1


def test_transaction_failure_not_swallowed():
    """Database exceptions during driver binding must fail closed and roll back, not be swallowed."""
    db = MockDriverDBConnection()
    db.simulate_db_error = True

    with pytest.raises(HTTPException) as exc_info:
        sync_clerk_principal(lambda: db, "user_fail_driver", ORG_A, "driver", "Fail Driver")

    assert exc_info.value.status_code == 503
    assert db.rolled_back


def test_non_driver_no_driver():
    """Non-driver roles (admin, fraud_analyst, member) must receive driver_id None and no driver row."""
    db = MockDriverDBConnection()
    for role in ["admin", "fraud_analyst", "member"]:
        result = sync_clerk_principal(lambda: db, f"user_{role}", ORG_A, role, f"User {role}")
        assert result is not None
        assert result["driver_id"] is None
    assert len(db.drivers) == 0


def test_collision_fail_closed():
    """If deterministic driver ID or external_ref collides with an existing profile belonging to another principal, fail closed."""
    db = MockDriverDBConnection()
    subject = "user_driver_collide"
    deterministic_id = str(uuid.uuid5(uuid.UUID(ORG_A), subject))

    # Pre-insert collision driver linked to different principal
    db.drivers[deterministic_id] = {
        "id": deterministic_id,
        "organization_id": ORG_A,
        "principal_id": "other-principal-uuid",
        "external_ref": f"clerk:{subject}",
        "display_name": "Imposter Driver",
        "partner_type": "owner_driver",
        "account_status": "active",
        "is_synthetic": False,
    }

    with pytest.raises(HTTPException) as exc_info:
        sync_clerk_principal(lambda: db, subject, ORG_A, "driver", "Colliding Driver")

    assert exc_info.value.status_code in (403, 409)


def test_ensure_driver_profile_creates_deterministic_profile():
    """ensure_driver_profile provisions deterministic profile without modifying principal or roles."""
    db = MockDriverDBConnection()
    principal_id = "principal-uuid-101"
    subject = "user_driver_clerk_101"
    expected_driver_id = str(uuid.uuid5(uuid.UUID(ORG_A), subject))

    driver_id = ensure_driver_profile(lambda: db, principal_id, ORG_A, subject, "Profile Driver")
    assert driver_id == expected_driver_id
    assert db.committed

    driver = db.drivers[expected_driver_id]
    assert driver["principal_id"] == principal_id
    assert driver["organization_id"] == ORG_A
    assert driver["external_ref"] == f"clerk:{subject}"
    assert driver["display_name"] == "Profile Driver"

    # Assert no statements touched app.principals or app.principal_roles
    for stmt, _ in db.statements:
        assert "INSERT INTO app.principals" not in stmt
        assert "UPDATE app.principals" not in stmt
        assert "INSERT INTO app.principal_roles" not in stmt


def test_ensure_driver_profile_preserves_existing_link():
    """ensure_driver_profile returns already linked driver without mutation."""
    db = MockDriverDBConnection()
    principal_id = "principal-uuid-102"
    existing_driver_id = "018f2f4e-aaaa-7000-8000-000000000001"
    db.drivers[existing_driver_id] = {
        "id": existing_driver_id,
        "organization_id": ORG_A,
        "principal_id": principal_id,
        "external_ref": "drv_existing_102",
        "display_name": "Existing Driver",
        "partner_type": "owner_driver",
        "account_status": "active",
        "is_synthetic": False,
    }

    driver_id = ensure_driver_profile(lambda: db, principal_id, ORG_A, "user_clerk_102", "Driver")
    assert driver_id == existing_driver_id
    # Assert no INSERT statements were executed
    for stmt, _ in db.statements:
        assert "INSERT INTO app.drivers" not in stmt


def test_ensure_driver_profile_collision_fails_closed():
    """ensure_driver_profile fails closed (409) when deterministic id or external_ref collides."""
    db = MockDriverDBConnection()
    subject = "user_driver_collide_ensure"
    deterministic_id = str(uuid.uuid5(uuid.UUID(ORG_A), subject))
    db.drivers[deterministic_id] = {
        "id": deterministic_id,
        "organization_id": ORG_A,
        "principal_id": "other-principal",
        "external_ref": f"clerk:{subject}",
        "display_name": "Other Driver",
        "partner_type": "owner_driver",
        "account_status": "active",
        "is_synthetic": False,
    }

    with pytest.raises(HTTPException) as exc_info:
        ensure_driver_profile(lambda: db, "my-principal", ORG_A, subject, "Colliding Driver")

    assert exc_info.value.status_code == 409


def test_ensure_driver_profile_org_mismatch_fails_403():
    """ensure_driver_profile fails 403 if existing driver linked to principal has different org."""
    db = MockDriverDBConnection()
    principal_id = "principal-uuid-103"
    existing_id = "018f2f4e-bbbb-7000-8000-000000000002"
    db.drivers[existing_id] = {
        "id": existing_id,
        "organization_id": ORG_B,
        "principal_id": principal_id,
        "external_ref": "drv_103",
        "display_name": "Driver",
        "partner_type": "owner_driver",
        "account_status": "active",
        "is_synthetic": False,
    }

    with pytest.raises(HTTPException) as exc_info:
        ensure_driver_profile(lambda: db, principal_id, ORG_A, "user_clerk_103", "Driver")

    assert exc_info.value.status_code == 403


def test_ensure_driver_profile_db_error_fails_503_and_rolls_back():
    """ensure_driver_profile rolls back and raises 503 on db failure."""
    db = MockDriverDBConnection()
    db.simulate_db_error = True

    with pytest.raises(HTTPException) as exc_info:
        ensure_driver_profile(lambda: db, "p-err", ORG_A, "user_err", "Driver")

    assert exc_info.value.status_code == 503
    assert db.rolled_back
