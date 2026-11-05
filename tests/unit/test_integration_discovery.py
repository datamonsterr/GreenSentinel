"""Tests for dynamic integration test discovery via pytest docker marker."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

PREVIOUSLY_LISTED_FILES = [
    "tests/integration/test_database_seed.py",
    "tests/integration/services/test_database_health.py",
    "tests/integration/services/test_queue_worker.py",
    "tests/integration/services/test_reliable_telemetry.py",
    "tests/integration/services/test_case_agent_sessions.py",
    "tests/integration/services/test_case_workspace.py",
    "tests/integration/services/test_guardrail_integration.py",
    "tests/integration/services/test_telemetry_routes_traffic.py",
    "tests/integration/test_chat_ui_contract.py",
    "tests/integration/test_telemetry_schema_accuracy.py",
    "tests/integration/services/test_canonical_tool_execution.py",
    "tests/integration/services/test_agent_workflow_service.py",
    "tests/integration/api/test_agent_workflow_routes.py",
    "tests/integration/agents/test_runtime_tool_boundary.py",
    "tests/integration/api/test_agent_runtime_persistence.py",
    "tests/integration/api/test_tool_runtime_api.py",
    "tests/integration/services/test_precedent_history_integration.py",
    "tests/integration/test_db_schema_parity_integration.py",
    "tests/integration/api/test_org_auth_regressions.py",
    "tests/integration/services/test_real_driver_db_integration.py",
    "tests/integration/scripts/test_postgis_preview_migration_integration.py",
]


def test_integration_script_discovery():
    script_text = (REPO_ROOT / "scripts/test_integration.sh").read_text(encoding="utf-8")
    assert "-m docker" in script_text, "test_integration.sh must discover tests via -m docker"
    assert "tests/integration/services/" not in script_text, (
        "test_integration.sh must not contain hardcoded tests/integration/services/ paths"
    )


def test_previously_listed_files_have_docker_marker():
    for rel_path in PREVIOUSLY_LISTED_FILES:
        file_path = REPO_ROOT / rel_path
        if file_path.exists():
            content = file_path.read_text(encoding="utf-8")
            assert "pytest.mark.docker" in content, f"Expected {rel_path} to contain 'pytest.mark.docker'"


def test_no_orphan_integration_suites():
    # Rationale: other integration suites are intentionally outside the required CI gate.
    scan_dirs = [
        REPO_ROOT / "tests/integration/agents",
        REPO_ROOT / "tests/integration/rag",
    ]
    orphans = []
    for scan_dir in scan_dirs:
        for test_file in sorted(scan_dir.rglob("test_*.py")):
            if "_live" in test_file.name:
                continue
            content = test_file.read_text(encoding="utf-8")
            if "pytest.mark.docker" not in content and "pytest.mark.live" not in content:
                orphans.append(str(test_file.relative_to(REPO_ROOT)))
    assert not orphans, f"Found orphan integration suites without docker/live marker or _live filename: {orphans}"
