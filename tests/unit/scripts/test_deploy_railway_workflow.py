from pathlib import Path

import yaml


def test_railway_workflow_python_heredocs_compile():
    workflow = yaml.safe_load(Path(".github/workflows/deploy-railway.yml").read_text(encoding="utf-8"))
    heredocs = []
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            run = step.get("run", "")
            lines = run.splitlines()
            for index, line in enumerate(lines):
                if "python3 - <<'PY'" not in line:
                    continue
                body = []
                for candidate in lines[index + 1 :]:
                    if candidate.strip() == "PY":
                        break
                    body.append(candidate)
                else:
                    raise AssertionError("unterminated Python heredoc")
                heredocs.append("\n".join(body))

    assert heredocs
    for source in heredocs:
        compile(source, ".github/workflows/deploy-railway.yml", "exec")


def test_preview_auth_e2e_runs_on_runner_host_with_playwright_browsers():
    workflow = yaml.safe_load(Path(".github/workflows/deploy-vercel.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["preview-real-account-e2e"]

    assert "container" not in job
    install_step = next(step for step in job["steps"] if step.get("name") == "Install webapp dependencies & browsers")
    assert "pnpm exec playwright install chromium" in install_step["run"]
    assert "sudo" not in install_step["run"]
    assert "install-deps" not in install_step["run"]


def test_railway_jobs_use_distribution_aware_docker_setup():
    workflow = yaml.safe_load(Path(".github/workflows/deploy-railway.yml").read_text(encoding="utf-8"))
    for job_name in ("validate-config", "deploy-pr-preview"):
        steps = workflow["jobs"][job_name]["steps"]
        step = next(step for step in steps if step.get("name") == "Ensure Docker and build tools")
        assert step["run"] == "bash scripts/ci/ensure_docker.sh"
