"""Durable, tenant-scoped solved-case and precedent history persistence."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal
from uuid import UUID, uuid4

from src.models.schemas import (
    PrecedentProvenance,
    PrecedentWorkflowItem,
    WorkflowDecision,
    WorkflowHumanAction,
    WorkflowToolCall,
    WorkflowTrace,
)

SCORE_SEMANTICS = "uncalibrated_case_similarity_not_adjudication"
TRACE_SCHEMA_VERSION = "2.0"


class PrecedentPersistenceError(RuntimeError):
    """Raised when authoritative precedent persistence cannot be completed."""


def _is_uuid(value: str) -> bool:
    try:
        UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return False
    return True


def _json_value(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _hash_bytes(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def _canonical_trace(trace: WorkflowTrace) -> tuple[str, str]:
    payload = json.dumps(trace.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return payload, hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _context_row_to_item(row: dict[str, Any]) -> PrecedentWorkflowItem:
    trace = WorkflowTrace.model_validate(_json_value(row["workflow_trace"], {}))
    published_at = _iso(row.get("published_at"))
    provenance = PrecedentProvenance(
        organization_id=str(row["organization_id"]),
        assignment_id=str(row["assignment_id"]),
        case_id=str(row["case_id"]),
        conversation_session_id=(str(row["conversation_session_id"]) if row.get("conversation_session_id") else None),
        driver_submission_id=(str(row["driver_submission_id"]) if row.get("driver_submission_id") else None),
        conversation_state=row["conversation_state"],
        evidence_snapshot_id=str(row["evidence_snapshot_id"]),
        policy_version_id=str(row["policy_version_id"]),
        adjudication_id=str(row["adjudication_id"]),
        published_by=str(row["published_by"]),
        published_at=published_at,
        trace_schema_version=row["trace_schema_version"],
        source_kind="finalized_case",
        read_only=bool(row["read_only"]),
        eligible_for_reuse=bool(row["eligible_for_reuse"]),
    )
    decision = trace.final_decision
    return PrecedentWorkflowItem(
        id=str(row["id"]),
        case_id=str(row["case_id"]),
        violation_code=row.get("violation_code") or "insufficient_evidence",
        claim_type=row.get("claim_type") or "not_recorded",
        district=None,
        title=row["title"],
        driver_statement_summary=row.get("driver_statement") or "",
        workflow_trace=trace,
        verdict=decision.verdict if decision else "incomplete",
        confidence_score=1.0,
        created_at=published_at,
        provenance=provenance,
    )


def list_finalized(
    conn: Any,
    *,
    organization_id: str,
    violation_code: str | None = None,
    claim_type: str | None = None,
    limit: int = 50,
) -> list[PrecedentWorkflowItem]:
    clauses = ["organization_id = %s::uuid", "eligible_for_reuse"]
    params: list[Any] = [organization_id]
    if violation_code:
        clauses.append("upper(violation_code) = upper(%s)")
        params.append(violation_code)
    if claim_type:
        clauses.append("lower(claim_type) = lower(%s)")
        params.append(claim_type)
    params.append(limit)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT * FROM app.solved_case_contexts
            WHERE {" AND ".join(clauses)}
            ORDER BY published_at DESC, id
            LIMIT %s
            """,
            params,
        )
        return [_context_row_to_item(dict(row)) for row in cur.fetchall()]


def get_finalized(conn: Any, *, precedent_id: str, organization_id: str) -> PrecedentWorkflowItem | None:
    if not _is_uuid(precedent_id) or not _is_uuid(organization_id):
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM app.solved_case_contexts
            WHERE id = %s::uuid AND organization_id = %s::uuid
            """,
            (precedent_id, organization_id),
        )
        row = cur.fetchone()
    return _context_row_to_item(dict(row)) if row else None


def get_finalized_by_case(conn: Any, *, case_id: str, organization_id: str) -> PrecedentWorkflowItem | None:
    if not _is_uuid(case_id) or not _is_uuid(organization_id):
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM app.solved_case_contexts
            WHERE case_id = %s::uuid AND organization_id = %s::uuid
            """,
            (case_id, organization_id),
        )
        row = cur.fetchone()
    return _context_row_to_item(dict(row)) if row else None


def _load_source_row(cur: Any, *, case_id: str, organization_id: str) -> dict[str, Any]:
    cur.execute(
        """
        SELECT fc.id AS case_id, fc.organization_id, fc.assignment_id,
               fc.suspected_category AS violation_code, fc.status,
               ta.driver_id, d.principal_id AS driver_principal_id,
               cas.id AS conversation_session_id, cas.created_by AS conversation_created_by,
               ds.id AS driver_submission_id, ds.statement AS driver_submission_statement,
               ds.received_at AS driver_submission_received_at,
               ds.provenance ->> 'claim_type' AS claim_type,
               es.id AS evidence_snapshot_id, es.policy_version_id,
               a.id AS adjudication_id, a.analyst_id, a.outcome, a.rationale,
               a.explicit_human_approval, a.request_hash, a.approved_at
        FROM app.fraud_cases fc
        JOIN app.trip_assignments ta ON ta.id = fc.assignment_id
        JOIN app.drivers d ON d.id = ta.driver_id
        JOIN app.adjudications a ON a.case_id = fc.id
        JOIN app.evidence_snapshots es ON es.id = a.evidence_snapshot_id
        LEFT JOIN app.case_agent_sessions cas
          ON cas.case_id = fc.id AND cas.organization_id = fc.organization_id
        LEFT JOIN LATERAL (
            SELECT id, statement, received_at, provenance
            FROM app.driver_submissions
            WHERE case_id = fc.id AND statement IS NOT NULL
            ORDER BY received_at DESC NULLS LAST, id DESC
            LIMIT 1
        ) ds ON true
        WHERE fc.id = %s::uuid AND fc.organization_id = %s::uuid
        """,
        (case_id, organization_id),
    )
    row = cur.fetchone()
    if not row:
        raise PrecedentPersistenceError("A finalized case with signed adjudication was not found")
    source = dict(row)
    if source["status"] != "resolved" or not source["explicit_human_approval"]:
        raise PrecedentPersistenceError("Only resolved cases with explicit human approval may become precedents")
    return source


def _load_human_actions(cur: Any, source: dict[str, Any]) -> tuple[list[WorkflowHumanAction], str | None]:
    session_id = source.get("conversation_session_id")
    statement = source.get("driver_submission_statement")
    actions: list[WorkflowHumanAction] = []
    if statement:
        actions.append(
            WorkflowHumanAction(
                actor_id=str(source["driver_principal_id"]) if source.get("driver_principal_id") else None,
                actor_role="driver",
                action_type="driver_submission",
                summary=statement,
                timestamp=_iso(source.get("driver_submission_received_at")),
                source_ref=f"driver_submission:{source['driver_submission_id']}",
            )
        )
    if not session_id:
        return actions, statement
    cur.execute(
        """
        SELECT id, role, content, created_at
        FROM app.case_agent_messages
        WHERE session_id = %s::uuid
        ORDER BY sequence
        """,
        (session_id,),
    )
    for raw in cur.fetchall():
        row = dict(raw)
        role = row["role"]
        if role == "user":
            actor_id = source.get("conversation_created_by")
            action_type = "analyst_message"
        else:
            continue
        actions.append(
            WorkflowHumanAction(
                actor_id=str(actor_id) if actor_id else None,
                actor_role="analyst",
                action_type=action_type,
                summary=row["content"],
                timestamp=_iso(row["created_at"]),
                source_ref=f"case_agent_message:{row['id']}",
            )
        )
    return actions, statement


def _load_tool_calls(cur: Any, *, case_id: str, organization_id: str) -> list[WorkflowToolCall]:
    cur.execute(
        """
        SELECT run_id, events
        FROM app.agent_runtime_turns
        WHERE case_id = %s::uuid AND organization_id = %s::uuid
        ORDER BY created_at, run_id
        """,
        (case_id, organization_id),
    )
    calls: list[WorkflowToolCall] = []
    for raw in cur.fetchall():
        row = dict(raw)
        starts: dict[str, dict[str, Any]] = {}
        for event in _json_value(row.get("events"), []):
            payload = event.get("payload") or {}
            call_id = payload.get("tool_call_id")
            if event.get("type") == "tool.start" and call_id:
                starts[str(call_id)] = event
            elif event.get("type") == "tool.end" and call_id:
                start = starts.pop(str(call_id), {})
                calls.append(
                    WorkflowToolCall(
                        tool_name=str(payload.get("tool_name") or payload.get("tool_id") or "unknown"),
                        input_summary=None,
                        output_summary=payload.get("summary"),
                        executed_at=start.get("timestamp") or event.get("timestamp"),
                        status=str(payload.get("status") or "unknown"),
                        source_ref=f"agent_runtime_turn:{row['run_id']}:{event.get('event_id', call_id)}",
                    )
                )
    return calls


def publish_finalized(
    conn: Any,
    *,
    case_id: str,
    organization_id: str,
    published_by: str,
) -> PrecedentWorkflowItem:
    """Create one immutable context from real, linked database records."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM app.solved_case_contexts WHERE case_id = %s::uuid", (case_id,))
        existing = cur.fetchone()
        if existing:
            if str(existing["organization_id"]) != organization_id:
                raise PrecedentPersistenceError("Solved context belongs to another tenant")
            return _context_row_to_item(dict(existing))

        source = _load_source_row(cur, case_id=case_id, organization_id=organization_id)
        if str(source["analyst_id"]) != published_by:
            raise PrecedentPersistenceError("Only the analyst who signed the decision may publish its context")

        actions, driver_statement = _load_human_actions(cur, source)
        tool_calls = _load_tool_calls(cur, case_id=case_id, organization_id=organization_id)
        adjudication_id = str(source["adjudication_id"])
        evidence_snapshot_id = str(source["evidence_snapshot_id"])
        policy_version_id = str(source["policy_version_id"])
        trace = WorkflowTrace(
            schema_version=TRACE_SCHEMA_VERSION,
            agent_tools_called=tool_calls,
            human_actions_performed=actions,
            driver_response_summary=driver_statement or "",
            related_policies=[],
            final_decision=WorkflowDecision(
                verdict=source["outcome"],
                penalty_amount=0,
                rationale=source["rationale"],
                decided_by=str(source["analyst_id"]),
                decided_at=str(_iso(source["approved_at"])),
                adjudication_id=adjudication_id,
                evidence_snapshot_id=evidence_snapshot_id,
                policy_version_id=policy_version_id,
                request_hash=_hash_bytes(source.get("request_hash")),
                explicit_human_approval=True,
            ),
            source_refs=[
                f"case:{case_id}",
                f"assignment:{source['assignment_id']}",
                f"evidence_snapshot:{evidence_snapshot_id}",
                f"policy_version:{policy_version_id}",
                f"adjudication:{adjudication_id}",
            ]
            + [action.source_ref for action in actions if action.source_ref]
            + [tool.source_ref for tool in tool_calls if tool.source_ref],
        )
        trace_json, trace_hash = _canonical_trace(trace)
        precedent_id = uuid4()
        conversation_state = (
            "linked" if source.get("conversation_session_id") or source.get("driver_submission_id") else "not_available"
        )
        cur.execute(
            """
            INSERT INTO app.solved_case_contexts (
                id, organization_id, case_id, assignment_id,
                conversation_session_id, driver_submission_id, conversation_state,
                evidence_snapshot_id, policy_version_id, adjudication_id,
                published_by, violation_code, claim_type, title,
                driver_statement, workflow_trace, workflow_trace_hash,
                trace_schema_version, published_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s
            )
            RETURNING *
            """,
            (
                precedent_id,
                organization_id,
                case_id,
                source["assignment_id"],
                source.get("conversation_session_id"),
                source.get("driver_submission_id"),
                conversation_state,
                evidence_snapshot_id,
                policy_version_id,
                adjudication_id,
                published_by,
                source.get("violation_code"),
                source.get("claim_type"),
                f"Resolved case {case_id}",
                driver_statement,
                trace_json,
                trace_hash,
                TRACE_SCHEMA_VERSION,
                source["approved_at"],
            ),
        )
        row = cur.fetchone()
    return _context_row_to_item(dict(row))


def record_reuse(
    conn: Any,
    *,
    organization_id: str,
    current_case_id: str,
    precedent: PrecedentWorkflowItem,
    actor_id: str,
    action: str,
    similarity_score: float,
    retrieval_model: str,
    matching_factors: list[str],
    request_id: str | None = None,
) -> str:
    if precedent.provenance.source_kind != "finalized_case" or not precedent.provenance.eligible_for_reuse:
        raise PrecedentPersistenceError("Legacy or incomplete precedent records cannot be applied")
    request_uuid = UUID(request_id) if request_id else uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO app.precedent_reuse_history (
                organization_id, current_case_id, precedent_context_id, actor_id,
                action, similarity_score, score_semantics, retrieval_model,
                matching_factors, precedent_trace_hash, request_id
            )
            SELECT %s, %s, sc.id, %s, %s, %s, %s, %s, %s::jsonb,
                   sc.workflow_trace_hash, %s
            FROM app.solved_case_contexts sc
            WHERE sc.id = %s AND sc.organization_id = %s
            RETURNING id
            """,
            (
                organization_id,
                current_case_id,
                actor_id,
                action,
                similarity_score,
                SCORE_SEMANTICS,
                retrieval_model,
                json.dumps(matching_factors, ensure_ascii=False),
                request_uuid,
                precedent.id,
                organization_id,
            ),
        )
        row = cur.fetchone()
        if not row:
            raise PrecedentPersistenceError("Precedent is unavailable in this tenant")
    return str(row["id"])


def get_legacy_read_only(conn: Any, *, precedent_id: str, organization_id: str) -> PrecedentWorkflowItem | None:
    """Tenant-scoped compatibility adapter; legacy records are never reuse-eligible."""
    if not _is_uuid(precedent_id) or not _is_uuid(organization_id):
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pw.*, fc.organization_id
            FROM app.precedent_workflows pw
            JOIN app.fraud_cases fc ON fc.id = pw.case_id
            WHERE pw.id = %s::uuid AND fc.organization_id = %s::uuid
            """,
            (precedent_id, organization_id),
        )
        row = cur.fetchone()
    if not row:
        return None
    data = dict(row)
    trace = WorkflowTrace.model_validate(_json_value(data["workflow_trace"], {}))
    source_kind: Literal["legacy_fixture", "legacy_appeal"] = (
        "legacy_appeal" if "appeal" in str(data.get("verdict", "")).lower() else "legacy_fixture"
    )
    return PrecedentWorkflowItem(
        id=str(data["id"]),
        case_id=str(data["case_id"]) if data.get("case_id") else None,
        violation_code=data["violation_code"],
        claim_type=data["claim_type"],
        district=data.get("district"),
        title=data["title"],
        driver_statement_summary=data.get("driver_statement_summary") or "",
        workflow_trace=trace,
        verdict=data["verdict"],
        confidence_score=float(data.get("confidence_score") or 0),
        created_at=_iso(data.get("created_at")),
        provenance=PrecedentProvenance(
            organization_id=str(data["organization_id"]),
            case_id=str(data["case_id"]) if data.get("case_id") else None,
            source_kind=source_kind,
            read_only=True,
            eligible_for_reuse=False,
        ),
    )


def record_application_from_latest_view(
    conn: Any,
    *,
    organization_id: str,
    current_case_id: str,
    precedent_id: str,
    actor_id: str,
    request_id: str | None = None,
) -> str:
    """Append application history using the actor's actual latest retrieval result."""
    request_uuid = UUID(request_id) if request_id else uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO app.precedent_reuse_history (
                organization_id, current_case_id, precedent_context_id, actor_id,
                action, similarity_score, score_semantics, retrieval_model,
                matching_factors, precedent_trace_hash, request_id
            )
            SELECT h.organization_id, h.current_case_id, h.precedent_context_id, h.actor_id,
                   'applied', h.similarity_score, h.score_semantics, h.retrieval_model,
                   h.matching_factors, h.precedent_trace_hash, %s
            FROM app.precedent_reuse_history h
            JOIN app.solved_case_contexts sc ON sc.id = h.precedent_context_id
            WHERE h.organization_id = %s::uuid
              AND h.current_case_id = %s::uuid
              AND h.precedent_context_id = %s::uuid
              AND h.actor_id = %s::uuid
              AND h.action = 'viewed'
              AND sc.eligible_for_reuse
            ORDER BY h.created_at DESC
            LIMIT 1
            RETURNING id
            """,
            (request_uuid, organization_id, current_case_id, precedent_id, actor_id),
        )
        row = cur.fetchone()
        if not row:
            raise PrecedentPersistenceError("Apply requires a prior tenant-scoped retrieval by the same analyst")
    return str(row["id"])
