"""Integration-suite fixtures.

Includes shared disposable-PostgreSQL-database fixtures for real-DB
integration tests. Extracted from
tests/integration/services/test_driver_profile_sql_integration.py
(Issue #479/#480 PR review) so every suite that needs a throwaway database
with the full migration chain applied reuses one helper instead of
duplicating it.

Use the disposable *database* fixtures (not a disposable *schema*) whenever
the code under test issues its own `SET search_path = app, ...` (e.g.
src/services/driver_service.py), since a schema-only fixture cannot redirect
a hardcoded `app` search path.
"""

from __future__ import annotations

import os
import time
from urllib.parse import urlparse

import psycopg
import pytest
from psycopg import sql

from scripts.migrate_postgres import apply_migrations, get_target_connection

_HEURISTIC_WORKER_MODULES = {"test_queue_worker", "test_telemetry_routes_traffic"}


@pytest.fixture(autouse=True)
def _heuristic_assessment_for_worker_tests(request, monkeypatch):
    """Worker integration tests assert heuristic Jev categories, not R3D classifier output."""
    if request.module.__name__.rsplit(".", 1)[-1] not in _HEURISTIC_WORKER_MODULES:
        return
    from src.services.case_service import get_case_service

    monkeypatch.setattr(get_case_service().settings, "fraud_classifier_enabled", False)


@pytest.fixture(autouse=True)
def configure_integration_test_auth(monkeypatch):
    """Ensure integration tests run with APP_ENV=test and test_auth_enabled=true even when .env is sourced."""
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("TEST_AUTH_ENABLED", "true")
    from src.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def get_base_dsn() -> str:
    return (
        os.environ.get("TARGET_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("MIGRATION_DATABASE_URL")
        or "postgresql://postgres:postgrespassword@127.0.0.1:5432/postgres"
    )


def assert_loopback_target(dsn: str) -> None:
    parsed = urlparse(dsn)
    host = (parsed.hostname or "127.0.0.1").lower()
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise RuntimeError(
            f"Safety guard: refusing to run disposable-database integration test against non-loopback host '{host}'"
        )


def is_postgres_available() -> bool:
    try:
        base_dsn = get_base_dsn()
        assert_loopback_target(base_dsn)
        with psycopg.connect(base_dsn, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                return bool(cur.fetchone())
    except Exception:
        return False


@pytest.fixture(scope="module")
def disposable_database_dsn():
    """Disposable database (full migration chain applied), dropped at teardown.

    Unlike a disposable *schema*, this gives the real `app` schema name inside
    a throwaway database, so code that hardcodes `SET search_path = app, ...`
    (src/services/driver_service.py) is naturally isolated: the database
    itself is disposable, never the shared dev/app database.
    """
    base_dsn = get_base_dsn()
    assert_loopback_target(base_dsn)

    stamp = int(time.time() * 1000)
    dbname = f"test_p063_disposable_{stamp}"

    parsed = urlparse(base_dsn)
    user = parsed.username or "postgres"
    password = parsed.password or "postgrespassword"
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 5432
    admin_dsn = f"postgresql://{user}:{password}@{host}:{port}/postgres"
    target_dsn = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"

    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {};").format(sql.Identifier(dbname)))

    mig_conn = get_target_connection(target_dsn)
    try:
        apply_migrations(mig_conn, target_url=target_dsn)
    finally:
        mig_conn.close()

    yield target_dsn

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


class DsnCaseService:
    """Minimal CaseService stand-in: a fresh connection per call, like the real one."""

    def __init__(self, dsn: str):
        self._dsn = dsn

    def _get_db_connection(self):
        return psycopg.connect(self._dsn, row_factory=psycopg.rows.dict_row)

    def _require_test_fallback(self):
        raise AssertionError("SQL path test must not hit the in-memory fallback")


@pytest.fixture
def disposable_case_service(disposable_database_dsn):
    return DsnCaseService(disposable_database_dsn)
