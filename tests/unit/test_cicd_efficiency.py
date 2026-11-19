"""CI efficiency: caches, stale-run cancellation, honest IaC auth paths."""

import pathlib


def _read(p):
    return pathlib.Path(p).read_text()


def test_ci_preserves_active_verification_runs():
    wf = _read(".github/workflows/ci.yml")
    workflow_concurrency = wf.split("concurrency:", 1)[1].split("jobs:", 1)[0]
    assert "cancel-in-progress: false" in workflow_concurrency, (
        "active verification and expensive GIS reruns must finish"
    )


def test_persisted_gis_gate_removed_from_ci():
    wf = _read(".github/workflows/ci.yml")
    assert "test_gis_persisted.sh" not in wf, "issue #61 GIS gate removed from automated CI"


def test_browser_e2e_runs_without_docker():
    wf = _read(".github/workflows/ci.yml")
    browser_job = wf.split("  browser-e2e:", 1)[1].split("\n  build-and-cache:", 1)[0]
    assert "docker_up.sh" not in browser_job, "browser-e2e must not run Docker services"
    assert "ms-playwright" in browser_job, "browser-e2e must cache Playwright browsers"
    assert "actions/download-artifact@v4" in browser_job, "browser-e2e must download build artifact"
    assert ".next-gis" in browser_job, "browser-e2e must download .next-gis build artifact"
    assert "PLAYWRIGHT_SERVER_MODE: start" in browser_job or "PLAYWRIGHT_SERVER_MODE=start" in browser_job, (
        "browser-e2e must run on next start"
    )
    assert "steps.webapp-artifact.outcome != 'success'" in browser_job
    assert 'NEXT_PUBLIC_GIS_OPTIMIZED_TEST: "true"' in browser_job
    assert "run: pnpm build" in browser_job
    assert "=dev" not in browser_job, "browser-e2e must not run in dev server mode"


def test_webapp_build_caches_bundle():
    wf = _read(".github/workflows/ci.yml")
    webapp_job = wf.split("  webapp-build:", 1)[1].split("\n  integration-tests:", 1)[0]
    assert "actions/upload-artifact@v4" in webapp_job, "webapp-build must upload build artifact"
    assert ".next-gis" in webapp_job, "webapp-build must upload .next-gis build artifact"
    assert "if-no-files-found: error" in webapp_job, "webapp-build must fail if no files are found"
    assert "pnpm build" in webapp_job, "webapp-build must run pnpm build"
    assert "NEXT_PUBLIC_GIS_OPTIMIZED_TEST" in webapp_job, (
        "webapp-build must set NEXT_PUBLIC_GIS_OPTIMIZED_TEST for isolated GIS build escape hatch"
    )
    assert "src/webapp/**/*.ts" not in webapp_job, (
        "cache post-step must not hash the full source tree on slow self-hosted runners"
    )
    assert "timeout-minutes: 35" in webapp_job, "webapp-build must tolerate I/O delays on shared self-hosted runners"


def test_playwright_config_server_mode():
    cfg = _read("src/webapp/playwright.config.ts")
    assert "PLAYWRIGHT_SERVER_MODE" in cfg
    assert "next start" in cfg
    assert "CI ? 1 : 0" in cfg


def test_integration_job_skips_node_toolchain():
    wf = _read(".github/workflows/ci.yml")
    integration_job = wf.split("  integration-tests:", 1)[1].split("\n  browser-e2e:", 1)[0]
    assert "pnpm" not in integration_job, "integration-tests should not setup or run pnpm"
    assert "playwright" not in integration_job, "integration-tests should not setup or run Playwright"


def test_agent_suites_run_in_unit_tests():
    wf = _read(".github/workflows/ci.yml")
    assert "agent-tests:" not in wf


def test_ci_caches_pnpm_store():
    wf = _read(".github/workflows/ci.yml")
    assert "pnpm-lock.yaml" in wf and "cache" in wf, "pnpm installs must hit a lockfile-keyed cache"


def test_ci_caches_playwright_browsers():
    wf = _read(".github/workflows/ci.yml")
    assert "ms-playwright" in wf, "chromium downloads must be cached between runs"


def test_ci_caches_uv_packages():
    wf = _read(".github/workflows/ci.yml")
    assert "astral-sh/setup-uv" in wf, "uv must come from setup-uv (guaranteed on PATH)"
    assert "UV_CACHE_DIR" in wf and "greensentinel-uv-cache" in wf, (
        "uv cache must live in an isolated per-run dir, not shared ~/.cache/uv"
    )


def test_unit_tests_use_uv_run_with_preflight():
    wf = _read(".github/workflows/ci.yml")
    assert "uv run --python .venv" in wf, "pytest must run via uv run, not a bare .venv path"
    assert "Verify Python test environment" in wf, "a preflight step must surface interpreter errors"
    unit_job = wf.split("  unit-tests:", 1)[1].split("\n  frontend-vitest:", 1)[0]
    assert "-X importtime" not in unit_job, "unit tests must not flood shared runners with import traces"
    assert "tests/unit/ -q -n 1" in unit_job
    assert "--maxWorkers=2 --minWorkers=1" in wf
    assert "timeout-minutes: 45" in wf


def test_vercel_workflow_caches_pnpm_store():
    wf = _read(".github/workflows/deploy-vercel.yml")
    assert "pnpm-lock.yaml" in wf and "cache" in wf


def test_actions_run_on_supported_node_runtime():
    for wf_file in (
        ".github/workflows/ci.yml",
        ".github/workflows/deploy-railway.yml",
        ".github/workflows/deploy-vercel.yml",
    ):
        wf = _read(wf_file)
        assert "actions/checkout@v4" not in wf, f"{wf_file} still pins node20 checkout"
        assert "actions/setup-node@v4" not in wf, f"{wf_file} still pins node20 setup-node"
        assert "actions/cache@v4" not in wf, f"{wf_file} still pins node20 cache"


def test_qdrant_image_pinned():
    compose = _read("docker-compose.yml")
    docker_up = _read("scripts/docker_up.sh")
    assert "qdrant/qdrant:latest" not in compose, "docker-compose.yml must not use latest tag for qdrant"
    assert "qdrant/qdrant:latest" not in docker_up, "scripts/docker_up.sh must not use latest tag for qdrant"
    assert "qdrant/qdrant:v1.19.1" in compose
    assert "qdrant/qdrant:v1.19.1" in docker_up


def test_backend_image_build_uses_layer_cache():
    wf = _read(".github/workflows/ci.yml")
    assert "cache-from: type=gha" in wf, "ci.yml must configure GitHub Actions cache for docker build"
    build_job = wf.split("  build-and-cache:", 1)[1]
    assert "docker/setup-buildx-action" in build_job
    assert "docker/build-push-action" in build_job
    assert "cache-to: type=gha" in build_job


def test_no_self_hosted_or_oci_references():
    import glob

    for path in glob.glob(".github/**/*.yml", recursive=True):
        wf = _read(path)
        assert "self-hosted" not in wf, path
        assert "OCI_" not in wf, path
