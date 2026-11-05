"""CI must apply IaC saved plans *and* ship the checkout, gated on deployment SUCCESS.

`railway config apply` writes configuration only. A job that applies a plan and
stops can report success while the service keeps running an older build, which
is how staging's 2026-10-12 backend met a newer frontend and rendered "Access
denied" for every signed-in user on 2026-10-15.
"""

import pathlib

import yaml


def _read(p):
    return pathlib.Path(p).read_text()


def _jobs():
    return yaml.safe_load(_read(".github/workflows/deploy-railway.yml"))["jobs"]


def _job(name):
    return yaml.safe_dump(_jobs()[name])


def test_persistent_envs_use_config_apply():
    wf = _read(".github/workflows/deploy-railway.yml")
    assert "railway config plan" in wf, "CI must run config plan"
    assert "railway config apply" in wf, "CI must apply IaC plan for dev/staging/prod"


def test_drift_gate_exists():
    wf = _read(".github/workflows/deploy-railway.yml")
    assert "detailed-exit-code" in wf, "CI needs drift gate (config plan --detailed-exit-code)"


def test_persistent_envs_refuse_test_auth():
    wf = _read(".github/workflows/deploy-railway.yml")
    assert "TEST_AUTH_ENABLED" in wf, "CI must guard hosted envs against fixture auth"
    assert "APP_ENV" in wf


def test_persistent_envs_ship_code_after_config_apply():
    for job_name in ("deploy-dev", "deploy-staging", "deploy-production"):
        job = _job(job_name)
        assert "railway config apply --plan" in job, f"{job_name} must apply the saved plan"
        assert "scripts/railway_deploy_code.sh" in job, (
            f"{job_name} must deploy application code: config apply ships no source"
        )
        apply_at = job.index("railway config apply --plan")
        deploy_at = job.index("scripts/railway_deploy_code.sh")
        assert deploy_at > apply_at, f"{job_name} must deploy code after the plan applies"


def test_code_deploy_helper_waits_for_success():
    script = _read("scripts/railway_deploy_code.sh")
    assert "railway up" in script, "code deploys upload the checked-out tree"
    assert "SUCCESS" in script, "helper must gate on the deployment reaching SUCCESS"
    assert "FAILED|CRASHED|REMOVED|SKIPPED" in script, "failed deployments must fail the job"
    assert "env -u RAILWAY_TOKEN" in script, (
        "uploads run with the project token, the credential authorize_preview.sh already proves"
    )


def test_staging_smoke_gates_on_account_settings_contract():
    smoke = next(step for step in _jobs()["deploy-staging"]["steps"] if "Smoke Test" in str(step.get("name", "")))
    run = smoke["run"]
    assert 'python3 scripts/staging_smoke.py --api-url "${STAGING_API_URL}"' in run
    assert "simulate_trip_stream.py" not in run, "the simulator defaults to local, infinite work"
    assert "|| true" not in run, "a broken staging contract must fail the deployment gate"
    assert not smoke.get("continue-on-error", False)
    assert 0 < smoke["timeout-minutes"] <= 4, "the smoke step must have a hard deadline"
    assert "STAGING_API_URL" in smoke["env"]
    assert "Synthetic" not in _jobs()["deploy-staging"]["name"]
