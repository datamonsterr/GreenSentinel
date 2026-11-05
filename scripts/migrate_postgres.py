#!/usr/bin/env python3
"""
PostgreSQL Schema & Data Migration Script.

Connects to target PostgreSQL (local container or Railway), applies all schema migrations
from db/migrations/ in sorted order, loads and seeds data from data/synthetic/seed_data.json,
applies enrichments, and verifies table counts and spatial integrity.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv
from psycopg import sql

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migration")

ROOT_DIR = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = ROOT_DIR / "db" / "migrations"
SEED_FILE = ROOT_DIR / "data" / "synthetic" / "seed_data.json"


def get_target_connection(target_url: str | None = None) -> psycopg.Connection:
    load_dotenv()
    url = (
        target_url
        or os.environ.get("TARGET_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("MIGRATION_DATABASE_URL")
        or "postgresql://postgres:postgrespassword@localhost:5432/postgres"
    )
    safe_host = url.split("@")[-1] if "@" in url else url
    logger.info("Connecting to target database: %s", safe_host)

    last_error: Exception | None = None
    for attempt in range(1, 16):
        try:
            conn = psycopg.connect(url, autocommit=True)
            return conn
        except Exception as e:
            last_error = e
            logger.warning("Connection attempt %s/15 failed (%s), retrying in 2s...", attempt, e)
            time.sleep(2)

    logger.error("Failed to connect to %s after 15 attempts: %s", safe_host, last_error)
    if last_error:
        raise last_error
    raise RuntimeError(f"Unable to connect to {safe_host}")


def _is_remote_or_production(target_url: str | None = None) -> bool:
    url = (
        target_url
        or os.environ.get("TARGET_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("MIGRATION_DATABASE_URL")
        or ""
    ).lower()
    app_env = os.environ.get("APP_ENV", "").lower()
    if app_env in ("production", "staging", "prod"):
        return True
    remote_indicators = ("railway.app", "rlwy.net", "prod", "staging", "supabase", "aws", "gcp")
    return any(ind in url for ind in remote_indicators)


def _is_fixture_seed_authorized(args: argparse.Namespace) -> bool:
    return bool(
        getattr(args, "allow_remote_seed", False)
        or os.environ.get("ALLOW_FIXTURE_SEED", "").lower() in ("1", "true", "yes")
    )


def ensure_extensions_postgis(conn: psycopg.Connection, target_url: str | None = None) -> None:
    """Ensure PostGIS extension exists in 'extensions' or 'public' schema and configure session search_path.

    Fails closed if PostGIS is installed in an unapproved schema or missing on remote/shared targets.
    Does not commit or mutate database-wide catalog settings.
    """
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS extensions;")
        cur.execute("CREATE SCHEMA IF NOT EXISTS app;")
        cur.execute(
            "SELECT n.nspname FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace WHERE t.typname = 'geography';"
        )
        row = cur.fetchone()
        if row:
            actual_schema = row[0]
            if actual_schema == "extensions":
                cur.execute("SET search_path = app, extensions, public;")
                logger.info("Configured session search_path: app, extensions, public (PostGIS in extensions)")
                return
            elif actual_schema == "public":
                cur.execute("SET search_path = app, public, extensions;")
                logger.info("Configured session search_path: app, public, extensions (PostGIS in public)")
                return
            else:
                raise RuntimeError(
                    f"PostGIS extension schema mismatch: geography type is in schema '{actual_schema}', "
                    f"expected 'extensions' or 'public'. Prohibited unexpected schema; fail-closed."
                )

        if _is_remote_or_production(target_url):
            raise RuntimeError(
                "PostGIS extension is not installed in 'extensions' or 'public' schema on live host; "
                "automatic extension installation/dropping on live hosts is prohibited."
            )

        logger.info("Configuring PostGIS extension inside 'extensions' schema...")
        cur.execute("CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA extensions;")
        cur.execute("SET search_path = app, extensions, public;")


def apply_migrations(
    conn: psycopg.Connection, migrations_dir: Path = MIGRATIONS_DIR, target_url: str | None = None
) -> None:
    """Apply all .sql migration files in lexicographical order with idempotency tracking."""
    ensure_extensions_postgis(conn, target_url=target_url)
    if not migrations_dir.exists():
        logger.warning("Migrations directory not found: %s", migrations_dir)
        return

    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public.schema_migrations (
                version text PRIMARY KEY,
                applied_at timestamptz DEFAULT clock_timestamp()
            );
            """
        )
    conn.commit()

    sql_files = sorted(migrations_dir.glob("*.sql"))
    logger.info("Found %d migration files in %s", len(sql_files), migrations_dir)

    for sql_file in sql_files:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM public.schema_migrations WHERE version = %s;", (sql_file.name,))
            if cur.fetchone():
                logger.info("Skipping already applied migration: %s", sql_file.name)
                continue

        logger.info("Applying migration: %s", sql_file.name)
        content = sql_file.read_text(encoding="utf-8")
        try:
            with conn.cursor() as cur:
                cur.execute(content)
                cur.execute(
                    "INSERT INTO public.schema_migrations (version) VALUES (%s) ON CONFLICT DO NOTHING;",
                    (sql_file.name,),
                )
            conn.commit()
            logger.info("Successfully applied %s", sql_file.name)
        except Exception as exc:
            conn.rollback()
            err_msg = str(exc).lower()
            if "already exists" in err_msg or "duplicate" in err_msg:
                logger.warning("Migration %s already partially or fully applied: %s", sql_file.name, exc)
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO public.schema_migrations (version) VALUES (%s) ON CONFLICT DO NOTHING;",
                        (sql_file.name,),
                    )
                conn.commit()
            else:
                logger.error("Error executing migration %s: %s", sql_file.name, exc)
                raise


def seed_database_from_json(conn: psycopg.Connection, seed_path: Path = SEED_FILE) -> None:
    """Populate database from seed_data.json using seed_database module or direct SQL."""
    manifest: dict[str, Any] = {}
    if seed_path.exists():
        manifest = json.loads(seed_path.read_text(encoding="utf-8")).get("manifest", {})
    versioned_dataset = bool(manifest.get("dataset_version"))
    with conn.cursor() as cur:
        try:
            cur.execute("SELECT count(*) FROM app.passengers;")
            count = cur.fetchone()[0]
            if count > 0 and not versioned_dataset:
                logger.info("Database is already seeded (%d passengers found). Skipping seed import.", count)
                return
        except Exception:
            pass

    if not seed_path.exists():
        logger.warning("Seed data file not found: %s. Generating synthetic seed dataset...", seed_path)
        seed_path.parent.mkdir(parents=True, exist_ok=True)
        import subprocess

        gen_script = ROOT_DIR / "scripts" / "generate_synthetic_data.py"
        if gen_script.exists():
            subprocess.run([sys.executable, str(gen_script)], check=True, cwd=str(ROOT_DIR))
            logger.info("Generated synthetic seed dataset at %s", seed_path)
        else:
            logger.warning("Dataset generator %s not found. Skipping JSON seed.", gen_script)
            return

    logger.info("Seeding data from %s", seed_path)
    # Import and run seed logic
    sys.path.insert(0, str(ROOT_DIR))
    from scripts.seed_database import import_data

    import_data(seed_path, conn=conn)
    logger.info("Completed JSON seed import.")


def _apply_cockpit_evidence(target_url: str | None = None) -> None:
    """Cockpit evidence is idempotent, so it is applied even when full enrichment is skipped."""
    sys.path.insert(0, str(ROOT_DIR))
    try:
        from scripts.enrich_demo_data import enrich_cockpit_evidence_only

        url = (
            target_url
            or os.environ.get("TARGET_DATABASE_URL")
            or os.environ.get("DATABASE_URL")
            or os.environ.get("MIGRATION_DATABASE_URL")
        )
        if url:
            stats = enrich_cockpit_evidence_only(url)
            logger.info("Cockpit evidence applied: %s", stats)
    except Exception as e:
        logger.warning("Cockpit evidence seeding encountered non-fatal error: %s", e)


def run_enrichment_data(target_url: str | None = None, conn: psycopg.Connection | None = None) -> None:
    """Run data enrichment if available and not already enriched."""
    if conn:
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT count(*) FROM app.telemetry_points;")
                count = cur.fetchone()[0]
                if count >= 1400:
                    logger.info(
                        "Database already enriched (%d telemetry points found). Skipping full enrichment.", count
                    )
                    _apply_cockpit_evidence(target_url)
                    return
            except Exception:
                pass

    enrich_script = ROOT_DIR / "scripts" / "enrich_demo_data.py"
    if enrich_script.exists():
        logger.info("Running enrichment script...")
        sys.path.insert(0, str(ROOT_DIR))
        try:
            from scripts.enrich_demo_data import enrich

            url = (
                target_url
                or os.environ.get("TARGET_DATABASE_URL")
                or os.environ.get("DATABASE_URL")
                or os.environ.get("MIGRATION_DATABASE_URL")
                or "postgresql://postgres:postgrespassword@localhost:5432/postgres"
            )
            enrich(url)
            logger.info("Enrichment completed.")
        except Exception as e:
            logger.warning("Enrichment encountered non-fatal error: %s", e)


def run_preview_enrichment_data(target_url: str | None = None, conn: psycopg.Connection | None = None) -> None:
    """Run deterministic preview seed enrichment for analyst workspace evidence (#366)."""
    preview_script = ROOT_DIR / "scripts" / "seed_preview_enrichment.py"
    if preview_script.exists():
        logger.info("Running preview seed enrichment for analyst workspace evidence...")
        sys.path.insert(0, str(ROOT_DIR))
        try:
            from scripts.seed_preview_enrichment import enrich_preview_cases

            url = (
                target_url
                or os.environ.get("TARGET_DATABASE_URL")
                or os.environ.get("DATABASE_URL")
                or os.environ.get("MIGRATION_DATABASE_URL")
                or "postgresql://postgres:postgrespassword@localhost:5432/postgres"
            )
            enrich_preview_cases(database_url=url, dry_run=False)
            logger.info("Preview seed enrichment completed.")
        except Exception as e:
            logger.warning("Preview seed enrichment encountered non-fatal error: %s", e)


def verify_database(conn: psycopg.Connection, target_url: str | None = None) -> dict[str, Any]:
    """Verify table counts and spatial integrity."""
    logger.info("Verifying database schema and counts...")
    stats: dict[str, Any] = {}
    active_conn = conn
    if active_conn.closed:
        active_conn = get_target_connection(target_url)

    try:
        with active_conn.cursor() as cur:
            # Check app schema tables
            cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'app';")
            stats["app_tables_count"] = cur.fetchone()[0]

            # Key counts
            tables_to_check = [
                ("organizations", "app.organizations"),
                ("principals", "app.principals"),
                ("principal_roles", "app.principal_roles"),
                ("passengers", "app.passengers"),
                ("drivers", "app.drivers"),
                ("vehicles", "app.vehicles"),
                ("trips", "app.trips"),
                ("fraud_cases", "app.fraud_cases"),
                ("telemetry_points", "app.telemetry_points"),
            ]
            for key, table in tables_to_check:
                try:
                    schema, tbl = table.split(".")
                    query = sql.SQL("SELECT count(*) FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(tbl))
                    cur.execute(query)
                    stats[key] = cur.fetchone()[0]
                except Exception as e:
                    stats[key] = f"error: {e}"

            # Spatial check
            try:
                cur.execute("""
                    SELECT ST_AsText(pickup), ST_AsText(dropoff)
                    FROM app.trips
                    WHERE pickup IS NOT NULL AND dropoff IS NOT NULL
                    LIMIT 1;
                """)
                row = cur.fetchone()
                stats["spatial_valid"] = bool(row and row[0].startswith("POINT(") and row[1].startswith("POINT("))
            except Exception as e:
                stats["spatial_valid"] = f"error: {e}"

        logger.info("Database verification results: %s", json.dumps(stats, indent=2))
        return stats
    except Exception as e:
        logger.warning("Verification failed on current connection (%s), retrying with fresh connection...", e)
        fresh_conn = get_target_connection(target_url)
        try:
            with fresh_conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'app';")
                stats["app_tables_count"] = cur.fetchone()[0]
            logger.info("Database re-verification succeeded on fresh connection.")
            return stats
        finally:
            fresh_conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply db/migrations schema to PostgreSQL (defaults to schema-only)")
    parser.add_argument(
        "--target-url", "--database-url", type=str, dest="target_url", help="Target PostgreSQL connection URL"
    )
    parser.add_argument("--skip-migrations", action="store_true", help="Skip running schema migrations")
    parser.add_argument("--skip-seed", action="store_true", help="Deprecated: migrations default to schema-only")
    parser.add_argument(
        "--seed",
        "--with-seed",
        "--seed-fixtures",
        action="store_true",
        dest="seed",
        help="Explicitly opt-in to populating fixture seed data (refused on shared/production)",
    )
    parser.add_argument(
        "--allow-remote-seed",
        action="store_true",
        dest="allow_remote_seed",
        help="Explicitly authorize fixture seeding on remote/shared/production databases",
    )
    parser.add_argument("--verify-only", action="store_true", help="Only run verification")
    args = parser.parse_args()

    # Fixture seeding is strictly opt-in and refuses shared/prod unless scoped authorized config is present
    if args.seed and not args.skip_seed:
        if _is_remote_or_production(args.target_url) and not _is_fixture_seed_authorized(args):
            raise RuntimeError(
                "Refusing to seed fixtures to shared/production database without scoped authorized config "
                "(--allow-remote-seed or ALLOW_FIXTURE_SEED=true)."
            )

    conn = get_target_connection(args.target_url)

    if args.verify_only:
        verify_database(conn, args.target_url)
        conn.close()
        return

    if not args.skip_migrations:
        apply_migrations(conn, target_url=args.target_url)

    if args.seed and not args.skip_seed:
        seed_database_from_json(conn)
        run_enrichment_data(args.target_url, conn=conn)
        run_preview_enrichment_data(args.target_url, conn=conn)

    verify_database(conn, args.target_url)
    conn.close()
    logger.info("Migration finished successfully.")


if __name__ == "__main__":
    main()
