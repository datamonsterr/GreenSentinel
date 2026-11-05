#!/usr/bin/env python3
"""Bounded Workload Index Migration Runner.

Safely applies or rolls back the specific additive workload indexes in
db/migrations/20261015150000_workload_performance_indexes.sql without
dropping extensions, reseeding mocks, or disrupting active sessions.

Requires dry-run expected-plan-hash preflight and unconditional target validation.
NOTE: DO NOT APPLY TO SHARED DB DIRECTLY. Conductor executes reviewed apply.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Any

import psycopg

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.db_profile import (  # noqa: E402
    extract_safe_target_summary,
    resolve_connection_parameters,
)
from src.services.db_profiler import (  # noqa: E402
    DatabaseProfiler,
    redact_dsn_password,
    validate_disposable_database_url,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("apply_workload_indexes")

UP_MIGRATION_PATH = ROOT_DIR / "db" / "migrations" / "20261015150000_workload_performance_indexes.sql"
DOWN_MIGRATION_PATH = ROOT_DIR / "db" / "rollbacks" / "20261015150000_workload_performance_indexes.down.sql"


def get_relevant_catalog_state(conn: psycopg.Connection) -> dict[str, Any]:
    """Retrieve current catalog definitions for tables touched by the workload indexes."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT tablename, indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'app' AND tablename IN ('trip_assignments', 'fraud_cases')
            ORDER BY tablename, indexname;
            """
        )
        indexes = [{"table": r[0], "index": r[1], "def": r[2]} for r in cur.fetchall()]
        cur.execute(
            """
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'app' AND table_name IN ('trip_assignments', 'fraud_cases')
            ORDER BY table_name, column_name;
            """
        )
        columns = [{"table": r[0], "column": r[1], "type": r[2]} for r in cur.fetchall()]
        return {"indexes": indexes, "columns": columns}


def compute_plan_hash(
    action: str,
    migration_name: str,
    sql_content: str,
    env_identity: dict[str, str],
    catalog_state: dict[str, Any],
) -> str:
    """Compute canonical SHA256 plan fingerprint across migration bytes, target identity, and catalog."""
    hasher = hashlib.sha256()
    payload = {
        "action": action,
        "migration_name": migration_name,
        "sql_sha256": hashlib.sha256(sql_content.encode("utf-8")).hexdigest(),
        "env_identity": env_identity,
        "catalog_state": catalog_state,
    }
    hasher.update(json.dumps(payload, sort_keys=True).encode("utf-8"))
    return hasher.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="GreenSentinel Bounded Workload Index Migration Runner")
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument(
        "--env", choices=["dev", "staging", "production"], help="Allowed Railway target environment"
    )
    target_group.add_argument("--target-url", help="Direct Postgres connection URL (for local disposable test DB only)")

    parser.add_argument("--project", default="c49458fb-d741-468f-a3ed-d35b96788f68", help="Railway Project ID")
    parser.add_argument("--service", default="9710a2f5-ed77-472e-8e79-3b748bb73df2", help="Railway Postgres Service ID")
    parser.add_argument("--rollback", action="store_true", help="Apply rollback (.down.sql) instead of migration")
    parser.add_argument(
        "--confirm-apply", action="store_true", help="Explicit confirmation to execute DDL (default is dry-run)"
    )
    parser.add_argument(
        "--expected-plan-hash",
        help="Expected SHA256 plan hash required when running with --confirm-apply",
    )
    parser.add_argument("--lock-timeout-ms", type=int, default=5000, help="Lock timeout in ms (default 5000)")
    parser.add_argument(
        "--statement-timeout-ms", type=int, default=30000, help="Statement timeout in ms (default 30000)"
    )

    args = parser.parse_args()

    # Unconditionally validate direct target URLs BEFORE any connection or DDL attempt
    if args.target_url:
        validate_disposable_database_url(args.target_url)

    conn_params = resolve_connection_parameters(
        env=args.env, project_id=args.project, service_id=args.service, target_url=args.target_url
    )

    safe_target = extract_safe_target_summary(conn_params, args.env)
    logger.info(
        "Resolved target environment: env=%s, host=%s, db=%s",
        safe_target["target"],
        safe_target["host"],
        safe_target["database"],
    )

    migration_file = DOWN_MIGRATION_PATH if args.rollback else UP_MIGRATION_PATH
    if not migration_file.is_file():
        logger.error("Migration file not found: %s", migration_file)
        sys.exit(1)

    sql_content = migration_file.read_text(encoding="utf-8")
    action_name = "ROLLBACK" if args.rollback else "APPLY"

    logger.info("Selected %s migration script: %s", action_name, migration_file.name)

    try:
        conn = psycopg.connect(**conn_params, autocommit=False, connect_timeout=15)
    except Exception as exc:
        sanitized_err = redact_dsn_password(str(exc))
        logger.error("Database connection failed: %s", sanitized_err)
        sys.exit(1)

    profiler = DatabaseProfiler(conn=conn, timeout_ms=args.statement_timeout_ms)

    try:
        # 1. Read-only preflight schema verification
        preflight = profiler.preflight_schema_check(
            required_tables=["trip_assignments"],
            required_columns={
                "trip_assignments": ["id", "trip_id"],
            },
        )
        if not preflight["valid"]:
            logger.error("Preflight schema verification FAILED: %s", preflight)
            sys.exit(1)
        logger.info("Preflight schema verification PASSED.")

        # 2. Extract current catalog definition and compute expected plan hash
        catalog_state = get_relevant_catalog_state(conn)
        plan_hash = compute_plan_hash(
            action=action_name,
            migration_name=migration_file.name,
            sql_content=sql_content,
            env_identity=safe_target,
            catalog_state=catalog_state,
        )

        # 3. Dry-run mode: emit expected plan hash and preview without DDL
        if not args.confirm_apply:
            logger.warning("DRY-RUN MODE: --confirm-apply not specified. No DDL will be executed.")
            print("\n--- Workload Index Migration Preflight Summary ---")
            print(f"Target: env={safe_target['target']}, host={safe_target['host']}, db={safe_target['database']}")
            print(f"Action: {action_name}")
            print(f"Migration file: {migration_file.name}")
            print(f"Migration SQL SHA256: {hashlib.sha256(sql_content.encode('utf-8')).hexdigest()}")
            print(f"Expected Plan Hash: {plan_hash}")
            print("--------------------------------------------------\n")
            print("--- Migration SQL Preview ---")
            print(sql_content.strip())
            print("-----------------------------\n")
            logger.info(
                "Preflight completed successfully. To execute DDL, re-run with:\n"
                "  python3 scripts/apply_workload_indexes.py %s%s--confirm-apply --expected-plan-hash %s",
                f"--env {args.env} " if args.env else "--target-url <TARGET_URL> ",
                "--rollback " if args.rollback else "",
                plan_hash,
            )
            return

        # 4. Confirm mode: require matching --expected-plan-hash before DDL
        if not args.expected_plan_hash:
            logger.error(
                "Safety guardrail failure: --confirm-apply requires --expected-plan-hash <hash> "
                "generated by a dry-run preflight. Aborting before DDL."
            )
            sys.exit(1)

        if args.expected_plan_hash != plan_hash:
            logger.error(
                "Safety guardrail failure: Mismatched plan hash (expected '%s', got '%s'). "
                "Target catalog drifted, migration file modified, or environment mismatch. "
                "Execution aborted before DDL.",
                args.expected_plan_hash,
                plan_hash,
            )
            sys.exit(1)

        # 5. Inventory before execution
        indexes_before = {idx["index_name"] for idx in profiler.fetch_index_inventory("app")}

        # 6. Apply within transaction with strict lock and statement timeouts
        logger.info(
            "Executing %s within transaction (lock_timeout=%dms, statement_timeout=%dms)...",
            action_name,
            args.lock_timeout_ms,
            args.statement_timeout_ms,
        )
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(f"SET LOCAL lock_timeout = {int(args.lock_timeout_ms)};")
                cur.execute(f"SET LOCAL statement_timeout = {int(args.statement_timeout_ms)};")
                cur.execute(sql_content)

        logger.info("Transaction COMMITTED successfully.")

        # 7. Post-apply index verification
        indexes_after = {idx["index_name"] for idx in profiler.fetch_index_inventory("app")}
        added_indexes = indexes_after - indexes_before
        removed_indexes = indexes_before - indexes_after

        if added_indexes:
            logger.info("Newly created indexes: %s", sorted(added_indexes))
        if removed_indexes:
            logger.info("Removed indexes: %s", sorted(removed_indexes))

        logger.info("Index migration %s completed cleanly with zero side-effects.", action_name)

    except Exception as exc:
        conn.rollback()
        sanitized_err = redact_dsn_password(str(exc))
        logger.error("Migration %s failed: %s", action_name, sanitized_err)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
