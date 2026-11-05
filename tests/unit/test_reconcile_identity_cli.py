"""Unit tests for scripts/reconcile_identity.py CLI."""

from __future__ import annotations

import json

import pytest

from scripts.reconcile_identity import main


@pytest.fixture
def mock_audit_file(tmp_path):
    """Provide a self-contained mock audit file for CLI tests."""
    data = {
        "clerk": {
            "organizations": [
                {
                    "id": "org_3JeWZxDcpdvFmff2fW1nXP7tjm6",
                    "name": "VinUni Admin Org",
                    "slug": "vinuni-admin",
                    "created_at": 1700000000,
                }
            ],
            "total_orgs": 1,
            "users": [
                {
                    "id": "user_real_admin_01",
                    "first_name": "Admin",
                    "last_name": "User",
                    "primary_email": "admin@example.com",
                }
            ],
            "total_users": 1,
            "memberships": [
                {
                    "id": "mem_01",
                    "org_id": "org_3JeWZxDcpdvFmff2fW1nXP7tjm6",
                    "user_id": "user_real_admin_01",
                    "role": "org:admin",
                }
            ],
            "total_memberships": 1,
        },
        "databases": {
            "dev": {
                "migrations_count": 27,
                "latest_migration": "0027_test.sql",
                "organizations": [
                    {
                        "id": "018f2f4e-0000-7000-8000-000000000001",
                        "name": "VinUni Seed",
                        "clerk_org_id": "org_3JeWZxDcpdvFmff2fW1nXP7tjm6",
                    }
                ],
                "real_clerk_principals": [
                    {
                        "id": "018f2f4e-1000-7000-8000-000000000001",
                        "external_subject": "user_real_admin_01",
                        "organization_id": "018f2f4e-0000-7000-8000-000000000001",
                        "roles": ["admin"],
                        "status": "active",
                    }
                ],
                "mock_principals": [],
                "fraud_cases": [],
                "bound_drivers": [],
            }
        },
    }
    file_path = tmp_path / "mock-audit.json"
    file_path.write_text(json.dumps(data), encoding="utf-8")
    return str(file_path)


def test_cli_requires_env(capsys):
    """Verify CLI exits with code 2 if --env is missing."""
    code = main(["--audit"])
    assert code == 2
    captured = capsys.readouterr()
    assert "--env is required" in captured.err


def test_cli_audit_with_snapshot_file(mock_audit_file, capsys):
    """Verify --audit runs read-only with snapshot file and prints sanitized report."""
    code = main(["--audit", "--env", "dev", "--clerk-snapshot-file", mock_audit_file, "--offline"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Identity Reconciliation Plan: dev" in captured.out
    assert "Plan Hash" in captured.out
    assert "postgres://" not in captured.out
    assert "@" not in captured.out


def test_cli_plan_json(mock_audit_file, capsys):
    """Verify --plan --json outputs valid JSON plan without secrets."""
    code = main(["--plan", "--json", "--env", "dev", "--clerk-snapshot-file", mock_audit_file, "--offline"])
    assert code == 0
    captured = capsys.readouterr()
    plan_data = json.loads(captured.out)
    assert plan_data["env"] == "dev"
    assert "plan_hash" in plan_data
    assert "postgres://" not in captured.out


def test_cli_apply_requires_expected_plan_hash(capsys):
    """Verify --apply requires --expected-plan-hash."""
    code = main(["--apply", "--env", "dev", "--allow-live-apply"])
    assert code == 2
    captured = capsys.readouterr()
    assert "--expected-plan-hash is required" in captured.err


def test_cli_apply_refuses_without_explicit_allow(capsys):
    """Verify --apply fails if --allow-live-apply is missing."""
    code = main(["--apply", "--env", "dev", "--expected-plan-hash", "abcdef1234567890"])
    assert code == 1
    captured = capsys.readouterr()
    assert "blocked: --allow-live-apply flag required" in captured.err
