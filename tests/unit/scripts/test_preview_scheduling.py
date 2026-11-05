"""Sequence backend/frontend previews on a single available runner."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def test_backend_preview_calls_vercel_after_railway_completion():
    vercel = yaml.safe_load((ROOT / ".github/workflows/deploy-vercel.yml").read_text())["jobs"]
    railway = yaml.safe_load((ROOT / ".github/workflows/deploy-railway.yml").read_text())["jobs"]
    caller = railway["deploy-vercel-pr-preview"]
    assert caller["needs"] == ["deploy-pr-preview"]
    assert caller["uses"] == "./.github/workflows/deploy-vercel.yml"
    assert caller["with"]["railway_ready"] is True
    assert caller["secrets"] == "inherit"
    assert "always()" not in caller["if"]
    assert vercel["deploy-preview"]["runs-on"] == "self-hosted"
    assert not any(
        "wait-provisioning" in step.get("run", "") for job in vercel.values() for step in job.get("steps", [])
    )


def test_frontend_only_preview_does_not_require_backend_provisioning():
    workflow = yaml.safe_load((ROOT / ".github/workflows/deploy-vercel.yml").read_text())
    jobs = workflow["jobs"]
    trigger = workflow.get("on", workflow.get(True))
    assert trigger["workflow_call"]["inputs"]["railway_ready"]["type"] == "boolean"
    assert trigger["workflow_call"]["inputs"]["railway_ready"]["default"] is False
    assert jobs["deploy-preview"]["needs"] == ["classify-pr"]
    condition = jobs["deploy-preview"]["if"]
    assert "inputs.railway_ready == true" in condition
    assert "needs.classify-pr.outputs.frontend == 'true'" in condition
    assert "needs.classify-pr.outputs.backend != 'true'" in condition
