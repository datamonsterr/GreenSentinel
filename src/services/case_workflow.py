"""GSM case workflow stepper + post-adjudication transitions (ADR-031).

Pure helpers (`build_stepper`, `TRANSITIONS`) plus a small DB layer. Existing
statuses map onto reference steps; only the report/approval stages are new.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import HTTPException

# step key, actor role (reference code), Vietnamese label
STEPS: list[tuple[str, str, str]] = [
    ("NEED_TO_EXPLAIN", "TX", "Cần giải trình"),
    ("UNDER_REVIEW", "KSGL", "Đang thẩm định"),
    ("REVIEWED", "KSGL", "Đã thẩm định"),
    ("REPORT_ISSUED", "System", "Đã phát hành biên bản"),
    ("REPORT_CONFIRMED", "KSCL", "Depot xác nhận"),
    ("NEED_OPS_DIR_APPROVED", "OPS_DIR", "Chờ OPS DIR duyệt"),
    ("NEED_MKP_DIR_APPROVED", "MKP_DIR", "Chờ MKP DIR duyệt"),
    ("COMPLETED", "System", "Hoàn tất"),
]
STEP_KEYS = [s[0] for s in STEPS]

# our status -> the *current* step. Unlisted -> None (no stepper position).
STATUS_STEP: dict[str, str] = {
    "evidence_requested": "NEED_TO_EXPLAIN",
    "driver_disputed": "UNDER_REVIEW",  # driver already submitted; analyst reviews the explanation
    "ingested": "UNDER_REVIEW",
    "processing": "UNDER_REVIEW",
    "ready": "UNDER_REVIEW",
    "in_review": "UNDER_REVIEW",
    "escalated": "UNDER_REVIEW",
    "pending_analyst_review": "UNDER_REVIEW",
    "pending_driver_confirmation": "NEED_TO_EXPLAIN",  # driver asked to confirm/explain
    "driver_confirmed_resolution": "REVIEWED",
    "resolved": "REVIEWED",
    "suspended": "REVIEWED",  # sanction outcome of an adjudicated case
    "report_issued": "REPORT_ISSUED",
    "report_confirmed": "REPORT_CONFIRMED",
    "need_ops_dir_approved": "NEED_OPS_DIR_APPROVED",
    "need_mkp_dir_approved": "NEED_MKP_DIR_APPROVED",
    "completed": "COMPLETED",
}
CLOSED_STATUSES = frozenset({"auto_dismissed", "dismissed", "closed"})
# dispute_status values meaning the driver has already answered (case waits on analysts)
DRIVER_ANSWERED = frozenset({"in_dispute", "pending_review", "analyst_escalated"})
# statuses where the driver was asked / has answered, even without a timestamp row
EXPLAIN_STATUSES = frozenset({"evidence_requested", "driver_disputed", "pending_driver_confirmation"})

NEXT_ACTOR_TEXT: dict[str, tuple[str, str]] = {
    "NEED_TO_EXPLAIN": ("TX", "Tài xế giải trình"),
    "UNDER_REVIEW": ("KSGL", "Kiểm soát gian lận thẩm định"),
    "REVIEWED": ("KSGL", "Phát hành biên bản"),
    "REPORT_ISSUED": ("KSCL", "Depot (KSCL) xác nhận biên bản"),
    "REPORT_CONFIRMED": ("OPS_DIR", "Giám đốc vận hành duyệt"),
    "NEED_OPS_DIR_APPROVED": ("OPS_DIR", "Giám đốc vận hành duyệt"),
    "NEED_MKP_DIR_APPROVED": ("MKP_DIR", "Admin (Giám đốc Marketplace) duyệt"),
}
NEXT_ACTOR_DRIVER_ANSWERED = ("KSGL", "Kiểm soát gian lận xem xét giải trình của tài xế")


@dataclass(frozen=True)
class Transition:
    from_status: str
    to_status: str
    step: str  # step completed by this action (recorded in history)
    actor_role: str  # reference role code recorded with the event
    roles: tuple[str, ...]  # backend roles allowed (admin always allowed)


TRANSITIONS: dict[str, Transition] = {
    "issue-report": Transition(
        "resolved", "report_issued", "REPORT_ISSUED", "KSGL", ("analyst", "fraud_analyst", "senior_analyst")
    ),
    "confirm-report": Transition("report_issued", "need_ops_dir_approved", "REPORT_CONFIRMED", "KSCL", ("reviewer",)),
    "approve-ops": Transition(
        "need_ops_dir_approved", "need_mkp_dir_approved", "NEED_OPS_DIR_APPROVED", "OPS_DIR", ("ops_director",)
    ),
    "approve-marketplace": Transition(
        "need_mkp_dir_approved",
        "completed",
        "NEED_MKP_DIR_APPROVED",
        "MKP_DIR",
        ("marketplace_director",),  # admin acts as MKP director
    ),
}


def build_stepper(
    status: str | None,
    events: list[dict[str, Any]],
    created_at: datetime | None = None,
    dispute_status: str | None = None,
    timestamps: dict[str, datetime] | None = None,
) -> dict[str, Any]:
    """Stepper payload: per-step state (done/current/pending/skipped) + next actor.

    `timestamps` carries step times from sources other than workflow events
    (driver submission / evidence request -> NEED_TO_EXPLAIN, first review action -> UNDER_REVIEW,
    adjudication -> REVIEWED). `created_at` is accepted for compatibility but never used as a step time.
    """
    status = (status or "").lower()
    dispute = (dispute_status or "").lower()
    closed = status in CLOSED_STATUSES
    current_key = None if closed else STATUS_STEP.get(status)
    if status == "evidence_requested" and dispute in DRIVER_ANSWERED:
        current_key = "UNDER_REVIEW"
    cur = STEP_KEYS.index(current_key) if current_key else -1
    done_at = dict(timestamps or {})
    done_at.update({e["step"]: e["created_at"] for e in events})
    explained = (
        "NEED_TO_EXPLAIN" in done_at
        or status in EXPLAIN_STATUSES
        or dispute not in ("", "not_disputed")
    )
    steps = []
    for i, (key, actor, label) in enumerate(STEPS):
        if cur >= 0 and i < cur:
            state = "done" if key != "NEED_TO_EXPLAIN" or explained else "skipped"
        elif i == cur:
            state = "done" if status == "completed" else "current"
        else:
            state = "pending"
        steps.append(
            {
                "key": key,
                "label": label,
                "actor_role": actor,
                "state": state,
                "completed_at": done_at.get(key) if state == "done" else None,
            }
        )
    nxt = None
    if current_key and status != "completed":
        nxt = NEXT_ACTOR_TEXT.get(current_key)
        if current_key == "UNDER_REVIEW" and (status == "driver_disputed" or dispute in DRIVER_ANSWERED):
            nxt = NEXT_ACTOR_DRIVER_ANSWERED
    return {
        "status": status,
        "closed": closed,
        "steps": steps,
        "next": {"actor_role": nxt[0], "text": nxt[1]} if nxt else None,
    }


WORKFLOW_ROLES = frozenset({"reviewer", "ops_director", "marketplace_director"})


# role -> the status in which the case awaits that role's approval step
AWAITING_STATUS = {
    "reviewer": "report_issued",
    "ops_director": "need_ops_dir_approved",
    "marketplace_director": "need_mkp_dir_approved",
}


def is_workflow_only(roles: frozenset[str] | set[str]) -> bool:
    """True for principals holding a workflow role but no analyst/admin role (read-only case access)."""
    r = set(roles)
    return bool(r & WORKFLOW_ROLES) and not r & {"admin", "analyst", "fraud_analyst", "senior_analyst"}


def awaiting_status(roles: frozenset[str] | set[str]) -> str | None:
    """Step queue for the caller. Admin is the MKP director (last step); analysts have none."""
    if "admin" in roles:
        return "need_mkp_dir_approved"
    if set(roles) & {"analyst", "fraud_analyst", "senior_analyst"}:
        return None
    for r, st in AWAITING_STATUS.items():
        if r in roles:
            return st
    return None


def allowed_actions(status: str | None, roles: frozenset[str] | set[str]) -> list[str]:
    """Workflow actions the caller may take on a case in `status` (drives UI buttons)."""
    return [a for a, t in TRANSITIONS.items() if t.from_status == (status or "") and set(roles) & {"admin", *t.roles}]


def authorize(action: str, principal_roles: frozenset[str] | set[str]) -> Transition:
    t = TRANSITIONS.get(action)
    if t is None:
        raise HTTPException(404, f"Unknown workflow action '{action}'")
    if not (set(principal_roles) & {"admin", *t.roles}):
        raise HTTPException(403, f"Role not permitted for workflow action '{action}'")
    return t


def load_stepper(conn_factory: Callable[[], Any], case_id: str, organization_id: str) -> dict[str, Any]:
    conn = conn_factory()
    if conn is None:
        raise HTTPException(503, "Database unavailable")
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            cur.execute(
                "SELECT status, dispute_status, created_at FROM app.fraud_cases WHERE id::text = %s AND organization_id::text = %s",
                (case_id, organization_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Case not found")
            cur.execute(
                "SELECT approved_at FROM app.adjudications WHERE case_id::text = %s",
                (case_id,),
            )
            adj = cur.fetchone()
            cur.execute(
                """SELECT
                     (SELECT max(received_at) FROM app.driver_submissions WHERE case_id::text = %s) AS driver_at,
                     (SELECT min(created_at) FROM app.review_actions
                        WHERE case_id::text = %s AND action = 'request_evidence') AS asked_at,
                     (SELECT min(created_at) FROM app.review_actions WHERE case_id::text = %s) AS review_at""",
                (case_id, case_id, case_id),
            )
            tsr = cur.fetchone() or {}
            cur.execute(
                """SELECT e.step, e.created_at, e.actor_role, p.display_name
                   FROM app.case_workflow_events e LEFT JOIN app.principals p ON p.id = e.actor_id
                   WHERE e.case_id::text = %s ORDER BY e.created_at""",
                (case_id,),
            )
            events = [
                {
                    "step": r["step"],
                    "created_at": r["created_at"],
                    "actor_role": r["actor_role"],
                    "actor_name": r["display_name"],
                }
                for r in cur.fetchall()
            ]
        if row["status"] == "completed" and events:
            events.append(
                {
                    "step": "COMPLETED",
                    "created_at": events[-1]["created_at"],
                    "actor_role": "System",
                    "actor_name": None,
                }
            )
        if adj and not any(e["step"] == "REVIEWED" for e in events):
            events.append(
                {"step": "REVIEWED", "created_at": adj["approved_at"], "actor_role": "KSGL", "actor_name": None}
            )
        ts: dict[str, datetime] = {}
        explain_at = tsr.get("driver_at") or tsr.get("asked_at")
        if explain_at:
            ts["NEED_TO_EXPLAIN"] = explain_at
        review_at = (adj["approved_at"] if adj else None) or tsr.get("review_at")  # review ends at adjudication
        if review_at:
            ts["UNDER_REVIEW"] = review_at
        out = build_stepper(row["status"], events, row["created_at"], row.get("dispute_status"), ts)
        for s in out["steps"]:
            ev = next((e for e in events if e["step"] == s["key"]), None)
            s["actor_name"] = ev["actor_name"] if ev and s["state"] == "done" else None
            if s["completed_at"]:
                s["completed_at"] = s["completed_at"].isoformat()
        return out
    finally:
        conn.close()


def apply_transition(
    conn_factory: Callable[[], Any], case_id: str, organization_id: str, principal_id: str, action: str, roles: Any
) -> dict[str, Any]:
    t = authorize(action, roles)
    conn = conn_factory()
    if conn is None:
        raise HTTPException(503, "Database unavailable")
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            # compare-and-set: concurrent/invalid transitions update zero rows
            cur.execute(
                """UPDATE app.fraud_cases SET status = %s, updated_at = now()
                   WHERE id::text = %s AND organization_id::text = %s AND status = %s RETURNING id""",
                (t.to_status, case_id, organization_id, t.from_status),
            )
            if cur.fetchone() is None:
                raise HTTPException(409, f"Case must be in status '{t.from_status}' for '{action}'")
            cur.execute(
                """INSERT INTO app.case_workflow_events
                   (case_id, organization_id, step, from_status, to_status, actor_id, actor_role)
                   VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s::uuid, %s)""",
                (case_id, organization_id, t.step, t.from_status, t.to_status, principal_id, t.actor_role),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return load_stepper(conn_factory, case_id, organization_id)
