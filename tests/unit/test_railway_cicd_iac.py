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


def test_code_deploy_helper_waits_for_success():
    script = _read("scripts/railway_deploy_code.sh")
    assert "railway up" in script, "code deploys upload the checked-out tree"
    assert "SUCCESS" in script, "helper must gate on the deployment reaching SUCCESS"
    assert "FAILED|CRASHED|REMOVED|SKIPPED" in script, "failed deployments must fail the job"
    assert "env -u RAILWAY_TOKEN" in script, (
        "uploads run with the project token, the credential authorize_preview.sh already proves"
    )
