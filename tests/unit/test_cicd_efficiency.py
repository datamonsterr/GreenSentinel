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


def test_docker_integration_queue_does_not_replace_pending_ci():
    wf = _read(".github/workflows/ci.yml")
    docker_job = wf.split("  integration-tests:", 1)[1].split("\n  browser-e2e:", 1)[0]
    concurrency = docker_job.split("\n    concurrency:", 1)[1].split("\n    env:", 1)[0]
    assert "group: greensentinel-docker-services" in concurrency
    assert "queue: max" in concurrency, (
        "required integration runs must queue instead of replacing an existing pending Docker job"
    )
    assert "cancel-in-progress: false" in concurrency, "Docker-backed verification must remain serialized"


def test_persisted_gis_gate_removed_from_ci():
    wf = _read(".github/workflows/ci.yml")
    assert "test_gis_persisted.sh" not in wf, "issue #61 GIS gate removed from automated CI"


def test_browser_e2e_runs_without_docker():
    wf = _read(".github/workflows/ci.yml")
    browser_job = wf.split("  browser-e2e:", 1)[1].split("\n  build-and-cache:", 1)[0]
    assert "docker_up.sh" not in browser_job, "browser-e2e must not run Docker services"
    assert "rm -rf /target/src/webapp/node_modules" in browser_job
    assert "ms-playwright" in browser_job, "browser-e2e must cache Playwright browsers"
    assert "oci-download" in browser_job, "browser-e2e must download build artifact from OCI"
    assert ".next-gis" in browser_job, "browser-e2e must download .next-gis build artifact"
    assert "PLAYWRIGHT_SERVER_MODE: start" in browser_job or "PLAYWRIGHT_SERVER_MODE=start" in browser_job, (
        "browser-e2e must run on next start"
    )
    assert "steps.webapp-artifact.outputs.downloaded != 'true'" in browser_job
    assert 'NEXT_PUBLIC_GIS_OPTIMIZED_TEST: "true"' in browser_job
    assert "run: pnpm build" in browser_job
    assert "=dev" not in browser_job, "browser-e2e must not run in dev server mode"


def test_webapp_build_caches_bundle():
    wf = _read(".github/workflows/ci.yml")
    webapp_job = wf.split("  webapp-build:", 1)[1].split("\n  integration-tests:", 1)[0]
    assert "rm -rf /target/src/webapp/node_modules" in webapp_job
    assert "oci-upload" in webapp_job, "webapp-build must upload build artifact to OCI"
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


def test_frontend_vitest_removes_root_owned_dependencies_before_checkout():
    wf = _read(".github/workflows/ci.yml")
    frontend_job = wf.split("  frontend-vitest:", 1)[1].split("\n  webapp-build:", 1)[0]
    cleanup = frontend_job.index("rm -rf /target/src/webapp/node_modules")
    checkout = frontend_job.index("actions/checkout")
    assert cleanup < checkout


def test_preview_real_account_e2e_uses_runner_host_for_playwright():
    import yaml

    job = yaml.safe_load(_read(".github/workflows/deploy-vercel.yml"))["jobs"]["preview-real-account-e2e"]
    assert "container" not in job
    install_index = next(
        index
        for index, step in enumerate(job["steps"])
        if "pnpm exec playwright install chromium" in step.get("run", "")
    )
    auth_index = next(index for index, step in enumerate(job["steps"]) if step.get("id") == "auth-e2e")
    assert install_index < auth_index


def test_ci_repairs_root_owned_git_metadata_before_checkout():
    wf = _read(".github/workflows/ci.yml")
    jobs = (
        "format-and-lint",
        "unit-tests",
        "frontend-vitest",
        "webapp-build",
        "integration-tests",
        "browser-e2e",
        "build-and-cache",
    )
    for index, job_name in enumerate(jobs):
        job = wf.split(f"  {job_name}:", 1)[1]
        if index + 1 < len(jobs):
            job = job.split(f"\n  {jobs[index + 1]}:", 1)[0]
        repair = job.find('chown -R "$(id -u):$(id -g)" /target/.git')
        if repair < 0:
            repair = job.index("chown -R '\"$(id -u):$(id -g)\"' /target")
        checkout = job.index("actions/checkout")
        assert repair < checkout, f"{job_name} must repair .git ownership before checkout"


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


def test_vercel_preview_repairs_root_owned_workspace_before_checkout():
    wf = _read(".github/workflows/deploy-vercel.yml")
    preview_job = wf.split("  deploy-preview:", 1)[1].split("\n  preview-real-account-e2e:", 1)[0]
    cleanup = preview_job.index("chown -R")
    checkout = preview_job.index("actions/checkout")
    assert "rm -rf /target/src/webapp/node_modules /target/src/webapp/test-results" in preview_job
    assert cleanup < checkout


def test_railway_checkout_jobs_repair_root_owned_frontend_workspace():
    wf = _read(".github/workflows/deploy-railway.yml")
    jobs = ("validate-config", "iac-drift", "classify-pr")
    for index, job_name in enumerate(jobs):
        job = wf.split(f"  {job_name}:", 1)[1]
        if index + 1 < len(jobs):
            job = job.split(f"\n  {jobs[index + 1]}:", 1)[0]
        cleanup = job.index("rm -rf /target/src/webapp/node_modules /target/src/webapp/test-results")
        checkout = job.index("actions/checkout")
        assert cleanup < checkout, f"{job_name} must clean frontend workspace before checkout"
        assert "chown -R '\"$(id -u):$(id -g)\"' /target" in job


def test_railway_deploys_prefer_token_plans_with_documented_fallback():
    wf = _read(".github/workflows/deploy-railway.yml")
    assert "RAILWAY_TOKEN" in wf, "persistent deploys must use env-scoped tokens for config apply"
    assert "railway config apply --plan" in wf
    assert "Add RAILWAY_TOKEN" in wf or "RAILWAY_TOKEN_" in wf, (
        "missing-token path must tell how to enable code-deploys"
    )


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
        assert "actions/upload-artifact@v4" not in wf, f"{wf_file} still pins node20 upload-artifact"


def test_all_ci_artifacts_use_oci_actions():
    for wf_file in (".github/workflows/ci.yml", ".github/workflows/ci-draft.yml", ".github/workflows/ci_rag.yml"):
        wf = _read(wf_file)
        assert "actions/upload-artifact" not in wf
        assert "actions/download-artifact" not in wf


def test_preview_deploy_pins_backend_runtime_env():
    wf = _read(".github/workflows/deploy-vercel.yml")
    assert '-e "API_BASE_URL' in wf or "-e 'API_BASE_URL" in wf, (
        "preview deployments must carry the scoped backend at runtime "
        "(.vercel/.env.preview.local is build-time only; middleware reads runtime env)"
    )


def test_drift_gate_tolerates_pending_plans_on_prs():
    wf = _read(".github/workflows/deploy-railway.yml")
    assert "detailed-exit-code" in wf
    assert "eq 2" in wf and "pull_request" in wf, "PRs that change .railway/ legitimately show pending plans"


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


def test_all_workflow_jobs_use_self_hosted_runners():
    import yaml

    for path in pathlib.Path(".github/workflows").iterdir():
        if path.suffix not in {".yml", ".yaml"}:
            continue
        workflow = yaml.safe_load(path.read_text())
        for job_name, job in workflow["jobs"].items():
            if "uses" in job:
                continue  # Reusable workflows select runners in their own jobs.
            selector = job.get("runs-on")
            labels = selector.get("labels", []) if isinstance(selector, dict) else selector
            labels = [labels] if isinstance(labels, str) else labels
            assert labels and "self-hosted" in labels, f"{path}:{job_name} selects {selector!r}"
