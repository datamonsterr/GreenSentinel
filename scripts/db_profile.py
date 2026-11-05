#!/usr/bin/env python3
"""Database Performance Profiler and Index Audit CLI.

Safe, read-only profiling tool for inventorying Postgres indexes, auditing
unindexed foreign keys, verifying tenant isolation invariants, and executing
bounded EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) plans for allowlisted workloads
without mutating live data or exposing secrets.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import psycopg
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.services.db_profiler import (  # noqa: E402
    ALLOWLISTED_QUERIES,
    DEFAULT_STATEMENT_TIMEOUT_MS,
    DatabaseProfiler,
    redact_dsn_password,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("db_profile_cli")


def resolve_connection_parameters(
    env: str | None = None,
    project_id: str = "c49458fb-d741-468f-a3ed-d35b96788f68",
    service_id: str = "9710a2f5-ed77-472e-8e79-3b748bb73df2",
    target_url: str | None = None,
) -> dict[str, Any]:
    """Resolve database connection parameters safely in-process with zero secret leakage."""
    load_dotenv()
    if target_url:
        return {"conninfo": target_url}

    if env:
        logger.info("Fetching connection parameters from Railway CLI for env='%s'...", env)
        cmd = [
            "railway",
            "variable",
            "list",
            "--project",
            project_id,
            "--environment",
            env,
            "--service",
            service_id,
            "--json",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Railway CLI variable list failed: {res.stderr}")
        data = json.loads(res.stdout)
        host = data.get("RAILWAY_TCP_PROXY_DOMAIN")
        port = data.get("RAILWAY_TCP_PROXY_PORT")
        user = data.get("PGUSER")
        password = data.get("PGPASSWORD")
        dbname = data.get("PGDATABASE")
        if not (host and port and user and password and dbname):
            raise RuntimeError(f"Missing required proxy parameters in Railway response for env '{env}'")
        return {
            "host": host,
            "port": int(port),
            "user": user,
            "password": password,
            "dbname": dbname,
        }

    env_url = (
        os.environ.get("TARGET_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("MIGRATION_DATABASE_URL")
        or "postgresql://postgres:postgrespassword@localhost:5432/postgres"
    )
    return {"conninfo": env_url}


def extract_safe_target_summary(conn_params: dict[str, Any], env_label: str | None) -> dict[str, str]:
    """Extract public environment identity without exposing credentials."""
    host = "unknown"
    dbname = "unknown"
    if "conninfo" in conn_params:
        conninfo = conn_params["conninfo"]
        if "://" in conninfo:
            try:
                parsed = urlparse(conninfo)
                host = parsed.hostname or "unknown"
                dbname = parsed.path.lstrip("/") or "unknown"
            except Exception:
                pass
        else:
            import re

            m_host = re.search(r"\bhost\s*=\s*([^\s;]+)", conninfo, re.I)
            m_db = re.search(r"\bdb(?:name)?\s*=\s*([^\s;]+)", conninfo, re.I)
            if m_host:
                host = m_host.group(1).strip("'\"")
            if m_db:
                dbname = m_db.group(1).strip("'\"")
    else:
        host = str(conn_params.get("host", "unknown"))
        dbname = str(conn_params.get("dbname", "unknown"))

    # Extra defense: ensure no passwords accidentally seeped into host/dbname
    if any(s in host.lower() or s in dbname.lower() for s in ("password=", "pass=", "secret", "token")):
        host = "sanitized"
        dbname = "sanitized"

    return {
        "target": env_label or "custom",
        "host": host,
        "database": dbname,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="P-063 Database Performance Profiler & Index Auditor")
    parser.add_argument("--env", choices=["dev", "staging", "production"], help="Railway environment to profile")
    parser.add_argument("--project", default="c49458fb-d741-468f-a3ed-d35b96788f68", help="Railway Project ID")
    parser.add_argument("--service", default="9710a2f5-ed77-472e-8e79-3b748bb73df2", help="Railway Postgres Service ID")
    parser.add_argument("--target-url", help="Direct Postgres connection URL (for local or disposable DB)")
    parser.add_argument("--output-json", help="Path to write structured JSON audit results")
    parser.add_argument("--schema", default="app", help="Schema to audit")
    parser.add_argument(
        "--run-workload", choices=list(ALLOWLISTED_QUERIES.keys()), help="Run specific allowlisted query"
    )
    parser.add_argument(
        "--params-json",
        help="JSON string or file containing parameters array for --run-workload (e.g. '[\"uuid\", ...]')",
    )
    parser.add_argument(
        "--audit-all", action="store_true", help="Perform full inventory, FK audit, tenancy check, and sample explains"
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=DEFAULT_STATEMENT_TIMEOUT_MS,
        help="Statement timeout in ms (default 5000)",
    )

    args = parser.parse_args()

    # Early validation of workload parameters BEFORE connection attempt
    workload_params: list[Any] | None = None
    if args.run_workload:
        if not args.params_json:
            parser.error(
                f"--run-workload '{args.run_workload}' requires explicit --params-json containing parameter array."
            )
        raw_params = args.params_json.strip()
        if os.path.isfile(raw_params):
            with open(raw_params, encoding="utf-8") as f:
                parsed_json = json.load(f)
        else:
            try:
                parsed_json = json.loads(raw_params)
            except json.JSONDecodeError as exc:
                parser.error(f"--params-json is not valid JSON: {exc}")

        if not isinstance(parsed_json, (list, tuple)):
            parser.error("--params-json must be a JSON array of values.")

        workload_params = list(parsed_json)
        query_def = ALLOWLISTED_QUERIES[args.run_workload]
        expected_count = len(query_def.example_param_names)
        if len(workload_params) != expected_count:
            parser.error(
                f"Workload '{args.run_workload}' expects {expected_count} parameter(s) "
                f"{query_def.example_param_names}, but got {len(workload_params)}."
            )

    conn_params = resolve_connection_parameters(
        env=args.env, project_id=args.project, service_id=args.service, target_url=args.target_url
    )

    safe_target = extract_safe_target_summary(conn_params, args.env)
    logger.info(
        "Connecting to target database (env=%s, host=%s, db=%s)...",
        safe_target["target"],
        safe_target["host"],
        safe_target["database"],
    )

    try:
        conn = psycopg.connect(**conn_params, autocommit=False, connect_timeout=15)
    except Exception as exc:
        sanitized_err = redact_dsn_password(str(exc))
        logger.error("Database connection failed: %s", sanitized_err)
        sys.exit(1)

    profiler = DatabaseProfiler(conn=conn, timeout_ms=args.timeout_ms)

    report: dict[str, Any] = {
        "target": safe_target["target"],
        "connection": safe_target,
        "preflight": {},
        "tenancy": {},
        "indexes": [],
        "unindexed_foreign_keys": [],
        "workload_plans": {},
    }

    try:
        # 1. Preflight schema verification
        report["preflight"] = profiler.preflight_schema_check(
            required_tables=["organizations", "trips", "trip_assignments", "fraud_cases", "telemetry_points"],
            required_columns={
                "fraud_cases": ["id", "organization_id", "status", "priority_tier", "priority_score", "created_at"],
                "trip_assignments": ["id", "trip_id", "driver_id", "vehicle_id", "state"],
            },
        )

        # 2. Tenancy invariants verification
        if args.audit_all:
            logger.info("Verifying tenant isolation invariants...")
            report["tenancy"] = profiler.check_tenancy_invariants()
            logger.info("Tenancy verified: %s", report["tenancy"])

        # 3. Index inventory & FK audit
        if args.audit_all or not args.run_workload:
            logger.info("Auditing index inventory for schema '%s'...", args.schema)
            report["indexes"] = profiler.fetch_index_inventory(args.schema)
            logger.info("Found %d indexes.", len(report["indexes"]))

            logger.info("Auditing unindexed foreign keys...")
            report["unindexed_foreign_keys"] = profiler.audit_unindexed_foreign_keys(args.schema)
            logger.info("Found %d unindexed foreign keys.", len(report["unindexed_foreign_keys"]))

        # 4. Sample explains on real database records
        if args.audit_all:
            logger.info("Executing safe sample EXPLAINs for allowlisted workloads...")
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM app.organizations LIMIT 1;")
                org_row = cur.fetchone()
                org_id = org_row[0] if org_row else None

                cur.execute("SELECT id FROM app.trips LIMIT 1;")
                trip_row = cur.fetchone()
                trip_id = trip_row[0] if trip_row else None

                cur.execute("SELECT id FROM app.trip_assignments LIMIT 1;")
                ta_row = cur.fetchone()
                assignment_id = ta_row[0] if ta_row else None

                cur.execute("SELECT external_ref FROM app.drivers WHERE organization_id = %s LIMIT 1;", (org_id,))
                d_row = cur.fetchone()
                driver_ref = d_row[0] if d_row else None

            if org_id:
                try:
                    report["workload_plans"]["org_case_queue"] = profiler.explain_workload(
                        "org_case_queue", (org_id, "ready", 20, 0)
                    )
                except Exception as e:
                    logger.warning("Could not explain org_case_queue: %s", redact_dsn_password(str(e)))

            if trip_id:
                try:
                    report["workload_plans"]["trip_assignment_by_trip"] = profiler.explain_workload(
                        "trip_assignment_by_trip", (trip_id,)
                    )
                except Exception as e:
                    logger.warning("Could not explain trip_assignment_by_trip: %s", redact_dsn_password(str(e)))

            if assignment_id:
                try:
                    report["workload_plans"]["telemetry_points_by_assignment"] = profiler.explain_workload(
                        "telemetry_points_by_assignment", (assignment_id,)
                    )
                    report["workload_plans"]["case_by_assignment"] = profiler.explain_workload(
                        "case_by_assignment", (assignment_id,)
                    )
                except Exception as e:
                    logger.warning("Could not explain assignment workloads: %s", redact_dsn_password(str(e)))

            if org_id and driver_ref:
                try:
                    report["workload_plans"]["driver_lookup_by_external_ref"] = profiler.explain_workload(
                        "driver_lookup_by_external_ref", (org_id, driver_ref)
                    )
                except Exception as e:
                    logger.warning("Could not explain driver lookup workload: %s", redact_dsn_password(str(e)))

        # 5. Targeted workload execution
        if args.run_workload and workload_params is not None:
            logger.info("Executing allowlisted workload '%s'...", args.run_workload)
            plan = profiler.explain_workload(args.run_workload, tuple(workload_params))
            report["workload_plans"][args.run_workload] = plan
            logger.info(
                "Workload executed successfully: node_type=%s, total_cost=%s, execution_time_ms=%s",
                plan.get("node_type"),
                plan.get("total_cost"),
                plan.get("execution_time_ms"),
            )

        if args.output_json:
            out_path = Path(args.output_json)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            logger.info("Sanitized report written to %s", out_path)
        else:
            print(json.dumps(report, indent=2, default=str))

    finally:
        conn.close()


if __name__ == "__main__":
    main()
