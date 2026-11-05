"""Unit tests for additive test-store schema parity migration and safe rollback invariants.

Task: #423 under parent #394.
"""

from __future__ import annotations

import re
from pathlib import Path

MIGRATION_PATH = Path("db/migrations/20261016000000_test_store_schema_parity.sql")
ROLLBACK_PATH = Path("db/rollbacks/20261016000000_test_store_schema_parity.down.sql")
ROLLBACK_SCRIPT = Path("scripts/rollback_schema_parity_394.py")

EXPECTED_CHILD_ORG_TABLES = [
    "app.test_controls",
    "app.test_definition_revisions",
    "app.test_events",
    "app.test_idempotency_keys",
    "app.test_notifications",
    "app.test_outbox",
    "app.test_runs",
    "app.test_samples",
]


def test_migration_file_exists():
    assert MIGRATION_PATH.is_file(), f"Migration file missing at {MIGRATION_PATH}"


def test_rollback_file_exists():
    assert ROLLBACK_PATH.is_file(), f"Rollback file missing at {ROLLBACK_PATH}"


def test_rollback_guidance_script_exists():
    assert ROLLBACK_SCRIPT.is_file(), f"Rollback script missing at {ROLLBACK_SCRIPT}"


def test_migration_is_strictly_non_destructive():
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    destructive_keywords = [
        r"\bDROP\s+TABLE\b",
        r"\bDROP\s+COLUMN\b",
        r"\bTRUNCATE\b",
        r"\bDROP\s+DATABASE\b",
        r"\bDROP\s+EXTENSION\b",
        r"\bDROP\s+SCHEMA\b",
    ]
    for pattern in destructive_keywords:
        assert not re.search(pattern, sql, re.IGNORECASE), f"Destructive statement '{pattern}' found in migration"


def test_migration_has_explicit_schema_qualification():
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    # Verify no session search_path overrides
    assert "set search_path" not in sql.lower(), "Migration must not rely on or manipulate session search_path"

    # All ALTER TABLE, CREATE TABLE, and CREATE INDEX must use schema qualification
    alter_matches = re.findall(r"ALTER\s+TABLE\s+([a-zA-Z0-9_\.]+)", sql, re.IGNORECASE)
    for table in alter_matches:
        assert table.startswith("app."), f"Unqualified ALTER TABLE '{table}' found in migration"

    create_table_matches = re.findall(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z0-9_\.]+)", sql, re.IGNORECASE
    )
    for table in create_table_matches:
        assert table.startswith("app."), f"Unqualified CREATE TABLE '{table}' found in migration"

    create_idx_matches = re.findall(
        r"CREATE\s+INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?\w+\s+ON\s+([a-zA-Z0-9_\.]+)", sql, re.IGNORECASE
    )
    for table in create_idx_matches:
        assert table.startswith("app."), f"Unqualified CREATE INDEX on '{table}' found in migration"


def test_migration_adds_all_eight_child_organization_id_columns():
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    for table in EXPECTED_CHILD_ORG_TABLES:
        pattern = rf"ALTER\s+TABLE\s+{re.escape(table)}\s+ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+organization_id\s+uuid"
        assert re.search(pattern, sql, re.IGNORECASE), f"Missing organization_id column on {table}"


def test_migration_creates_contract_tables_and_columns():
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "app.test_run_requests" in sql, "Missing app.test_run_requests creation"
    assert "app.test_cases" in sql, "Missing app.test_cases creation"
    assert "messages jsonb not null default '[]'::jsonb" in sql.lower(), "Missing messages column definition"
    assert "created_by::text" in sql, "Missing created_by safe cast to text"


def test_migration_indexes_run_id_foreign_keys():
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "idx_test_run_requests_run" in sql, "Missing FK index on app.test_run_requests(run_id)"
    assert "idx_test_cases_run" in sql, "Missing FK index on app.test_cases(run_id)"
    assert "idx_test_runs_definition" in sql, "Missing FK index on app.test_runs(definition_revision_id)"


def test_migration_quarantine_reasons():
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    expected_reasons = [
        "invalid_org_reference",
        "unowned_plan",
        "parent_child_org_conflict",
        "unowned_revision",
        "unowned_run",
        "unowned_control",
        "unowned_sample",
        "unowned_event",
        "unowned_notification",
        "unowned_idempotency_key",
        "unowned_outbox",
    ]
    for reason in expected_reasons:
        assert reason in sql, f"Quarantine reason '{reason}' missing from migration"


def test_rollback_down_script_forbids_dropping_columns_or_tables():
    sql = ROLLBACK_PATH.read_text(encoding="utf-8")
    # Filter out single-line comments
    active_sql = "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))
    assert not re.search(r"\bDROP\s+TABLE\b", active_sql, re.IGNORECASE), "Rollback script must not execute DROP TABLE"
    assert not re.search(r"\bDROP\s+COLUMN\b", active_sql, re.IGNORECASE), (
        "Rollback script must not execute DROP COLUMN"
    )
    assert "additive" in sql.lower(), "Rollback script must document additive compatibility policy"
    assert "pg_restore" in sql, "Rollback script must document pg_restore command for full restore"


def test_rollback_guidance_cli_output(capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location("rollback_cli", ROLLBACK_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    exit_code = mod.main([])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "ADDITIVE BACKWARD COMPATIBILITY" in captured.out
    assert "DELETE FROM public.schema_migrations" in captured.out
    assert "pg_restore" in captured.out


def test_rollback_cli_manifest_and_checksum_verification(tmp_path):
    import hashlib
    import importlib.util
    import json

    spec = importlib.util.spec_from_file_location("rollback_cli", ROLLBACK_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Create dummy dump file
    dump_file = tmp_path / "test.dump"
    dump_content = b"PGDMP_DUMMY_DATA_12345"
    dump_file.write_bytes(dump_content)
    expected_sha = hashlib.sha256(dump_content).hexdigest()

    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(
        json.dumps(
            {
                "environments": {
                    "dev": {
                        "path": str(dump_file),
                        "sha256": expected_sha,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    # 1. Matching checksum succeeds
    rc = mod.main(["--manifest", str(manifest_file), "--check-backups", "--verify-checksums"])
    assert rc == 0

    # 2. Mismatching checksum fails
    bad_manifest = tmp_path / "bad_manifest.json"
    bad_manifest.write_text(
        json.dumps(
            {
                "environments": {
                    "dev": {
                        "path": str(dump_file),
                        "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    rc_bad = mod.main(["--manifest", str(bad_manifest), "--check-backups", "--verify-checksums"])
    assert rc_bad == 1
