from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from src.services.case_workflow import authorize, build_stepper


def test_status_maps_to_current_step():
    out = build_stepper("report_issued", [])
    states = {s["key"]: s["state"] for s in out["steps"]}
    assert states["REVIEWED"] == "done" and states["REPORT_ISSUED"] == "current"
    assert states["COMPLETED"] == "pending"
    assert out["next"] == {"actor_role": "KSCL", "text": "Depot (KSCL) xác nhận biên bản"}


@pytest.mark.parametrize("st", ["ready", "in_review", "escalated", "pending_analyst_review"])
def test_existing_review_statuses_are_under_review(st):
    cur = [s["key"] for s in build_stepper(st, [])["steps"] if s["state"] == "current"]
    assert cur == ["UNDER_REVIEW"]


def test_completed_all_done_with_timestamp_and_no_next():
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    out = build_stepper("completed", [{"step": "REPORT_CONFIRMED", "created_at": ts}])
    # driver was never asked to explain -> that step is skipped, not done
    assert all(s["state"] == "done" for s in out["steps"] if s["key"] != "NEED_TO_EXPLAIN")
    assert next(s for s in out["steps"] if s["key"] == "REPORT_CONFIRMED")["completed_at"] == ts
    assert out["next"] is None


def test_dismissed_is_closed_without_position():
    out = build_stepper("auto_dismissed", [])
    assert out["closed"] and out["next"] is None
    assert all(s["state"] == "pending" for s in out["steps"])


@pytest.mark.parametrize(
    "action,role",
    [
        ("confirm-report", "reviewer"),
        ("approve-ops", "ops_director"),
        ("approve-marketplace", "marketplace_director"),
        ("issue-report", "fraud_analyst"),
        ("issue-report", "analyst"),
    ],
)
def test_authorize_allowed(action, role):
    assert authorize(action, {role})


@pytest.mark.parametrize(
    "action,role",
    [
        ("confirm-report", "analyst"),
        ("approve-ops", "reviewer"),
        ("approve-marketplace", "ops_director"),
        ("issue-report", "reviewer"),
        ("confirm-report", "driver"),
    ],
)
def test_authorize_denied(action, role):
    with pytest.raises(HTTPException) as e:
        authorize(action, {role})
    assert e.value.status_code == 403


def test_admin_and_unknown_action():
    assert authorize("approve-ops", {"admin"})
    with pytest.raises(HTTPException) as e:
        authorize("nope", {"admin"})
    assert e.value.status_code == 404


def test_auth_known_roles_include_workflow_roles():
    from src.api.auth import WORKFLOW_ORG_ROLES

    assert WORKFLOW_ORG_ROLES == {"reviewer", "ops_director", "marketplace_director"}


def test_allowed_actions_by_status_and_role():
    from src.services.case_workflow import allowed_actions

    assert allowed_actions("report_issued", {"reviewer"}) == ["confirm-report"]
    assert allowed_actions("report_issued", {"analyst"}) == []
    assert allowed_actions("need_ops_dir_approved", {"admin"}) == ["approve-ops"]
    assert allowed_actions("resolved", {"fraud_analyst"}) == ["issue-report"]
