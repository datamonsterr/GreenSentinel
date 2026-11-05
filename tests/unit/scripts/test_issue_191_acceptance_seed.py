from pathlib import Path

import yaml

from scripts.enrich_demo_data import (
    ISSUE_191_ASSIGNMENT_ID,
    ISSUE_191_CASE_ID,
    ISSUE_191_PEER_ASSIGNMENT_IDS,
    ISSUE_191_PEER_SPEEDS_MPS,
    ISSUE_191_PEER_TRIP_IDS,
)

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent


def test_issue_191_acceptance_seed_has_three_independent_peer_trips():
    assert ISSUE_191_CASE_ID != ISSUE_191_ASSIGNMENT_ID
    assert len(ISSUE_191_PEER_TRIP_IDS) == 3
    assert len(set(ISSUE_191_PEER_TRIP_IDS)) == 3
    assert len(ISSUE_191_PEER_ASSIGNMENT_IDS) == 3
    assert len(set(ISSUE_191_PEER_ASSIGNMENT_IDS)) == 3
    assert ISSUE_191_ASSIGNMENT_ID not in ISSUE_191_PEER_ASSIGNMENT_IDS
    assert len(ISSUE_191_PEER_SPEEDS_MPS) == 3
    assert all(speed > 0 for speed in ISSUE_191_PEER_SPEEDS_MPS)


def test_dev_acceptance_seed_is_explicit_and_never_targets_staging_or_production():
    workflow = yaml.safe_load((ROOT_DIR / ".github/workflows/deploy-railway.yml").read_text(encoding="utf-8"))
    step = next(
        item
        for item in workflow["jobs"]["deploy-dev"]["steps"]
        if item.get("name") == "Seed Issue 191 acceptance data in Dev"
    )

    assert "workflow_dispatch" in step["if"]
    assert "target_env == 'dev'" in step["if"]
    assert "seed_issue_191_acceptance == true" in step["if"]
    assert "--allow-remote-seed" in step["run"]
