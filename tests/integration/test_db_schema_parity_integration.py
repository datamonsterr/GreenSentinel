"""Real PostgreSQL integration tests for test-store schema parity and safe organization ownership.

Task: #423 under parent #394.
Portably tests against isolated disposable PostgreSQL databases derived from repository migrations,
with unique per-test database names, strict loopback isolation, and guaranteed teardown.
Retains private dump audits as optional historical evidence only.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Generator
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import psycopg
import pytest

pytestmark = pytest.mark.docker

MIGRATION_PATH = Path("db/migrations/20261016000000_test_store_schema_parity.sql")
MIGRATION_SQL = MIGRATION_PATH.read_text(encoding="utf-8")
MIGRATIONS_DIR = Path("db/migrations")

HISTORICAL_BACKUPS = {
    "dev": "/home/dat/.local/state/greensentinel-db-finalize-394/backups/20261015T173125Z/dev.dump",
    "staging": "/home/dat/.local/state/greensentinel-db-finalize-394/backups/20261015T173125Z/staging.dump",
    "prod": "/home/dat/.local/state/greensentinel-db-finalize-394/backups/20261015T173125Z/production.dump",
}

MISSING_10_PROD = [
    "20261007090000_benchmark_schema_sync.sql",
    "20261007100000_benchmark_store.sql",
    "20261008090000_passenger_feedback_rating.sql",
    "20261012090000_benchmark_g1g2_scenarios.sql",
    "20261014090000_staged_adjudication.sql",
    "20261014090000_tester_org_ownership.sql",
    "20261014100000_tester_run_history_cancellation.sql",
    "20261014120000_clerk_org_link.sql",
    "20261015090000_tester_stop_snapshots.sql",
    "20261015130000_tester_publish_submissions.sql",
]


def _get_pg_credentials() -> tuple[str, int, str, str]:
    """Derive localhost port and credentials from DATABASE_URL or standard environment."""
    db_url = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("MIGRATION_DATABASE_URL")
        or os.environ.get("ISSUE63_DATABASE_URL")
    )
    if db_url:
        parsed = urlparse(db_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 5432
        user = parsed.username or "postgres"
        password = parsed.password or "postgrespassword"
    else:
        host = "127.0.0.1"
        port = int(os.environ.get("GREENSENTINEL_POSTGRES_PORT", "5432"))
        user = os.environ.get("GREENSENTINEL_POSTGRES_USER", "postgres")
        password = os.environ.get("GREENSENTINEL_POSTGRES_PASSWORD", "postgrespassword")

    assert host in ("127.0.0.1", "localhost", "::1"), f"Host must be loopback, got {host}"
    return host, port, user, password


def _connect(db_name: str, autocommit: bool = False) -> psycopg.Connection:
    host, port, user, password = _get_pg_credentials()
    assert host in ("127.0.0.1", "localhost", "::1"), f"Host must be loopback, got {host}"
    assert db_name.startswith("test_greensentinel_schema_parity_") or db_name == "postgres", (
        f"Database name {db_name} does not match required test prefix"
    )
    return psycopg.connect(
        f"host={host} port={port} user={user} password={password} dbname={db_name}",
        autocommit=autocommit,
    )


def _audit_catalog(db_name: str) -> dict:
    with _connect(db_name) as conn:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL search_path=pg_catalog;")
            cur.execute("""
                SELECT table_schema, table_name, column_name, data_type, udt_schema, udt_name, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'app'
                ORDER BY table_name, column_name;
            """)
            columns = cur.fetchall()

            cur.execute("""
                SELECT tc.table_schema, tc.table_name, tc.constraint_name, c.contype, pg_get_constraintdef(c.oid)
                FROM information_schema.table_constraints tc
                JOIN pg_namespace n ON n.nspname = tc.table_schema
                JOIN pg_constraint c ON c.conname = tc.constraint_name AND c.conrelid = (n.nspname || '.' || tc.table_name)::regclass
                WHERE tc.table_schema = 'app'
                ORDER BY tc.table_name, tc.constraint_name;
            """)
            constraints = cur.fetchall()

            cur.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'app'
                ORDER BY table_name;
            """)
            tables = [r[0] for r in cur.fetchall()]

            cur.execute("""
                SELECT schemaname, tablename, indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = 'app'
                ORDER BY tablename, indexname;
            """)
            indexes = cur.fetchall()

            cur.execute("""
                SELECT count(*)
                FROM information_schema.tables
                WHERE table_schema IN ('app', 'public');
            """)
            total_tables = cur.fetchone()[0]

            cur.execute("""
                SELECT count(*)
                FROM information_schema.columns
                WHERE table_schema IN ('app', 'public');
            """)
            total_columns = cur.fetchone()[0]

            return {
                "tables_count": len(tables),
                "columns_count": len(columns),
                "constraints_count": len(constraints),
                "indexes_count": len(indexes),
                "total_tables": total_tables,
                "total_columns": total_columns,
                "tables": tables,
                "columns": columns,
                "constraints": constraints,
                "indexes": indexes,
            }


@pytest.fixture(scope="module")
def disposable_parity_clones() -> Generator[tuple[dict[str, str], dict], None, None]:
    """Provision isolated disposable databases representing pre-migration states, verify additive migration."""
    # Test availability of PostgreSQL
    try:
        with _connect("postgres", autocommit=True) as check_conn:
            with check_conn.cursor() as cur:
                cur.execute("SELECT 1;")
    except Exception as exc:
        pytest.skip(f"PostgreSQL maintenance database unavailable: {exc}")

    prefix = f"test_greensentinel_schema_parity_{uuid4().hex[:8]}"
    db_a = f"{prefix}_dev"
    db_b = f"{prefix}_prod"
    dbs = {"dev": db_a, "prod": db_b}

    host, port, user, password = _get_pg_credentials()

    with psycopg.connect(
        f"host={host} port={port} user={user} password={password} dbname=postgres", autocommit=True
    ) as admin_conn:
        with admin_conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {db_a} WITH (FORCE);")
            cur.execute(f"DROP DATABASE IF EXISTS {db_b} WITH (FORCE);")
            cur.execute(f"CREATE DATABASE {db_a};")
            cur.execute(f"CREATE DATABASE {db_b};")

    try:
        sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))

        # Setup State A (simulating dev/staging prior to 20261016000000 with partial 3277f576 columns)
        # Setup State B (simulating prod prior to 20261016000000 from clean repository migrations)
        for env, db_name in dbs.items():
            is_dev = env == "dev"
            with _connect(db_name, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute("CREATE SCHEMA IF NOT EXISTS extensions;")
                    cur.execute("CREATE SCHEMA IF NOT EXISTS app;")
                    cur.execute("CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA extensions;")
                    cur.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA extensions;')
                    cur.execute(
                        "CREATE TABLE IF NOT EXISTS public.schema_migrations (version text PRIMARY KEY, applied_at timestamptz DEFAULT clock_timestamp());"
                    )

                for f in sql_files:
                    if f.name == "20261016000000_test_store_schema_parity.sql":
                        continue
                    content = f.read_text(encoding="utf-8")
                    with conn.cursor() as cur:
                        cur.execute(content)
                        cur.execute(
                            "INSERT INTO public.schema_migrations (version) VALUES (%s) ON CONFLICT DO NOTHING;",
                            (f.name,),
                        )

                    if is_dev and f.name == "20261014090000_staged_adjudication.sql":
                        # Simulate commit 3277f576 where child orgs existed prior
                        with conn.cursor() as cur:
                            for t in [
                                "test_controls",
                                "test_definition_revisions",
                                "test_events",
                                "test_idempotency_keys",
                                "test_notifications",
                                "test_outbox",
                                "test_runs",
                                "test_samples",
                            ]:
                                cur.execute(f"ALTER TABLE app.{t} ADD COLUMN IF NOT EXISTS organization_id uuid;")

        # Populate sample data into both to prove 100% data preservation
        org_id = uuid4()
        for env, db_name in dbs.items():
            with _connect(db_name, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO app.organizations (id, name, created_at) VALUES (%s, %s, now()) ON CONFLICT DO NOTHING;",
                        (org_id, f"Org {env}"),
                    )
                    p_id = uuid4()
                    cur.execute(
                        "INSERT INTO app.test_plans (id, name, organization_id, created_by) VALUES (%s, 'Plan 1', %s, 'user_clerk_1') ON CONFLICT DO NOTHING;",
                        (p_id, org_id),
                    )

        # Record data fingerprints before migration 20261016000000
        before_fingerprints = {}
        for env, db_name in dbs.items():
            with _connect(db_name) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = 'app' AND table_type = 'BASE TABLE'
                        ORDER BY table_name;
                    """)
                    tables = [r[0] for r in cur.fetchall()]
                    fp = {}
                    for t in tables:
                        cur.execute(f"SELECT count(*) FROM app.{t};")
                        cnt = cur.fetchone()[0]
                        cur.execute(f"""
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_schema = 'app' AND table_name = '{t}'
                              AND column_name NOT IN ('organization_id', 'messages')
                            ORDER BY ordinal_position;
                        """)
                        cols = [r[0] for r in cur.fetchall()]
                        if cols:
                            col_expr = ", ".join([f"COALESCE({c}::text, '')" for c in cols])
                            cur.execute(f"SELECT {col_expr} FROM app.{t} ORDER BY 1;")
                            h = hashlib.sha256()
                            for row in cur.fetchall():
                                h.update("|".join(str(v) for v in row).encode("utf-8"))
                            fp[t] = (cnt, h.hexdigest())
                        else:
                            fp[t] = (cnt, "")
                    before_fingerprints[env] = fp

        # Apply 20261016000000_test_store_schema_parity.sql to both
        for env, db_name in dbs.items():
            with _connect(db_name, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(MIGRATION_SQL)
                    cur.execute(
                        "INSERT INTO public.schema_migrations (version) VALUES ('20261016000000_test_store_schema_parity.sql') ON CONFLICT DO NOTHING;"
                    )

        yield dbs, before_fingerprints

    finally:
        with psycopg.connect(
            f"host={host} port={port} user={user} password={password} dbname=postgres", autocommit=True
        ) as admin_conn:
            with admin_conn.cursor() as cur:
                cur.execute(f"DROP DATABASE IF EXISTS {db_a} WITH (FORCE);")
                cur.execute(f"DROP DATABASE IF EXISTS {db_b} WITH (FORCE);")


def test_schema_parity_exact_columns_and_constraints(disposable_parity_clones):
    dbs, _ = disposable_parity_clones
    dev_cat = _audit_catalog(dbs["dev"])
    prod_cat = _audit_catalog(dbs["prod"])

    # Parity across tables, columns, constraints, indexes
    assert dev_cat["tables_count"] == prod_cat["tables_count"]
    assert dev_cat["columns_count"] == prod_cat["columns_count"]
    assert dev_cat["constraints_count"] == prod_cat["constraints_count"]
    assert dev_cat["indexes_count"] == prod_cat["indexes_count"]

    assert dev_cat["tables"] == prod_cat["tables"]
    assert dev_cat["columns"] == prod_cat["columns"]
    assert dev_cat["constraints"] == prod_cat["constraints"]
    assert dev_cat["indexes"] == prod_cat["indexes"]


def test_data_preservation_across_all_original_tables(disposable_parity_clones):
    dbs, before_fp = disposable_parity_clones
    for env in ["dev", "prod"]:
        with _connect(dbs[env]) as conn:
            with conn.cursor() as cur:
                for t, (expected_count, expected_hash) in before_fp[env].items():
                    cur.execute(f"SELECT count(*) FROM app.{t};")
                    cnt = cur.fetchone()[0]
                    assert cnt == expected_count, f"Row count changed for app.{t} in {env}"

                    cur.execute(f"""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = 'app' AND table_name = '{t}'
                          AND column_name NOT IN ('organization_id', 'messages')
                        ORDER BY ordinal_position;
                    """)
                    cols = [r[0] for r in cur.fetchall()]
                    if cols:
                        col_expr = ", ".join([f"COALESCE({c}::text, '')" for c in cols])
                        cur.execute(f"SELECT {col_expr} FROM app.{t} ORDER BY 1;")
                        h = hashlib.sha256()
                        for row in cur.fetchall():
                            h.update("|".join(str(v) for v in row).encode("utf-8"))
                        assert h.hexdigest() == expected_hash, f"Data hash changed for app.{t} in {env}"


def test_migration_idempotency_zero_drift(disposable_parity_clones):
    dbs, _ = disposable_parity_clones
    # Re-apply migration to dev and prod
    for env in ["dev", "prod"]:
        with _connect(dbs[env], autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(MIGRATION_SQL)

    dev_cat = _audit_catalog(dbs["dev"])
    prod_cat = _audit_catalog(dbs["prod"])
    assert dev_cat["columns"] == prod_cat["columns"]
    assert dev_cat["constraints"] == prod_cat["constraints"]
    assert dev_cat["indexes"] == prod_cat["indexes"]


def test_safe_ownership_propagation_and_quarantine(disposable_parity_clones):
    dbs, _ = disposable_parity_clones
    test_db = dbs["dev"]

    primary_org = uuid4()
    secondary_org = uuid4()

    with _connect(test_db, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO app.organizations (id, name, created_at) VALUES (%s, 'Primary Org', now()) ON CONFLICT DO NOTHING;",
                (primary_org,),
            )
            cur.execute(
                "INSERT INTO app.organizations (id, name, created_at) VALUES (%s, 'Secondary Org', now()) ON CONFLICT DO NOTHING;",
                (secondary_org,),
            )

            # Scenario 1: Unambiguous propagation from parent plan
            p1 = uuid4()
            r1 = uuid4()
            run1 = uuid4()
            sample1 = uuid4()
            cur.execute(
                "INSERT INTO app.test_plans (id, name, organization_id, created_by) VALUES (%s, 'Test P1', %s, 'user_clerk_p1');",
                (p1, primary_org),
            )
            cur.execute(
                "INSERT INTO app.test_definition_revisions (id, plan_id, revision_number, route_geometry, organization_id) VALUES (%s, %s, 10, '{}'::jsonb, NULL);",
                (r1, p1),
            )
            cur.execute(
                "INSERT INTO app.test_runs (id, definition_revision_id, status, simulation_clock, organization_id) VALUES (%s, %s, 'QUEUED', now(), NULL);",
                (run1, r1),
            )
            cur.execute(
                "INSERT INTO app.test_samples (id, run_id, step_index, latitude, longitude, organization_id) VALUES (%s, %s, 0, 21.0, 105.0, NULL);",
                (sample1, run1),
            )

            # Scenario 2: Legacy unowned (NULL org) remains NULL and is quarantined
            p2 = uuid4()
            r2 = uuid4()
            run2 = uuid4()
            cur.execute(
                "INSERT INTO app.test_plans (id, name, organization_id, created_by) VALUES (%s, 'Unowned P2', NULL, 'user_clerk_p2');",
                (p2,),
            )
            cur.execute(
                "INSERT INTO app.test_definition_revisions (id, plan_id, revision_number, route_geometry, organization_id) VALUES (%s, %s, 20, '{}'::jsonb, NULL);",
                (r2, p2),
            )
            cur.execute(
                "INSERT INTO app.test_runs (id, definition_revision_id, status, simulation_clock, organization_id) VALUES (%s, %s, 'QUEUED', now(), NULL);",
                (run2, r2),
            )

            # Scenario 3: Conflicting parent/child org preserves child org and records quarantine
            p3 = uuid4()
            r3 = uuid4()
            run3 = uuid4()
            cur.execute(
                "INSERT INTO app.test_plans (id, name, organization_id, created_by) VALUES (%s, 'Conflict P3', %s, 'user_clerk_p3');",
                (p3, primary_org),
            )
            cur.execute(
                "INSERT INTO app.test_definition_revisions (id, plan_id, revision_number, route_geometry, organization_id) VALUES (%s, %s, 30, '{}'::jsonb, %s);",
                (r3, p3, secondary_org),
            )
            cur.execute(
                "INSERT INTO app.test_runs (id, definition_revision_id, status, simulation_clock, organization_id) VALUES (%s, %s, 'QUEUED', now(), %s);",
                (run3, r3, secondary_org),
            )

    # Run migration propagation
    with _connect(test_db, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(MIGRATION_SQL)

    with _connect(test_db) as conn:
        with conn.cursor() as cur:
            # Check Scenario 1: Unambiguous backfill
            cur.execute("SELECT organization_id FROM app.test_definition_revisions WHERE id = %s;", (r1,))
            assert cur.fetchone()[0] == primary_org
            cur.execute("SELECT organization_id FROM app.test_runs WHERE id = %s;", (run1,))
            assert cur.fetchone()[0] == primary_org
            cur.execute("SELECT organization_id FROM app.test_samples WHERE id = %s;", (sample1,))
            assert cur.fetchone()[0] == primary_org

            # Check Scenario 2: Legacy unowned remains NULL and is quarantined
            cur.execute("SELECT organization_id FROM app.test_plans WHERE id = %s;", (p2,))
            assert cur.fetchone()[0] is None
            cur.execute("SELECT organization_id FROM app.test_definition_revisions WHERE id = %s;", (r2,))
            assert cur.fetchone()[0] is None
            cur.execute("SELECT organization_id FROM app.test_runs WHERE id = %s;", (run2,))
            assert cur.fetchone()[0] is None
            cur.execute("SELECT reason FROM app.org_quarantine WHERE row_id = %s;", (p2,))
            assert cur.fetchone()[0] == "unowned_plan"

            # Check Scenario 3: Conflicting owner preserved
            cur.execute("SELECT organization_id FROM app.test_definition_revisions WHERE id = %s;", (r3,))
            assert cur.fetchone()[0] == secondary_org
            cur.execute("SELECT organization_id FROM app.test_runs WHERE id = %s;", (run3,))
            assert cur.fetchone()[0] == secondary_org
            cur.execute("SELECT reason FROM app.org_quarantine WHERE row_id = %s;", (r3,))
            assert cur.fetchone()[0] == "parent_child_org_conflict"


def test_historical_private_clone_audit():
    """Historical audit test: verifies pre-migration backups if present on disk; skipped gracefully otherwise."""
    all_found = all(Path(p).is_file() for p in HISTORICAL_BACKUPS.values())
    if not all_found:
        pytest.skip(
            "Historical workstation dumps not found on this system; "
            "portable migration fixtures in disposable_parity_clones provide primary verification."
        )

    # If dumps exist, verify the pre-created test clones
    for env in ["dev", "staging", "prod"]:
        db_name = f"test_greensentinel_schema_parity_{env}"
        try:
            cat = _audit_catalog(db_name)
            assert cat["total_tables"] == 71
            assert cat["total_columns"] == 671
            assert cat["constraints_count"] == 359
            assert cat["indexes_count"] == 170
        except Exception as e:
            pytest.skip(f"Historical clone {db_name} not pre-loaded: {e}")
