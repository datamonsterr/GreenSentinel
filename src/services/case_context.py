"""Trusted, source-backed case context assembled before model invocation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from src.models.tool_contracts import ToolExecutionContext
from src.services.case_service import get_case_service


async def build_case_context(context: ToolExecutionContext) -> dict[str, Any]:
    """Load a frozen role-scoped dossier; missing evidence stays explicitly missing."""
    service = get_case_service()
    conn = service._get_db_connection()
    snapshot: dict[str, Any] = {}
    owner: dict[str, Any] = {}
    if conn is None:
        raise RuntimeError("Case database is unavailable")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT c.assigned_analyst_id, a.driver_id, d.principal_id
                   FROM app.fraud_cases c
                   LEFT JOIN app.trip_assignments a ON a.id = c.assignment_id
                   LEFT JOIN app.drivers d ON d.id=a.driver_id
                   WHERE c.id = %s::uuid AND c.organization_id = %s::uuid""",
                (context.case_id, context.organization_id),
            )
            owner = dict(cur.fetchone() or {})
            if not owner:
                raise PermissionError("case is not owned by the actor organization")
            if (
                "driver" in context.roles
                and not context.roles.intersection({"analyst", "senior_analyst", "admin"})
                and (
                    str(owner.get("driver_id")) != context.driver_id
                    or str(owner.get("principal_id")) != context.actor_id
                )
            ):
                raise PermissionError("driver may access only their assigned case")
            if (
                "analyst" in context.roles
                and not context.roles.intersection({"senior_analyst", "admin"})
                and str(owner.get("assigned_analyst_id")) != context.actor_id
            ):
                raise PermissionError("analyst is not the assigned case owner")
            cur.execute(
                """SELECT id, version, dossier_hash, policy_version_id, event_cutoff_at, dossier
                   FROM app.evidence_snapshots WHERE case_id = %s::uuid
                   ORDER BY version DESC LIMIT 1""",
                (context.case_id,),
            )
            row = cur.fetchone()
            if row:
                snapshot = dict(row)
            cur.execute(
                """SELECT q.id,q.question_kind,q.payload,q.status,a.submitted_value,a.explanation,a.submitted_at
                           FROM app.workflow_questions q LEFT JOIN app.workflow_answers a ON a.question_id=q.id
                           WHERE q.case_id=%s::uuid AND (a.respondent_principal_id=%s::uuid OR
                               (a.id IS NULL AND q.created_by_actor_id=%s::uuid)) ORDER BY q.created_at LIMIT 30""",
                (context.case_id, context.actor_id, context.actor_id),
            )
            interactions = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
    result = await service.get_case_detail(case_id=context.case_id, organization_id=context.organization_id)
    full = result.model_dump(mode="json")
    # Driver projection excludes analyst/audit/other-party material and all trust fields.
    if "driver" in context.roles and "analyst" not in context.roles and "admin" not in context.roles:
        case = {
            key: full.get(key)
            for key in (
                "case",
                "trip",
                "telemetry_samples",
                "route_geometry",
                "traffic_corroboration",
                "timeline_milestones",
                "missingness_alerts",
                "destination",
            )
        }
    else:
        case = full

    def remove_labels(value):
        blocked = {
            "scenario",
            "scenario_type",
            "scenario_family",
            "expected_category",
            "expected_outcome",
            "expected_guardrail",
            "expected_guardrail_reason",
            "intent",
            "simulation_id",
        }
        if isinstance(value, dict):
            return {k: remove_labels(v) for k, v in value.items() if k not in blocked}
        if isinstance(value, list):
            return [remove_labels(v) for v in value]
        return value

    case = remove_labels(case)
    import json

    case["interactions"] = json.loads(json.dumps(interactions, default=str))
    fact = case.get("case") or {}
    case["context_brief_vi"] = (
        f"Vụ việc {context.case_id}, trạng thái {fact.get('status', 'chưa có dữ liệu')}; nhóm cảnh báo {fact.get('category', 'chưa xác định')} là nghi vấn chờ xác nhận. Dữ kiện và thông tin thiếu cần được đối chiếu theo hồ sơ có nguồn; quyết định thuộc analyst có quyền."
    )
    if "driver" in context.roles and not context.roles.intersection({"analyst", "senior_analyst", "admin"}):
        if case.get("case"):
            case["case"] = {
                k: v for k, v in case["case"].items() if k not in {"assigned_analyst_name", "assigned_analyst_id"}
            }
    # Bound prompt size while preserving full records in authorized tools.
    if len(case.get("telemetry_samples", [])) > 24:
        points = case["telemetry_samples"]
        case["telemetry_samples"] = points[:12] + points[-12:]
        case["telemetry_summary"] = {"record_count": len(points), "prompt_samples_are_partial": True}
    snapshot_hash = snapshot.get("dossier_hash")
    if isinstance(snapshot_hash, bytes):
        snapshot_hash = snapshot_hash.hex()
    cutoff = snapshot.get("event_cutoff_at")
    if cutoff is not None and hasattr(cutoff, "isoformat"):
        cutoff = cutoff.isoformat()
    return {
        "schema_version": "case-context.v1",
        "case_id": context.case_id,
        "evidence": case,
        "evidence_status": "available" if snapshot else "unavailable",
        "evidence_snapshot": {
            "id": str(snapshot.get("id")) if snapshot else None,
            "version": snapshot.get("version"),
            "hash": snapshot_hash,
            "policy_version_id": str(snapshot.get("policy_version_id")) if snapshot.get("policy_version_id") else None,
            "cutoff_at": cutoff,
        },
        "prepared_at": datetime.now(UTC).isoformat(),
        "frozen": True,
        "source": "app.fraud_cases",
    }


async def resolve_case_context(context: ToolExecutionContext) -> dict[str, Any]:
    """Public resolver expected by runtime callers; returns the frozen dossier dict."""
    return await build_case_context(context)


def prune_case_context(dossier: dict[str, Any], intent: str = "case_investigation") -> dict[str, Any]:
    """Filter out irrelevant context fields to prevent context bloat and prompt leakage."""
    if not isinstance(dossier, dict):
        return {}
    if intent in {"conversational", "out_of_scope", "adversarial_attack"}:
        return {}

    pruned = dict(dossier)
    raw_ev = dossier.get("evidence", {})
    evidence = dict(raw_ev) if isinstance(raw_ev, dict) else {}

    if intent == "policy_inquiry":
        # Keep only basic case metadata and policy version; strip driver PII, GPS, and route telemetry
        pruned_evidence = {
            "case": {
                "id": evidence.get("case", {}).get("id") if isinstance(evidence.get("case"), dict) else None,
                "status": evidence.get("case", {}).get("status") if isinstance(evidence.get("case"), dict) else None,
                "suspected_category": (
                    (evidence.get("case", {}).get("category") or evidence.get("case", {}).get("suspected_category"))
                    if isinstance(evidence.get("case"), dict)
                    else None
                ),
                "priority_tier": evidence.get("case", {}).get("priority_tier")
                if isinstance(evidence.get("case"), dict)
                else None,
            },
            "context_brief_vi": evidence.get("context_brief_vi", ""),
        }
        pruned["evidence"] = pruned_evidence
        return pruned

    if intent == "case_investigation":
        # Retain case facts, milestones, brief, and summary, but prune raw telemetry samples
        # and bulky route coordinates so model accesses them on-demand via tools.
        if "telemetry_samples" in evidence:
            sample_count = len(evidence["telemetry_samples"]) if isinstance(evidence["telemetry_samples"], list) else 0
            evidence.pop("telemetry_samples", None)
            evidence["telemetry_summary"] = {
                "record_count": sample_count,
                "note": "Raw GPS telemetry available via inspect_trip_telemetry tool.",
            }
        if "route_geometry" in evidence:
            evidence.pop("route_geometry", None)
        pruned["evidence"] = evidence
        return pruned

    return pruned
