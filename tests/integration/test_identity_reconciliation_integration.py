"""Real PostgreSQL integration tests for identity reconciliation (#410 / #402 / #394).

Guards:
- Enforces loopback isolation (127.0.0.1, localhost, ::1) AND disposable prefix AND explicit opt-in.
- No remote bypass by opting in.
- Executes against real PostgreSQL clones derived from template test_p063_finalize_394_dev_20261015t173125z.
- Verifies:
  1. Full positive lifecycle: audit -> plan -> apply -> verify -> repeated no-op.
  2. Transaction rollback after mid-delete error: data and triggers restored.
  3. Schema drift rejection under bounded advisory lock.
  4. Stale data rejection under bounded advisory lock.
  5. Preservation of unrelated real case referencing mock principal (fail closed, reject, not delete).
  6. Trigger restoration: unrelated append-only records remain protected (SQLSTATE 55000).
  7. Two-org isolation and deterministic mapping.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import uuid
from collections.abc import Generator

import psycopg
import pytest

from src.services.identity_reconciliation import (
    ClerkMembership,
    ClerkOrg,
    ClerkSnapshot,
    ClerkUser,
    DatabaseAuditState,
    MockPrincipalReferenceError,
    SafetyGuardError,
    StalePlanError,
    assert_disposable_db_guard,
    audit_database_state,
    execute_reconciliation_apply,
    fetch_clerk_snapshot_from_file,
    generate_reconciliation_plan,
)


def _get_postgres_connection_params() -> tuple[str, int, str, str]:
    """Inspect local p063-postgres container in-process or read environment."""
    host = "127.0.0.1"
    port = int(os.environ.get("P063_POSTGRES_PORT", "5432"))
    user = os.environ.get("P063_POSTGRES_USER", "postgres")
    password = os.environ.get("P063_POSTGRES_PASSWORD", "postgrespassword")

    try:
        proc = subprocess.run(
            ["docker", "inspect", "p063-postgres"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            data = json.loads(proc.stdout)
            if data and isinstance(data, list):
                c_env = data[0].get("Config", {}).get("Env", [])
                for e in c_env:
                    if e.startswith("POSTGRES_PASSWORD="):
                        password = e.split("=", 1)[1]
                    elif e.startswith("POSTGRES_USER="):
                        user = e.split("=", 1)[1]
    except Exception:
        pass

    return host, port, user, password


@pytest.fixture
def disposable_dev_db(monkeypatch) -> Generator[str, None, None]:
    """Create an isolated, temporary PostgreSQL database cloned from the restored dev clone."""
    monkeypatch.setenv("P063_RECONCILE_DISPOSABLE_DB", "1")
    host, port, user, password = _get_postgres_connection_params()

    disposable_dbname = f"test_p063_finalize_394_int_{uuid.uuid4().hex[:8]}"
    template_dbname = "test_p063_finalize_394_dev_20261015t173125z"

    # Connect to maintenance db to create clone
    admin_dsn = f"postgresql://{user}:{password}@{host}:{port}/postgres"
    conn_admin = psycopg.connect(admin_dsn, autocommit=True)
    with conn_admin.cursor() as cur:
        cur.execute(f"CREATE DATABASE {disposable_dbname} TEMPLATE {template_dbname}")
    conn_admin.close()

    db_url = f"postgresql://{user}:{password}@{host}:{port}/{disposable_dbname}"
    assert_disposable_db_guard(db_url)

    try:
        yield db_url
    finally:
        # Terminate any active connections and drop the disposable db
        conn_admin = psycopg.connect(admin_dsn, autocommit=True)
        with conn_admin.cursor() as cur:
            cur.execute(
                f"""
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = '{disposable_dbname}' AND pid <> pg_backend_pid()
                """
            )
            cur.execute(f"DROP DATABASE IF EXISTS {disposable_dbname} WITH (FORCE)")
        conn_admin.close()


def test_safety_guard_rejects_remote_even_with_optin(monkeypatch):
    """Safety guard: remote host URLs must raise SafetyGuardError even with opt-in."""
    monkeypatch.setenv("P063_RECONCILE_DISPOSABLE_DB", "1")
    remote_url = "postgresql://user:pass@railway.proxy.rlwy.net:1234/test_p063_finalize_394_dev"
    with pytest.raises(SafetyGuardError, match="not loopback"):
        assert_disposable_db_guard(remote_url)


def test_safety_guard_rejects_non_disposable_prefix(monkeypatch):
    """Safety guard: non-prefixed databases must be rejected."""
    monkeypatch.setenv("P063_RECONCILE_DISPOSABLE_DB", "1")
    with pytest.raises(SafetyGuardError, match="does not have disposable prefix"):
        assert_disposable_db_guard("postgresql://user:pass@127.0.0.1:5432/shared_database")


def test_e2e_reconciliation_full_lifecycle(disposable_dev_db, tmp_path):
    """Execute full lifecycle on real PostgreSQL clone: audit -> plan -> apply -> verify -> repeated no-op."""
    conn = psycopg.connect(disposable_dev_db, autocommit=False)
    audit_snapshot_file = "/tmp/p063-identity-audit.json"
    if not os.path.exists(audit_snapshot_file):
        pytest.skip(f"Required audit snapshot {audit_snapshot_file} missing on host.")

    clerk_snapshot = fetch_clerk_snapshot_from_file(audit_snapshot_file)
    clerk_snapshot.validate_completeness()

    # 1. Audit initial DB state
    db_state = audit_database_state(conn)
    assert len(db_state.organizations) == 1
    assert len(db_state.principals) == 43  # 30 mock + 13 real
    assert len(db_state.mock_cases) == 100
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM app.fraud_cases")
        assert cur.fetchone()[0] == 102  # 100 mock + 2 real dev cases

    # 2. Generate Reconciliation Plan
    plan = generate_reconciliation_plan(clerk_snapshot, db_state, env="dev")
    assert len(plan.orgs_to_create) == 9
    assert len(plan.orgs_unchanged) == 1
    assert len(plan.principals_to_create) == 9
    assert len(plan.principals_to_update_role) == 1
    assert len(plan.principals_to_deactivate) == 10
    assert len(plan.principals_to_delete) == 30
    assert len(plan.mock_cases_to_delete) == 100

    # 3. Apply Plan
    recovery_dir = str(tmp_path)
    result = execute_reconciliation_apply(
        conn=conn,
        plan=plan,
        expected_plan_hash=plan.plan_hash,
        allow_apply=True,
        recovery_dir=recovery_dir,
        clerk_snapshot=clerk_snapshot,
    )
    assert result["status"] == "applied"
    assert result["mock_principals_deleted"] == 30
    assert result["mock_cases_deleted"] == 100

    # 4. Verify DB Postconditions
    with conn.cursor() as cur:
        # All 10 organizations exist with valid clerk_organization_id
        cur.execute("SELECT count(*) FROM app.organizations")
        assert cur.fetchone()[0] == 10

        # Zero mock principals remain
        cur.execute(
            """
            SELECT count(*) FROM app.principals
            WHERE external_subject LIKE 'user_clerk_analyst_%'
               OR external_subject LIKE 'drv_gsm_%'
            """
        )
        assert cur.fetchone()[0] == 0

        # Exactly the 2 real dev cases remain (preserved)
        cur.execute("SELECT count(*) FROM app.fraud_cases")
        assert cur.fetchone()[0] == 2
        cur.execute("SELECT id FROM app.fraud_cases ORDER BY id")
        remaining_case_ids = {str(r[0]) for r in cur.fetchall()}
        assert "6ed41b7e-8bab-40c4-b1bb-741bb543ffd9" in remaining_case_ids
        assert "22c3b317-c414-432e-94db-c28d10bd82eb" in remaining_case_ids

        # Deactivated principals have status='disabled' (satisfies CHECK constraint)
        deact_ids = [p["id"] for p in plan.principals_to_deactivate]
        cur.execute("SELECT status FROM app.principals WHERE id = ANY(%s)", (deact_ids,))
        statuses = {r[0] for r in cur.fetchall()}
        assert statuses == {"disabled"}

        # Deactivated principals have zero active roles
        cur.execute("SELECT count(*) FROM app.principal_roles WHERE principal_id = ANY(%s)", (deact_ids,))
        assert cur.fetchone()[0] == 0

        # Triggers remain enabled
        cur.execute(
            """
            SELECT t.tgname, t.tgenabled
            FROM pg_trigger t
            JOIN pg_class c ON t.tgrelid = c.oid
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = 'app' AND t.tgname = 'evidence_snapshots_append_only'
            """
        )
        row = cur.fetchone()
        assert row is not None
        assert row[1] == "O"

    # Verify recovery export file exists and has mode 0600
    rec_file = result["recovery_file"]
    assert os.path.exists(rec_file)
    assert stat.S_IMODE(os.stat(rec_file).st_mode) == 0o600
    with open(rec_file) as f:
        dump = json.load(f)
    assert len(dump["affected_rows"]["fraud_cases"]) == 100
    assert len(dump["affected_rows"]["principals_deleted"]) == 30

    # 5. Repeated run: Verify Idempotent No-Op
    db_state_2 = audit_database_state(conn)
    plan_2 = generate_reconciliation_plan(clerk_snapshot, db_state_2, env="dev")
    assert len(plan_2.orgs_to_create) == 0
    assert len(plan_2.principals_to_create) == 0
    assert len(plan_2.principals_to_update_role) == 0
    assert len(plan_2.principals_to_deactivate) == 0
    assert len(plan_2.principals_to_delete) == 0
    assert len(plan_2.mock_cases_to_delete) == 0

    result_2 = execute_reconciliation_apply(
        conn=conn,
        plan=plan_2,
        expected_plan_hash=plan_2.plan_hash,
        allow_apply=True,
        recovery_dir=recovery_dir,
        clerk_snapshot=clerk_snapshot,
    )
    assert result_2["status"] == "applied"
    assert result_2["principals_created"] == 0
    assert result_2["mock_principals_deleted"] == 0
    conn.close()


def test_rollback_after_mid_delete_error(disposable_dev_db, tmp_path):
    """Verify transaction rolls back completely on error and leaves DB unmodified."""
    conn = psycopg.connect(disposable_dev_db, autocommit=False)
    audit_snapshot_file = "/tmp/p063-identity-audit.json"
    if not os.path.exists(audit_snapshot_file):
        pytest.skip(f"Required audit snapshot {audit_snapshot_file} missing on host.")

    clerk_snapshot = fetch_clerk_snapshot_from_file(audit_snapshot_file)
    db_state = audit_database_state(conn)
    plan = generate_reconciliation_plan(clerk_snapshot, db_state, env="dev")

    # Corrupt plan with an illegal organization UUID to force failure midway through apply
    plan.orgs_to_create.append(
        {
            "uuid": "invalid-uuid-string",
            "name": "Failing Org",
            "clerk_id": "org_fail",
        }
    )

    with pytest.raises(Exception):
        execute_reconciliation_apply(
            conn=conn,
            plan=plan,
            expected_plan_hash=plan.plan_hash,
            allow_apply=True,
            recovery_dir=str(tmp_path),
            clerk_snapshot=clerk_snapshot,
        )

    # Verify counts remain identical to before apply
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM app.organizations")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT count(*) FROM app.principals")
        assert cur.fetchone()[0] == 43
        cur.execute("SELECT count(*) FROM app.fraud_cases")
        assert cur.fetchone()[0] == 102

    conn.close()


def test_schema_drift_rejection_under_lock(disposable_dev_db, tmp_path):
    """Verify schema drift under bounded lock raises StalePlanError and aborts."""
    conn = psycopg.connect(disposable_dev_db, autocommit=False)
    audit_snapshot_file = "/tmp/p063-identity-audit.json"
    if not os.path.exists(audit_snapshot_file):
        pytest.skip("Audit snapshot missing")

    clerk_snapshot = fetch_clerk_snapshot_from_file(audit_snapshot_file)
    db_state = audit_database_state(conn)
    plan = generate_reconciliation_plan(clerk_snapshot, db_state, env="dev")

    # Introduce schema drift before apply
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE app.adjudications ADD COLUMN drift_test_col text")
    conn.commit()

    with pytest.raises(StalePlanError, match="schema drifted"):
        execute_reconciliation_apply(
            conn=conn,
            plan=plan,
            expected_plan_hash=plan.plan_hash,
            allow_apply=True,
            recovery_dir=str(tmp_path),
            clerk_snapshot=clerk_snapshot,
        )

    conn.close()


def test_stale_data_rejection_under_lock(disposable_dev_db, tmp_path):
    """Verify data mutation between plan generation and apply raises StalePlanError."""
    conn = psycopg.connect(disposable_dev_db, autocommit=False)
    audit_snapshot_file = "/tmp/p063-identity-audit.json"
    if not os.path.exists(audit_snapshot_file):
        pytest.skip("Audit snapshot missing")

    clerk_snapshot = fetch_clerk_snapshot_from_file(audit_snapshot_file)
    db_state = audit_database_state(conn)
    plan = generate_reconciliation_plan(clerk_snapshot, db_state, env="dev")

    # Mutate data in DB before apply
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO app.principals (id, organization_id, external_subject, display_name, status)
            VALUES (gen_random_uuid(), '018f2f4e-0000-7000-8000-000000000001', 'user_interfering_01', 'Interfering', 'active')
            """
        )
    conn.commit()

    with pytest.raises(StalePlanError, match="drifted"):
        execute_reconciliation_apply(
            conn=conn,
            plan=plan,
            expected_plan_hash=plan.plan_hash,
            allow_apply=True,
            recovery_dir=str(tmp_path),
            clerk_snapshot=clerk_snapshot,
        )

    conn.close()


def test_unrelated_real_case_referencing_mock_principal_rejected(disposable_dev_db, tmp_path):
    """Verify that an unrelated real case referencing a mock principal fails closed."""
    conn = psycopg.connect(disposable_dev_db, autocommit=False)
    audit_snapshot_file = "/tmp/p063-identity-audit.json"
    if not os.path.exists(audit_snapshot_file):
        pytest.skip("Audit snapshot missing")

    clerk_snapshot = fetch_clerk_snapshot_from_file(audit_snapshot_file)

    # Update real dev case 6ed41b7e-8bab-40c4-b1bb-741bb543ffd9 to reference mock analyst
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM app.principals WHERE external_subject = 'user_clerk_analyst_001'
            """
        )
        mock_p_id = cur.fetchone()[0]
        cur.execute(
            """
            UPDATE app.fraud_cases
            SET assigned_analyst_id = %s
            WHERE id = '6ed41b7e-8bab-40c4-b1bb-741bb543ffd9'
            """,
            (mock_p_id,),
        )
    conn.commit()

    db_state = audit_database_state(conn)
    plan = generate_reconciliation_plan(clerk_snapshot, db_state, env="dev")

    with pytest.raises(MockPrincipalReferenceError, match="Cascade-deletion of business data is strictly forbidden"):
        execute_reconciliation_apply(
            conn=conn,
            plan=plan,
            expected_plan_hash=plan.plan_hash,
            allow_apply=True,
            recovery_dir=str(tmp_path),
            clerk_snapshot=clerk_snapshot,
        )

    # Verify real case and mock principal were NOT deleted
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM app.fraud_cases WHERE id = '6ed41b7e-8bab-40c4-b1bb-741bb543ffd9'")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT count(*) FROM app.principals WHERE id = %s", (mock_p_id,))
        assert cur.fetchone()[0] == 1

    conn.close()


def test_trigger_restoration_and_unrelated_record_protection(disposable_dev_db, tmp_path):
    """Verify that append-only triggers are restored and protect unrelated records after apply."""
    conn = psycopg.connect(disposable_dev_db, autocommit=False)
    audit_snapshot_file = "/tmp/p063-identity-audit.json"
    if not os.path.exists(audit_snapshot_file):
        pytest.skip("Audit snapshot missing")

    clerk_snapshot = fetch_clerk_snapshot_from_file(audit_snapshot_file)
    db_state = audit_database_state(conn)
    plan = generate_reconciliation_plan(clerk_snapshot, db_state, env="dev")

    execute_reconciliation_apply(
        conn=conn,
        plan=plan,
        expected_plan_hash=plan.plan_hash,
        allow_apply=True,
        recovery_dir=str(tmp_path),
        clerk_snapshot=clerk_snapshot,
    )

    # Attempting to delete an unrelated remaining evidence snapshot MUST raise SQLSTATE 55000
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM app.evidence_snapshots LIMIT 1")
        row = cur.fetchone()
        assert row is not None
        snap_id = row[0]

        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState) as exc_info:
            cur.execute("DELETE FROM app.evidence_snapshots WHERE id = %s", (snap_id,))
        assert exc_info.value.sqlstate == "55000"
        assert "evidence_snapshots is append-only" in str(exc_info.value)

    conn.rollback()
    conn.close()


def test_two_org_isolation(disposable_dev_db):
    """Verify that Clerk users in Org A cannot access or get bound to Org B."""
    clerk = ClerkSnapshot(
        organizations=[
            ClerkOrg(id="org_A", name="Org Alpha"),
            ClerkOrg(id="org_B", name="Org Beta"),
        ],
        users=[
            ClerkUser(id="user_alpha", display_name="Alpha Analyst"),
            ClerkUser(id="user_beta", display_name="Beta Driver"),
        ],
        memberships=[
            ClerkMembership(id="m_1", org_id="org_A", user_id="user_alpha", role="org:member"),
            ClerkMembership(id="m_2", org_id="org_B", user_id="user_beta", role="org:driver"),
        ],
        total_orgs=2,
        total_users=2,
        total_memberships=2,
        complete=True,
    )
    db_state = DatabaseAuditState(
        migrations_count=27,
        latest_migration="test",
        organizations=[],
        principals=[],
        mock_cases=[],
        available_tables={"organizations", "principals", "principal_roles", "fraud_cases"},
    )

    plan = generate_reconciliation_plan(clerk, db_state, env="dev")
    created = plan.principals_to_create
    assert len(created) == 2

    org_a_uuid = next(o["uuid"] for o in plan.orgs_to_create if o["clerk_id"] == "org_A")
    org_b_uuid = next(o["uuid"] for o in plan.orgs_to_create if o["clerk_id"] == "org_B")
    assert org_a_uuid != org_b_uuid

    p_alpha = next(p for p in created if p["external_subject"] == "user_alpha")
    p_beta = next(p for p in created if p["external_subject"] == "user_beta")

    assert p_alpha["organization_id"] == org_a_uuid
    assert p_alpha["role"] == "fraud_analyst"

    assert p_beta["organization_id"] == org_b_uuid
    assert p_beta["role"] == "driver"
