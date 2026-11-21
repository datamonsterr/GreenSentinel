"""Status -> stepper mapping table (every fraud_cases.status / dispute_status combination)."""

from datetime import UTC, datetime

import pytest

from src.services.case_workflow import build_stepper

T = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)


def _states(out):
    return {s["key"]: s["state"] for s in out["steps"]}


def _current(out):
    return [s["key"] for s in out["steps"] if s["state"] == "current"]


# status, dispute_status, expected current step (None = no position), next actor (None = no callout)
TABLE = [
    ("ingested", "not_disputed", "UNDER_REVIEW", "KSGL"),
    ("processing", "not_disputed", "UNDER_REVIEW", "KSGL"),
    ("ready", "not_disputed", "UNDER_REVIEW", "KSGL"),
    ("in_review", "not_disputed", "UNDER_REVIEW", "KSGL"),
    ("in_review", "pending", "UNDER_REVIEW", "KSGL"),
    ("escalated", "not_disputed", "UNDER_REVIEW", "KSGL"),
    ("pending_analyst_review", "pending_review", "UNDER_REVIEW", "KSGL"),
    ("evidence_requested", "pending", "NEED_TO_EXPLAIN", "TX"),
    ("evidence_requested", "not_disputed", "NEED_TO_EXPLAIN", "TX"),
    ("evidence_requested", "in_dispute", "UNDER_REVIEW", "KSGL"),  # driver already submitted
    ("driver_disputed", "in_dispute", "UNDER_REVIEW", "KSGL"),
    ("driver_disputed", "analyst_escalated", "UNDER_REVIEW", "KSGL"),
    ("pending_driver_confirmation", "pending_confirmation", "NEED_TO_EXPLAIN", "TX"),
    ("driver_confirmed_resolution", "not_disputed", "REVIEWED", "KSGL"),
    ("resolved", "not_disputed", "REVIEWED", "KSGL"),
    ("suspended", "not_disputed", "REVIEWED", "KSGL"),
    ("report_issued", "not_disputed", "REPORT_ISSUED", "KSCL"),
    ("report_confirmed", "not_disputed", "REPORT_CONFIRMED", "OPS_DIR"),
    ("need_ops_dir_approved", "not_disputed", "NEED_OPS_DIR_APPROVED", "OPS_DIR"),
    ("need_mkp_dir_approved", "not_disputed", "NEED_MKP_DIR_APPROVED", "MKP_DIR"),
    ("completed", "not_disputed", None, None),
    ("auto_dismissed", "auto_dismissed", None, None),
    ("dismissed", "not_disputed", None, None),
    ("closed", "not_disputed", None, None),
    ("processing_failed", "not_disputed", None, None),
    (None, None, None, None),
    ("something_new", None, None, None),
]


@pytest.mark.parametrize("status,dispute,cur,actor", TABLE)
def test_status_table(status, dispute, cur, actor):
    out = build_stepper(status, [], T, dispute_status=dispute)
    assert _current(out) == ([cur] if cur else [])
    assert (out["next"]["actor_role"] if out["next"] else None) == actor
    assert out["closed"] is (status in {"auto_dismissed", "dismissed", "closed"})


def test_driver_submitted_text_differs_from_review_text():
    sub = build_stepper("driver_disputed", [], T, dispute_status="in_dispute")["next"]["text"]
    plain = build_stepper("in_review", [], T)["next"]["text"]
    assert sub != plain and "giải trình" in sub


def test_explain_step_done_with_driver_timestamp_when_driver_submitted():
    ts = {"NEED_TO_EXPLAIN": datetime(2026, 1, 3, tzinfo=UTC)}
    out = build_stepper("driver_disputed", [], T, dispute_status="in_dispute", timestamps=ts)
    s = out["steps"][0]
    assert s["state"] == "done" and s["completed_at"] == ts["NEED_TO_EXPLAIN"]


def test_explain_step_skipped_when_driver_never_asked():
    out = build_stepper("in_review", [], T, dispute_status="not_disputed")
    assert _states(out)["NEED_TO_EXPLAIN"] == "skipped"
    assert out["steps"][0]["completed_at"] is None


def test_explain_step_not_stamped_with_case_creation_time():
    out = build_stepper("resolved", [], T, dispute_status="not_disputed")
    assert out["steps"][0]["state"] == "skipped" and out["steps"][0]["completed_at"] is None


def test_under_review_and_reviewed_use_review_and_adjudication_timestamps():
    ts = {"UNDER_REVIEW": datetime(2026, 2, 1, tzinfo=UTC), "REVIEWED": datetime(2026, 2, 2, tzinfo=UTC)}
    out = build_stepper("report_issued", [], T, timestamps=ts)
    by = {s["key"]: s for s in out["steps"]}
    assert by["UNDER_REVIEW"]["completed_at"] == ts["UNDER_REVIEW"]
    assert by["REVIEWED"]["completed_at"] == ts["REVIEWED"]


def test_completed_marks_everything_after_explain_done():
    out = build_stepper("completed", [], T, dispute_status="not_disputed")
    st = _states(out)
    assert st["NEED_TO_EXPLAIN"] == "skipped"
    assert all(v == "done" for k, v in st.items() if k != "NEED_TO_EXPLAIN")


def test_closed_case_shows_no_position():
    out = build_stepper("closed", [], T)
    assert out["closed"] and set(_states(out).values()) <= {"pending", "skipped"}
