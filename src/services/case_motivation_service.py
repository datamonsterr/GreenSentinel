"""Structured, versioned motivation assessment per case (slice S-M, ADR-032).

Rule-based generation (all numbers computed here, never by an LLM) plus an optional
validated LLM rationale with deterministic fallback. Persisted append-only in
``app.case_motivation_assessments``; the latest version wins.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field

from src.services.motivation_assessment_service import (
    _facts,
    assess_driver_motivation,
    generate_motivation_assessment,
)

MotiveCategory = Literal["reward_threshold", "subsidy_surge", "fare_inflation", "platform_fault", "unclear"]

# Seam: constant catalogue now; S-K published kb `motive` objects can replace/extend it later.
MOTIVE_CATALOGUE: dict[str, dict[str, str]] = {
    "reward_threshold": {"vi": "Chạm ngưỡng thưởng", "en": "Reward threshold"},
    "subsidy_surge": {"vi": "Trợ giá / giờ cao điểm", "en": "Subsidy / surge"},
    "fare_inflation": {"vi": "Tăng cước phí", "en": "Fare inflation"},
    "platform_fault": {"vi": "Lỗi nền tảng", "en": "Platform fault"},
    "unclear": {"vi": "Chưa rõ", "en": "Unclear"},
}

WRITE_ROLES = ("analyst", "senior_analyst", "admin")

_RATIONALE_VI: dict[str, str] = {
    "reward_threshold": "Hành trình có khoản thưởng và dấu hiệu bất thường; cần đối chiếu có phải nhằm chạm ngưỡng thưởng không.",
    "subsidy_surge": "Có lợi ích tăng thêm từ trợ giá hoặc giờ cao điểm đi kèm bất thường; cần đối chiếu trước khi kết luận.",
    "fare_inflation": "Cước thực tế cao hơn báo giá kèm tín hiệu bất thường; cần đối chiếu, chưa chứng minh tài xế cố ý.",
    "platform_fault": "Có sự cố nền tảng được xác nhận; bất thường có thể ngoài ý muốn, cần đối chiếu tác động lên hành trình.",
    "unclear": "Chưa đủ bằng chứng để xác định động cơ của tài xế.",
}


class Signal(BaseModel):
    code: str = Field(min_length=1, max_length=60)
    value: float | str | bool | None = None
    unit: str | None = Field(default=None, max_length=20)
    detail: str | None = Field(default=None, max_length=300)


class MotivationDraft(BaseModel):
    motive_category: MotiveCategory
    signals: list[Signal] = Field(default_factory=list, max_length=20)
    amount_at_stake_vnd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    confidence: float = Field(default=0.0, ge=0, le=1, allow_inf_nan=False)
    rationale: str = Field(default="", max_length=2000)
    source: Literal["ai", "rule", "analyst"] = "rule"


class MotivationEdit(BaseModel):
    """Analyst edit. Amounts stay system-computed, so they are not editable."""

    motive_category: MotiveCategory
    signals: list[Signal] = Field(default_factory=list, max_length=20)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    rationale: str = Field(min_length=1, max_length=2000)
    expected_version: int | None = Field(default=None, ge=0)


class ConfirmRequest(BaseModel):
    expected_version: int | None = Field(default=None, ge=1)


def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError):
        return None


def build_structured_assessment(
    trip: dict[str, Any] | None, features: dict[str, Any] | None, telemetry: list[dict[str, Any]] | None
) -> MotivationDraft:
    """Deterministic category, signals, amount and confidence from case evidence."""
    facts = _facts(trip, features, telemetry)
    legacy = assess_driver_motivation(trip=trip, features=features, telemetry=telemetry)
    bonus = _num((trip or {}).get("bonus_amount_vnd")) or 0.0
    surge = facts["surge_capture_incremental_vnd"]
    subsidy = facts["subsidy_incremental_vnd"]
    fare = facts["fare_delta_vnd"]
    mock = facts["mock_location_samples"]
    incident = facts["platform_incident_confirmed"]
    deviation = facts["route_deviation_ratio"]

    signals: list[Signal] = []
    if mock:
        signals.append(Signal(code="mock_location", value=float(mock), unit="samples"))
    if fare is not None and fare > 0:
        signals.append(Signal(code="fare_delta", value=round(fare, 2), unit="VND"))
    if surge > 0:
        signals.append(Signal(code="surge_capture", value=round(surge, 2), unit="VND"))
    if subsidy > 0:
        signals.append(Signal(code="subsidy", value=round(subsidy, 2), unit="VND"))
    if bonus > 0:
        signals.append(Signal(code="bonus", value=round(bonus, 2), unit="VND"))
    if incident:
        signals.append(Signal(code="platform_incident", value=True))
    if deviation is not None and deviation > 0:
        signals.append(Signal(code="route_deviation", value=round(deviation, 3), unit="ratio"))
    stationary = facts["stationary_duration_s"]
    if stationary is not None and stationary > 0:
        signals.append(Signal(code="stationary", value=round(stationary, 1), unit="s"))

    abnormal = bool(mock or (deviation or 0) > 0 or (stationary or 0) > 0)
    category: MotiveCategory = "unclear"
    amount: float | None = legacy.economic_incentive_reward or None
    if incident and not mock:
        category = "platform_fault"
    elif surge > 0 or subsidy > 0:
        category = "subsidy_surge"
        amount = amount or surge + subsidy
    elif bonus > 0 and abnormal:
        category = "reward_threshold"
        amount = amount or bonus
    elif fare is not None and fare > 0 and abnormal:
        category = "fare_inflation"
    strong = sum(s.code in ("mock_location", "fare_delta", "surge_capture", "subsidy", "bonus", "platform_incident") for s in signals)
    confidence = 0.2 if category == "unclear" else min(0.85, round(0.35 + 0.1 * strong + (0.1 if mock else 0), 3))
    return MotivationDraft(
        motive_category=category,
        signals=signals,
        amount_at_stake_vnd=round(amount, 2) if amount else None,
        confidence=confidence,
        rationale=_RATIONALE_VI[category],
        source="rule",
    )


async def generate_assessment(
    *, trip: dict[str, Any] | None, features: dict[str, Any] | None, telemetry: list[dict[str, Any]] | None,
    evidence_scope: str = "", organization_id: str | None = None,
) -> MotivationDraft:
    """Rule draft; rationale swapped for the validated LLM narrative when it differs from the fallback."""
    draft = build_structured_assessment(trip, features, telemetry)
    if draft.motive_category == "unclear":
        return draft
    try:
        fallback = assess_driver_motivation(trip=trip, features=features, telemetry=telemetry)
        ai = await generate_motivation_assessment(
            trip=trip, features=features, telemetry=telemetry, evidence_scope=evidence_scope, organization_id=organization_id
        )
        text = ai.natural_vietnamese_narrative.strip()
        if text and text != fallback.natural_vietnamese_narrative and len(text) <= 2000:
            return draft.model_copy(update={"rationale": text, "source": "ai"})
    except Exception:
        pass
    return draft


# ---- persistence ---------------------------------------------------------------------------------

_COLS = (
    "id, case_id, organization_id, version, motive_category, signals, amount_at_stake_vnd, confidence, "
    "rationale, source, status, confirmed_by, confirmed_at, created_by, created_at"
)


def _row(r: dict[str, Any]) -> dict[str, Any]:
    out = dict(r)
    for key in ("id", "case_id", "organization_id", "confirmed_by", "created_by"):
        out[key] = str(out[key]) if out.get(key) is not None else None
    for key in ("amount_at_stake_vnd", "confidence"):
        out[key] = float(out[key]) if out.get(key) is not None else None
    for key in ("confirmed_at", "created_at"):
        out[key] = out[key].isoformat() if out.get(key) is not None else None
    return out


def _conn(conn_factory: Callable[[], Any]) -> Any:
    conn = conn_factory()
    if conn is None:
        raise HTTPException(503, "Database unavailable")
    return conn


def _audit(cur: Any, org: str, actor: str, case_id: str, action: str, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, default=str)
    cur.execute(
        """INSERT INTO app.audit_events (event_id, organization_id, actor_id, case_id, action, result,
                                        request_id, redacted_payload, previous_hash, event_hash)
           VALUES (gen_random_uuid(), %s::uuid, %s::uuid, %s::uuid, %s, 'accepted', gen_random_uuid(),
                   %s::jsonb, '\\x'::bytea, %s)""",
        (org, actor, case_id, action, body, hashlib.sha256(body.encode()).digest()),
    )


def _latest(cur: Any, case_id: str, org: str) -> dict[str, Any] | None:
    cur.execute(
        f"SELECT {_COLS} FROM app.case_motivation_assessments "
        "WHERE case_id::text = %s AND organization_id::text = %s ORDER BY version DESC LIMIT 1",
        (case_id, org),
    )
    row = cur.fetchone()
    return _row(row) if row else None


def load(conn_factory: Callable[[], Any], case_id: str, org: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Latest persisted assessment (or None) plus lightweight version history, newest first."""
    conn = _conn(conn_factory)
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            latest = _latest(cur, case_id, org)
            cur.execute(
                "SELECT version, source, status, created_at FROM app.case_motivation_assessments "
                "WHERE case_id::text = %s AND organization_id::text = %s ORDER BY version DESC LIMIT 50",
                (case_id, org),
            )
            history = [
                {**dict(r), "created_at": r["created_at"].isoformat()} for r in cur.fetchall()
            ]
        return latest, history
    finally:
        conn.close()


def _append(conn: Any, case_id: str, org: str, actor: str, draft: MotivationDraft, action: str,
            expected_version: int | None) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute("SET search_path = app, extensions, public;")
        cur.execute(
            "SELECT id FROM app.fraud_cases WHERE id::text = %s AND organization_id::text = %s", (case_id, org)
        )
        if cur.fetchone() is None:
            raise HTTPException(404, "Case not found")
        current = _latest(cur, case_id, org)
        current_version = current["version"] if current else 0
        if expected_version is not None and expected_version != current_version:
            raise HTTPException(409, "Motivation assessment changed; reload before saving")
        cur.execute(
            f"""INSERT INTO app.case_motivation_assessments
                (case_id, organization_id, version, motive_category, signals, amount_at_stake_vnd, confidence,
                 rationale, source, status, created_by)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s::jsonb, %s, %s, %s, %s, 'draft', %s::uuid)
                RETURNING {_COLS}""",
            (
                case_id, org, current_version + 1, draft.motive_category,
                json.dumps([s.model_dump() for s in draft.signals]), draft.amount_at_stake_vnd,
                draft.confidence, draft.rationale, draft.source, actor,
            ),
        )
        saved = _row(cur.fetchone())
        _audit(cur, org, actor, case_id, action,
               {"version": saved["version"], "motive_category": draft.motive_category, "source": draft.source})
    return saved


def _run(conn_factory: Callable[[], Any], fn: Callable[[Any], dict[str, Any]]) -> dict[str, Any]:
    conn = _conn(conn_factory)
    try:
        out = fn(conn)
        conn.commit()
        return out
    except Exception as exc:
        conn.rollback()
        if type(exc).__name__ == "UniqueViolation":
            raise HTTPException(409, "Concurrent motivation update; retry") from exc
        raise
    finally:
        conn.close()


def save_generated(conn_factory: Callable[[], Any], case_id: str, org: str, actor: str, draft: MotivationDraft) -> dict[str, Any]:
    return _run(conn_factory, lambda c: _append(c, case_id, org, actor, draft, "motivation_generated", None))


def save_edit(conn_factory: Callable[[], Any], case_id: str, org: str, actor: str, edit: MotivationEdit) -> dict[str, Any]:
    def op(conn: Any) -> dict[str, Any]:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            previous = _latest(cur, case_id, org)
        draft = MotivationDraft(
            motive_category=edit.motive_category, signals=edit.signals, confidence=edit.confidence,
            rationale=edit.rationale, source="analyst",
            amount_at_stake_vnd=previous["amount_at_stake_vnd"] if previous else None,
        )
        return _append(conn, case_id, org, actor, draft, "motivation_edited", edit.expected_version)

    return _run(conn_factory, op)


def confirm(conn_factory: Callable[[], Any], case_id: str, org: str, actor: str, expected_version: int | None) -> dict[str, Any]:
    def op(conn: Any) -> dict[str, Any]:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            latest = _latest(cur, case_id, org)
            if latest is None:
                raise HTTPException(404, "No motivation assessment to confirm; generate one first")
            if expected_version is not None and expected_version != latest["version"]:
                raise HTTPException(409, "Motivation assessment changed; reload before confirming")
            if latest["status"] == "confirmed":
                raise HTTPException(409, "Motivation assessment already confirmed")
            cur.execute(
                f"""UPDATE app.case_motivation_assessments SET status = 'confirmed', confirmed_by = %s::uuid,
                    confirmed_at = now() WHERE id = %s::uuid AND status = 'draft' RETURNING {_COLS}""",
                (actor, latest["id"]),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(409, "Motivation assessment already confirmed")
            saved = _row(row)
            _audit(cur, org, actor, case_id, "motivation_confirmed", {"version": saved["version"]})
        return saved

    return _run(conn_factory, op)


async def get_view(case_service: Any, case_id: str, org: str) -> dict[str, Any]:
    """Persisted latest if any; otherwise the unsaved rule-based draft from case evidence (version 0)."""
    resolved = case_service._resolve_case_id(case_id)
    latest, history = await asyncio.to_thread(load, case_service._get_db_connection, resolved, org)
    if latest is not None:
        return {"assessment": latest, "persisted": True, "versions": history}
    detail = await case_service._get_case_detail_data(case_id, organization_id=org)
    draft = build_structured_assessment(detail.trip, detail.features, detail.telemetry_samples)
    return {"assessment": {**draft.model_dump(), "id": None, "case_id": resolved, "version": 0, "status": "draft"},
            "persisted": False, "versions": history}


async def generate_and_save(case_service: Any, case_id: str, org: str, actor: str) -> dict[str, Any]:
    detail = await case_service._get_case_detail_data(case_id, organization_id=org)
    draft = await generate_assessment(
        trip=detail.trip, features=detail.features, telemetry=detail.telemetry_samples,
        evidence_scope=str(detail.case.trip_id or detail.case.id), organization_id=org,
    )
    resolved = case_service._resolve_case_id(case_id)
    return await asyncio.to_thread(save_generated, case_service._get_db_connection, resolved, org, actor, draft)
