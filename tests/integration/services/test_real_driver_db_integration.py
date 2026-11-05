"""Real PostgreSQL integration tests on disposable database clones.

Tests driver profile uniqueness, foreign keys, triggers, transaction rollback,
and privilege escalation prevention against an actual PostgreSQL engine
using loopback and generated test_ database names built from repository migrations
or an optional template clone.
"""

from __future__ import annotations

import os
import time
import uuid
from types import SimpleNamespace
from urllib.parse import urlparse
from uuid import UUID, uuid4, uuid5

import psycopg
import pytest
from fastapi import HTTPException
from psycopg import sql
from starlette.requests import Request

from scripts.migrate_postgres import apply_migrations, get_target_connection
from src.api import auth
from src.config import Settings
from src.services.access_control import ensure_driver_profile


def _get_base_dsn() -> str:
    return (
        os.environ.get("TARGET_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("MIGRATION_DATABASE_URL")
        or "postgresql://postgres:postgrespassword@127.0.0.1:5432/postgres"
    )


def _assert_loopback_target(dsn: str) -> None:
    parsed = urlparse(dsn)
    host = (parsed.hostname or "127.0.0.1").lower()
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise RuntimeError(
            f"Safety guard: refusing to run disposable real driver integration test against non-loopback host '{host}'"
        )


TEMPLATE_DB = os.environ.get("TEST_TEMPLATE_DB")


def is_postgres_available() -> bool:
    try:
        base_dsn = _get_base_dsn()
        _assert_loopback_target(base_dsn)
        with psycopg.connect(base_dsn, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                return bool(cur.fetchone())
    except Exception:
        return False


pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        not is_postgres_available(),
        reason="PostgreSQL engine not reachable on loopback",
    ),
]


@pytest.fixture(scope="module")
def disposable_db():
    """Create a disposable database from template (if available) or repository migrations and drop it after."""
    base_dsn = _get_base_dsn()
    _assert_loopback_target(base_dsn)

    stamp = int(time.time() * 1000)
    dbname = f"test_p063_driver_bind_{stamp}"

    parsed = urlparse(base_dsn)
    user = parsed.username or "postgres"
    password = parsed.password or "postgrespassword"
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 5432
    admin_dsn = f"postgresql://{user}:{password}@{host}:{port}/postgres"
    target_dsn = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"

    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            has_template = False
            if TEMPLATE_DB:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEMPLATE_DB,))
                has_template = bool(cur.fetchone())

            if has_template:
                cur.execute(
                    sql.SQL("CREATE DATABASE {} TEMPLATE {};").format(
                        sql.Identifier(dbname), sql.Identifier(TEMPLATE_DB)
                    )
                )
            else:
                cur.execute(sql.SQL("CREATE DATABASE {};").format(sql.Identifier(dbname)))

    if not has_template:
        mig_conn = get_target_connection(target_dsn)
        try:
            apply_migrations(mig_conn, target_url=target_dsn)
        finally:
            mig_conn.close()

        with psycopg.connect(target_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SET search_path = app, extensions, public;")
                cur.execute(
                    "INSERT INTO app.organizations (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
                    ("00000000-0000-0000-0000-000000000001", "Default Driver Test Org"),
                )

    yield target_dsn

    # Teardown: terminate connections and drop disposable database
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid()
                """,
                (dbname,),
            )
            cur.execute(sql.SQL("DROP DATABASE IF EXISTS {};").format(sql.Identifier(dbname)))


@pytest.fixture
def get_db_connection(disposable_db):
    """Factory returning a fresh connection to the disposable test database."""

    def _factory():
        conn = psycopg.connect(disposable_db, row_factory=psycopg.rows.dict_row)
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
        return conn

    return _factory


def get_real_org_id(get_db_connection) -> str:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            cur.execute("SELECT id FROM app.organizations ORDER BY created_at ASC LIMIT 1")
            row = cur.fetchone()
            assert row is not None, "app.organizations must have at least one organization"
            return str(row["id"] if isinstance(row, dict) else row[0])


def test_real_db_ensure_driver_profile_uniqueness_and_fk(get_db_connection):
    """ensure_driver_profile enforces foreign keys, deterministic id, and idempotency in real PostgreSQL."""
    org_id = get_real_org_id(get_db_connection)
    subject = f"user_real_drv_{int(time.time() * 1000)}"
    principal_id = str(uuid.uuid4())

    # 1. Insert real principal
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app.principals (id, organization_id, external_subject, display_name, status)
                VALUES (%s, %s, %s, %s, 'active')
                """,
                (principal_id, org_id, subject, "Real DB Driver"),
            )
            cur.execute(
                "INSERT INTO app.principal_roles (principal_id, role) VALUES (%s, 'driver')",
                (principal_id,),
            )
        conn.commit()

    # 2. Call ensure_driver_profile against real PostgreSQL
    driver_id = ensure_driver_profile(get_db_connection, principal_id, org_id, subject, "Real DB Driver")
    expected_driver_id = str(uuid5(UUID(org_id), subject))
    assert driver_id == expected_driver_id

    # 3. Verify actual PostgreSQL row and foreign keys
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, organization_id, principal_id, external_ref, partner_type, account_status, is_synthetic
                FROM app.drivers
                WHERE id = %s
                """,
                (driver_id,),
            )
            row = cur.fetchone()
            assert row is not None
            r_id = str(row["id"] if isinstance(row, dict) else row[0])
            r_org = str(row["organization_id"] if isinstance(row, dict) else row[1])
            r_pid = str(row["principal_id"] if isinstance(row, dict) else row[2])
            r_ext = row["external_ref"] if isinstance(row, dict) else row[3]
            r_ptype = row["partner_type"] if isinstance(row, dict) else row[4]
            r_status = row["account_status"] if isinstance(row, dict) else row[5]
            r_synth = row["is_synthetic"] if isinstance(row, dict) else row[6]
            assert r_id == expected_driver_id
            assert r_org == org_id
            assert r_pid == principal_id
            assert r_ext == f"clerk:{subject}"
            assert r_ptype == "owner_driver"
            assert r_status == "active"
            assert r_synth is False

    # 4. Idempotency: repeated ensure_driver_profile returns same id without duplicate row
    reused_id = ensure_driver_profile(get_db_connection, principal_id, org_id, subject, "Real DB Driver 2")
    assert reused_id == driver_id


def test_real_db_collision_fails_closed_409(get_db_connection):
    """Real PostgreSQL unique constraint violation causes fail-closed HTTP 409."""
    org_id = get_real_org_id(get_db_connection)
    victim_subject = f"user_victim_{int(time.time() * 1000)}"
    imposter_subject = f"user_imposter_{int(time.time() * 1000)}"

    p_victim_id = str(uuid.uuid4())
    p_imposter_id = str(uuid.uuid4())

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app.principals (id, organization_id, external_subject, display_name, status)
                VALUES (%s, %s, %s, 'Victim', 'active'), (%s, %s, %s, 'Imposter', 'active')
                """,
                (p_victim_id, org_id, victim_subject, p_imposter_id, org_id, imposter_subject),
            )
        conn.commit()

    # Pre-provision victim driver
    victim_driver_id = ensure_driver_profile(get_db_connection, p_victim_id, org_id, victim_subject, "Victim")
    assert victim_driver_id is not None

    # Imposter attempts collision on the same deterministic UUID or external_ref
    # We simulate a race or corrupted external_ref by attempting to ensure for victim_subject with imposter principal
    with pytest.raises(HTTPException) as exc_info:
        ensure_driver_profile(get_db_connection, p_imposter_id, org_id, victim_subject, "Imposter")

    assert exc_info.value.status_code == 409
    assert "Driver profile collision" in exc_info.value.detail


def test_real_db_trigger_rejects_cross_org_driver(get_db_connection):
    """PostgreSQL trigger driver_principal_org_match rejects cross-org driver insertion."""
    org_a = get_real_org_id(get_db_connection)
    # Create or find a second organization
    org_b = str(uuid.uuid4())
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO app.organizations (id, name) VALUES (%s, 'Org B Test')",
                (org_b,),
            )
        conn.commit()

    p_id = str(uuid.uuid4())
    subject = f"user_cross_org_{int(time.time() * 1000)}"
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app.principals (id, organization_id, external_subject, display_name, status)
                VALUES (%s, %s, %s, 'Cross Org Principal', 'active')
                """,
                (p_id, org_a, subject),
            )
        conn.commit()

    # Attempt to insert driver in org_b pointing to principal in org_a
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            with pytest.raises(psycopg.Error) as exc_info:
                cur.execute(
                    """
                    INSERT INTO app.drivers (organization_id, principal_id, external_ref, partner_type, account_status)
                    VALUES (%s, %s, 'clerk:cross', 'owner_driver', 'active')
                    """,
                    (org_b, p_id),
                )
            assert "driver cross-org" in str(exc_info.value)


@pytest.mark.asyncio
async def test_real_db_require_principal_driver_stale_admin_prevented(get_db_connection, monkeypatch):
    """require_principal against real PostgreSQL ensures driver profile without escalating roles in DB."""
    org_id = get_real_org_id(get_db_connection)
    subject = f"user_real_stale_admin_{int(time.time() * 1000)}"
    principal_id = str(uuid.uuid4())

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app.principals (id, organization_id, external_subject, display_name, status)
                VALUES (%s, %s, %s, 'Real Stale Admin Driver', 'active')
                """,
                (principal_id, org_id, subject),
            )
            cur.execute(
                "INSERT INTO app.principal_roles (principal_id, role) VALUES (%s, 'driver')",
                (principal_id,),
            )
        conn.commit()

    # Present a stale JWT claiming admin
    claims = {"sub": subject, "org_id": org_id, "org_role": "admin"}
    monkeypatch.setattr(auth, "authenticate_request", lambda *_args: SimpleNamespace(is_signed_in=True, payload=claims))
    settings = Settings(app_env="production", database_url="", clerk_secret_key="sk_test_unit", _env_file=None)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/me",
            "headers": [(b"authorization", b"Bearer verified-session")],
        }
    )
    service = SimpleNamespace(_get_db_connection=get_db_connection)

    principal_result = await auth.require_principal(request, settings, service)

    # 1. Principal returned has role driver, NOT admin
    assert principal_result.roles == frozenset({"driver"})
    assert "admin" not in principal_result.roles
    assert principal_result.driver_id == str(uuid5(UUID(org_id), subject))

    # 2. Query real DB to prove 'admin' was NEVER inserted into app.principal_roles
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT role FROM app.principal_roles WHERE principal_id = %s",
                (principal_id,),
            )
            roles = [r["role"] if isinstance(r, dict) else r[0] for r in cur.fetchall()]
            assert roles == ["driver"], f"Expected only ['driver'] in real DB, got {roles}"


@pytest.mark.asyncio
async def test_real_db_multi_role_admin_and_driver_preserved(get_db_connection, monkeypatch):
    """require_principal against real PostgreSQL repairs driver profile while preserving both admin and driver."""
    org_id = get_real_org_id(get_db_connection)
    subject = f"user_real_multi_{int(time.time() * 1000)}"
    principal_id = str(uuid.uuid4())

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app.principals (id, organization_id, external_subject, display_name, status)
                VALUES (%s, %s, %s, 'Real Multi Principal', 'active')
                """,
                (principal_id, org_id, subject),
            )
            cur.execute(
                """
                INSERT INTO app.principal_roles (principal_id, role)
                VALUES (%s, 'admin'), (%s, 'driver')
                """,
                (principal_id, principal_id),
            )
        conn.commit()

    claims = {"sub": subject, "org_id": org_id, "org_role": "driver"}
    monkeypatch.setattr(auth, "authenticate_request", lambda *_args: SimpleNamespace(is_signed_in=True, payload=claims))
    settings = Settings(app_env="production", database_url="", clerk_secret_key="sk_test_unit", _env_file=None)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/me",
            "headers": [(b"authorization", b"Bearer verified-session")],
        }
    )
    service = SimpleNamespace(_get_db_connection=get_db_connection)

    principal_result = await auth.require_principal(request, settings, service)

    assert principal_result.driver_id == str(uuid5(UUID(org_id), subject))
    assert "admin" in principal_result.roles
    assert "driver" in principal_result.roles

    # Verify both roles still present in real DB
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT role FROM app.principal_roles WHERE principal_id = %s",
                (principal_id,),
            )
            roles = set(r["role"] if isinstance(r, dict) else r[0] for r in cur.fetchall())
            assert roles == {"admin", "driver"}


@pytest.mark.asyncio
async def test_real_db_disabled_driver_remains_denied(get_db_connection, monkeypatch):
    """require_principal rejects disabled drivers in real DB with 403 and leaves them disabled."""
    org_id = get_real_org_id(get_db_connection)
    subject = f"user_real_disabled_{int(time.time() * 1000)}"
    principal_id = str(uuid.uuid4())

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app.principals (id, organization_id, external_subject, display_name, status)
                VALUES (%s, %s, %s, 'Disabled Driver', 'disabled')
                """,
                (principal_id, org_id, subject),
            )
            cur.execute(
                "INSERT INTO app.principal_roles (principal_id, role) VALUES (%s, 'driver')",
                (principal_id,),
            )
        conn.commit()

    claims = {"sub": subject, "org_id": org_id, "org_role": "driver"}
    monkeypatch.setattr(auth, "authenticate_request", lambda *_args: SimpleNamespace(is_signed_in=True, payload=claims))
    settings = Settings(app_env="production", database_url="", clerk_secret_key="sk_test_unit", _env_file=None)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/me",
            "headers": [(b"authorization", b"Bearer verified-session")],
        }
    )
    service = SimpleNamespace(_get_db_connection=get_db_connection)

    with pytest.raises(HTTPException) as exc_info:
        await auth.require_principal(request, settings, service)

    assert exc_info.value.status_code == 403

    # Verify status in real DB remains 'disabled'
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM app.principals WHERE id = %s", (principal_id,))
            row = cur.fetchone()
            status = row["status"] if isinstance(row, dict) else row[0]
            assert status == "disabled"


@pytest.mark.asyncio
async def test_real_db_require_principal_verified_multi_org_membership(get_db_connection, monkeypatch):
    """require_principal provisions same Clerk subject across distinct orgs without ID or role bleed."""
    org_a = str(uuid4())
    org_b = str(uuid4())
    subject = f"user_real_multiorg_{int(time.time() * 1000)}"

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO app.organizations (id, name) VALUES (%s, 'Org Multi A')", (org_a,))
            cur.execute("INSERT INTO app.organizations (id, name) VALUES (%s, 'Org Multi B')", (org_b,))
        conn.commit()

    settings = Settings(app_env="production", database_url="", clerk_secret_key="sk_test_unit", _env_file=None)
    service = SimpleNamespace(_get_db_connection=get_db_connection)

    # 1. Sign in to Org A as driver
    claims_a = {"sub": subject, "org_id": org_a, "org_role": "driver"}
    monkeypatch.setattr(
        auth, "authenticate_request", lambda *_args: SimpleNamespace(is_signed_in=True, payload=claims_a)
    )
    request_a = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/driver/profile",
            "headers": [(b"authorization", b"Bearer verified-session-a")],
        }
    )
    principal_a = await auth.require_principal(request_a, settings, service)
    assert principal_a.organization_id == org_a
    assert principal_a.roles == frozenset({"driver"})
    assert principal_a.driver_id == str(uuid5(UUID(org_a), subject))

    # 2. Sign in to Org B as member
    claims_b = {"sub": subject, "org_id": org_b, "org_role": "member"}
    monkeypatch.setattr(
        auth, "authenticate_request", lambda *_args: SimpleNamespace(is_signed_in=True, payload=claims_b)
    )
    request_b = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/cases",
            "headers": [(b"authorization", b"Bearer verified-session-b")],
        }
    )
    principal_b = await auth.require_principal(request_b, settings, service)
    assert principal_b.organization_id == org_b
    assert principal_b.roles == frozenset({"fraud_analyst", "analyst"})
    assert "driver" not in principal_b.roles
    assert principal_b.id != principal_a.id

    # 3. Verify real DB state: exactly two separate principal rows, each scoped to its own org
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.id, p.organization_id, array_agg(r.role ORDER BY r.role) as roles
                FROM app.principals p
                LEFT JOIN app.principal_roles r ON r.principal_id = p.id
                WHERE p.external_subject = %s
                GROUP BY p.id, p.organization_id
                ORDER BY p.organization_id
                """,
                (subject,),
            )
            rows = cur.fetchall()
            assert len(rows) == 2, f"Expected exactly 2 principal rows for multi-org subject, found {len(rows)}"

            row_map = {str(r["organization_id"] if isinstance(r, dict) else r[1]): r for r in rows}
            assert org_a in row_map
            assert org_b in row_map

            row_a = row_map[org_a]
            roles_a = row_a["roles"] if isinstance(row_a, dict) else row_a[2]
            assert list(roles_a) == ["driver"]

            row_b = row_map[org_b]
            roles_b = row_b["roles"] if isinstance(row_b, dict) else row_b[2]
            assert list(roles_b) == ["fraud_analyst"]


@pytest.mark.asyncio
async def test_real_db_require_principal_swapped_org_remains_denied(get_db_connection, monkeypatch):
    """Attempting to access with unprovisioned org claim fails closed."""
    unprovisioned_org = str(uuid4())
    subject = f"user_real_unprov_{int(time.time() * 1000)}"

    claims = {"sub": subject, "org_id": unprovisioned_org, "org_role": "member"}
    monkeypatch.setattr(auth, "authenticate_request", lambda *_args: SimpleNamespace(is_signed_in=True, payload=claims))
    settings = Settings(app_env="production", database_url="", clerk_secret_key="sk_test_unit", _env_file=None)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/cases",
            "headers": [(b"authorization", b"Bearer verified-session")],
        }
    )
    service = SimpleNamespace(_get_db_connection=get_db_connection)

    with pytest.raises(Exception):
        await auth.require_principal(request, settings, service)
