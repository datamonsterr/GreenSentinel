"""Live driver 90-day scorecard backing the Cockpit Driver tab (issue #100).

Spec: docs/architecture/COMPONENT_DATA_SOURCES.md §3.1. SQL lives in this
service layer (never in api routes). Adjudication outcomes follow the real
schema (``dismiss`` / ``warn`` / ``fine`` / ``suspend``); the spec SQL names
stale ``approve`` / ``reject`` verdicts, mapped here to the frontend
``exonerated`` / ``penalized`` / ``warned`` statuses.
"""

from __future__ import annotations

import base64
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

try:
    from fastapi import HTTPException as _FastAPIHTTPException
except ImportError:

    class _FallbackHTTPError(Exception):
        def __init__(self, status_code: int = 500, detail: str = ""):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    HTTPException: type[_FallbackHTTPError] | type[_FastAPIHTTPException] = _FallbackHTTPError
else:
    HTTPException = _FastAPIHTTPException

from src.models.schemas import (
    DriverFeedbackItem,
    DriverFeedbackResponse,
    DriverPastIncident,
    DriverProfileResponse,
    DriverScorecardResponse,
    DriverVehicleInfo,
    WeeklyRatingTrend,
)

SCORE_WINDOW_DAYS = 90
BENCHMARK_VIOLATION_RATIO = 5.0
PENALIZED_OUTCOMES = frozenset({"fine", "suspend", "reject"})
EXONERATED_OUTCOME = "dismiss"
LEGACY_EXONERATED_OUTCOME = "approve"
DEFAULT_INVESTIGATION_FINDING = "Đã xác minh qua đối soát dữ liệu viễn thông"
DEFAULT_VIOLATION_TYPE = "Nghi vấn vi phạm"


def compute_scorecard_metrics(total_trips: int, total_cases: int, penalized_cases: int) -> dict[str, Any]:
    """Pure metric math: ratios with zero-safe divisors, risk clamped to [10, 99]."""
    violation_ratio = round((total_cases / max(total_trips, 1)) * 100, 1)
    fined_ratio = round((penalized_cases / max(total_cases, 1)) * 100, 1)
    risk = min(99, max(10, round(total_cases * 15 + penalized_cases * 25)))
    return {
        "violation_ratio_90d": violation_ratio,
        "fined_ratio": fined_ratio,
        "repeat_offense_risk_score": risk,
        "benchmark_violation_ratio": BENCHMARK_VIOLATION_RATIO,
    }


def compute_tenure_months(created_at: datetime | str | None, now: datetime | None = None) -> int:
    """Whole months since driver creation; 0 when the timestamp is unknown."""
    if not created_at:
        return 0
    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            return 0
    ref = now or datetime.now(UTC)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    months = (ref.year - created_at.year) * 12 + (ref.month - created_at.month)
    return max(0, months)


def map_incident_status(outcome: str | None) -> str:
    norm = str(outcome or "").strip().lower()
    if norm == EXONERATED_OUTCOME or norm == LEGACY_EXONERATED_OUTCOME:
        return "exonerated"
    if norm in PENALIZED_OUTCOMES:
        return "penalized"
    return "warned"


def map_action_taken(outcome: str | None) -> str:
    norm = str(outcome or "").strip().lower()
    if norm == EXONERATED_OUTCOME or norm == LEGACY_EXONERATED_OUTCOME:
        return "Miễn trừ xử phạt (Exonerated)"
    if norm in PENALIZED_OUTCOMES:
        return "Cảnh cáo & Khấu trừ vi phạm"
    return "Cảnh cáo kỹ thuật hệ thống"


def build_incident(
    trip_id: str,
    occurred_at: str,
    violation_type: str | None,
    investigation_finding: str | None,
    outcome: str | None,
) -> DriverPastIncident:
    return DriverPastIncident(
        trip_id=trip_id,
        occurred_at=occurred_at,
        violation_type=violation_type or DEFAULT_VIOLATION_TYPE,
        investigation_finding=investigation_finding or DEFAULT_INVESTIGATION_FINDING,
        action_taken=map_action_taken(outcome),
        status=map_incident_status(outcome),  # type: ignore[arg-type]
    )


def _parse_ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def _within_window(value: Any, cutoff: datetime) -> bool:
    parsed = _parse_ts(value)
    return parsed is None or parsed >= cutoff


MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


_CLERK_PRINCIPAL_ID_RE = re.compile(r"^user_[A-Za-z0-9]+$")


def _sanitize_display_name(value: str | None) -> str | None:
    """Never surface a raw Clerk principal id (e.g. ``user_...``) as a display name.

    Auto-provisioned drivers with no stored name must read as unset (null),
    never the JIT-provisioning subject id used as a storage fallback.
    """
    if value and _CLERK_PRINCIPAL_ID_RE.match(value):
        return None
    return value


def _is_valid_uuid(value: str) -> bool:
    """True iff value parses as an RFC 4122 UUID (any version)."""
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def validate_month_param(month: str | None) -> None:
    """Raise 422 when month is set but not strictly YYYY-MM (01..12)."""
    if month is None:
        return
    if not MONTH_PATTERN.match(month):
        raise HTTPException(status_code=422, detail="month must match YYYY-MM (01..12)")


def month_bounds_utc(month: str) -> tuple[datetime, datetime]:
    """Half-open [start, end) UTC datetime bounds for a YYYY-MM month in Asia/Ho_Chi_Minh."""
    year, mon = int(month[:4]), int(month[5:7])
    start_local = datetime(year, mon, 1, tzinfo=VN_TZ)
    if mon == 12:
        end_local = datetime(year + 1, 1, 1, tzinfo=VN_TZ)
    else:
        end_local = datetime(year, mon + 1, 1, tzinfo=VN_TZ)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def _in_month(started_at: Any, month: str | None) -> bool:
    """True iff started_at falls inside the Asia/Ho_Chi_Minh month boundary (half-open)."""
    if not month:
        return True
    parsed = _parse_ts(started_at)
    if parsed is None:
        return False
    start, end = month_bounds_utc(month)
    return start <= parsed < end


async def get_driver_scorecard(
    driver_id: str,
    organization_id: str | None,
    case_service: Any = None,
) -> DriverScorecardResponse:
    """Scorecard for a driver UUID or external ref; 404 unknown, 403 cross-org, 503 no DB."""
    from src.services.case_service import get_case_service

    cs = case_service or get_case_service()
    conn = cs._get_db_connection()
    if conn is None:
        cs._require_test_fallback()
        return _memory_scorecard(str(driver_id), organization_id, cs)
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            cur.execute(
                """SELECT id, organization_id, created_at FROM app.drivers
                   WHERE id::text = %s OR external_ref = %s LIMIT 1;""",
                (str(driver_id), str(driver_id)),
            )
            driver = cur.fetchone()
            if not driver:
                raise HTTPException(status_code=404, detail=f"Driver {driver_id} not found")
            if organization_id and str(driver["organization_id"]) != str(organization_id):
                raise HTTPException(status_code=403, detail="Driver access denied")
            driver_uuid = driver["id"]
            window = f"{SCORE_WINDOW_DAYS} days"
            # Measured trip volume wins: app.driver_trips is the trip ledger
            # the driver app itself reads. Fall back to the legacy app.trips
            # join only when the driver has no measured rows in the window.
            measured_trips = 0
            try:
                cur.execute("SAVEPOINT scorecard_measured_trips;")
                cur.execute(
                    """SELECT COUNT(*) AS total_trips FROM app.driver_trips
                       WHERE driver_id = %s AND started_at >= NOW() - %s::interval;""",
                    (driver_uuid, window),
                )
                measured_trips = int((cur.fetchone() or {}).get("total_trips", 0))
                cur.execute("RELEASE SAVEPOINT scorecard_measured_trips;")
            except Exception:
                try:
                    cur.execute("ROLLBACK TO SAVEPOINT scorecard_measured_trips;")
                except Exception:
                    pass
                measured_trips = 0
            if measured_trips:
                total_trips = measured_trips
            else:
                cur.execute(
                    """SELECT COUNT(*) AS total_trips FROM app.trips t
                       JOIN app.trip_assignments ta ON ta.trip_id = t.id
                       WHERE ta.driver_id = %s AND t.created_at >= NOW() - %s::interval;""",
                    (driver_uuid, window),
                )
                total_trips = int((cur.fetchone() or {}).get("total_trips", 0))
            cur.execute(
                """SELECT COUNT(*) AS total_cases,
                           COUNT(*) FILTER (WHERE a.outcome IN ('fine', 'suspend', 'reject')) AS penalized_cases
                   FROM app.fraud_cases fc
                   JOIN app.trip_assignments ta ON ta.id = fc.assignment_id
                   LEFT JOIN app.adjudications a ON a.case_id = fc.id
                   WHERE ta.driver_id = %s AND fc.created_at >= NOW() - %s::interval;""",
                (driver_uuid, window),
            )
            counts = cur.fetchone() or {}
            total_cases = int(counts.get("total_cases", 0))
            penalized_cases = int(counts.get("penalized_cases", 0))
            cur.execute(
                """SELECT t.id::text AS trip_id,
                          TO_CHAR(fc.created_at, 'YYYY-MM-DD HH24:MI') AS occurred_at,
                          fc.created_at AS created_raw,
                          COALESCE(fc.suspected_category, %s) AS violation_type,
                          COALESCE(a.rationale, %s) AS investigation_finding,
                          a.outcome AS outcome
                   FROM app.fraud_cases fc
                   JOIN app.trip_assignments ta ON ta.id = fc.assignment_id
                   JOIN app.trips t ON t.id = ta.trip_id
                   LEFT JOIN app.adjudications a ON a.case_id = fc.id
                   WHERE ta.driver_id = %s
                   ORDER BY fc.created_at DESC LIMIT 3;""",
                (DEFAULT_VIOLATION_TYPE, DEFAULT_INVESTIGATION_FINDING, driver_uuid),
            )
            rows = [dict(r) for r in cur.fetchall()]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Scorecard database unavailable") from exc
    finally:
        conn.close()
    metrics = compute_scorecard_metrics(total_trips, total_cases, penalized_cases)
    incidents = [
        build_incident(
            r["trip_id"], r["occurred_at"], r["violation_type"], r["investigation_finding"], r.get("outcome")
        )
        for r in rows
    ]
    return DriverScorecardResponse(
        driver_id=str(driver_id),
        tenure_months=compute_tenure_months(driver.get("created_at")),
        past_incidents=incidents,
        total_trips=total_trips,
        total_cases=total_cases,
        **metrics,
    )


def _memory_scorecard(driver_id: str, organization_id: str | None, cs: Any) -> DriverScorecardResponse:
    """Test-stack fallback over in-memory seed state; unknown drivers are 404."""
    driver = cs._drivers.get(driver_id)
    if driver is None:
        for record in cs._drivers.values():
            if record.get("external_ref") == driver_id:
                driver = record
                break
    if driver is None:
        raise HTTPException(status_code=404, detail=f"Driver {driver_id} not found")
    if organization_id and driver.get("organization_id") and str(driver["organization_id"]) != str(organization_id):
        raise HTTPException(status_code=403, detail="Driver access denied")
    cutoff = datetime.now(UTC) - timedelta(days=SCORE_WINDOW_DAYS)
    measured_trips = sum(
        1
        for t in _memory_driver_trips.values()
        if str(t.get("driver_id")) in (str(driver.get("id", driver_id)), str(driver_id))
        and _within_window(t.get("started_at"), cutoff)
    )
    assignment_ids = [
        a
        for a, rec in cs._assignments.items()
        if str(rec.get("driver_id")) == str(driver.get("id", driver_id)) or str(rec.get("driver_id")) == driver_id
    ]
    total_trips = 0
    for asgn in assignment_ids:
        trip = cs._trips.get(str(cs._assignments[asgn].get("trip_id", ""))) or {}
        if _within_window(trip.get("created_at"), cutoff):
            total_trips += 1
    if measured_trips:
        total_trips = measured_trips
    driver_cases = [c for c in cs._cases.values() if str(c.get("assignment_id")) in set(assignment_ids)]
    driver_cases = [c for c in driver_cases if _within_window(c.get("created_at"), cutoff)]
    total_cases = len(driver_cases)
    outcomes = {str(adj.get("case_id")): str(adj.get("outcome", "")).lower() for adj in cs._adjudications}
    penalized_cases = sum(1 for c in driver_cases if outcomes.get(str(c.get("id"))) in PENALIZED_OUTCOMES)
    metrics = compute_scorecard_metrics(total_trips, total_cases, penalized_cases)
    driver_cases.sort(key=lambda c: str(c.get("created_at") or ""), reverse=True)
    incidents = []
    for case in driver_cases[:3]:
        asgn = cs._assignments.get(str(case.get("assignment_id"))) or {}
        outcome = outcomes.get(str(case.get("id")))
        rationale = next(
            (adj.get("rationale") for adj in cs._adjudications if str(adj.get("case_id")) == str(case.get("id"))),
            None,
        )
        incidents.append(
            build_incident(
                str(asgn.get("trip_id") or case.get("trip_id") or case.get("id")),
                str(case.get("created_at") or ""),
                case.get("suspected_category"),
                rationale,
                outcome,
            )
        )
    return DriverScorecardResponse(
        driver_id=driver_id,
        tenure_months=compute_tenure_months(driver.get("created_at")),
        past_incidents=incidents,
        total_trips=total_trips,
        total_cases=total_cases,
        **metrics,
    )


async def get_case_driver_scorecard(
    case_id: str,
    organization_id: str | None,
    case_service: Any = None,
) -> DriverScorecardResponse:
    """Alias resolving a case to its driver; unknown cases are 404."""
    from src.services.case_service import get_case_service

    cs = case_service or get_case_service()
    conn = cs._get_db_connection()
    if conn is None:
        cs._require_test_fallback()
        case = cs._cases.get(cs._resolve_case_id(case_id), {})
        if not case:
            raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
        if organization_id and case.get("organization_id", organization_id) != organization_id:
            raise HTTPException(status_code=403, detail="Case access denied")
        asgn = cs._assignments.get(str(case.get("assignment_id"))) or {}
        driver_id = asgn.get("driver_id")
        if not driver_id:
            raise HTTPException(status_code=404, detail=f"Case {case_id} has no driver")
        return await get_driver_scorecard(str(driver_id), organization_id, case_service=cs)
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            cur.execute(
                """SELECT ta.driver_id FROM app.fraud_cases fc
                   JOIN app.trip_assignments ta ON ta.id = fc.assignment_id
                   WHERE fc.id::text = %s LIMIT 1;""",
                (cs._resolve_case_id(case_id),),
            )
            row = cur.fetchone()
            if not row or not row.get("driver_id"):
                raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
            driver_id = str(row["driver_id"])
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Scorecard database unavailable") from exc
    finally:
        conn.close()
    return await get_driver_scorecard(driver_id, organization_id, case_service=cs)


# In-memory test store for driver_trips and trip_ratings
_memory_driver_trips: dict[str, dict[str, Any]] = {}
_memory_trip_ratings: dict[str, dict[str, Any]] = {}


def encode_trip_cursor(started_at: datetime | str, trip_id: str) -> str:
    """Encode (started_at, trip_id) into an opaque, URL-safe base64 string."""
    if hasattr(started_at, "isoformat"):
        ts_str = started_at.isoformat()
    else:
        ts_str = str(started_at)
    payload = json.dumps([ts_str, str(trip_id)])
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("utf-8")


def decode_trip_cursor(cursor: str) -> tuple[datetime, str] | None:
    """Decode opaque cursor into (started_at_dt, trip_id). Returns None if invalid."""
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8")
        data = json.loads(raw)
        if isinstance(data, list) and len(data) == 2:
            ts_str, trip_id = data
            dt = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt, str(trip_id)
    except Exception:
        return None
    return None


def _format_trip_record(row: dict[str, Any], rating: dict[str, Any] | None = None) -> dict[str, Any]:
    """Normalize a driver_trips record with optional trip_ratings."""
    started_at = row.get("started_at")
    if hasattr(started_at, "isoformat"):
        started_at = started_at.isoformat()
    ended_at = row.get("ended_at")
    if hasattr(ended_at, "isoformat"):
        ended_at = ended_at.isoformat()

    rating_data = None
    if rating:
        r_created = rating.get("created_at")
        if hasattr(r_created, "isoformat"):
            r_created = r_created.isoformat()
        rating_data = {
            "stars": rating.get("stars"),
            "comment": rating.get("comment"),
            "locale": rating.get("locale"),
            "created_at": r_created,
        }
    elif row.get("rating_stars") is not None:
        r_created = row.get("rating_created_at")
        if hasattr(r_created, "isoformat"):
            r_created = r_created.isoformat()
        rating_data = {
            "stars": row.get("rating_stars"),
            "comment": row.get("rating_comment"),
            "locale": row.get("rating_locale"),
            "created_at": r_created,
        }

    return {
        "trip_id": str(row.get("trip_id", "")),
        "driver_id": str(row.get("driver_id", "")),
        "organization_id": str(row.get("organization_id", "")) if row.get("organization_id") else None,
        "pickup_label": row.get("pickup_label") or "Điểm đón",
        "pickup_lat": float(row["pickup_lat"]) if row.get("pickup_lat") is not None else None,
        "pickup_lng": float(row["pickup_lng"]) if row.get("pickup_lng") is not None else None,
        "dropoff_label": row.get("dropoff_label") or "Điểm đến",
        "dropoff_lat": float(row["dropoff_lat"]) if row.get("dropoff_lat") is not None else None,
        "dropoff_lng": float(row["dropoff_lng"]) if row.get("dropoff_lng") is not None else None,
        "started_at": started_at,
        "ended_at": ended_at,
        "distance_km": float(row.get("distance_km") or 0.0),
        "duration_min": float(row.get("duration_min") or 0.0),
        "fare_vnd": int(row.get("fare_vnd") or 0),
        "payment_method": str(row.get("payment_method") or "wallet"),
        "payment_method_synthetic": bool(row.get("payment_method_synthetic", True)),
        "status": str(row.get("status") or "completed"),
        "case_id": str(row["case_id"]) if row.get("case_id") else None,
        "has_case": bool(row.get("case_id")),
        "rating": rating_data,
    }


async def list_driver_trips(
    driver_id: str,
    cursor: str | None = None,
    limit: int = 20,
    status: str | None = None,
    month: str | None = None,
    organization_id: str | None = None,
    case_service: Any = None,
) -> dict[str, Any]:
    """Retrieve paginated trips for a driver from app.driver_trips + app.trip_ratings.

    ``total`` and ``counts`` are always computed independent of ``cursor`` (same
    driver/org/month WHERE); ``counts`` additionally ignores ``status`` so tab
    badges reflect the full month regardless of the active filter.
    """
    if not driver_id or not str(driver_id).strip():
        raise HTTPException(status_code=403, detail="driver_id is required")
    validate_month_param(month)

    did = str(driver_id).strip()
    clamped_limit = max(1, min(int(limit), 50))
    from src.services.case_service import get_case_service

    cs = case_service or get_case_service()
    conn = cs._get_db_connection()

    if conn is None:
        # In-memory test fallback
        cs._require_test_fallback()
        base_trips = [t for t in _memory_driver_trips.values() if str(t.get("driver_id")) == did]
        if organization_id:
            base_trips = [t for t in base_trips if str(t.get("organization_id")) == str(organization_id)]
        if month:
            base_trips = [t for t in base_trips if _in_month(t.get("started_at"), month)]

        def is_flagged(t: dict[str, Any]) -> bool:
            return bool(t.get("case_id")) or t.get("status") == "flagged"

        def is_completed(t: dict[str, Any]) -> bool:
            return t.get("status") == "completed" and not t.get("case_id")

        counts = {
            "all": len(base_trips),
            "completed": len([t for t in base_trips if is_completed(t)]),
            "flagged": len([t for t in base_trips if is_flagged(t)]),
        }

        if status == "flagged":
            trips = [t for t in base_trips if is_flagged(t)]
        elif status == "completed":
            trips = [t for t in base_trips if is_completed(t)]
        elif status:
            trips = [t for t in base_trips if t.get("status") == status]
        else:
            trips = base_trips

        total = len(trips)

        def trip_sort_key(t: dict[str, Any]) -> tuple[datetime, str]:
            dt = _parse_ts(t.get("started_at")) or datetime.min.replace(tzinfo=UTC)
            return (dt, str(t.get("trip_id", "")))

        trips = sorted(trips, key=trip_sort_key, reverse=True)

        if cursor:
            dec = decode_trip_cursor(cursor)
            if dec:
                cur_dt, cur_id = dec
                trips = [t for t in trips if trip_sort_key(t) < (cur_dt, cur_id)]

        page = trips[:clamped_limit]
        has_more = len(trips) > clamped_limit
        formatted = []
        for t in page:
            tid = str(t.get("trip_id"))
            rating = _memory_trip_ratings.get(tid)
            formatted.append(_format_trip_record(t, rating))

        next_cursor = (
            encode_trip_cursor(page[-1].get("started_at"), str(page[-1].get("trip_id")))
            if (has_more and page)
            else None
        )
        return {
            "trips": formatted,
            "total": total,
            "next_cursor": next_cursor,
            "counts": counts,
        }

    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")

            base_where = "WHERE t.driver_id = %s"
            base_params: list[Any] = [did]
            if organization_id:
                base_where += " AND t.organization_id = %s"
                base_params.append(organization_id)
            if month:
                start, end = month_bounds_utc(month)
                base_where += " AND t.started_at >= %s AND t.started_at < %s"
                base_params.extend([start, end])

            # Per-status counts independent of the `status` filter (tab badges).
            cur.execute(
                f"""
                SELECT
                    COUNT(*) AS all_count,
                    COUNT(*) FILTER (WHERE t.status = 'completed' AND t.case_id IS NULL) AS completed_count,
                    COUNT(*) FILTER (WHERE t.case_id IS NOT NULL OR t.status = 'flagged') AS flagged_count
                FROM app.driver_trips t
                {base_where}
                """,
                tuple(base_params),
            )
            counts_row = dict(cur.fetchone() or {})
            counts = {
                "all": int(counts_row.get("all_count") or 0),
                "completed": int(counts_row.get("completed_count") or 0),
                "flagged": int(counts_row.get("flagged_count") or 0),
            }

            status_where = base_where
            status_params = list(base_params)
            if status == "flagged":
                status_where += " AND (t.case_id IS NOT NULL OR t.status = 'flagged')"
            elif status == "completed":
                status_where += " AND t.status = 'completed' AND t.case_id IS NULL"
            elif status:
                status_where += " AND t.status = %s"
                status_params.append(status)

            # total independent of cursor, scoped by driver/org/month/status.
            cur.execute(
                f"SELECT COUNT(*) AS total FROM app.driver_trips t {status_where}",
                tuple(status_params),
            )
            total_row = dict(cur.fetchone() or {})
            total = int(total_row.get("total") or 0)

            query = f"""
                SELECT t.trip_id, t.driver_id, t.organization_id, t.pickup_label,
                       t.pickup_lat, t.pickup_lng, t.dropoff_label, t.dropoff_lat, t.dropoff_lng,
                       t.started_at, t.ended_at, t.distance_km, t.duration_min, t.fare_vnd,
                       t.payment_method, t.payment_method_synthetic, t.status, t.case_id,
                       r.stars as rating_stars, r.comment as rating_comment, r.created_at as rating_created_at,
                       r.locale as rating_locale
                FROM app.driver_trips t
                LEFT JOIN app.trip_ratings r ON r.trip_id = t.trip_id
                {status_where}
            """
            params = list(status_params)

            if cursor:
                dec = decode_trip_cursor(cursor)
                if dec:
                    cur_dt, cur_id = dec
                    query += " AND (t.started_at, t.trip_id) < (%s, %s)"
                    params.extend([cur_dt, cur_id])

            query += " ORDER BY t.started_at DESC, t.trip_id DESC LIMIT %s"
            params.append(clamped_limit + 1)

            cur.execute(query, tuple(params))
            rows = [dict(r) for r in cur.fetchall()]

            has_more = len(rows) > clamped_limit
            page_rows = rows[:clamped_limit]
            formatted_trips = [_format_trip_record(r) for r in page_rows]
            next_cursor = (
                encode_trip_cursor(page_rows[-1]["started_at"], str(page_rows[-1]["trip_id"]))
                if (has_more and page_rows)
                else None
            )

            return {
                "trips": formatted_trips,
                "total": total,
                "next_cursor": next_cursor,
                "counts": counts,
            }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Driver trips database unavailable") from exc
    finally:
        conn.close()


async def get_driver_trips_monthly_summary(
    driver_id: str,
    month: str | None = None,
    organization_id: str | None = None,
    case_service: Any = None,
) -> dict[str, Any]:
    """Retrieve monthly earnings and trip statistics summary for a driver.

    ``trip_count`` is the count of all trips in the month (any status), not
    just completed ones; see DriverTripsSummaryResponse.trip_count docstring.
    """
    if not driver_id or not str(driver_id).strip():
        raise HTTPException(status_code=403, detail="driver_id is required")
    validate_month_param(month)

    did = str(driver_id).strip()
    from src.services.case_service import get_case_service

    cs = case_service or get_case_service()
    conn = cs._get_db_connection()

    if conn is None:
        cs._require_test_fallback()
        trips = [t for t in _memory_driver_trips.values() if str(t.get("driver_id")) == did]
        if organization_id:
            trips = [t for t in trips if str(t.get("organization_id")) == str(organization_id)]
        if month:
            trips = [t for t in trips if _in_month(t.get("started_at"), month)]

        trip_count = len(trips)
        total_fare_vnd = sum(int(t.get("fare_vnd", 0)) for t in trips)
        total_distance_km = round(sum(float(t.get("distance_km", 0.0)) for t in trips), 2)

        rated_stars = []
        for t in trips:
            tid = str(t.get("trip_id"))
            r = _memory_trip_ratings.get(tid)
            if r and r.get("stars") is not None:
                rated_stars.append(float(r["stars"]))
        avg_rating = round(sum(rated_stars) / len(rated_stars), 2) if rated_stars else None

        return {
            "month": month,
            "trip_count": trip_count,
            "total_fare_vnd": total_fare_vnd,
            "total_distance_km": total_distance_km,
            "avg_rating": avg_rating,
        }

    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            query = """
                SELECT COUNT(*) as trip_count,
                       COALESCE(SUM(t.fare_vnd), 0) as total_fare,
                       COALESCE(SUM(t.distance_km), 0.0) as total_distance,
                       AVG(r.stars) as avg_rating
                FROM app.driver_trips t
                LEFT JOIN app.trip_ratings r ON r.trip_id = t.trip_id
                WHERE t.driver_id = %s
            """
            params: list[Any] = [did]
            if organization_id:
                query += " AND t.organization_id = %s"
                params.append(organization_id)
            if month:
                start, end = month_bounds_utc(month)
                query += " AND t.started_at >= %s AND t.started_at < %s"
                params.extend([start, end])

            cur.execute(query, tuple(params))
            row = cur.fetchone()
            if not row:
                return {
                    "month": month,
                    "trip_count": 0,
                    "total_fare_vnd": 0,
                    "total_distance_km": 0.0,
                    "avg_rating": None,
                }
            row_dict = dict(row)
            avg_r = row_dict.get("avg_rating")
            return {
                "month": month,
                "trip_count": int(row_dict.get("trip_count") or 0),
                "total_fare_vnd": int(row_dict.get("total_fare") or 0),
                "total_distance_km": round(float(row_dict.get("total_distance") or 0.0), 2),
                "avg_rating": round(float(avg_r), 2) if avg_r is not None else None,
            }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Driver trips database unavailable") from exc
    finally:
        conn.close()


async def get_driver_trip_summary(
    trip_id: str,
    driver_id: str,
    organization_id: str | None = None,
    case_service: Any = None,
) -> dict[str, Any]:
    """Retrieve detailed trip summary with rating, enforcing driver ownership.

    Returns 404 NOT_FOUND for foreign, missing, or malformed (non-UUID) trip
    ids, to prevent existence probing and to avoid a 503 from a malformed
    UUID literal reaching Postgres.
    """
    if not trip_id or not str(trip_id).strip():
        raise HTTPException(status_code=404, detail="trip_id is required")
    if not driver_id or not str(driver_id).strip():
        raise HTTPException(status_code=403, detail="driver_id is required")

    tid = str(trip_id).strip()
    did = str(driver_id).strip()

    if not _is_valid_uuid(tid):
        raise HTTPException(status_code=404, detail=f"Trip {trip_id} not found")

    from src.services.case_service import get_case_service

    cs = case_service or get_case_service()
    conn = cs._get_db_connection()

    if conn is None:
        # In-memory test fallback
        cs._require_test_fallback()
        trip = _memory_driver_trips.get(tid)
        if not trip:
            raise HTTPException(status_code=404, detail=f"Trip {trip_id} not found")
        actual_driver = str(trip.get("driver_id", ""))
        if actual_driver != did:
            raise HTTPException(
                status_code=404,
                detail=f"Trip {trip_id} not found",
            )
        rating = _memory_trip_ratings.get(tid)
        return _format_trip_record(trip, rating)

    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            cur.execute(
                """
                SELECT t.trip_id, t.driver_id, t.organization_id, t.pickup_label,
                       t.pickup_lat, t.pickup_lng, t.dropoff_label, t.dropoff_lat, t.dropoff_lng,
                       t.started_at, t.ended_at, t.distance_km, t.duration_min, t.fare_vnd,
                       t.payment_method, t.payment_method_synthetic, t.status, t.case_id,
                       r.stars as rating_stars, r.comment as rating_comment, r.created_at as rating_created_at,
                       r.locale as rating_locale
                FROM app.driver_trips t
                LEFT JOIN app.trip_ratings r ON r.trip_id = t.trip_id
                WHERE t.trip_id = %s
                LIMIT 1;
                """,
                (tid,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Trip {trip_id} not found")

            row_dict = dict(row)
            actual_driver = str(row_dict.get("driver_id", ""))
            if actual_driver != did:
                raise HTTPException(
                    status_code=404,
                    detail=f"Trip {trip_id} not found",
                )
            if organization_id and str(row_dict.get("organization_id")) != str(organization_id):
                raise HTTPException(status_code=404, detail=f"Trip {trip_id} not found")

            return _format_trip_record(row_dict)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Driver trips database unavailable") from exc
    finally:
        conn.close()


def _iso_week_floor(dt: datetime) -> datetime:
    """Midnight Monday (UTC) of the ISO calendar week containing dt."""
    d = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return d - timedelta(days=d.weekday())


def _weekly_bucket_bounds(ref_now: datetime) -> list[tuple[str, datetime, datetime]]:
    """8 ISO calendar-week buckets (Mon 00:00 .. next Mon 00:00), oldest first, ending with the current week."""
    current_week_start = _iso_week_floor(ref_now)
    bounds = []
    for i in range(7, -1, -1):
        w_start = current_week_start - timedelta(weeks=i)
        w_end = w_start + timedelta(weeks=1)
        bounds.append((f"W{8 - i}", w_start, w_end))
    return bounds


def _rating_distribution_query(has_org: bool) -> str:
    org_clause = " AND t.organization_id = %s" if has_org else ""
    return f"""
        SELECT r.stars, COUNT(*) AS cnt
        FROM app.driver_trips t
        JOIN app.trip_ratings r ON r.trip_id = t.trip_id
        WHERE t.driver_id = %s AND r.stars BETWEEN 1 AND 5{org_clause}
        GROUP BY r.stars;
    """


def _weekly_trend_query(has_org: bool) -> str:
    org_clause = " AND t.organization_id = %s" if has_org else ""
    return f"""
        SELECT date_trunc('week', r.created_at) AS week_start,
               COUNT(*) AS cnt,
               AVG(r.stars) AS avg_stars
        FROM app.driver_trips t
        JOIN app.trip_ratings r ON r.trip_id = t.trip_id
        WHERE t.driver_id = %s AND r.stars BETWEEN 1 AND 5
              AND r.created_at >= %s{org_clause}
        GROUP BY date_trunc('week', r.created_at);
    """


def _rating_params(driver_id: str, organization_id: str | None, extra: list[Any] | None = None) -> tuple[Any, ...]:
    params: list[Any] = [driver_id]
    if extra:
        params.extend(extra)
    if organization_id:
        params.append(organization_id)
    return tuple(params)


async def get_driver_profile(
    driver_id: str,
    organization_id: str | None = None,
    case_service: Any = None,
) -> DriverProfileResponse:
    """Retrieve driver profile with identity, vehicle, 90-day scorecard, ratings, distribution, and weekly trend.
    404 NOT_FOUND for unknown or foreign driver identity.
    """
    if not driver_id or not str(driver_id).strip():
        raise HTTPException(status_code=404, detail="Driver not found")
    did = str(driver_id).strip()

    from src.services.case_service import get_case_service

    cs = case_service or get_case_service()
    conn = cs._get_db_connection()

    display_name: str | None = None
    member_since: str | None = None
    vehicle_info: DriverVehicleInfo | None = None

    ref_now = datetime.now(UTC)
    week_bounds = _weekly_bucket_bounds(ref_now)
    oldest_week_start = week_bounds[0][1]

    try:
        # Step 1: fetch scorecard (inside try/finally so `conn` is never leaked
        # if this raises, e.g. 404 for an unknown driver). The scorecard raises
        # 403 for cross-org access; the profile contract is 404 for unknown or
        # foreign driver identity (never leaking existence), so remap it here.
        try:
            scorecard = await get_driver_scorecard(did, organization_id, cs)
        except HTTPException as exc:
            if exc.status_code == 403:
                raise HTTPException(status_code=404, detail=f"Driver {did} not found") from exc
            raise

        # Step 2: fetch driver identity and vehicle
        if conn is None:
            cs._require_test_fallback()
            driver = cs._drivers.get(did)
            if not driver:
                for rec in cs._drivers.values():
                    if rec.get("external_ref") == did:
                        driver = rec
                        break
            if not driver:
                raise HTTPException(status_code=404, detail=f"Driver {did} not found")
            if (
                organization_id
                and driver.get("organization_id")
                and str(driver["organization_id"]) != str(organization_id)
            ):
                raise HTTPException(status_code=404, detail=f"Driver {did} not found")

            display_name = _sanitize_display_name(driver.get("display_name") or driver.get("full_name"))
            created_at_val = driver.get("created_at")
            if hasattr(created_at_val, "isoformat"):
                member_since = created_at_val.isoformat()
            elif created_at_val:
                member_since = str(created_at_val)

            v_model = driver.get("vehicle_model")
            v_plate = driver.get("vehicle_plate")
            if not v_plate or not v_model:
                for asgn in cs._assignments.values():
                    if str(asgn.get("driver_id")) == did or str(asgn.get("driver_id")) == str(driver.get("id")):
                        vid = asgn.get("vehicle_id")
                        if vid and vid in cs._vehicles:
                            veh = cs._vehicles[vid]
                            v_plate = v_plate or veh.get("registration_ref")
                            v_model = v_model or veh.get("service_class") or veh.get("vehicle_type")
                        break
            if v_model or v_plate:
                vehicle_info = DriverVehicleInfo(model=v_model, plate=v_plate)

            # In-memory ratings calculation; only measured stars 1..5 count
            # toward the average/distribution (comment-only rows are excluded here
            # but remain valid customer feedback, see list_driver_feedback).
            driver_trips = [t for t in _memory_driver_trips.values() if str(t.get("driver_id")) == did]
            if organization_id:
                driver_trips = [t for t in driver_trips if str(t.get("organization_id")) == str(organization_id)]

            trip_ids = {str(t.get("trip_id")) for t in driver_trips}
            ratings: list[dict[str, Any]] = []
            for tid in trip_ids:
                r = _memory_trip_ratings.get(tid)
                if r and r.get("stars") is not None and int(r["stars"]) in (1, 2, 3, 4, 5):
                    ratings.append(r)
        else:
            with conn.cursor() as cur:
                cur.execute("SET search_path = app, extensions, public;")
                query = """
                    SELECT d.id, d.organization_id, d.created_at,
                           COALESCE(d.display_name, p.display_name) as display_name,
                           v.registration_ref as vehicle_plate,
                           COALESCE(v.service_class, v.vehicle_type) as vehicle_model
                    FROM app.drivers d
                    LEFT JOIN app.principals p ON d.principal_id = p.id
                    LEFT JOIN app.driver_vehicle_assignments dva ON d.id = dva.driver_id AND dva.effective_to IS NULL
                    LEFT JOIN app.vehicles v ON dva.vehicle_id = v.id
                    WHERE (d.id::text = %s OR d.external_ref = %s)
                """
                params = [did, did]
                if organization_id:
                    query += " AND d.organization_id = %s"
                    params.append(organization_id)
                query += " LIMIT 1;"
                cur.execute(query, tuple(params))
                driver_row = cur.fetchone()
                if not driver_row:
                    raise HTTPException(status_code=404, detail=f"Driver {did} not found")
                d_dict = dict(driver_row)
                if organization_id and str(d_dict.get("organization_id")) != str(organization_id):
                    raise HTTPException(status_code=404, detail=f"Driver {did} not found")

                display_name = _sanitize_display_name(d_dict.get("display_name"))
                c_at = d_dict.get("created_at")
                if hasattr(c_at, "isoformat"):
                    member_since = c_at.isoformat()
                elif c_at:
                    member_since = str(c_at)

                if d_dict.get("vehicle_model") or d_dict.get("vehicle_plate"):
                    vehicle_info = DriverVehicleInfo(
                        model=d_dict.get("vehicle_model"),
                        plate=d_dict.get("vehicle_plate"),
                    )

                driver_uuid_str = str(d_dict["id"])

                # Distribution/average aggregated in SQL (GROUP BY stars),
                # restricted to measured stars 1..5.
                cur.execute(
                    _rating_distribution_query(organization_id is not None),
                    _rating_params(driver_uuid_str, organization_id),
                )
                dist_rows = [dict(row) for row in cur.fetchall()]

                cur.execute(
                    _weekly_trend_query(organization_id is not None),
                    _rating_params(driver_uuid_str, organization_id, extra=[oldest_week_start]),
                )
                week_rows = [dict(row) for row in cur.fetchall()]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Driver database unavailable") from exc
    finally:
        if conn is not None:
            conn.close()

    # Step 3: Compute rating metrics (measured values only)
    if conn is None:
        rated_count = len(ratings)
        rating_average = None
        dist = {"5": 0, "4": 0, "3": 0, "2": 0, "1": 0}
        if rated_count > 0:
            stars_list = [int(r["stars"]) for r in ratings]
            rating_average = round(sum(stars_list) / rated_count, 2)
            for s in stars_list:
                key = str(s)
                if key in dist:
                    dist[key] += 1
    else:
        dist = {"5": 0, "4": 0, "3": 0, "2": 0, "1": 0}
        for row in dist_rows:
            key = str(int(row["stars"]))
            if key in dist:
                dist[key] = int(row["cnt"])
        rated_count = sum(dist.values())
        rating_average = round(sum(int(k) * v for k, v in dist.items()) / rated_count, 2) if rated_count else None

    # Step 4: Weekly rating trend for last 8 ISO calendar weeks, aggregated via SQL
    # (date_trunc('week', ...)) for the DB path; mirrored bucketing in Python for
    # the in-memory test fallback. Weeks with no measured ratings are gaps (null avg).
    weekly_trend: list[WeeklyRatingTrend] = []
    if conn is None:
        for w_label, w_start, w_end in week_bounds:
            week_ratings = []
            for r in ratings:
                r_ts = _parse_ts(r.get("created_at"))
                if r_ts and w_start <= r_ts < w_end:
                    week_ratings.append(int(r["stars"]))
            w_avg = round(sum(week_ratings) / len(week_ratings), 2) if week_ratings else None
            weekly_trend.append(
                WeeklyRatingTrend(
                    week_label=w_label,
                    week_start=w_start.strftime("%Y-%m-%d"),
                    average_rating=w_avg,
                    rated_count=len(week_ratings),
                )
            )
    else:
        by_week_start = {}
        for row in week_rows:
            ws = row.get("week_start")
            ws_date = ws.date() if hasattr(ws, "date") else ws
            by_week_start[ws_date] = row
        for w_label, w_start, _w_end in week_bounds:
            row = by_week_start.get(w_start.date())
            cnt = int(row["cnt"]) if row else 0
            avg_stars = round(float(row["avg_stars"]), 2) if row and row.get("avg_stars") is not None else None
            weekly_trend.append(
                WeeklyRatingTrend(
                    week_label=w_label,
                    week_start=w_start.strftime("%Y-%m-%d"),
                    average_rating=avg_stars,
                    rated_count=cnt,
                )
            )

    return DriverProfileResponse(
        driver_id=did,
        display_name=display_name,
        vehicle=vehicle_info,
        member_since=member_since,
        scorecard=scorecard,
        rating_average=rating_average,
        rated_count=rated_count,
        distribution=dist,
        weekly_trend=weekly_trend,
    )


async def list_driver_feedback(
    driver_id: str,
    cursor: str | None = None,
    limit: int = 20,
    organization_id: str | None = None,
    case_service: Any = None,
) -> DriverFeedbackResponse:
    """Retrieve paginated customer feedback for a driver.
    404 NOT_FOUND for unknown or foreign driver identity.
    """
    if not driver_id or not str(driver_id).strip():
        raise HTTPException(status_code=404, detail="Driver not found")
    did = str(driver_id).strip()
    clamped_limit = max(1, min(int(limit), 50))

    from src.services.case_service import get_case_service

    cs = case_service or get_case_service()
    conn = cs._get_db_connection()

    if conn is None:
        cs._require_test_fallback()
        driver = cs._drivers.get(did)
        if not driver:
            for rec in cs._drivers.values():
                if rec.get("external_ref") == did:
                    driver = rec
                    break
        if not driver:
            raise HTTPException(status_code=404, detail=f"Driver {did} not found")
        if organization_id and driver.get("organization_id") and str(driver["organization_id"]) != str(organization_id):
            raise HTTPException(status_code=404, detail=f"Driver {did} not found")

        trips = [t for t in _memory_driver_trips.values() if str(t.get("driver_id")) == did]
        if organization_id:
            trips = [t for t in trips if str(t.get("organization_id")) == str(organization_id)]

        feedback_list = []
        for t in trips:
            tid = str(t.get("trip_id"))
            r = _memory_trip_ratings.get(tid)
            if r is None:
                continue
            stars = r.get("stars")
            comment = r.get("comment")
            has_comment = bool(comment and str(comment).strip())
            # A feedback row is valid when it has measured stars OR a non-empty
            # comment (comment-only ratings are valid customer feedback).
            if stars is None and not has_comment:
                continue
            c_at = r.get("created_at")
            if hasattr(c_at, "isoformat"):
                c_at = c_at.isoformat()
            # Never substitute the trip's started_at for the rating date: the
            # rating date is the rating's own created_at, or null.
            date_value = str(c_at) if c_at else None
            feedback_list.append(
                {
                    "id": tid,
                    "stars": stars,
                    "comment": comment,
                    "date": date_value,
                    "created_at": date_value,
                }
            )

        def fb_sort_key(item: dict[str, Any]) -> tuple[datetime, str]:
            dt = _parse_ts(item.get("date")) or datetime.min.replace(tzinfo=UTC)
            return (dt, str(item.get("id", "")))

        feedback_list.sort(key=fb_sort_key, reverse=True)
        full_total = len(feedback_list)

        paged_list = feedback_list
        if cursor:
            dec = decode_trip_cursor(cursor)
            if dec:
                cur_dt, cur_id = dec
                paged_list = [fb for fb in feedback_list if fb_sort_key(fb) < (cur_dt, cur_id)]

        page = paged_list[:clamped_limit]
        has_more = len(paged_list) > clamped_limit
        next_cursor = (
            encode_trip_cursor(page[-1]["date"] or "1970-01-01T00:00:00+00:00", str(page[-1]["id"]))
            if (has_more and page)
            else None
        )

        return DriverFeedbackResponse(
            items=[DriverFeedbackItem(**fb) for fb in page],
            next_cursor=next_cursor,
            total=full_total,
        )

    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            cur.execute(
                "SELECT id, organization_id FROM app.drivers WHERE id::text = %s OR external_ref = %s LIMIT 1;",
                (did, did),
            )
            d_row = cur.fetchone()
            if not d_row:
                raise HTTPException(status_code=404, detail=f"Driver {did} not found")
            if organization_id and str(d_row["organization_id"]) != str(organization_id):
                raise HTTPException(status_code=404, detail=f"Driver {did} not found")

            # A feedback row is valid when it has measured stars OR a non-empty
            # comment (comment-only ratings are valid customer feedback).
            feedback_filter = " AND (r.stars IS NOT NULL OR (r.comment IS NOT NULL AND r.comment <> ''))"

            count_query = f"""
                SELECT COUNT(*) AS total
                FROM app.driver_trips t
                JOIN app.trip_ratings r ON r.trip_id = t.trip_id
                WHERE t.driver_id = %s{feedback_filter}
            """
            count_params: list[Any] = [did]
            if organization_id:
                count_query += " AND t.organization_id = %s"
                count_params.append(organization_id)
            cur.execute(count_query, tuple(count_params))
            full_total = int((cur.fetchone() or {}).get("total", 0))

            query = f"""
                SELECT r.trip_id, r.stars, r.comment, r.created_at
                FROM app.driver_trips t
                JOIN app.trip_ratings r ON r.trip_id = t.trip_id
                WHERE t.driver_id = %s{feedback_filter}
            """
            params: list[Any] = [did]
            if organization_id:
                query += " AND t.organization_id = %s"
                params.append(organization_id)

            if cursor:
                dec = decode_trip_cursor(cursor)
                if dec:
                    cur_dt, cur_id = dec
                    query += " AND (r.created_at, r.trip_id) < (%s, %s)"
                    params.extend([cur_dt, cur_id])

            query += " ORDER BY r.created_at DESC, r.trip_id DESC LIMIT %s"
            params.append(clamped_limit + 1)

            cur.execute(query, tuple(params))
            rows = [dict(r) for r in cur.fetchall()]

            has_more = len(rows) > clamped_limit
            page_rows = rows[:clamped_limit]

            items = []
            for row in page_rows:
                c_at = row.get("created_at")
                c_at_str = c_at.isoformat() if hasattr(c_at, "isoformat") else str(c_at)
                items.append(
                    DriverFeedbackItem(
                        id=str(row["trip_id"]),
                        stars=row.get("stars"),
                        comment=row.get("comment"),
                        date=c_at_str,
                        created_at=c_at_str,
                    )
                )

            next_cursor = (
                encode_trip_cursor(page_rows[-1]["created_at"], str(page_rows[-1]["trip_id"]))
                if (has_more and page_rows)
                else None
            )

            return DriverFeedbackResponse(
                items=items,
                next_cursor=next_cursor,
                total=full_total,
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Driver feedback database unavailable") from exc
    finally:
        conn.close()
