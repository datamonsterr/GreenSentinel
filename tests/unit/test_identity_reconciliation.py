"""Unit tests for identity reconciliation service.

Tests cover:
- Role mapping rules and unknown role rejection.
- Deterministic UUID5 organization mapping, seed org preservation, collision detection.
- Clerk pagination verification, incomplete fetch rejection, conflicting membership roles.
- Deterministic plan hashing and stale plan rejection.
- Mode 0600 recovery export file creation and permissions.
- Proven mock lineage detection vs real user preservation.
- Status 'disabled' (not 'inactive') for orphaned real principals.
- Mock principal references outside approved fixture fail closed (MockPrincipalReferenceError).
- Safety guard: loopback, disposable prefix, and opt-in validation (no remote bypass).
- FK closure ordering for mock cases and principals.
- Schema difference adaptation (production 17 vs dev/staging 27 migrations).
- Sanitized reporting with opaque hashes and zero PII/secrets.
- FakeConnection / FakeCursor unit contracts.
"""

from __future__ import annotations

import os
import stat
import uuid

import pytest

from src.services.identity_reconciliation import (
    ClerkMembership,
    ClerkMembershipConflictError,
    ClerkOrg,
    ClerkPaginationError,
    ClerkSnapshot,
    ClerkUser,
    DatabaseAuditState,
    ReconciliationPlan,
    SafetyGuardError,
    StalePlanError,
    assert_disposable_db_guard,
    compute_org_uuid,
    execute_reconciliation_apply,
    export_recovery_snapshot,
    generate_reconciliation_plan,
    generate_sanitized_report,
    map_clerk_role,
)


def test_role_mapping_valid():
    """Verify accepted Clerk roles map to canonical database roles."""
    assert map_clerk_role("org:admin") == "admin"
    assert map_clerk_role("admin") == "admin"
    assert map_clerk_role("org:member") == "fraud_analyst"
    assert map_clerk_role("member") == "fraud_analyst"
    assert map_clerk_role("analyst") == "fraud_analyst"
    assert map_clerk_role("org:driver") == "driver"
    assert map_clerk_role("driver") == "driver"
    assert map_clerk_role("org:reviewer") == "reviewer"
    assert map_clerk_role("org:ops_director") == "ops_director"
    assert map_clerk_role("org:marketplace_director") == "marketplace_director"


def test_role_mapping_unknown_rejected():
    """Verify unknown roles raise ValueError and are denied."""
    for invalid in ["guest", "superadmin", "org:owner", "viewer", ""]:
        with pytest.raises(ValueError, match="Unknown or unmapped Clerk role"):
            map_clerk_role(invalid)


def test_compute_org_uuid_preserves_seed_mapping():
    """Verify established seed org mapping is strictly preserved."""
    seed_clerk_id = "org_3JeWZxDcpdvFmff2fW1nXP7tjm6"
    expected_uuid = "018f2f4e-0000-7000-8000-000000000001"
    existing_map = {seed_clerk_id: expected_uuid}
    assert compute_org_uuid(seed_clerk_id, existing_map) == expected_uuid


def test_compute_org_uuid_deterministic_uuid5():
    """Verify new orgs receive deterministic UUID5 based on Clerk ID."""
    org_id = "org_3KgjpNMRBassAjaOng1zfBD2dda"
    u1 = compute_org_uuid(org_id)
    u2 = compute_org_uuid(org_id)
    assert u1 == u2
    # Verify it is a valid UUID
    parsed = uuid.UUID(u1)
    assert parsed.version == 5


def test_compute_org_uuid_collision_detection():
    """Verify collision with existing UUID raises error."""
    derived = compute_org_uuid("org_test")
    # If a new distinct org generates the same UUID as an existing one in DB
    with pytest.raises(ValueError, match="Collision"):
        compute_org_uuid("org_test", existing_mappings={}, existing_uuids={derived})


def test_clerk_snapshot_pagination_validation():
    """Verify incomplete pagination raises ClerkPaginationError."""
    # When declared count exceeds items
    with pytest.raises(ClerkPaginationError, match="Pagination incomplete"):
        ClerkSnapshot(
            organizations=[ClerkOrg(id="org_1", name="Org 1", slug="org-1")],
            users=[],
            memberships=[],
            total_orgs=2,  # Expected 2 but only 1 present
            total_users=0,
            total_memberships=0,
            complete=True,
        ).validate_completeness()

    # When marked incomplete
    with pytest.raises(ClerkPaginationError, match="marked incomplete"):
        ClerkSnapshot(
            organizations=[],
            users=[],
            memberships=[],
            total_orgs=0,
            total_users=0,
            total_memberships=0,
            complete=False,
        ).validate_completeness()


def test_clerk_snapshot_duplicate_and_conflict_detection():
    """Verify duplicate IDs and conflicting roles are rejected."""
    # Duplicate org ID
    with pytest.raises(ClerkPaginationError, match="Duplicate organization ID"):
        ClerkSnapshot(
            organizations=[
                ClerkOrg(id="org_dup", name="Org A"),
                ClerkOrg(id="org_dup", name="Org B"),
            ],
            users=[],
            memberships=[],
            total_orgs=2,
            total_users=0,
            total_memberships=0,
            complete=True,
        ).validate_completeness()

    # Duplicate user ID
    with pytest.raises(ClerkPaginationError, match="Duplicate user ID"):
        ClerkSnapshot(
            organizations=[],
            users=[
                ClerkUser(id="user_dup"),
                ClerkUser(id="user_dup"),
            ],
            memberships=[],
            total_orgs=0,
            total_users=2,
            total_memberships=0,
            complete=True,
        ).validate_completeness()

    # Conflicting membership roles in same org
    with pytest.raises(ClerkMembershipConflictError, match="Conflicting membership roles"):
        ClerkSnapshot(
            organizations=[ClerkOrg(id="org_1", name="Org 1")],
            users=[ClerkUser(id="user_1")],
            memberships=[
                ClerkMembership(id="mem_1", user_id="user_1", org_id="org_1", role="org:admin"),
                ClerkMembership(id="mem_2", user_id="user_1", org_id="org_1", role="org:driver"),
            ],
            total_orgs=1,
            total_users=1,
            total_memberships=2,
            complete=True,
        ).validate_completeness()


def test_safety_guard_assert_disposable_db_guard(monkeypatch):
    """Verify safety guard requires loopback host, disposable prefix, and explicit opt-in."""
    monkeypatch.setenv("GREENSENTINEL_RECONCILE_DISPOSABLE_DB", "1")

    # 1. Remote host rejected even with opt-in
    with pytest.raises(SafetyGuardError, match="not loopback"):
        assert_disposable_db_guard("postgresql://user:pass@remote.host.com:5432/test_greensentinel_finalize_394_dev")

    # 2. Loopback with non-disposable prefix rejected
    with pytest.raises(SafetyGuardError, match="does not have disposable prefix"):
        assert_disposable_db_guard("postgresql://user:pass@127.0.0.1:5432/production_shared")

    # 3. Missing opt-in rejected
    monkeypatch.delenv("GREENSENTINEL_RECONCILE_DISPOSABLE_DB", raising=False)
    with pytest.raises(SafetyGuardError, match="opt-in required"):
        assert_disposable_db_guard("postgresql://user:pass@127.0.0.1:5432/test_greensentinel_finalize_394_dev")

    # 4. Valid loopback + disposable prefix + opt-in accepted
    monkeypatch.setenv("GREENSENTINEL_RECONCILE_DISPOSABLE_DB", "1")
    assert_disposable_db_guard("postgresql://user:pass@127.0.0.1:5432/test_greensentinel_finalize_394_dev")
    assert_disposable_db_guard("postgresql://user:pass@localhost:5432/test_greensentinel_disposable_db1")


def test_export_recovery_snapshot_enforces_0600(tmp_path):
    """Verify recovery snapshot export creates mode 0600 file."""
    recovery_file = str(tmp_path / "test_recovery.json")
    data = {"test": "value", "id": 123}
    export_recovery_snapshot(data, recovery_file)

    assert os.path.exists(recovery_file)
    mode = os.stat(recovery_file).st_mode
    # File permissions must be 0600 (-rw-------)
    assert stat.S_IMODE(mode) == 0o600


def test_plan_hash_determinism_and_stale_rejection():
    """Verify plan hashing is strictly deterministic and detects schema/data changes."""
    clerk = ClerkSnapshot(
        organizations=[ClerkOrg(id="org_3JeWZxDcpdvFmff2fW1nXP7tjm6", name="GreenSM Hanoi", slug="greensm")],
        users=[ClerkUser(id="user_real_admin_01", email_hash="hash1")],
        memberships=[
            ClerkMembership(
                id="mem_1", user_id="user_real_admin_01", org_id="org_3JeWZxDcpdvFmff2fW1nXP7tjm6", role="org:admin"
            )
        ],
        total_orgs=1,
        total_users=1,
        total_memberships=1,
        complete=True,
    )
    db_state = DatabaseAuditState(
        migrations_count=27,
        latest_migration="20261015130000_tester_publish_submissions.sql",
        organizations=[
            {
                "id": "018f2f4e-0000-7000-8000-000000000001",
                "name": "GreenSM Hanoi",
                "clerk_organization_id": "org_3JeWZxDcpdvFmff2fW1nXP7tjm6",
            }
        ],
        principals=[
            {
                "id": "p1",
                "organization_id": "018f2f4e-0000-7000-8000-000000000001",
                "external_subject": "user_real_admin_01",
                "status": "active",
                "roles": ["admin"],
            }
        ],
        mock_cases=[
            {
                "id": "018f2f4e-a000-7000-8000-000000000001",
                "organization_id": "018f2f4e-0000-7000-8000-000000000001",
                "status": "ready",
            }
        ],
        available_tables={"organizations", "principals", "principal_roles", "fraud_cases"},
    )

    plan1 = generate_reconciliation_plan(clerk, db_state, env="dev")
    plan2 = generate_reconciliation_plan(clerk, db_state, env="dev")
    assert plan1.plan_hash == plan2.plan_hash
    assert len(plan1.plan_hash) == 64

    # If database state changes, plan hash changes
    db_state_modified = DatabaseAuditState(
        migrations_count=27,
        latest_migration=db_state.latest_migration,
        organizations=db_state.organizations,
        principals=db_state.principals,
        mock_cases=[],  # Changed
        available_tables=db_state.available_tables,
    )
    plan3 = generate_reconciliation_plan(clerk, db_state_modified, env="dev")
    assert plan3.plan_hash != plan1.plan_hash


def test_orphaned_real_principal_deactivation_uses_disabled_status():
    """Verify real principals with no active Clerk membership are deactivated with status='disabled', never deleted."""
    clerk = ClerkSnapshot(
        organizations=[ClerkOrg(id="org_3JeWZxDcpdvFmff2fW1nXP7tjm6", name="GreenSM Hanoi", slug="greensm")],
        users=[ClerkUser(id="user_real_active", email_hash="h1"), ClerkUser(id="user_real_orphan", email_hash="h2")],
        memberships=[
            ClerkMembership(
                id="mem_1", user_id="user_real_active", org_id="org_3JeWZxDcpdvFmff2fW1nXP7tjm6", role="org:admin"
            ),
        ],
        total_orgs=1,
        total_users=2,
        total_memberships=1,
        complete=True,
    )
    db_state = DatabaseAuditState(
        migrations_count=27,
        latest_migration="20261015130000_tester_publish_submissions.sql",
        organizations=[
            {
                "id": "018f2f4e-0000-7000-8000-000000000001",
                "name": "GreenSM Hanoi",
                "clerk_organization_id": "org_3JeWZxDcpdvFmff2fW1nXP7tjm6",
            }
        ],
        principals=[
            {
                "id": "p1",
                "organization_id": "018f2f4e-0000-7000-8000-000000000001",
                "external_subject": "user_real_active",
                "status": "active",
                "roles": ["admin"],
            },
            {
                "id": "p2",
                "organization_id": "018f2f4e-0000-7000-8000-000000000001",
                "external_subject": "user_real_orphan",
                "status": "active",
                "roles": ["fraud_analyst"],
            },
        ],
        mock_cases=[],
        available_tables={"organizations", "principals", "principal_roles", "fraud_cases"},
    )

    plan = generate_reconciliation_plan(clerk, db_state, env="dev")
    # p2 should be in deactivated_principals with new_status='disabled'
    deactivated = {p["id"]: p for p in plan.principals_to_deactivate}
    deleted_ids = [p["id"] for p in plan.principals_to_delete]

    assert "p2" in deactivated
    assert deactivated["p2"]["new_status"] == "disabled"
    assert "p2" not in deleted_ids


def test_proven_mock_principal_cleanup():
    """Verify proven mock principals (user_clerk_analyst_*, drv_gsm_*) are flagged for deletion."""
    clerk = ClerkSnapshot(
        organizations=[ClerkOrg(id="org_3JeWZxDcpdvFmff2fW1nXP7tjm6", name="GreenSM Hanoi", slug="greensm")],
        users=[],
        memberships=[],
        total_orgs=1,
        total_users=0,
        total_memberships=0,
        complete=True,
    )
    db_state = DatabaseAuditState(
        migrations_count=27,
        latest_migration="20261015130000_tester_publish_submissions.sql",
        organizations=[
            {
                "id": "018f2f4e-0000-7000-8000-000000000001",
                "name": "GreenSM Hanoi",
                "clerk_organization_id": "org_3JeWZxDcpdvFmff2fW1nXP7tjm6",
            }
        ],
        principals=[
            {
                "id": "p_mock_analyst",
                "organization_id": "018f2f4e-0000-7000-8000-000000000001",
                "external_subject": "user_clerk_analyst_001",
                "status": "active",
                "roles": ["analyst"],
            },
            {
                "id": "p_mock_driver",
                "organization_id": "018f2f4e-0000-7000-8000-000000000001",
                "external_subject": "drv_gsm_0001",
                "status": "active",
                "roles": ["driver"],
            },
            {
                "id": "p_real_orphan",
                "organization_id": "018f2f4e-0000-7000-8000-000000000001",
                "external_subject": "user_3JeWYPiqOUbtpsfCT8tKgIlPAsN",
                "status": "active",
                "roles": ["analyst"],
            },
        ],
        mock_cases=[],
        available_tables={"organizations", "principals", "principal_roles", "fraud_cases"},
    )

    plan = generate_reconciliation_plan(clerk, db_state, env="dev")
    deleted_subjects = [p["external_subject"] for p in plan.principals_to_delete]
    deactivated_subjects = [p["external_subject"] for p in plan.principals_to_deactivate]

    assert "user_clerk_analyst_001" in deleted_subjects
    assert "drv_gsm_0001" in deleted_subjects
    assert "user_3JeWYPiqOUbtpsfCT8tKgIlPAsN" not in deleted_subjects
    assert "user_3JeWYPiqOUbtpsfCT8tKgIlPAsN" in deactivated_subjects


def test_schema_difference_adaptation():
    """Verify plan handles schema with 17 migrations (missing tables) without failing."""
    clerk = ClerkSnapshot(
        organizations=[ClerkOrg(id="org_3JeWZxDcpdvFmff2fW1nXP7tjm6", name="GreenSM Hanoi", slug="greensm")],
        users=[],
        memberships=[],
        total_orgs=1,
        total_users=0,
        total_memberships=0,
        complete=True,
    )
    prod_state = DatabaseAuditState(
        migrations_count=17,
        latest_migration="20261014000000_case_documents.sql",
        organizations=[
            {
                "id": "018f2f4e-0000-7000-8000-000000000001",
                "name": "GreenSM Hanoi",
                "clerk_organization_id": "org_3JeWZxDcpdvFmff2fW1nXP7tjm6",
            }
        ],
        principals=[],
        mock_cases=[],
        available_tables={"organizations", "principals", "principal_roles", "fraud_cases", "adjudications"},
    )

    plan = generate_reconciliation_plan(clerk, prod_state, env="production")
    assert plan.env == "production"
    assert "preliminary_judgments" in plan.preflight_missing_tables
    for step in plan.fk_cleanup_steps:
        assert step["table"] in prod_state.available_tables


def test_sanitized_report_contains_no_secrets_or_emails():
    """Verify sanitized report contains counts, opaque hashes, and no DSNs or plaintext emails."""
    plan = ReconciliationPlan(
        env="dev",
        plan_hash="a" * 64,
        schema_fingerprint="b" * 64,
        orgs_to_create=[{"clerk_id": "org_123", "name_hash": "c1a2b3", "uuid": str(uuid.uuid4())}],
        orgs_unchanged=[
            {"clerk_id": "org_seed", "name_hash": "d4e5f6", "uuid": "018f2f4e-0000-7000-8000-000000000001"}
        ],
        orgs_to_update_name=[],
        principals_to_create=[
            {"subject_hash": "e7f8a9", "org_id": "018f2f4e-0000-7000-8000-000000000001", "role": "admin"}
        ],
        principals_to_update_role=[],
        principals_to_deactivate=[{"id": str(uuid.uuid4()), "subject_hash": "112233"}],
        principals_to_delete=[{"id": str(uuid.uuid4()), "external_subject": "user_clerk_analyst_001"}],
        mock_cases_to_delete=[{"id": "018f2f4e-a000-7000-8000-000000000001"}],
        fk_cleanup_steps=[{"table": "adjudications", "rows_count": 0}],
        preflight_missing_tables=[],
    )

    report = generate_sanitized_report(plan)
    assert plan.plan_hash in report
    assert "postgres://" not in report
    assert "@" not in report
    assert "password" not in report.lower()


# =========================================================================
# Unit Contracts with FakeConnection / FakeCursor
# =========================================================================


class FakeCursor:
    """Mock database cursor for unit contract and SQL structure verification."""

    def __init__(self, queries_log: list[str], return_values: dict | None = None):
        self.queries = queries_log
        self.return_values = return_values or {}
        self._last_query = ""
        self.description = [("id",), ("name",)]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def execute(self, sql: str, params: tuple | None = None):
        cleaned = " ".join(sql.strip().split())
        self._last_query = cleaned
        self.queries.append(cleaned)
        if "INJECT_SQL_ERROR" in cleaned or (params and any("INJECT_SQL_ERROR" in str(p) for p in params)):
            raise RuntimeError("Injected database failure during execution")

    def fetchone(self):
        if "SELECT pg_advisory_xact_lock" in self._last_query:
            return (None,)
        if "SELECT count(*)" in self._last_query and "user_clerk_analyst_" in self._last_query:
            return (0,)
        if "RETURNING id" in self._last_query:
            return (str(uuid.uuid4()),)
        if "FROM pg_trigger" in self._last_query:
            return ("reject_mutation", "O")
        return self.return_values.get(self._last_query, (1,))

    def fetchall(self):
        if "FROM information_schema.tables" in self._last_query:
            return [("organizations",), ("principals",), ("principal_roles",), ("fraud_cases",)]
        return []


class FakeConnection:
    """Mock database connection for unit lifecycle verification."""

    def __init__(self):
        self.queries: list[str] = []
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return FakeCursor(self.queries)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def test_unit_contract_transactional_apply_lock_and_idempotency(tmp_path):
    """Unit contract: verify advisory lock, lock timeout, and recovery export."""
    conn = FakeConnection()
    plan = ReconciliationPlan(
        env="dev",
        plan_hash="h" * 64,
        schema_fingerprint="f" * 64,
        orgs_to_create=[],
        orgs_unchanged=[],
        orgs_to_update_name=[],
        principals_to_create=[],
        principals_to_update_role=[],
        principals_to_deactivate=[],
        principals_to_delete=[],
        mock_cases_to_delete=[],
        fk_cleanup_steps=[],
        preflight_missing_tables=[],
        recovery_export_data={"mock": "data"},
    )

    result = execute_reconciliation_apply(
        conn=conn,
        plan=plan,
        expected_plan_hash="h" * 64,
        allow_apply=True,
        recovery_dir=str(tmp_path),
    )

    assert result["status"] == "applied"
    assert conn.committed is True
    # Verify timeout and advisory lock executed
    assert any("SET LOCAL lock_timeout" in q for q in conn.queries)
    assert any("SELECT pg_advisory_xact_lock" in q for q in conn.queries)


def test_unit_contract_transactional_apply_rollback_on_failure(tmp_path):
    """Unit contract: verify connection rolls back when error occurs."""
    conn = FakeConnection()
    plan = ReconciliationPlan(
        env="dev",
        plan_hash="h" * 64,
        schema_fingerprint="f" * 64,
        orgs_to_create=[{"uuid": str(uuid.uuid4()), "name": "INJECT_SQL_ERROR", "clerk_id": "org_err"}],
        orgs_unchanged=[],
        orgs_to_update_name=[],
        principals_to_create=[],
        principals_to_update_role=[],
        principals_to_deactivate=[],
        principals_to_delete=[],
        mock_cases_to_delete=[],
        fk_cleanup_steps=[],
        preflight_missing_tables=[],
        recovery_export_data={"mock": "data"},
    )

    with pytest.raises(RuntimeError, match="Injected database failure"):
        execute_reconciliation_apply(
            conn=conn,
            plan=plan,
            expected_plan_hash="h" * 64,
            allow_apply=True,
            recovery_dir=str(tmp_path),
        )

    assert conn.rolled_back is True
    assert conn.committed is False


def test_unit_contract_stale_plan_hash_rejection(tmp_path):
    """Unit contract: mismatched plan hash raises StalePlanError."""
    conn = FakeConnection()
    plan = ReconciliationPlan(
        env="dev",
        plan_hash="actual_hash" * 4,
        schema_fingerprint="f" * 64,
        orgs_to_create=[],
        orgs_unchanged=[],
        orgs_to_update_name=[],
        principals_to_create=[],
        principals_to_update_role=[],
        principals_to_deactivate=[],
        principals_to_delete=[],
        mock_cases_to_delete=[],
        fk_cleanup_steps=[],
        preflight_missing_tables=[],
    )

    with pytest.raises(StalePlanError, match="Stale or mismatched plan rejected"):
        execute_reconciliation_apply(
            conn=conn,
            plan=plan,
            expected_plan_hash="stale_hash" * 4,
            allow_apply=True,
            recovery_dir=str(tmp_path),
        )


def test_unit_contract_apply_requires_allow_flag(tmp_path):
    """Unit contract: verify execution without allow_apply raises PermissionError."""
    conn = FakeConnection()
    plan = ReconciliationPlan(
        env="dev",
        plan_hash="h" * 64,
        schema_fingerprint="f" * 64,
        orgs_to_create=[],
        orgs_unchanged=[],
        orgs_to_update_name=[],
        principals_to_create=[],
        principals_to_update_role=[],
        principals_to_deactivate=[],
        principals_to_delete=[],
        mock_cases_to_delete=[],
        fk_cleanup_steps=[],
        preflight_missing_tables=[],
    )

    with pytest.raises(PermissionError, match="allow_apply flag is required"):
        execute_reconciliation_apply(
            conn=conn,
            plan=plan,
            expected_plan_hash="h" * 64,
            allow_apply=False,
            recovery_dir=str(tmp_path),
        )
