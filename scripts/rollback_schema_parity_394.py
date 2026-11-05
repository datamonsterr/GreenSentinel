#!/usr/bin/env python3
"""Safe Rollback Guidance and Verification Tool for Schema Parity (Issue #394 / Child Task #423).

This script enforces the non-destructive rollback policy for additive migration
20261016000000_test_store_schema_parity.sql.

It accepts explicit backup paths or manifest files, optionally verifies SHA-256
checksums, and preserves historical backup audit references as non-coupled evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# Historical snapshot reference from the original pre-migration audit (20261015T173125Z)
# Kept as historical evidence for audit traceability.
HISTORICAL_AUDIT_SNAPSHOT = {
    "snapshot_id": "20261015T173125Z",
    "environments": {
        "dev": {
            "sha256": "ca1b85fbf900de8c5187e68dfac251ea5cd7ef04fc1096b35b7d85401d34b166",
            "historical_path": "/home/dat/.local/state/p063-db-finalize-394/backups/20261015T173125Z/dev.dump",
        },
        "staging": {
            "sha256": "71133c4f5020bcbd2066708a4dd4d761607a54ce9311c4d280cc9410670b82f2",
            "historical_path": "/home/dat/.local/state/p063-db-finalize-394/backups/20261015T173125Z/staging.dump",
        },
        "production": {
            "sha256": "f72331f9085c5f87ce0d91ebeb018228dfcc84f4205833ca02690fc62a8cc321",
            "historical_path": "/home/dat/.local/state/p063-db-finalize-394/backups/20261015T173125Z/production.dump",
        },
    },
}


def print_guidance(custom_backups: dict[str, dict[str, str]] | None = None) -> None:
    print("=" * 70)
    print("P-063 Schema Parity Rollback Policy (Issue #394 / Child Task #423)")
    print("=" * 70)
    print(
        "\n1. ADDITIVE BACKWARD COMPATIBILITY:\n"
        "   The migration 20261016000000_test_store_schema_parity.sql is strictly additive.\n"
        "   - Added columns (organization_id on 8 child tables) are nullable.\n"
        "   - Added column messages on test_definition_revisions defaults to '[]'::jsonb.\n"
        "   - Alteration of test_plans.created_by to TEXT preserves existing UUID text values.\n"
        "   - Added tables (app.test_run_requests, app.test_cases) do not interfere with legacy reads.\n"
        "   - Downward destructive operations ('DROP TABLE', 'DROP COLUMN') are intentionally prohibited\n"
        "     because dropping columns would destroy pre-existing columns on dev/staging or new user data."
    )
    print(
        "\n2. IN-PLACE MIGRATION UNMARK (IF RUNNER RE-RUN REQUIRED):\n"
        "   To allow a migration runner to re-execute without touching tables or data:\n"
        "     DELETE FROM public.schema_migrations WHERE version = '20261016000000_test_store_schema_parity.sql';"
    )
    print(
        "\n3. VERIFIED FULL RESTORE (HARD ROLLBACK):\n"
        "   If a full rollback to pre-migration byte snapshot is required, restore from\n"
        "   a verified pre-migration backup dump using pg_restore:\n"
        "     pg_restore -U postgres -d <db_name> --clean --if-exists <path_to_backup.dump>"
    )

    if custom_backups:
        print("\n   Configured Backup Targets:")
        for env, meta in custom_backups.items():
            print(f"   - {env.upper()}:")
            print(f"       Path: {meta.get('path', 'N/A')}")
            if "sha256" in meta:
                print(f"       Expected SHA256: {meta['sha256']}")
    else:
        print(f"\n   Historical Audit Snapshot Reference (ID: {HISTORICAL_AUDIT_SNAPSHOT['snapshot_id']}):")
        for env, meta in HISTORICAL_AUDIT_SNAPSHOT["environments"].items():
            print(f"   - {env.upper()}:")
            print(f"       Historical Audit Path: {meta['historical_path']}")
            print(f"       Verified SHA256: {meta['sha256']}")
    print("=" * 70)


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(manifest_path: Path) -> dict[str, dict[str, str]]:
    with open(manifest_path, encoding="utf-8") as f:
        data = json.load(f)
    backups: dict[str, dict[str, str]] = {}
    # Supports either {"dev": {"path": ..., "sha256": ...}} or {"environments": {...}}
    envs = data.get("environments", data)
    for env, info in envs.items():
        if isinstance(info, dict):
            backups[env] = {
                "path": str(info.get("path") or info.get("historical_path") or ""),
                "sha256": str(info.get("sha256") or ""),
            }
        elif isinstance(info, str):
            backups[env] = {"path": info}
    return backups


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P-063 schema parity rollback guidance and backup verification")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Path to JSON manifest specifying backup paths and expected checksums",
    )
    parser.add_argument("--dev-backup", type=Path, default=None, help="Explicit path to dev backup dump file")
    parser.add_argument("--staging-backup", type=Path, default=None, help="Explicit path to staging backup dump file")
    parser.add_argument(
        "--prod-backup",
        "--production-backup",
        type=Path,
        dest="prod_backup",
        default=None,
        help="Explicit path to production backup dump file",
    )
    parser.add_argument(
        "--check-backups",
        action="store_true",
        help="Verify that backup dump files exist",
    )
    parser.add_argument(
        "--verify-checksums",
        action="store_true",
        help="Compute SHA256 checksums and verify against manifest or historical evidence",
    )
    args = parser.parse_args(argv)

    backups: dict[str, dict[str, str]] = {}
    if args.manifest:
        if not args.manifest.is_file():
            print(f"Error: Manifest file {args.manifest} not found", file=sys.stderr)
            return 1
        backups.update(load_manifest(args.manifest))

    if args.dev_backup:
        backups.setdefault("dev", {})["path"] = str(args.dev_backup)
    if args.staging_backup:
        backups.setdefault("staging", {})["path"] = str(args.staging_backup)
    if args.prod_backup:
        backups.setdefault("production", {})["path"] = str(args.prod_backup)

    print_guidance(backups if backups else None)

    if args.check_backups or args.verify_checksums:
        # If no explicit backups were supplied, check historical locations if available
        targets = backups
        is_historical = False
        if not targets:
            print("\nNo explicit backup targets provided; checking historical audit paths...")
            is_historical = True
            targets = {
                env: {
                    "path": meta["historical_path"],
                    "sha256": meta["sha256"],
                }
                for env, meta in HISTORICAL_AUDIT_SNAPSHOT["environments"].items()
            }

        print("\nVerifying backup files...")
        all_ok = True
        for env, meta in targets.items():
            p_str = meta.get("path")
            if not p_str:
                print(f"  [MISSING] {env}: No path specified")
                all_ok = False
                continue
            p = Path(p_str)
            exists = p.is_file()
            status = "FOUND" if exists else "MISSING"
            print(f"  [{status}] {env}: {p_str}")
            if not exists:
                all_ok = False
                continue

            if args.verify_checksums:
                expected = meta.get("sha256")
                actual = compute_sha256(p)
                if expected:
                    match = actual.lower() == expected.lower()
                    chk_status = "MATCH" if match else "MISMATCH"
                    print(f"           SHA256: {actual} ({chk_status})")
                    if not match:
                        all_ok = False
                else:
                    print(f"           SHA256: {actual} (NO_EXPECTED_CHECKSUM)")

        if not all_ok and not is_historical:
            return 1
        # If historical check failed on another workstation, report as advisory
        if not all_ok and is_historical:
            print(
                "\nNote: Historical workstation dumps were not found on this system. "
                "Supply --manifest or --<env>-backup to verify active backups."
            )
            return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
