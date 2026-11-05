#!/usr/bin/env python3
"""GreenSentinel Database Identity Reconciliation CLI (#410 / #402 / #394).

Audited repository-owned dry-run and apply tool:
- Mirrors paginated Clerk organizations and memberships to target database environment.
- Reconciles Clerk memberships to DB roles (admin, fraud_analyst, driver); unknown roles denied.
- Deactivates orphaned real principals without deleting historical records (status='disabled').
- Deletes proven mock principals and cases with complete catalog-derived FK closure.
- Protects real business records: never deletes fraud cases or audit rows via mock principal FKs.
- Enforces mode 0600 recovery export with actual row contents before any database apply.
- Enforces advisory transaction lock, lock timeouts set before acquisition, and expected plan hash verification.
- Emits sanitized count-only report with opaque hashes; never echoes secrets or PII.

Usage:
    # 1. Read-only audit & plan generation (offline using audit snapshot)
    python scripts/reconcile_identity.py --audit --env dev --clerk-snapshot-file /tmp/greensentinel-identity-audit.json --offline

    # 2. Output plan JSON with plan hash
    python scripts/reconcile_identity.py --plan --json --env staging --offline

    # 3. Live audit against database
    python scripts/reconcile_identity.py --audit --env dev --database-url "$DATABASE_URL"

    # 4. Transactional apply (BLOCKED without explicit review & allow flag)
    python scripts/reconcile_identity.py --apply --env dev --database-url "$DATABASE_URL" \
        --expected-plan-hash <hash> --allow-live-apply

Exit codes:
    0: Success
    1: Error / verification failure / stale plan / live mutation blocked
    2: Usage or argument error
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.services.identity_reconciliation import (  # noqa: E402
    ClerkAPIError,
    ClerkMembershipConflictError,
    ClerkPaginationError,
    DatabaseAuditState,
    MockPrincipalReferenceError,
    SafetyGuardError,
    SchemaMismatchError,
    StalePlanError,
    TriggerMismatchError,
    assert_disposable_db_guard,
    audit_database_state,
    execute_reconciliation_apply,
    export_recovery_snapshot,
    fetch_clerk_snapshot_from_api,
    fetch_clerk_snapshot_from_file,
    generate_reconciliation_plan,
    generate_sanitized_report,
)


def _connect_db(database_url: str):
    try:
        import psycopg
    except ImportError:
        print("error: psycopg is required (pip install psycopg[binary])", file=sys.stderr)
        sys.exit(2)
    try:
        return psycopg.connect(database_url, autocommit=False, connect_timeout=15)
    except Exception as exc:
        print(f"error: failed to connect to database: {exc}", file=sys.stderr)
        sys.exit(1)


def _load_offline_db_state(snapshot_file: str, env: str) -> DatabaseAuditState:
    with open(snapshot_file, encoding="utf-8") as f:
        data = json.load(f)

    dbs = data.get("databases", {})
    if env not in dbs:
        raise ValueError(f"Environment {env!r} not found in snapshot databases: {list(dbs.keys())}")

    env_db = dbs[env]
    available_tables = {
        "organizations",
        "principals",
        "principal_roles",
        "drivers",
        "fraud_cases",
        "adjudications",
        "review_actions",
        "review_leases",
        "audit_events",
        "case_agent_sessions",
        "case_agent_messages",
        "workflow_questions",
        "workflow_answers",
        "workflow_minutes",
        "workflow_action_requests",
        "agent_runtime_turns",
        "solved_case_contexts",
        "precedent_reuse_history",
    }
    # Prod migration history 17 vs dev/staging 27
    if env_db.get("migrations_count", 0) < 20:
        # Exclude tables added after migration 17
        available_tables -= {
            "driver_admission_sanctions",
            "preliminary_judgments",
            "benchmark_scenarios",
            "org_bootstrap_state",
        }
    else:
        available_tables.update(["driver_admission_sanctions", "preliminary_judgments"])

    # Organizations normalization
    raw_orgs = env_db.get("organizations", [])
    organizations = []
    for o in raw_orgs:
        clerk_id = o.get("clerk_organization_id") or o.get("clerk_org_id")
        organizations.append(
            {
                "id": o.get("id"),
                "name": o.get("name"),
                "clerk_organization_id": clerk_id,
            }
        )

    # Aggregate mock principals and real principals
    principals = []
    for p in env_db.get("real_clerk_principals", []):
        principals.append(
            {
                "id": p.get("id"),
                "organization_id": p.get("organization_id"),
                "external_subject": p.get("external_subject"),
                "display_name": p.get("display_name"),
                "status": p.get("status", "active"),
                "roles": p.get("roles", []),
            }
        )
    for p in env_db.get("mock_principals", []):
        principals.append(
            {
                "id": p.get("id"),
                "organization_id": p.get("organization_id"),
                "external_subject": p.get("external_subject"),
                "display_name": p.get("display_name"),
                "status": p.get("status", "active"),
                "roles": p.get("roles", []),
            }
        )

    mock_cases = [c for c in env_db.get("fraud_cases", []) if c["id"].startswith("018f2f4e-a000-7000-8000-")]

    return DatabaseAuditState(
        migrations_count=env_db.get("migrations_count", 0),
        latest_migration=env_db.get("latest_migration"),
        organizations=organizations,
        principals=principals,
        mock_cases=mock_cases,
        available_tables=available_tables,
        drivers=env_db.get("bound_drivers", []),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GreenSentinel Database Identity Reconciliation CLI")
    parser.add_argument("--env", choices=["dev", "staging", "production", "test", "local"], help="Target environment")
    parser.add_argument("--audit", action="store_true", help="Perform read-only audit and print sanitized report")
    parser.add_argument("--plan", action="store_true", help="Generate and output reconciliation plan")
    parser.add_argument("--apply", action="store_true", help="Execute transactional reconciliation apply")
    parser.add_argument("--export-recovery", action="store_true", help="Explicitly write mode 0600 recovery backup")
    parser.add_argument("--json", action="store_true", help="Output plan in JSON format")
    parser.add_argument("--offline", action="store_true", help="Use offline snapshot data for DB state")
    parser.add_argument("--clerk-snapshot-file", default=None, help="Path to Clerk snapshot / audit JSON file")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", ""), help="PostgreSQL connection URL")
    parser.add_argument("--expected-plan-hash", help="Expected plan hash required for --apply")
    parser.add_argument("--allow-live-apply", action="store_true", help="Explicit opt-in to execute database mutation")
    parser.add_argument(
        "--recovery-dir",
        default=os.environ.get("TMPDIR", "/tmp"),
        help="Directory to store mode 0600 recovery backups",
    )

    args = parser.parse_args(argv)

    if not args.env:
        print("error: --env is required (dev, staging, production, test, local)", file=sys.stderr)
        return 2

    # Default action is --audit if neither --plan nor --apply nor --export-recovery
    is_audit = args.audit or (not args.plan and not args.apply and not args.export_recovery)

    if args.apply:
        if not args.expected_plan_hash:
            print("error: --expected-plan-hash is required when applying reconciliation", file=sys.stderr)
            return 2

        allow_flag = args.allow_live_apply or (os.environ.get("ALLOW_LIVE_DB_APPLY") == "1")
        if not allow_flag:
            print(
                "error: apply blocked: --allow-live-apply flag required. Conductor review must precede live mutations.",
                file=sys.stderr,
            )
            return 1

    # 1. Load Clerk Snapshot
    clerk_file = args.clerk_snapshot_file
    if not clerk_file:
        if os.path.exists("/tmp/greensentinel-identity-audit.json"):
            clerk_file = "/tmp/greensentinel-identity-audit.json"

    try:
        if clerk_file and os.path.exists(clerk_file):
            clerk_snapshot = fetch_clerk_snapshot_from_file(clerk_file)
        else:
            clerk_secret = os.environ.get("CLERK_SECRET_KEY")
            if not clerk_secret:
                print("error: either --clerk-snapshot-file or CLERK_SECRET_KEY is required", file=sys.stderr)
                return 2
            clerk_snapshot = fetch_clerk_snapshot_from_api(clerk_secret)
    except (ClerkAPIError, ClerkPaginationError, ClerkMembershipConflictError) as exc:
        print(f"error: Clerk snapshot fetch failed: {exc}", file=sys.stderr)
        return 1

    # 2. Load DB Audit State
    conn = None
    try:
        if args.offline:
            if not clerk_file or not os.path.exists(clerk_file):
                print("error: --offline requires valid --clerk-snapshot-file with database audit data", file=sys.stderr)
                return 2
            db_state = _load_offline_db_state(clerk_file, args.env)
        else:
            if not args.database_url:
                print("error: --database-url or DATABASE_URL is required (or use --offline)", file=sys.stderr)
                return 2
            # Assert loopback and disposable prefix guard before connecting
            assert_disposable_db_guard(args.database_url)
            conn = _connect_db(args.database_url)
            db_state = audit_database_state(conn)
    except SafetyGuardError as exc:
        print(f"error: safety guard rejected connection: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: failed to load database state: {exc}", file=sys.stderr)
        if conn:
            conn.close()
        return 1

    # 3. Generate Plan
    try:
        plan = generate_reconciliation_plan(clerk_snapshot, db_state, env=args.env)
    except Exception as exc:
        print(f"error: failed to generate reconciliation plan: {exc}", file=sys.stderr)
        if conn:
            conn.close()
        return 1

    # 4. Handle Actions
    if args.export_recovery:
        recovery_path = os.path.join(args.recovery_dir, f"recovery_{args.env}_{plan.plan_hash[:12]}.json")
        export_recovery_snapshot(plan.recovery_export_data, recovery_path)
        print(f"Recovery export created: {recovery_path}")

    if args.apply:
        if not args.expected_plan_hash:
            print("error: --expected-plan-hash is required when applying reconciliation", file=sys.stderr)
            if conn:
                conn.close()
            return 2

        allow_flag = args.allow_live_apply or (os.environ.get("ALLOW_LIVE_DB_APPLY") == "1")
        if not allow_flag:
            print(
                "error: apply blocked: --allow-live-apply flag required. Conductor review must precede live mutations.",
                file=sys.stderr,
            )
            if conn:
                conn.close()
            return 1

        if not conn:
            print("error: cannot apply in offline mode; database connection required", file=sys.stderr)
            return 2

        try:
            result = execute_reconciliation_apply(
                conn=conn,
                plan=plan,
                expected_plan_hash=args.expected_plan_hash,
                allow_apply=allow_flag,
                recovery_dir=args.recovery_dir,
                clerk_snapshot=clerk_snapshot,
            )
            print(json.dumps(result, indent=2))
            return 0
        except (StalePlanError, SchemaMismatchError, MockPrincipalReferenceError, TriggerMismatchError) as exc:
            print(f"error: apply rejected: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"error: apply transaction failed and was rolled back: {exc}", file=sys.stderr)
            return 1
        finally:
            if conn:
                conn.close()

    if args.plan:
        if args.json:
            plan_dict = {
                "env": plan.env,
                "plan_hash": plan.plan_hash,
                "schema_fingerprint": plan.schema_fingerprint,
                "orgs_to_create_count": len(plan.orgs_to_create),
                "orgs_unchanged_count": len(plan.orgs_unchanged),
                "orgs_to_update_name_count": len(plan.orgs_to_update_name),
                "principals_to_create_count": len(plan.principals_to_create),
                "principals_to_update_role_count": len(plan.principals_to_update_role),
                "principals_to_deactivate_count": len(plan.principals_to_deactivate),
                "principals_to_delete_count": len(plan.principals_to_delete),
                "mock_cases_to_delete_count": len(plan.mock_cases_to_delete),
                "fk_cleanup_steps_count": len(plan.fk_cleanup_steps),
                "preflight_missing_tables": plan.preflight_missing_tables,
            }
            print(json.dumps(plan_dict, indent=2))
        else:
            print(generate_sanitized_report(plan))
        if conn:
            conn.close()
        return 0

    if is_audit:
        print(generate_sanitized_report(plan))
        if conn:
            conn.close()
        return 0

    if conn:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
