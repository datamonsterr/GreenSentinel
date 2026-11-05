"""Workflow repository: database CRUD for questions, answers, minutes and action requests.

This module is owned by the #86 / feat/60-workflows worker. All writes are
idempotent. Concurrent duplicate writes use ON CONFLICT and re-fetch.
No in-memory fallback for state that requires DB persistence; DB errors
surface as WorkflowPersistenceError.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class WorkflowPersistenceError(Exception):
    """Raised when a DB operation fails and the caller must surface it."""

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ─── Questions ────────────────────────────────────────────────────────────────


def upsert_question(
    conn: Any,
    *,
    case_id: str,
    organization_id: str,
    question_id_stable: str,
    question_kind: str,
    purpose: str,
    actor_target: str,
    payload: dict[str, Any],
    created_by_actor_id: str | None,
    expires_at: str | None = None,
) -> dict[str, Any]:
    """Insert a new question or return the existing row for the same stable ID.

    Increments revision if a prior pending/answered question exists.
    Idempotent: calling twice with same arguments returns the same row.
    """
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")

            # Fetch the latest existing revision for this stable ID + case
            cur.execute(
                """
                SELECT id, revision, status
                FROM app.workflow_questions
                WHERE case_id = %s::uuid AND question_id_stable = %s
                ORDER BY revision DESC LIMIT 1
                """,
                (case_id, question_id_stable),
            )
            existing = cur.fetchone()

            if existing:
                existing_dict = dict(existing)
                if existing_dict["status"] == "pending":
                    # Idempotent: same stable ID with pending → return existing
                    return _fetch_question_by_id(cur, str(existing_dict["id"]))
                # Prior answered/declined → new revision
                new_revision = existing_dict["revision"] + 1
            else:
                new_revision = 1

            new_id = str(uuid4())
            cur.execute(
                """
                INSERT INTO app.workflow_questions
                    (id, question_id_stable, revision, case_id, organization_id,
                     actor_target, question_kind, purpose, payload,
                     created_by_actor_id, expires_at)
                VALUES (%s::uuid, %s, %s, %s::uuid, %s::uuid, %s, %s, %s, %s::jsonb, %s::uuid, %s)
                ON CONFLICT (case_id, question_id_stable, revision) DO NOTHING
                RETURNING id, question_id_stable, revision, case_id, organization_id,
                          actor_target, question_kind, purpose, payload, status,
                          created_by_actor_id, created_at, answered_at, expires_at
                """,
                (
                    new_id,
                    question_id_stable,
                    new_revision,
                    case_id,
                    organization_id,
                    actor_target,
                    question_kind,
                    purpose,
                    json.dumps(payload),
                    created_by_actor_id,
                    expires_at,
                ),
            )
            row = cur.fetchone()
            if row is None:
                # Concurrent insert won the conflict; re-fetch
                row = _fetch_question_row(cur, case_id, question_id_stable, new_revision)

            conn.commit()
            return _row_to_dict(row)
    except WorkflowPersistenceError:
        raise
    except Exception as exc:
        logger.error("upsert_question failed: %s", exc)
        raise WorkflowPersistenceError(str(exc)) from exc


def _fetch_question_by_id(cur: Any, question_id: str) -> dict[str, Any]:
    cur.execute(
        """
        SELECT id, question_id_stable, revision, case_id, organization_id,
               actor_target, question_kind, purpose, payload, status,
               created_by_actor_id, created_at, answered_at, expires_at
        FROM app.workflow_questions WHERE id = %s::uuid
        """,
        (question_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise WorkflowPersistenceError(f"Question {question_id} not found", retryable=False)
    return _row_to_dict(row)


def _fetch_question_row(cur: Any, case_id: str, stable_id: str, revision: int) -> dict[str, Any]:
    cur.execute(
        """
        SELECT id, question_id_stable, revision, case_id, organization_id,
               actor_target, question_kind, purpose, payload, status,
               created_by_actor_id, created_at, answered_at, expires_at
        FROM app.workflow_questions
        WHERE case_id = %s::uuid AND question_id_stable = %s AND revision = %s
        """,
        (case_id, stable_id, revision),
    )
    row = cur.fetchone()
    if row is None:
        raise WorkflowPersistenceError(f"Question {stable_id}@{revision} for case {case_id} not found", retryable=False)
    return _row_to_dict(row)


def get_question_by_id(conn: Any, question_id: str) -> dict[str, Any]:
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            return _fetch_question_by_id(cur, question_id)
    except WorkflowPersistenceError:
        raise
    except Exception as exc:
        raise WorkflowPersistenceError(str(exc)) from exc


def list_questions(conn: Any, *, case_id: str, organization_id: str, status: str = "pending") -> list[dict[str, Any]]:
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            cur.execute(
                """
                SELECT id, question_id_stable, revision, case_id, organization_id,
                       actor_target, question_kind, purpose, payload, status,
                       created_by_actor_id, created_at, answered_at, expires_at
                FROM app.workflow_questions
                WHERE case_id = %s::uuid AND organization_id = %s::uuid AND status = %s
                ORDER BY created_at ASC, revision ASC
                """,
                (case_id, organization_id, status),
            )
            return [_row_to_dict(row) for row in cur.fetchall()]
    except Exception as exc:
        raise WorkflowPersistenceError(str(exc)) from exc


def mark_question_answered(conn: Any, question_id: str) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            cur.execute(
                """
                UPDATE app.workflow_questions
                SET status = 'answered', answered_at = now()
                WHERE id = %s::uuid AND status = 'pending'
                """,
                (question_id,),
            )
            conn.commit()
    except Exception as exc:
        raise WorkflowPersistenceError(str(exc)) from exc


# ─── Answers ──────────────────────────────────────────────────────────────────


def insert_answer(
    conn: Any,
    *,
    question_id: str,
    respondent_principal_id: str,
    submitted_value: Any,
    explanation: str | None,
    idempotency_key: str,
) -> tuple[dict[str, Any], bool]:
    """Insert an answer idempotently.

    Returns (answer_dict, already_existed).
    """
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")

            # Fast path: check idempotency key first
            cur.execute(
                """
                SELECT id, question_id, respondent_principal_id, submitted_value,
                       explanation, submitted_at, idempotency_key
                FROM app.workflow_answers WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            )
            existing = cur.fetchone()
            if existing:
                return _row_to_dict(existing), True

            new_id = str(uuid4())
            cur.execute(
                """
                INSERT INTO app.workflow_answers
                    (id, question_id, respondent_principal_id, submitted_value,
                     explanation, idempotency_key)
                VALUES (%s::uuid, %s::uuid, %s::uuid, %s::jsonb, %s, %s)
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING id, question_id, respondent_principal_id, submitted_value,
                          explanation, submitted_at, idempotency_key
                """,
                (
                    new_id,
                    question_id,
                    respondent_principal_id,
                    json.dumps(submitted_value),
                    explanation,
                    idempotency_key,
                ),
            )
            row = cur.fetchone()
            if row is None:
                # Concurrent insert; re-fetch
                cur.execute(
                    """
                    SELECT id, question_id, respondent_principal_id, submitted_value,
                           explanation, submitted_at, idempotency_key
                    FROM app.workflow_answers WHERE idempotency_key = %s
                    """,
                    (idempotency_key,),
                )
                row = cur.fetchone()
                if row is None:
                    raise WorkflowPersistenceError("Answer insert race condition unresolved")
                conn.commit()
                return _row_to_dict(row), True

            conn.commit()
            return _row_to_dict(row), False
    except WorkflowPersistenceError:
        raise
    except Exception as exc:
        raise WorkflowPersistenceError(str(exc)) from exc


# ─── Minutes ──────────────────────────────────────────────────────────────────


def insert_minutes(
    conn: Any,
    *,
    case_id: str,
    organization_id: str,
    decision_id: str | None,
    content: dict[str, Any],
    map_ref: str | None,
    evidence_snapshot_id: str | None,
    drafted_by: str | None,
) -> dict[str, Any]:
    """Insert a new minutes draft, auto-incrementing revision."""
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")

            cur.execute(
                """
                SELECT COALESCE(MAX(revision), 0) + 1 AS next_rev
                FROM app.workflow_minutes WHERE case_id = %s::uuid
                """,
                (case_id,),
            )
            row = cur.fetchone()
            next_rev = (dict(row) if row else {"next_rev": 1})["next_rev"]

            new_id = str(uuid4())
            cur.execute(
                """
                INSERT INTO app.workflow_minutes
                    (id, case_id, organization_id, revision, decision_id,
                     content, map_ref, evidence_snapshot_id, drafted_by)
                VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s::uuid,
                        %s::jsonb, %s, %s::uuid, %s::uuid)
                ON CONFLICT (case_id, revision) DO NOTHING
                RETURNING id, case_id, organization_id, revision, decision_id,
                          content, map_ref, evidence_snapshot_id, status,
                          approved_by, approved_at, approved_content_hash,
                          sent_at, delivery_state, outbox_event_id, drafted_by, created_at
                """,
                (
                    new_id,
                    case_id,
                    organization_id,
                    next_rev,
                    decision_id,
                    json.dumps(content),
                    map_ref,
                    evidence_snapshot_id,
                    drafted_by,
                ),
            )
            inserted = cur.fetchone()
            if inserted is None:
                # Concurrent race; fetch existing revision
                cur.execute(
                    """
                    SELECT id, case_id, organization_id, revision, decision_id,
                           content, map_ref, evidence_snapshot_id, status,
                           approved_by, approved_at, approved_content_hash,
                           sent_at, delivery_state, outbox_event_id, drafted_by, created_at
                    FROM app.workflow_minutes
                    WHERE case_id = %s::uuid AND revision = %s
                    """,
                    (case_id, next_rev),
                )
                inserted = cur.fetchone()
                if inserted is None:
                    raise WorkflowPersistenceError("Minutes insert race condition unresolved")

            conn.commit()
            return _row_to_dict(inserted)
    except WorkflowPersistenceError:
        raise
    except Exception as exc:
        raise WorkflowPersistenceError(str(exc)) from exc


def get_minutes_by_id(conn: Any, minutes_id: str) -> dict[str, Any]:
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            cur.execute(
                """
                SELECT id, case_id, organization_id, revision, decision_id,
                       content, map_ref, evidence_snapshot_id, status,
                       approved_by, approved_at, approved_content_hash,
                       sent_at, delivery_state, outbox_event_id, drafted_by, created_at
                FROM app.workflow_minutes WHERE id = %s::uuid
                """,
                (minutes_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise WorkflowPersistenceError(f"Minutes {minutes_id} not found", retryable=False)
            return _row_to_dict(row)
    except WorkflowPersistenceError:
        raise
    except Exception as exc:
        raise WorkflowPersistenceError(str(exc)) from exc


def approve_minutes(
    conn: Any,
    minutes_id: str,
    *,
    approved_by: str,
    content_hash: str,
) -> dict[str, Any]:
    """Approve minutes; verifies content hash matches exactly."""
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            cur.execute(
                """
                UPDATE app.workflow_minutes
                SET status = 'approved',
                    approved_by = %s::uuid,
                    approved_at = now(),
                    approved_content_hash = %s
                WHERE id = %s::uuid AND status IN ('draft', 'preview')
                RETURNING id, case_id, organization_id, revision, decision_id,
                          content, map_ref, evidence_snapshot_id, status,
                          approved_by, approved_at, approved_content_hash,
                          sent_at, delivery_state, outbox_event_id, drafted_by, created_at
                """,
                (approved_by, content_hash, minutes_id),
            )
            row = cur.fetchone()
            if row is None:
                # May already be approved
                cur.execute(
                    "SELECT status, approved_content_hash FROM app.workflow_minutes WHERE id = %s::uuid",
                    (minutes_id,),
                )
                existing = cur.fetchone()
                if existing and dict(existing)["status"] == "approved":
                    return get_minutes_by_id(conn, minutes_id)
                raise WorkflowPersistenceError(f"Minutes {minutes_id} not in approvable state", retryable=False)
            conn.commit()
            return _row_to_dict(row)
    except WorkflowPersistenceError:
        raise
    except Exception as exc:
        raise WorkflowPersistenceError(str(exc)) from exc


def post_minutes_to_outbox(
    conn: Any,
    minutes_id: str,
    *,
    case_id: str,
    organization_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Write outbox event and mark minutes sent; both in one transaction."""
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")

            # Verify minutes is approved and not already sent
            cur.execute(
                "SELECT status, approved_content_hash FROM app.workflow_minutes WHERE id = %s::uuid",
                (minutes_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise WorkflowPersistenceError(f"Minutes {minutes_id} not found", retryable=False)
            minutes_row = dict(row)
            if minutes_row["status"] == "sent":
                cur.execute(
                    """
                    SELECT content, approved_content_hash,
                           evidence_snapshot_id,
                           (SELECT evidence_snapshot_id FROM app.adjudications
                            WHERE case_id = wm.case_id) AS current_evidence_snapshot_id
                    FROM app.workflow_minutes wm
                    WHERE wm.id = %s::uuid
                    """,
                    (minutes_id,),
                )
                sent_integrity = dict(cur.fetchone())
                current_hash = hashlib.sha256(
                    json.dumps(sent_integrity["content"], sort_keys=True, ensure_ascii=False).encode()
                ).hexdigest()
                if current_hash != sent_integrity["approved_content_hash"]:
                    raise WorkflowPersistenceError("Sent minutes content changed", retryable=False)
                if str(sent_integrity["evidence_snapshot_id"]) != str(sent_integrity["current_evidence_snapshot_id"]):
                    raise WorkflowPersistenceError("Sent minutes evidence snapshot changed", retryable=False)
                return get_minutes_by_id(conn, minutes_id)
            if minutes_row["status"] != "approved":
                raise WorkflowPersistenceError(f"Minutes {minutes_id} must be approved before sending", retryable=False)

            cur.execute(
                """
                SELECT wm.content, wm.case_id, wm.organization_id,
                       a.evidence_snapshot_id AS current_evidence_snapshot_id,
                       wm.evidence_snapshot_id
                FROM app.workflow_minutes wm
                LEFT JOIN app.adjudications a ON a.case_id = wm.case_id
                WHERE wm.id = %s::uuid
                FOR UPDATE OF wm
                """,
                (minutes_id,),
            )
            locked = cur.fetchone()
            locked_dict = dict(locked)
            content_hash = hashlib.sha256(
                json.dumps(locked_dict["content"], sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            if content_hash != minutes_row["approved_content_hash"]:
                raise WorkflowPersistenceError(
                    "Approved minutes content changed; fetch a fresh preview",
                    retryable=False,
                )
            if str(locked_dict["current_evidence_snapshot_id"]) != str(locked_dict["evidence_snapshot_id"]):
                raise WorkflowPersistenceError(
                    "Evidence snapshot changed after approval; create a new revision",
                    retryable=False,
                )

            cur.execute(
                """
                INSERT INTO app.case_agent_sessions (organization_id, case_id)
                VALUES (%s::uuid, %s::uuid)
                ON CONFLICT (case_id) DO UPDATE SET case_id = EXCLUDED.case_id
                RETURNING id
                """,
                (organization_id, case_id),
            )
            session_id = str(cur.fetchone()["id"])
            conversation_turn_id = str(uuid4())
            conversation_content = json.dumps(
                {"type": "approved_case_minutes", **payload},
                ensure_ascii=False,
                sort_keys=True,
            )
            cur.execute(
                """
                INSERT INTO app.case_agent_messages (session_id, turn_id, role, content)
                VALUES (%s::uuid, %s::uuid, 'driver_agent', %s)
                ON CONFLICT (session_id, turn_id, role) DO NOTHING
                """,
                (session_id, conversation_turn_id, conversation_content),
            )

            # Insert outbox event
            outbox_id = str(uuid4())
            cur.execute(
                """
                INSERT INTO app.outbox_events
                    (id, aggregate_type, aggregate_id, aggregate_version, event_type, payload)
                SELECT %s::uuid, 'workflow_minutes', %s::uuid, revision, 'minutes.sent', %s::jsonb
                FROM app.workflow_minutes WHERE id = %s::uuid
                ON CONFLICT (aggregate_type, aggregate_id, aggregate_version, event_type)
                DO NOTHING
                """,
                (outbox_id, minutes_id, json.dumps(payload), minutes_id),
            )

            # Mark minutes sent
            cur.execute(
                """
                UPDATE app.workflow_minutes
                SET status = 'sent',
                    sent_at = now(),
                    delivery_state = 'stored',
                    outbox_event_id = %s::uuid
                WHERE id = %s::uuid AND status = 'approved'
                  AND approved_content_hash = %s
                """,
                (outbox_id, minutes_id, content_hash),
            )
            if cur.rowcount != 1:
                raise WorkflowPersistenceError("Minutes send lost approval race", retryable=False)
            conn.commit()
            return get_minutes_by_id(conn, minutes_id)
    except WorkflowPersistenceError:
        raise
    except Exception as exc:
        raise WorkflowPersistenceError(str(exc)) from exc


# ─── Action requests ──────────────────────────────────────────────────────────


def upsert_action_request(
    conn: Any,
    *,
    case_id: str,
    organization_id: str,
    action_kind: str,
    requested_by: str,
    payload: dict[str, Any],
    payload_hash: str,
) -> tuple[dict[str, Any], bool]:
    """Insert or return existing action request (idempotent on payload_hash)."""
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")

            new_id = str(uuid4())
            cur.execute(
                """
                INSERT INTO app.workflow_action_requests
                    (id, case_id, organization_id, action_kind, requested_by, payload, payload_hash)
                VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s::uuid, %s::jsonb, %s)
                ON CONFLICT (case_id, action_kind, payload_hash) DO NOTHING
                RETURNING id, case_id, organization_id, action_kind, requested_by,
                          payload, payload_hash, status, approved_by, decided_at,
                          denial_reason, created_at
                """,
                (
                    new_id,
                    case_id,
                    organization_id,
                    action_kind,
                    requested_by,
                    json.dumps(payload),
                    payload_hash,
                ),
            )
            row = cur.fetchone()
            if row is None:
                # Already exists
                cur.execute(
                    """
                    SELECT id, case_id, organization_id, action_kind, requested_by,
                           payload, payload_hash, status, approved_by, decided_at,
                           denial_reason, created_at
                    FROM app.workflow_action_requests
                    WHERE case_id = %s::uuid AND action_kind = %s AND payload_hash = %s
                    """,
                    (case_id, action_kind, payload_hash),
                )
                row = cur.fetchone()
                if row is None:
                    raise WorkflowPersistenceError("Action request race condition unresolved")
                conn.commit()
                return _row_to_dict(row), True

            conn.commit()
            return _row_to_dict(row), False
    except WorkflowPersistenceError:
        raise
    except Exception as exc:
        raise WorkflowPersistenceError(str(exc)) from exc


def get_action_request_by_id(conn: Any, action_id: str) -> dict[str, Any]:
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            cur.execute(
                """
                SELECT id, case_id, organization_id, action_kind, requested_by,
                       payload, payload_hash, status, approved_by, decided_at,
                       denial_reason, created_at
                FROM app.workflow_action_requests WHERE id = %s::uuid
                """,
                (action_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise WorkflowPersistenceError(f"Action request {action_id} not found", retryable=False)
            return _row_to_dict(row)
    except WorkflowPersistenceError:
        raise
    except Exception as exc:
        raise WorkflowPersistenceError(str(exc)) from exc


# ─── Case-bound sources ───────────────────────────────────────────────────────


def get_minutes_sources(conn: Any, *, case_id: str, organization_id: str) -> dict[str, Any]:
    """Read the authoritative decision, snapshot and observed path for a case."""
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            cur.execute(
                """
                SELECT fc.assignment_id, ta.driver_id, a.id AS decision_id, a.evidence_snapshot_id,
                       a.analyst_id, a.outcome, a.rationale, a.approved_at,
                       es.version AS evidence_version, es.dossier_hash,
                       rs.id AS route_snapshot_id, rs.map_version, rs.provider,
                       rs.provenance,
                       COALESCE(
                           json_agg(
                               json_build_object(
                                   'lon', ST_X(tp.position::geometry),
                                   'lat', ST_Y(tp.position::geometry),
                                   'occurred_at', tp.occurred_at
                               ) ORDER BY tp.occurred_at
                           ) FILTER (WHERE tp.position IS NOT NULL), '[]'::json
                       ) AS traveled_path
                FROM app.fraud_cases fc
                LEFT JOIN app.trip_assignments ta ON ta.id = fc.assignment_id
                LEFT JOIN app.adjudications a ON a.case_id = fc.id
                LEFT JOIN app.evidence_snapshots es ON es.id = a.evidence_snapshot_id
                LEFT JOIN LATERAL (
                    SELECT rs.* FROM app.route_snapshots rs
                    WHERE rs.assignment_id = fc.assignment_id
                    ORDER BY rs.calculated_at DESC LIMIT 1
                ) rs ON true
                LEFT JOIN app.telemetry_points tp
                    ON tp.assignment_id = fc.assignment_id
                   AND (es.event_cutoff_at IS NULL OR tp.occurred_at <= es.event_cutoff_at)
                WHERE fc.id = %s::uuid AND fc.organization_id = %s::uuid
                GROUP BY fc.assignment_id, ta.driver_id, a.id, a.evidence_snapshot_id, a.analyst_id,
                         a.outcome, a.rationale, a.approved_at, es.version, es.dossier_hash,
                         rs.id, rs.map_version, rs.provider, rs.provenance
                """,
                (case_id, organization_id),
            )
            row = cur.fetchone()
            if row is None:
                raise WorkflowPersistenceError("Case not found in organization", retryable=False)
            return _row_to_dict(row)
    except WorkflowPersistenceError:
        raise
    except Exception as exc:
        raise WorkflowPersistenceError(str(exc)) from exc


def get_policy_deadline_hours(conn: Any, *, case_id: str, organization_id: str) -> int | None:
    """Return only a published, case-linked policy deadline; absent means unknown."""
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            cur.execute(
                """
                SELECT pv.action_matrix, fc.suspected_category
                FROM app.fraud_cases fc
                LEFT JOIN LATERAL (
                    SELECT es.policy_version_id
                    FROM app.evidence_snapshots es
                    WHERE es.case_id = fc.id
                    ORDER BY es.version DESC LIMIT 1
                ) es ON true
                LEFT JOIN app.policy_versions pv
                  ON pv.id = es.policy_version_id AND pv.status = 'published'
                WHERE fc.id = %s::uuid AND fc.organization_id = %s::uuid
                """,
                (case_id, organization_id),
            )
            row = cur.fetchone()
            if not row:
                raise WorkflowPersistenceError("Case not found in organization", retryable=False)
            data = dict(row)
            matrix = data.get("action_matrix") or {}
            category = data.get("suspected_category")
            policy = matrix.get(category) if isinstance(matrix, dict) and category else None
            if not isinstance(policy, dict):
                return None
            value = policy.get("evidence_request_deadline_hours", policy.get("deadline_hours"))
            return int(value) if isinstance(value, int) and 1 <= value <= 168 else None
    except WorkflowPersistenceError:
        raise
    except Exception as exc:
        raise WorkflowPersistenceError(str(exc)) from exc


def append_minutes_message(conn: Any, *, case_id: str, content: str, turn_id: str, organization_id: str) -> str:
    """Append the approved document to the existing case conversation transaction."""
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            cur.execute(
                """
                INSERT INTO app.case_agent_sessions (organization_id, case_id)
                VALUES (%s::uuid, %s::uuid)
                ON CONFLICT (case_id) DO UPDATE SET case_id = EXCLUDED.case_id
                RETURNING id
                """,
                (organization_id, case_id),
            )
            session_id = str(cur.fetchone()["id"])
            cur.execute(
                """
                INSERT INTO app.case_agent_messages (session_id, turn_id, role, content)
                VALUES (%s::uuid, %s::uuid, 'assistant', %s)
                ON CONFLICT (session_id, turn_id, role) DO NOTHING
                RETURNING id
                """,
                (session_id, turn_id, content),
            )
            row = cur.fetchone()
            conn.commit()
            return str(row["id"]) if row else session_id
    except Exception as exc:
        raise WorkflowPersistenceError(str(exc)) from exc


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Convert a psycopg DictRow or regular row to a plain dict."""
    if hasattr(row, "_asdict"):
        d = row._asdict()
    elif hasattr(row, "keys"):
        d = dict(row)
    else:
        d = dict(row)

    # Serialize datetime → ISO string, UUID → str, bytes → hex
    result: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, datetime):
            result[k] = v.isoformat()
        elif hasattr(v, "hex") and isinstance(v, bytes):
            result[k] = v.hex()
        else:
            try:
                import uuid

                if isinstance(v, uuid.UUID):
                    result[k] = str(v)
                else:
                    result[k] = v
            except Exception:
                result[k] = v
    return result
