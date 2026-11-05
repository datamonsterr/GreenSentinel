import asyncio
import hashlib
import json
import logging
import math
import os
import re
import time
import unicodedata
from collections.abc import AsyncGenerator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar
from uuid import UUID, uuid4

try:
    import psycopg as _psycopg
    from psycopg.rows import dict_row as _dict_row
except ImportError:
    psycopg = None
    dict_row = None
else:
    psycopg = _psycopg
    dict_row = _dict_row

try:
    import redis as _redis
except ImportError:
    redis = None
else:
    redis = _redis

try:
    from fastapi import HTTPException as _FastAPIHTTPException
except ImportError:

    class _FallbackHTTPError(Exception):
        """Fallback HTTPException when fastapi is not installed (e.g. lightweight eval environments)."""

        def __init__(self, status_code: int = 500, detail: str = ""):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    HTTPException: type[_FallbackHTTPError] | type[_FastAPIHTTPException] = _FallbackHTTPError
else:
    HTTPException = _FastAPIHTTPException


from src.config import Settings, get_settings
from src.models.schemas import (
    ActiveReviewLeaseSummary,
    AdjudicationRequest,
    AdjudicationResponse,
    AnalystAuditLedgerItem,
    AnalystAuditProfileResponse,
    AnalystDecisionMetrics,
    AnalystGovernanceLimits,
    AnalyticsDispositionMetrics,
    AnalyticsMetricsResponse,
    AnalyticsPerformanceMetrics,
    AnalyticsQueueMetrics,
    AnalyticsSystemHealth,
    CaseActionRequest,
    CaseActionResponse,
    CaseDetailResponse,
    CaseListResponse,
    CasePolicyClause,
    CasePolicyResponse,
    ClaimCaseRequest,
    ClaimCaseResponse,
    ConversationMessage,
    ForensicAbnormality,
    ForensicBriefResponse,
    FraudCaseSummary,
    IngestResult,
    PolicyChatRequest,
    PreliminaryAssessmentRequest,
    PreliminaryJudgment,
    ReleaseCaseRequest,
    ReleaseCaseResponse,
    SimulationTriggerResponse,
    StagedAdjudicationContext,
    TelemetryEventEnvelope,
    WorkflowDraftRequest,
    WorkflowDraftResponse,
)
from src.services.motivation_assessment_service import (
    assess_driver_motivation,
    fare_economics_from_record,
    generate_motivation_assessment,
)
from src.services.route_analytics import (
    build_trip_timeline_milestones,
    detect_telemetry_missingness,
)
from src.services.routing_service import fetch_osrm_route
from src.services.supabase import SupabaseRestClient

logger = logging.getLogger(__name__)

# S4-RETIRE #303 inventory (operational trip/case mocks retired; test fixtures under
# tests/ and eval/ golden sets are out of scope and preserved):
# | # | Location | Retired mock | Replacement / explicit unavailable |
# |---|---|---|---|
# | 1 | scripts/seed_database.py main() | default data/synthetic/seed_data.json (legacy, no manifest) | GREENSENTINEL_SEED_PATH explicit versioned road-v1 dataset (scripts/road_dataset.py, ADR-011); unversioned refused unless GREENSENTINEL_ALLOW_LEGACY_SEED=1 |
# | 2 | CaseService._load_seed_data/_find_seed_file | legacy seed_data defaults auto-loaded | only manifest.dataset_version==road-v1 loads; else accurate empty state |
# | 3 | CaseService aliases | hardcoded legacy aliases retired (see git history) | removed; unknown ids are 404 | # S4-RETIRE-allow: inventory names retired mocks
# | 4 | CaseService.get_principal_role/list_principals | fallback actors (name-matched fraud_analyst, 3 hardcoded principals) | unauthorized / [] on unavailable DB; explicit in-memory test principals only |
# | 5 | DriverDisputeService._traffic_overrides | hardcoded case-026 success (2.88m/s, heavy) | explicit unavailable traffic; scenario overrides via isolated seeder only |
# | 6 | adjudication-data-adapter getDriverScorecard | hash-synthesized ratios + fake incidents retired | live GET /api/v1/drivers/{id}/scorecard via src/services/driver_service.py (issue #100) | # S4-RETIRE-allow: inventory names retired mocks
# | 7 | adjudication-data-adapter getTrafficProbeSummary | default-speed/provider success retired | explicit UNAVAILABLE | # S4-RETIRE-allow: inventory names retired mocks
# | 8 | driver-info-tab | synthetic fallback driver retired | explicit empty state, no synthetic driver | # S4-RETIRE-allow: inventory names retired mocks
# | Approved explicit-unavailable: empty org -> empty list; unavailable DB (non-test) -> 503; missing telemetry/traffic -> unavailable flags (ADR-011). |
# | Preserved (out of scope): tests/fixtures/mock-data.ts, eval golden sets, real user evidence/cases/decisions/audit records. |


def _source_backed_route_geometry(route_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return only validated road geometry with explicit OSRM provenance."""
    geometry: dict[str, Any] = {}
    for item in route_rows:
        provenance = item.get("provenance") or {}
        if isinstance(provenance, str):
            try:
                provenance = json.loads(provenance)
            except (TypeError, ValueError):
                continue
        if (
            str(item.get("provider", "")).lower() != "osrm"
            or not isinstance(provenance, dict)
            or provenance.get("source") != "osrm"
            or provenance.get("status") != "ok"
        ):
            continue
        leg = item.get("leg")
        route = item.get("route")
        if isinstance(route, str):
            try:
                route = json.loads(route)
            except (TypeError, ValueError):
                continue
        coordinates = route.get("coordinates") if isinstance(route, dict) else None
        if leg not in {"pickup", "destination"} or not isinstance(coordinates, list) or len(coordinates) < 2:
            continue
        geometry[f"{leg}_route"] = {
            "id": str(item["id"]),
            "provider": item["provider"],
            "route": route,
            "coordinates": coordinates,
            "distance_m": item.get("distance_m"),
            "duration_s": item.get("duration_s"),
            "map_version": item.get("map_version"),
            "provenance": provenance,
            "is_shortest_path": False,
        }
    return geometry or None


def _is_replaceable_route_snapshot(provider: Any, provenance: Any) -> bool:
    """Identify only known synthetic or legacy seed routes for live replacement."""
    if isinstance(provenance, str):
        try:
            provenance = json.loads(provenance)
        except (TypeError, ValueError):
            return False
    if not isinstance(provenance, dict):
        return False
    return provider in {"synthetic-straight-line", "osrm-hanoi"} and (
        provenance.get("origin") == "synthetic"
        or (provider == "osrm-hanoi" and provenance.get("origin") == "osrm" and provenance.get("profile") == "car")
    )


def _valid_coordinate_pair(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        longitude, latitude = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None
    if not all(map(math.isfinite, (longitude, latitude))):
        return None
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        return None
    return [longitude, latitude]


def _normalize_search_text(text: str | None) -> str:
    """Normalize text for accent-insensitive and case-insensitive comparison."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    unaccented = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return unaccented.replace("đ", "d").strip()


def _require_org_scope(organization_id: str | None, *, allow_unscoped: bool = False) -> str:
    """S4-TENANT #294: persisted reads/writes require server-supplied org scope.

    Callers pass Principal.organization_id; client-supplied org params are never
    trusted (routes take no org input). Only the /test/* stack
    (`allow_unscoped`, i.e. APP_ENV=test with test_auth_enabled) may read
    without scope; every other DB access without org is a 403.
    """
    if organization_id:
        return str(organization_id)
    if allow_unscoped:
        return ""
    raise HTTPException(status_code=403, detail="Organization scope required")


def _blocking_guardrail_reasons(
    *,
    incident_type: str | None = None,
    quality_flags: Any = None,
    app_crashed: bool = False,
    telemetry_unavailable: bool = False,
    heavy_congestion: bool = False,
) -> list[str]:
    """Derive decision blocks from evidence; never use simulation ground truth.

    A mock location provider is ERR-05 fraud evidence, not a technical fault, so it
    never blocks a decision.
    """
    reasons: list[str] = []
    if incident_type:
        reasons.append(f"platform_incident:{incident_type}")
    if isinstance(quality_flags, str):
        try:
            quality_flags = json.loads(quality_flags)
        except (TypeError, ValueError):
            quality_flags = [quality_flags]
    if not isinstance(quality_flags, list):
        quality_flags = []
    codes = {str(flag.get("code") if isinstance(flag, dict) else flag).strip().lower() for flag in quality_flags}
    if app_crashed or codes.intersection({"app_crashed", "app_crash_incident"}):
        reasons.append("app_crash_incident")
    if telemetry_unavailable or codes.intersection(
        {"telemetry_unavailable", "gps_unavailable", "network_unavailable", "network_offline"}
    ):
        reasons.append("telemetry_unavailable")
    if "invalid_telemetry" in codes:
        reasons.append("invalid_telemetry")
    if heavy_congestion or "heavy_congestion_detected" in codes:
        reasons.append("heavy_congestion_detected")
    return list(dict.fromkeys(reasons))


class CaseService:
    """Service handling fraud cases, telemetry, simulations, leases, and adjudication.

    Uses PostgreSQL / Supabase data from schema `app`. Seed storage is test-only.
    """

    AUTHORIZED_REVIEW_ROLES: ClassVar[set[str]] = {
        "analyst",
        "fraud_analyst",
        "senior_analyst",
        "admin",
    }

    def __init__(self, settings: Settings | None = None, redis_client: Any = None) -> None:
        self.settings = settings or get_settings()
        self.supabase = SupabaseRestClient(self.settings)
        self._redis_client = redis_client
        self._principal_roles: dict[str, str] = {}
        self._case_aliases: dict[str, str] = {}

        # In-memory storage structures initialized from seed data
        self._raw_seed: dict[str, Any] = {}
        self._cases: dict[str, dict[str, Any]] = {}
        self._trips: dict[str, dict[str, Any]] = {}
        self._assignments: dict[str, dict[str, Any]] = {}
        self._telemetry_points: list[dict[str, Any]] = []
        self._evidence_snapshots: dict[str, dict[str, Any]] = {}
        self._feature_sets: dict[str, dict[str, Any]] = {}
        self._model_assessments: dict[str, dict[str, Any]] = {}
        self._route_snapshots: dict[str, dict[str, Any]] = {}
        self._platform_incidents: dict[str, dict[str, Any]] = {}
        self._simulation_labels: dict[str, dict[str, Any]] = {}
        # Telemetry guardrail results written by the queue worker, keyed by case id.
        self._guardrails: dict[str, dict[str, Any] | None] = {}
        self._policy_chunks: list[dict[str, Any]] = []
        self._drivers: dict[str, dict[str, Any]] = {}
        self._vehicles: dict[str, dict[str, Any]] = {}
        self._driver_statuses: dict[str, str] = {}
        self._analysts: dict[str, dict[str, Any]] = {}

        # Runtime mutation state
        self._ingested_events: dict[str, dict[str, Any]] = {}
        self._active_leases: dict[str, dict[str, Any]] = {}
        self._leases: dict[str, dict[str, Any]] = self._active_leases
        self._principals: dict[str, dict[str, Any]] = {}
        self._recorded_actions: list[dict[str, Any]] = []
        self._adjudications: list[dict[str, Any]] = []
        self._preliminary_judgments: dict[str, PreliminaryJudgment] = {}
        self._candidate_routes: dict[str, list[dict[str, Any]]] = {}
        self._traffic_corroborations: dict[str, dict[str, Any]] = {}
        self._timeline_milestones: dict[str, list[dict[str, Any]]] = {}
        self._missingness_alerts: dict[str, list[dict[str, Any]]] = {}
        self._destinations: dict[str, dict[str, Any]] = {}
        self._has_app_tables: bool | None = None
        self._in_memory_sessions: bool = self.settings.app_env in ("test", "development")
        self._agent_sessions: dict[str, dict[str, Any]] = {}
        self._agent_messages: dict[str, list[dict[str, Any]]] = {}
        self._last_redis_fail_time: float = 0.0

        if self.settings.app_env == "test":
            self._load_seed_data()

    def _test_stack_unscoped(self) -> bool:
        """True only for the /test/* stack: APP_ENV=test with test_auth_enabled."""
        return self.settings.app_env == "test" and self.settings.test_auth_enabled

    def _get_db_connection(self):
        """Try connecting to database_url if configured and verified to have schema 'app'."""
        db_url = self.settings.database_url
        if not db_url or psycopg is None:
            self._require_test_fallback()
            return None

        if self._has_app_tables is False:
            self._require_test_fallback()
            return None
        try:
            conn = psycopg.connect(db_url, row_factory=dict_row, autocommit=False, connect_timeout=5)
            if self._has_app_tables is None:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM information_schema.tables WHERE table_schema = 'app' AND table_name = 'trips';"
                    )
                    if not cur.fetchone():
                        self._has_app_tables = False
                        conn.close()
                        self._require_test_fallback()
                        return None
                    self._has_app_tables = True
            return conn
        except Exception:
            # A test process must not pay the connection timeout on every
            # repository lookup when its isolated database is intentionally
            # unavailable. Development keeps retrying so a database started
            # after the API can still be discovered.
            if self.settings.app_env == "test":
                self._has_app_tables = False
            self._require_test_fallback()
            return None

    def list_simulation_actors(self, organization_id: str) -> dict[str, list[dict[str, str]]]:
        """Return tenant-owned actors and globally published policies."""
        conn = self._get_db_connection()
        if conn is None:
            return {"drivers": [], "passengers": [], "vehicles": [], "policies": []}
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, COALESCE(external_ref, id::text) AS display_name FROM app.drivers WHERE organization_id = %s AND account_status = 'active' ORDER BY display_name",
                    (organization_id,),
                )
                drivers = [dict(r) for r in cur.fetchall()]
                cur.execute(
                    "SELECT id, COALESCE(external_ref, id::text) AS display_name FROM app.passengers WHERE organization_id = %s ORDER BY display_name",
                    (organization_id,),
                )
                passengers = [dict(r) for r in cur.fetchall()]
                cur.execute(
                    "SELECT id, registration_ref AS display_name FROM app.vehicles WHERE organization_id = %s ORDER BY display_name",
                    (organization_id,),
                )
                vehicles = [dict(r) for r in cur.fetchall()]
                cur.execute(
                    "SELECT id, version AS display_name FROM app.policy_versions WHERE status = 'published' ORDER BY version"
                )
                policies = [dict(r) for r in cur.fetchall()]
            return {
                kind: [{"id": str(row["id"]), "display_name": str(row["display_name"])} for row in rows]
                for kind, rows in {
                    "drivers": drivers,
                    "passengers": passengers,
                    "vehicles": vehicles,
                    "policies": policies,
                }.items()
            }
        finally:
            conn.close()

    def _recorded_guardrail_reasons(self, *case_ids: Any) -> list[str]:
        """Blocking reasons from the telemetry guardrail the queue worker recorded for a case."""
        for case_id in case_ids:
            recorded = self._guardrails.get(str(case_id))
            if recorded:
                return _blocking_guardrail_reasons(quality_flags=recorded.get("quality_flags"))
        return []

    def _require_test_fallback(self) -> None:
        if self.settings.app_env != "test":
            raise HTTPException(status_code=503, detail="Case database unavailable")

    @staticmethod
    def _build_conversation(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        messages = [entry for entry in entries if str(entry.get("text") or "").strip()]
        return sorted(messages, key=lambda entry: str(entry.get("occurred_at") or ""))

    @staticmethod
    def _is_valid_uuid(val: Any) -> bool:
        if not val:
            return False
        try:
            UUID(str(val))
            return True
        except (ValueError, TypeError, AttributeError):
            return False

    def _resolve_case_id(self, case_id: str) -> str:
        """Resolve explicit scenario-seeder aliases to canonical UUIDs; unknown ids pass through for 404."""
        if not case_id:
            return case_id
        cid = str(case_id).strip()
        if cid in self._cases:
            if cid in self._case_aliases and self._is_valid_uuid(self._case_aliases[cid]):
                return self._case_aliases[cid]
            return cid

        cid_lower = cid.lower()
        if cid_lower in self._case_aliases:
            return self._case_aliases[cid_lower]

        for real_id, c in self._cases.items():
            token = str(c.get("case_token", "")).lower()
            if token and (token == cid_lower or token.replace("#", "") == cid_lower):
                return real_id

        return cid

    def get_principal_display_name(self, principal_id: str) -> str | None:
        conn = self._get_db_connection()
        if conn is None:
            return self._analysts.get(principal_id, {}).get("display_name")
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT display_name FROM app.principals WHERE id = %s;", (principal_id,))
                row = cur.fetchone()
                return row["display_name"] if row else None
        except Exception:
            raise HTTPException(status_code=503, detail="Principal database unavailable") from None
        finally:
            conn.close()

    def set_principal_display_name(self, principal_id: str, display_name: str) -> None:
        if principal_id not in self._analysts:
            self._analysts[principal_id] = {}
        self._analysts[principal_id]["display_name"] = display_name
        conn = self._get_db_connection()
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    cur.execute(
                        "UPDATE app.principals SET display_name = %s WHERE id = %s;",
                        (display_name, principal_id),
                    )
                    conn.commit()
            except Exception:
                pass
            finally:
                conn.close()

    def get_principal_role(self, principal_id: str, explicit_role: str | None = None) -> str:
        """Determine principal role: 'analyst', 'senior_analyst', 'admin', or 'unauthorized'."""
        if explicit_role:
            norm = explicit_role.strip().lower()
            if norm in self.AUTHORIZED_REVIEW_ROLES:
                return norm
            return norm

        pid = str(principal_id).strip()
        fixture_auth = self.settings.app_env == "test" and self.settings.test_auth_enabled
        if fixture_auth and pid in self._principal_roles:
            return self._principal_roles[pid]

        if self._is_valid_uuid(pid):
            conn = self._get_db_connection()
            if conn is not None:
                try:
                    with conn.cursor() as cur:
                        cur.execute("SET search_path = app, extensions, public;")
                        cur.execute(
                            "SELECT r.role FROM app.principal_roles r JOIN app.principals p ON p.id=r.principal_id WHERE p.id = %s AND p.status='active' ORDER BY CASE r.role WHEN 'senior_analyst' THEN 0 WHEN 'analyst' THEN 1 WHEN 'fraud_analyst' THEN 1 ELSE 2 END LIMIT 1;",
                            (pid,),
                        )
                        row = cur.fetchone()
                        if row and row.get("role"):
                            return row["role"]
                except Exception:
                    pass
                finally:
                    conn.close()

        # S4-RETIRE #303: no name-based fallback actors. Unknown principals are
        # unauthorized; explicit test principals come only from _principal_roles.
        return "unauthorized"

    def update_principal_role(self, principal_id: str, role: str, organization_id: str | None = None) -> None:
        """Update or assign principal role in memory and in app.principal_roles if DB is available."""
        conn = self._get_db_connection()
        if (
            conn is None
            and organization_id
            and not (self.settings.app_env == "test" and self.settings.test_auth_enabled)
        ):
            raise HTTPException(503, "Principal database unavailable")
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    if organization_id:
                        cur.execute(
                            "SELECT id FROM app.principals WHERE id = %s AND organization_id = %s FOR UPDATE",
                            (principal_id, organization_id),
                        )
                        if not cur.fetchone():
                            raise HTTPException(403, "Principal access denied")
                    cur.execute(
                        "DELETE FROM app.principal_roles WHERE principal_id = %s;",
                        (principal_id,),
                    )
                    cur.execute(
                        """
                        INSERT INTO app.principal_roles (principal_id, role)
                        VALUES (%s, %s)
                        ON CONFLICT (principal_id, role) DO NOTHING;
                        """,
                        (principal_id, role),
                    )
                    conn.commit()
            except HTTPException:
                conn.rollback()
                raise
            except Exception as e:
                conn.rollback()
                raise HTTPException(503, "Principal role update unavailable") from e
            finally:
                conn.close()

        self._principal_roles[str(principal_id)] = role

    def list_principals(self, organization_id: str | None = None) -> list[dict[str, Any]]:
        """List principals with active roles for account settings and role management."""
        conn = self._get_db_connection()
        if (
            conn is None
            and organization_id
            and not (self.settings.app_env == "test" and self.settings.test_auth_enabled)
        ):
            raise HTTPException(503, "Principal database unavailable")
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    cur.execute(
                        """
                        SELECT p.id, p.display_name, p.external_subject, p.status,
                               array_remove(array_agg(r.role), null) AS roles
                        FROM app.principals p
                        LEFT JOIN app.principal_roles r ON r.principal_id = p.id
                        WHERE (%s::uuid IS NULL OR p.organization_id = %s::uuid)
                        GROUP BY p.id, p.display_name, p.external_subject, p.status
                        ORDER BY p.created_at ASC
                        LIMIT 100;
                        """,
                        (organization_id, organization_id),
                    )
                    rows = cur.fetchall()
                    if rows:
                        return [
                            {
                                "id": str(r["id"]),
                                "display_name": r["display_name"],
                                "external_subject": r.get("external_subject"),
                                "roles": r.get("roles") or [],
                                "status": r.get("status", "active"),
                            }
                            for r in rows
                        ]
                    if organization_id:
                        return []
            except Exception as exc:
                if organization_id:
                    raise HTTPException(503, "Principal database unavailable") from exc
            finally:
                conn.close()

        res = []
        for pid, role in self._principal_roles.items():
            res.append(
                {
                    "id": pid,
                    "display_name": self.get_principal_display_name(pid) or f"User {pid[:8]}",
                    "external_subject": pid,
                    "roles": [role],
                    "status": "active",
                }
            )
        # S4-RETIRE #303: accurate empty state. No hardcoded fallback actors.
        return res

    def get_redis_client(self) -> Any:
        """Get or lazily connect to Redis client for review lock mutual exclusion."""
        if self._redis_client is not None:
            return self._redis_client
        if redis is None:
            return None
        now = time.time()
        if self._last_redis_fail_time and (now - self._last_redis_fail_time < 10.0):
            return None
        try:
            redis_url = os.getenv("REDIS_URL")
            if redis_url:
                client = redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=0.2,
                    socket_timeout=0.2,
                    retry_on_timeout=False,
                )
            else:
                host = os.getenv("REDIS_HOST", "localhost")
                port = int(os.getenv("REDIS_PORT", "6379"))
                client = redis.Redis(
                    host=host,
                    port=port,
                    decode_responses=True,
                    socket_connect_timeout=0.2,
                    socket_timeout=0.2,
                    retry_on_timeout=False,
                )
            client.ping()
            self._redis_client = client
            return self._redis_client
        except Exception:
            self._last_redis_fail_time = now
            return None

    def is_driver_suspended(self, driver_id: str) -> bool:
        """Check if driver account_status is 'suspended' in database or in-memory state."""
        if not driver_id:
            return False
        str_id = str(driver_id).strip()

        # Try database check first
        conn = self._get_db_connection()
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    cur.execute(
                        "SELECT account_status FROM app.drivers WHERE id::text = %s OR external_ref = %s LIMIT 1;",
                        (str_id, str_id),
                    )
                    row = cur.fetchone()
                    if row:
                        return row.get("account_status") == "suspended"
            except Exception:
                pass
            finally:
                conn.close()

        # Fallback to in-memory state
        if str_id in self._driver_statuses:
            return self._driver_statuses[str_id] == "suspended"
        for d_id, driver in self._drivers.items():
            if str(d_id) == str_id or driver.get("external_ref") == str_id:
                return driver.get("account_status") == "suspended"
        return False

    def set_driver_status(self, driver_id: str, status: str = "suspended") -> None:
        """Update driver account_status both in-memory and in database."""
        str_id = str(driver_id).strip()
        self._driver_statuses[str_id] = status
        if str_id in self._drivers:
            self._drivers[str_id]["account_status"] = status
        for d_id, driver in self._drivers.items():
            if str(d_id) == str_id or driver.get("external_ref") == str_id:
                driver["account_status"] = status

        conn = self._get_db_connection()
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    cur.execute(
                        "UPDATE app.drivers SET account_status = %s WHERE id::text = %s OR external_ref = %s;",
                        (status, str_id, str_id),
                    )
                conn.commit()
            except Exception:
                if conn:
                    conn.rollback()
            finally:
                conn.close()

    ACCEPTED_DATASET_VERSION = "road-v1"

    def _find_seed_file(self) -> Path | None:
        # S4-RETIRE #303: accepted dataset/import path first (GREENSENTINEL_SEED_PATH);
        # legacy data/synthetic/seed_data.json is last and still requires a
        # road-v1 manifest to load (see _load_seed_data).
        candidates = [
            os.getenv("GREENSENTINEL_SEED_PATH"),
            os.getenv("SEED_DATA_PATH"),
            "data/road-v1/seed_data.json",
            "data/synthetic/seed_data.json",
        ]
        for c in candidates:
            if c:
                p = Path(c).resolve()
                if p.is_file():
                    return p
        return None

    def _load_seed_data(self) -> None:
        seed_file = self._find_seed_file()
        if seed_file and seed_file.is_file():
            try:
                with open(seed_file, encoding="utf-8") as f:
                    loaded = json.load(f)
                manifest = loaded.get("manifest", {}) if isinstance(loaded, dict) else {}
                if manifest.get("dataset_version") != self.ACCEPTED_DATASET_VERSION:
                    if os.getenv("GREENSENTINEL_ALLOW_LEGACY_SEED") != "1":
                        print(
                            f"Warning: Refusing legacy seed without manifest.dataset_version="
                            f"{self.ACCEPTED_DATASET_VERSION}: {seed_file}. "
                            "Set GREENSENTINEL_SEED_PATH to a road-v1 dataset or "
                            "GREENSENTINEL_ALLOW_LEGACY_SEED=1 for explicit legacy import. "
                            "Starting from accurate empty state."
                        )
                        self._raw_seed = {}
                    else:
                        self._raw_seed = loaded
                else:
                    self._raw_seed = loaded
            except Exception as e:
                print(f"Warning: Failed to load seed file {seed_file}: {e}")
                self._raw_seed = {}

        for c in self._raw_seed.get("fraud_cases", []):
            self._cases[str(c["id"])] = dict(c)
        for t in self._raw_seed.get("trips", []):
            self._trips[str(t["id"])] = dict(t)
        for a in self._raw_seed.get("trip_assignments", []):
            self._assignments[str(a["id"])] = dict(a)
        self._telemetry_points = [dict(tp) for tp in self._raw_seed.get("telemetry_points", [])]
        for s in self._raw_seed.get("evidence_snapshots", []):
            self._evidence_snapshots[str(s["id"])] = dict(s)
        for fs in self._raw_seed.get("feature_sets", []):
            self._feature_sets[str(fs["id"])] = dict(fs)
        for ma in self._raw_seed.get("model_assessments", []):
            self._model_assessments[str(ma["id"])] = dict(ma)
        for rs in self._raw_seed.get("route_snapshots", []):
            self._route_snapshots[str(rs["assignment_id"])] = dict(rs)
        for pi in self._raw_seed.get("platform_incidents", []):
            self._platform_incidents[str(pi["assignment_id"])] = dict(pi)
        for sl in self._raw_seed.get("simulation_labels", []):
            self._simulation_labels[str(sl["assignment_id"])] = dict(sl)
        self._policy_chunks = [dict(pc) for pc in self._raw_seed.get("policy_chunks", [])]
        for d in self._raw_seed.get("drivers", []):
            self._drivers[str(d["id"])] = dict(d)
            self._driver_statuses[str(d["id"])] = d.get("account_status", "active")
        for pr in self._raw_seed.get("principal_roles", []):
            self._principal_roles[str(pr.get("principal_id"))] = str(pr.get("role", "analyst"))
        for a in self._raw_seed.get("analysts", []):
            self._analysts[str(a["id"])] = dict(a)

        # S4-RETIRE #303: no hardcoded legacy case aliases. Explicit
        # scenario-seeder aliases are registered by ScenarioSeeder only.
        self._case_aliases = {}

    def _analyst_matches(self, analyst_a: Any, analyst_b: Any) -> bool:
        """Check if two analyst identifiers match by ID or display name."""
        if not analyst_a or not analyst_b:
            return False
        sa = str(analyst_a).strip().lower()
        sb = str(analyst_b).strip().lower()
        if sa == sb:
            return True
        for a_id, a_data in self._analysts.items():
            name = str(a_data.get("display_name", "")).strip().lower()
            if (sa == a_id.lower() or sa == name) and (sb == a_id.lower() or sb == name):
                return True
        return False

    def _sync_case_dict(self, canonical_id: str) -> None:
        """Keep canonical and alias case dictionary objects synchronized."""
        canonical = self._cases.get(canonical_id)
        if not canonical:
            return
        for alias, target in self._case_aliases.items():
            if target == canonical_id:
                alias_copy = dict(canonical)
                alias_copy["id"] = alias
                alias_copy["case_token"] = f"#{alias.upper()}" if not alias.startswith("#") else alias
                self._cases[alias] = alias_copy

    async def check_database_health(self) -> str:
        """Check Supabase or local postgres connectivity."""
        conn = self._get_db_connection()
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
                conn.close()
                return "connected"
            except Exception:
                pass

        if await self.supabase.is_connected():
            return "connected"
        return "disconnected"

    # 1. Telemetry Ingest
    async def ingest_telemetry(self, envelope: TelemetryEventEnvelope) -> IngestResult:
        if envelope.driver_id and self.is_driver_suspended(str(envelope.driver_id)):
            raise HTTPException(
                status_code=403,
                detail=f"Driver {envelope.driver_id} is currently suspended and cannot accept or make trips",
            )

        dedup_key = f"{envelope.source}:{envelope.assignment_id}:{envelope.sequence}"
        event_id_str = str(envelope.event_id)
        raw_payload_bytes = json.dumps(envelope.payload.model_dump(mode="json"), sort_keys=True).encode("utf-8")
        payload_hash = hashlib.sha256(raw_payload_bytes).digest()

        # Check in-memory duplicates
        if dedup_key in self._ingested_events or event_id_str in self._ingested_events:
            prior = self._ingested_events.get(event_id_str) or self._ingested_events[dedup_key]
            if prior.get("payload") != envelope.payload.model_dump(mode="json"):
                raise HTTPException(status_code=409, detail="Telemetry event has a different payload")
            return IngestResult(
                status="duplicate",
                event_id=envelope.event_id,
                duplicate=True,
                detail=f"Telemetry sequence {envelope.sequence} already ingested for trip {envelope.trip_id}",
            )

        # Try inserting into real database if available
        conn = self._get_db_connection()
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    # Check duplicate in app.ingest_events
                    cur.execute(
                        "SELECT event_id, payload FROM app.ingest_events WHERE event_id = %s OR (source = %s AND assignment_id = %s AND producer_sequence = %s);",
                        (envelope.event_id, envelope.source, envelope.assignment_id, envelope.sequence),
                    )
                    existing = cur.fetchone()
                    if existing:
                        stored_payload = existing["payload"] if isinstance(existing, dict) else existing[1]
                        if stored_payload != envelope.payload.model_dump(mode="json"):
                            raise HTTPException(status_code=409, detail="Telemetry event has a different payload")
                        conn.rollback()
                        # Do NOT close conn here — the finally block below handles cleanup
                        # consistently for all exit paths (return, raise, normal exit).
                        return IngestResult(
                            status="duplicate",
                            event_id=envelope.event_id,
                            duplicate=True,
                            detail=f"Telemetry sequence {envelope.sequence} already ingested",
                        )

                    # S4-TENANT #294: org binds from the parent trip row. Unknown
                    # trips are a 404, never silently assigned to a default org.
                    cur.execute("SELECT organization_id FROM app.trips WHERE id = %s;", (envelope.trip_id,))
                    org_row = cur.fetchone()
                    if not org_row or not org_row.get("organization_id"):
                        raise HTTPException(status_code=404, detail=f"Trip {envelope.trip_id} not found")
                    org_id = org_row["organization_id"]

                    cur.execute(
                        """
                        INSERT INTO app.ingest_events (
                            event_id, organization_id, schema_version, event_type, source,
                            occurred_at, correlation_id, causation_id, simulation_run_id,
                            trip_id, assignment_id, driver_id, producer_sequence, payload, payload_hash
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING RETURNING event_id;
                        """,
                        (
                            envelope.event_id,
                            org_id,
                            envelope.schema_version,
                            envelope.event_type,
                            envelope.source,
                            envelope.occurred_at,
                            envelope.correlation_id,
                            envelope.causation_id,
                            envelope.simulation_run_id,
                            envelope.trip_id,
                            envelope.assignment_id,
                            envelope.driver_id,
                            envelope.sequence,
                            json.dumps(envelope.payload.model_dump(mode="json")),
                            payload_hash,
                        ),
                    )

                    if not cur.fetchone():
                        cur.execute(
                            "SELECT payload FROM app.ingest_events WHERE event_id = %s OR (source = %s AND assignment_id = %s AND producer_sequence = %s)",
                            (envelope.event_id, envelope.source, envelope.assignment_id, envelope.sequence),
                        )
                        raced = cur.fetchone()
                        raced_payload = raced["payload"] if isinstance(raced, dict) else raced[0]
                        if raced_payload != envelope.payload.model_dump(mode="json"):
                            raise HTTPException(status_code=409, detail="Telemetry event has a different payload")
                        conn.rollback()
                        return IngestResult(status="duplicate", event_id=envelope.event_id, duplicate=True)

                    pos = envelope.payload.position
                    pos_geom = f"POINT({pos.longitude} {pos.latitude})" if pos else None

                    cur.execute(
                        """
                        INSERT INTO app.telemetry_points (
                            event_id, assignment_id, occurred_at, position, speed_mps, bearing_deg,
                            accuracy_m, app_state, network_state, gps_state, mock_location_reported
                        ) VALUES (
                            %s, %s, %s,
                            CASE WHEN %s::text IS NOT NULL THEN ST_SetSRID(ST_GeomFromText(%s), 4326)::geography ELSE NULL END,
                            %s, %s, %s, %s, %s, %s, %s
                        )
                        ON CONFLICT DO NOTHING;
                        """,
                        (
                            envelope.event_id,
                            envelope.assignment_id,
                            envelope.occurred_at,
                            pos_geom,
                            pos_geom,
                            envelope.payload.speed_mps,
                            envelope.payload.bearing_deg,
                            pos.accuracy_m if pos else None,
                            envelope.payload.app_state,
                            envelope.payload.network_state,
                            envelope.payload.gps_state,
                            envelope.payload.mock_location_reported,
                        ),
                    )
                    conn.commit()
            except Exception:
                if conn:
                    conn.rollback()
                raise
            finally:
                if conn:
                    conn.close()

        record = envelope.model_dump(mode="json")
        self._ingested_events[dedup_key] = record
        self._ingested_events[event_id_str] = record

        return IngestResult(
            status="ingested",
            event_id=envelope.event_id,
            duplicate=False,
        )

    @staticmethod
    def select_least_loaded_analyst(cur: Any, organization_id: str) -> str | None:
        """Select an active analyst while holding a row lock for this transaction.

        The lock prevents two workers assigning the same least-loaded analyst based
        on the same stale workload snapshot.  Caller must commit or roll back.
        """
        cur.execute(
            """
            SELECT p.id
            FROM app.principals p
            WHERE p.id = (
                SELECT candidate.id
                FROM app.principals candidate
                JOIN app.principal_roles candidate_role ON candidate_role.principal_id = candidate.id
                LEFT JOIN app.fraud_cases open_case
                  ON open_case.assigned_analyst_id = candidate.id
                 AND open_case.status IN ('ready', 'in_review')
                WHERE candidate.organization_id = %s
                  AND candidate.status = 'active'
                  AND candidate_role.role IN ('analyst', 'senior_analyst', 'fraud_analyst')
                GROUP BY candidate.id
                ORDER BY count(open_case.id), candidate.id
                LIMIT 1
            )
            FOR UPDATE SKIP LOCKED;
            """,
            (organization_id,),
        )
        row = cur.fetchone()
        return str(row["id"] if isinstance(row, dict) else row[0]) if row else None

    # 2. Simulations
    async def trigger_simulation(
        self,
        scenario: str,
        analyst_id: str | None = None,
        seed: int | None = None,
        driver_id: str | None = None,
    ) -> SimulationTriggerResponse:
        scenario_map = {
            "driver_stall_cancel": "intentional_dic",
            "gps_spoofing": "fake_gps",
            "normal_trip": "traffic_gridlock",
        }
        normalized_scenario = scenario_map.get(scenario, scenario)

        valid_scenarios = (
            "intentional_dic",
            "traffic_gridlock",
            "technical_dropout",
            "fake_gps",
            "gps_jitter",
            "driver_stall_cancel",
            "gps_spoofing",
            "normal_trip",
        )
        if scenario not in valid_scenarios and normalized_scenario not in valid_scenarios:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid simulation scenario '{scenario}'. Allowed: {', '.join(valid_scenarios)}",
            )

        if driver_id and self.is_driver_suspended(str(driver_id)):
            raise HTTPException(
                status_code=403,
                detail=f"Driver {driver_id} is currently suspended and cannot accept or make trips",
            )

        scenario_to_case_id = {
            "intentional_dic": "018f2f4e-a000-7000-8000-000000000001",
            "traffic_gridlock": "018f2f4e-a000-7000-8000-000000000026",
            "technical_dropout": "018f2f4e-a000-7000-8000-000000000041",
            "fake_gps": "018f2f4e-a000-7000-8000-000000000061",
            "gps_jitter": "018f2f4e-a000-7000-8000-000000000081",
        }
        case_id = scenario_to_case_id.get(normalized_scenario)

        # Check in real database if possible
        conn = self._get_db_connection()
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    cur.execute(
                        """
                        SELECT c.id, a.driver_id FROM app.fraud_cases c
                        JOIN app.trip_assignments a ON c.assignment_id = a.id
                        JOIN app.simulation_labels l ON l.assignment_id = a.id
                        JOIN app.simulation_runs r ON l.simulation_run_id = r.id
                        WHERE r.scenario = %s
                        LIMIT 1;
                        """,
                        (normalized_scenario,),
                    )
                    row = cur.fetchone()
                    if row:
                        case_id = str(row["id"])
                        if not driver_id and row.get("driver_id") and self.is_driver_suspended(str(row["driver_id"])):
                            raise HTTPException(
                                status_code=403,
                                detail=f"Driver {row['driver_id']} is currently suspended and cannot accept or make trips",
                            )
            except HTTPException:
                raise
            except Exception:
                pass
            finally:
                conn.close()

        if not case_id or case_id not in self._cases:
            case_id = next(iter(self._cases.keys())) if self._cases else "018f2f4e-a000-7000-8000-000000000001"

        if not driver_id and case_id in self._cases:
            asgn_id = self._cases[case_id].get("assignment_id")
            if asgn_id in self._assignments:
                case_driver = self._assignments[asgn_id].get("driver_id")
                if case_driver and self.is_driver_suspended(str(case_driver)):
                    raise HTTPException(
                        status_code=403,
                        detail=f"Driver {case_driver} is currently suspended and cannot accept or make trips",
                    )

        return SimulationTriggerResponse(
            scenario=scenario,
            case_id=case_id,
            status="triggered",
        )

    # 3. Case Queue Listing
    async def list_cases(
        self,
        status: str | None = None,
        priority: str | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
        organization_id: str | None = None,
        analyst_id: str | None = None,
        availability: str = "available",
    ) -> CaseListResponse:
        if availability not in {"available", "mine", "all"}:
            raise HTTPException(status_code=400, detail="Invalid availability filter")
        allowed_statuses = {
            "ready",
            "in_review",
            "escalated",
            "resolved",
            "dismissed",
            "evidence_requested",
            "suspended",
            "auto_dismissed",
            "driver_disputed",
            "pending_analyst_review",
        }
        if status is not None and status.strip().lower() not in allowed_statuses:
            raise HTTPException(status_code=400, detail="Invalid status filter")
        active_only = status is None and availability in {"available", "mine"}
        terminal_statuses = ("resolved", "dismissed", "suspended", "auto_dismissed")
        target_tier: int | None = None
        if priority is not None:
            p_upper = priority.strip().upper()
            if p_upper.startswith("P") and p_upper[1:].isdigit():
                target_tier = int(p_upper[1:])
            elif p_upper.isdigit():
                target_tier = int(p_upper)

        conn = self._get_db_connection()
        if conn is not None:
            _require_org_scope(organization_id, allow_unscoped=self._test_stack_unscoped())
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    where_clauses = []
                    params: list[Any] = []
                    if organization_id:
                        where_clauses.append("c.organization_id = %s")
                        params.append(organization_id)

                    # SQL-INJECTION SAFETY NOTE:
                    # `where_sql` is assembled from hard-coded string literals
                    # ("LOWER(c.status) = LOWER(%s)", "c.priority_tier = %s").
                    # No user-supplied text is ever interpolated into the SQL
                    # structure — only into the parameterized %s placeholders.
                    # Explicit allowlist validation below is an extra defence-in-depth.
                    if status is not None:
                        where_clauses.append("LOWER(c.status) = LOWER(%s)")
                        params.append(status.strip())
                    elif active_only:
                        where_clauses.append("LOWER(COALESCE(c.status, 'ready')) <> ALL(%s)")
                        params.append(list(terminal_statuses))

                    if target_tier is not None:
                        where_clauses.append("c.priority_tier = %s")
                        params.append(target_tier)

                    if search and search.strip():
                        s_term = f"%{search.strip()}%"
                        where_clauses.append(
                            """EXISTS (
                                SELECT 1 FROM app.trip_assignments a
                                LEFT JOIN app.drivers d ON a.driver_id = d.id
                                LEFT JOIN app.principals p_dr ON d.principal_id = p_dr.id
                                LEFT JOIN app.vehicles v ON a.vehicle_id = v.id
                                WHERE a.id = c.assignment_id AND (
                                    COALESCE(to_jsonb(d)->>'display_name', p_dr.display_name, '') ILIKE %s
                                    OR a.driver_id::text ILIKE %s
                                    OR COALESCE(d.external_ref, '') ILIKE %s
                                    OR COALESCE(v.registration_ref, '') ILIKE %s
                                )
                            )"""
                        )
                        params.extend([s_term, s_term, s_term, s_term])

                    if availability == "available":
                        if analyst_id is not None:
                            where_clauses.append(
                                """NOT EXISTS (
                                    SELECT 1 FROM app.review_leases lease
                                    LEFT JOIN app.principals p ON lease.analyst_id = p.id
                                    WHERE lease.case_id = c.id
                                      AND lease.expires_at > now()
                                      AND lease.analyst_id::text != %s
                                      AND COALESCE(p.external_subject, '') != %s
                                )"""
                            )
                            params.extend([str(analyst_id), str(analyst_id)])
                        else:
                            where_clauses.append(
                                "NOT EXISTS (SELECT 1 FROM app.review_leases lease WHERE lease.case_id = c.id AND lease.expires_at > now())"
                            )
                    elif availability == "mine":
                        where_clauses.append(
                            """EXISTS (
                                SELECT 1 FROM app.review_leases lease
                                LEFT JOIN app.principals p ON lease.analyst_id = p.id
                                WHERE lease.case_id = c.id
                                  AND lease.expires_at > now()
                                  AND (lease.analyst_id::text = %s OR COALESCE(p.external_subject, '') = %s)
                            )"""
                        )
                        params.extend([str(analyst_id), str(analyst_id)])
                    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

                    count_query = f"SELECT count(*) FROM app.fraud_cases c {where_sql};"
                    cur.execute(count_query, params)
                    total = cur.fetchone()["count"]

                    query = f"""
                        SELECT c.id, c.status, c.dispute_status, c.dispute_deadline, c.priority_tier, c.priority_score, c.suspected_category,
                               c.assigned_analyst_id, c.version, c.created_at, c.updated_at, c.sla_due_at,
                               a.trip_id, a.driver_id, a.id as assignment_id,
                               d.external_ref as driver_ref,
                               COALESCE(to_jsonb(d)->>'display_name', p_dr.display_name) as driver_name,
                               v.registration_ref as vehicle_plate,
                               fs.stationary_duration_s as stationary_duration_s,
                               p_an.display_name as analyst_name,
                               t.district as trip_district, ma.confidence,
                               lease.analyst_id as active_lease_analyst_id,
                               lease.expires_at as active_lease_expires_at
                        FROM app.fraud_cases c
                        LEFT JOIN app.trip_assignments a ON c.assignment_id = a.id
                        LEFT JOIN app.trips t ON a.trip_id = t.id
                        LEFT JOIN app.drivers d ON a.driver_id = d.id
                        LEFT JOIN app.principals p_dr ON d.principal_id = p_dr.id
                        LEFT JOIN app.principals p_an ON c.assigned_analyst_id = p_an.id
                        LEFT JOIN app.vehicles v ON a.vehicle_id = v.id
                        LEFT JOIN LATERAL (SELECT id FROM app.evidence_snapshots WHERE case_id = c.id ORDER BY version DESC LIMIT 1) es ON true
                        LEFT JOIN LATERAL (SELECT stationary_duration_s FROM app.feature_sets WHERE evidence_snapshot_id = es.id ORDER BY created_at DESC LIMIT 1) fs ON true
                        LEFT JOIN LATERAL (SELECT confidence FROM app.model_assessments WHERE evidence_snapshot_id = es.id ORDER BY created_at DESC LIMIT 1) ma ON true
                        LEFT JOIN LATERAL (SELECT analyst_id, expires_at FROM app.review_leases WHERE case_id = c.id AND expires_at > now() ORDER BY expires_at DESC LIMIT 1) lease ON true
                        {where_sql}
                        ORDER BY c.priority_tier ASC, c.priority_score DESC, c.created_at DESC
                        LIMIT %s OFFSET %s;
                    """
                    cur.execute(query, [*params, limit, offset])
                    rows = cur.fetchall()

                    now_utc = datetime.now(UTC)
                    items: list[FraudCaseSummary] = []
                    for r in rows:
                        tier = r["priority_tier"]
                        sla_due = r.get("sla_due_at")
                        sla_sec = None
                        if sla_due:
                            diff = int((sla_due - now_utc).total_seconds())
                            sla_sec = max(0, diff)

                        district = r.get("trip_district")

                        items.append(
                            FraudCaseSummary(
                                id=str(r["id"]),
                                trip_id=str(r["trip_id"]) if r["trip_id"] else None,
                                assignment_id=str(r["assignment_id"]) if r["assignment_id"] else None,
                                driver_id=str(r["driver_id"]) if r["driver_id"] else None,
                                status=r["status"] or "ready",
                                priority=f"P{tier}",
                                priority_score=r["priority_score"] or 0,
                                category=r["suspected_category"] or "none",
                                confidence=r.get("confidence"),
                                opened_at=r["created_at"],
                                updated_at=r["updated_at"],
                                assigned_analyst_id=str(r["assigned_analyst_id"]) if r["assigned_analyst_id"] else None,
                                active_lease_analyst_id=str(r["active_lease_analyst_id"])
                                if r.get("active_lease_analyst_id")
                                else None,
                                active_lease_expires_at=r.get("active_lease_expires_at"),
                                version=r["version"] or 1,
                                driver_name=r.get("driver_name"),
                                vehicle_plate=r.get("vehicle_plate"),
                                district=district,
                                stall_duration_s=r.get("stationary_duration_s"),
                                sla_countdown_s=sla_sec,
                                assigned_analyst_name=r.get("analyst_name"),
                                dispute_status=r.get("dispute_status") or "not_disputed",
                                dispute_deadline=r.get("dispute_deadline"),
                            )
                        )

                    return CaseListResponse(
                        items=items,
                        total=total,
                        limit=limit,
                        offset=offset,
                    )
            except HTTPException:
                raise
            except Exception:
                self._require_test_fallback()
            finally:
                conn.close()

        self._require_test_fallback()
        # In-memory fallback
        now = datetime.now(UTC)
        norm_search = _normalize_search_text(search) if search and search.strip() else None
        filtered = []
        for case_id, c in self._cases.items():
            if case_id in self._case_aliases:
                continue
            if organization_id and str(c.get("organization_id")) != organization_id:
                continue
            cid = str(c["id"])
            asgn = self._assignments.get(str(c.get("assignment_id", "")))

            if norm_search:
                driver_id_str = (
                    str(asgn.get("driver_id")) if asgn and asgn.get("driver_id") else str(c.get("driver_id", ""))
                )
                driver_rec = self._drivers.get(driver_id_str, {}) if driver_id_str else {}
                driver_name = driver_rec.get("display_name") or c.get("driver_name") or ""
                driver_ref = driver_rec.get("external_ref") or c.get("driver_ref") or ""

                vehicle_id_str = str(asgn.get("vehicle_id")) if asgn and asgn.get("vehicle_id") else ""
                vehicle_rec = self._vehicles.get(vehicle_id_str, {}) if vehicle_id_str else {}
                vehicle_plate = vehicle_rec.get("registration_ref") or c.get("vehicle_plate") or ""

                targets = [
                    _normalize_search_text(driver_name),
                    _normalize_search_text(driver_id_str),
                    _normalize_search_text(driver_ref),
                    _normalize_search_text(vehicle_plate),
                ]
                plate_clean = re.sub(r"[^a-z0-9]", "", _normalize_search_text(vehicle_plate))
                search_clean = re.sub(r"[^a-z0-9]", "", norm_search)
                plate_match = bool(search_clean and search_clean in plate_clean)

                if not (any(norm_search in t for t in targets if t) or plate_match):
                    continue

            active_lease = self._active_leases.get(cid) or self._active_leases.get(self._resolve_case_id(cid))
            if not active_lease:
                r = self.get_redis_client()
                if r is not None:
                    try:
                        raw_lock = r.get(f"review_lock:{cid}") or r.get(f"review_lock:{self._resolve_case_id(cid)}")
                        if raw_lock:
                            lock_data = json.loads(raw_lock)
                            exp_val = lock_data.get("expires_at")
                            exp = datetime.fromisoformat(exp_val) if isinstance(exp_val, str) else exp_val
                            if exp and exp > now:
                                active_lease = {
                                    "analyst_id": lock_data.get("analyst_id"),
                                    "expires_at": exp,
                                }
                    except Exception:
                        pass
            is_locked = bool(active_lease and active_lease.get("expires_at") and active_lease["expires_at"] > now)
            if availability == "available":
                if (
                    is_locked
                    and active_lease is not None
                    and not self._analyst_matches(active_lease.get("analyst_id"), analyst_id)
                ):
                    continue
            elif availability == "mine":
                if (
                    not is_locked
                    or active_lease is None
                    or not self._analyst_matches(active_lease.get("analyst_id"), analyst_id)
                ):
                    continue
            case_status = c.get("status", "ready")
            if (
                active_lease
                and active_lease.get("expires_at")
                and active_lease["expires_at"] > now
                and case_status == "ready"
            ):
                case_status = "in_review"

            if active_only and case_status.lower() in terminal_statuses:
                continue
            if status is not None and case_status.lower() != status.strip().lower():
                continue
            if target_tier is not None and c.get("priority_tier") != target_tier:
                continue
            filtered.append((c, case_status))

        filtered.sort(key=lambda x: (x[0].get("priority_tier", 2), -x[0].get("priority_score", 0)))
        total = len(filtered)
        page = filtered[offset : offset + limit]

        items = []
        for c, case_status in page:
            cid = str(c["id"])
            asgn = self._assignments.get(str(c.get("assignment_id", "")))
            tier = c.get("priority_tier", 2)

            active_lease = self._active_leases.get(cid) or self._active_leases.get(self._resolve_case_id(cid))
            active_analyst = None
            active_lease_analyst_id = None
            active_lease_expires_at = None
            if active_lease and active_lease.get("expires_at") and active_lease["expires_at"] > now:
                active_analyst = str(active_lease["analyst_id"])
                active_lease_analyst_id = active_analyst
                active_lease_expires_at = active_lease["expires_at"]

            assigned_id = active_analyst or (
                str(c.get("assigned_analyst_id")) if c.get("assigned_analyst_id") else None
            )
            assigned_name = None
            if assigned_id:
                if assigned_id in self._analysts:
                    assigned_name = self._analysts[assigned_id].get("display_name")
                else:
                    assigned_name = assigned_id

            driver_id_val = (
                str(asgn.get("driver_id"))
                if asgn and asgn.get("driver_id")
                else (str(c.get("driver_id")) if c.get("driver_id") else None)
            )
            driver_rec = self._drivers.get(driver_id_val, {}) if driver_id_val else {}
            driver_name_val = driver_rec.get("display_name") or c.get("driver_name")

            vehicle_id_val = str(asgn.get("vehicle_id")) if asgn and asgn.get("vehicle_id") else ""
            vehicle_rec = self._vehicles.get(vehicle_id_val, {}) if vehicle_id_val else {}
            vehicle_plate_val = vehicle_rec.get("registration_ref") or c.get("vehicle_plate")

            items.append(
                FraudCaseSummary(
                    id=cid,
                    trip_id=str(asgn.get("trip_id")) if asgn else None,
                    assignment_id=str(c.get("assignment_id")),
                    driver_id=driver_id_val,
                    status=case_status,
                    priority=f"P{tier}",
                    priority_score=c.get("priority_score", 0),
                    category=c.get("suspected_category") or "none",
                    confidence=c.get("confidence") or self._model_assessments.get(cid, {}).get("confidence"),
                    driver_name=driver_name_val,
                    vehicle_plate=vehicle_plate_val,
                    opened_at=c.get("created_at"),
                    updated_at=c.get("updated_at"),
                    assigned_analyst_id=assigned_id,
                    assigned_analyst_name=assigned_name,
                    active_lease_analyst_id=active_lease_analyst_id,
                    active_lease_expires_at=active_lease_expires_at,
                    version=c.get("version", 1),
                    dispute_status=c.get("dispute_status", "not_disputed"),
                    dispute_deadline=c.get("dispute_deadline"),
                )
            )

        return CaseListResponse(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        )

    # 3.1 Case History Listing (Processed / Finalized Cases)
    async def list_case_history(
        self,
        status: str | None = None,
        search: str | None = None,
        decision: str | None = None,
        analyst_id: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
        organization_id: str | None = None,
        driver_id: str | None = None,
    ) -> CaseListResponse:
        terminal_statuses = {"resolved", "dismissed", "auto_dismissed"}
        if status is not None and status.strip().lower() not in terminal_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid history status filter '{status}'. Allowed: {sorted(terminal_statuses)}",
            )

        conn = self._get_db_connection()
        if conn is not None:
            _require_org_scope(organization_id, allow_unscoped=self._test_stack_unscoped())
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    where_clauses = []
                    params: list[Any] = []
                    if organization_id:
                        where_clauses.append("c.organization_id = %s")
                        params.append(organization_id)

                    if driver_id:
                        where_clauses.append("a.driver_id::text = %s")
                        params.append(driver_id)

                    if status is not None:
                        where_clauses.append("LOWER(c.status) = LOWER(%s)")
                        params.append(status.strip())
                    else:
                        where_clauses.append("LOWER(c.status) = ANY(%s)")
                        params.append(["resolved", "dismissed", "auto_dismissed"])

                    if analyst_id:
                        where_clauses.append("c.assigned_analyst_id::text = %s")
                        params.append(analyst_id)

                    if start_date:
                        where_clauses.append("c.updated_at >= %s")
                        params.append(start_date)

                    if end_date:
                        where_clauses.append("c.updated_at <= %s")
                        params.append(end_date)

                    if search and search.strip():
                        s_term = f"%{search.strip()}%"
                        where_clauses.append(
                            """EXISTS (
                                SELECT 1 FROM app.trip_assignments a
                                LEFT JOIN app.drivers d ON a.driver_id = d.id
                                LEFT JOIN app.principals p_dr ON d.principal_id = p_dr.id
                                LEFT JOIN app.vehicles v ON a.vehicle_id = v.id
                                WHERE a.id = c.assignment_id AND (
                                    COALESCE(to_jsonb(d)->>'display_name', p_dr.display_name, '') ILIKE %s
                                    OR a.driver_id::text ILIKE %s
                                    OR COALESCE(d.external_ref, '') ILIKE %s
                                    OR COALESCE(v.registration_ref, '') ILIKE %s
                                )
                            )"""
                        )
                        params.extend([s_term, s_term, s_term, s_term])

                    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

                    count_query = f"SELECT count(*) FROM app.fraud_cases c LEFT JOIN app.trip_assignments a ON c.assignment_id = a.id {where_sql};"
                    cur.execute(count_query, params)
                    total = cur.fetchone()["count"]

                    query = f"""
                        SELECT c.id, c.status, c.dispute_status, c.dispute_deadline, c.priority_tier, c.priority_score, c.suspected_category,
                               c.assigned_analyst_id, c.version, c.created_at, c.updated_at, c.sla_due_at,
                               a.trip_id, a.driver_id, a.id as assignment_id,
                               d.external_ref as driver_ref,
                               COALESCE(to_jsonb(d)->>'display_name', p_dr.display_name) as driver_name,
                               v.registration_ref as vehicle_plate,
                               fs.stationary_duration_s as stationary_duration_s,
                               p_an.display_name as analyst_name,
                               t.district as trip_district, ma.confidence, adj.staged_context,
                               lease.analyst_id as active_lease_analyst_id,
                               lease.expires_at as active_lease_expires_at
                        FROM app.fraud_cases c
                        LEFT JOIN app.adjudications adj ON adj.case_id = c.id
                        LEFT JOIN app.trip_assignments a ON c.assignment_id = a.id
                        LEFT JOIN app.trips t ON a.trip_id = t.id
                        LEFT JOIN app.drivers d ON a.driver_id = d.id
                        LEFT JOIN app.principals p_dr ON d.principal_id = p_dr.id
                        LEFT JOIN app.principals p_an ON c.assigned_analyst_id = p_an.id
                        LEFT JOIN app.vehicles v ON a.vehicle_id = v.id
                        LEFT JOIN LATERAL (SELECT id FROM app.evidence_snapshots WHERE case_id = c.id ORDER BY version DESC LIMIT 1) es ON true
                        LEFT JOIN LATERAL (SELECT stationary_duration_s FROM app.feature_sets WHERE evidence_snapshot_id = es.id ORDER BY created_at DESC LIMIT 1) fs ON true
                        LEFT JOIN LATERAL (SELECT confidence FROM app.model_assessments WHERE evidence_snapshot_id = es.id ORDER BY created_at DESC LIMIT 1) ma ON true
                        LEFT JOIN LATERAL (SELECT analyst_id, expires_at FROM app.review_leases WHERE case_id = c.id AND expires_at > now() ORDER BY expires_at DESC LIMIT 1) lease ON true
                        {where_sql}
                        ORDER BY c.updated_at DESC, c.created_at DESC
                        LIMIT %s OFFSET %s;
                    """
                    cur.execute(query, [*params, limit, offset])
                    rows = cur.fetchall()

                    now_utc = datetime.now(UTC)
                    items: list[FraudCaseSummary] = []
                    for r in rows:
                        tier = r["priority_tier"]
                        sla_due = r.get("sla_due_at")
                        sla_sec = None
                        if sla_due:
                            diff = int((sla_due - now_utc).total_seconds())
                            sla_sec = max(0, diff)

                        district = r.get("trip_district")

                        items.append(
                            FraudCaseSummary(
                                id=str(r["id"]),
                                trip_id=str(r["trip_id"]) if r["trip_id"] else None,
                                assignment_id=str(r["assignment_id"]) if r["assignment_id"] else None,
                                driver_id=str(r["driver_id"]) if r["driver_id"] else None,
                                status=r["status"] or "resolved",
                                priority=f"P{tier}",
                                priority_score=r["priority_score"] or 0,
                                category=r["suspected_category"] or "none",
                                confidence=r.get("confidence"),
                                opened_at=r["created_at"],
                                updated_at=r["updated_at"],
                                assigned_analyst_id=str(r["assigned_analyst_id"]) if r["assigned_analyst_id"] else None,
                                active_lease_analyst_id=str(r["active_lease_analyst_id"])
                                if r.get("active_lease_analyst_id")
                                else None,
                                active_lease_expires_at=r.get("active_lease_expires_at"),
                                version=r["version"] or 1,
                                driver_name=r.get("driver_name"),
                                vehicle_plate=r.get("vehicle_plate"),
                                district=district,
                                stall_duration_s=r.get("stationary_duration_s"),
                                sla_countdown_s=sla_sec,
                                assigned_analyst_name=r.get("analyst_name"),
                                dispute_status=r.get("dispute_status") or "not_disputed",
                                dispute_deadline=r.get("dispute_deadline"),
                                **(r.get("staged_context") or {}),
                            )
                        )

                    return CaseListResponse(
                        items=items,
                        total=total,
                        limit=limit,
                        offset=offset,
                    )
            except HTTPException:
                raise
            except Exception:
                self._require_test_fallback()
            finally:
                conn.close()

        self._require_test_fallback()
        # In-memory fallback
        norm_search = _normalize_search_text(search) if search and search.strip() else None
        filtered = []
        for case_id, c in self._cases.items():
            if case_id in self._case_aliases:
                continue
            if organization_id and str(c.get("organization_id")) != organization_id:
                continue
            asgn = self._assignments.get(str(c.get("assignment_id", "")))
            if driver_id:
                c_drv = str(asgn.get("driver_id")) if asgn and asgn.get("driver_id") else str(c.get("driver_id", ""))
                if c_drv != driver_id:
                    continue

            case_status = str(c.get("status", "ready")).lower()
            if status is not None:
                if case_status != status.strip().lower():
                    continue
            else:
                if case_status not in terminal_statuses:
                    continue

            if analyst_id and str(c.get("assigned_analyst_id", "")) != analyst_id:
                continue

            updated_at = c.get("updated_at")
            if updated_at:
                if isinstance(updated_at, str):
                    try:
                        updated_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                    except Exception:
                        pass
                if start_date and isinstance(updated_at, datetime) and updated_at < start_date:
                    continue
                if end_date and isinstance(updated_at, datetime) and updated_at > end_date:
                    continue

            if norm_search:
                driver_id_str = (
                    str(asgn.get("driver_id")) if asgn and asgn.get("driver_id") else str(c.get("driver_id", ""))
                )
                driver_rec = self._drivers.get(driver_id_str, {}) if driver_id_str else {}
                driver_name = driver_rec.get("display_name") or c.get("driver_name") or ""
                driver_ref = driver_rec.get("external_ref") or c.get("driver_ref") or ""

                vehicle_id_str = str(asgn.get("vehicle_id")) if asgn and asgn.get("vehicle_id") else ""
                vehicle_rec = self._vehicles.get(vehicle_id_str, {}) if vehicle_id_str else {}
                vehicle_plate = vehicle_rec.get("registration_ref") or c.get("vehicle_plate") or ""

                targets = [
                    _normalize_search_text(driver_name),
                    _normalize_search_text(driver_id_str),
                    _normalize_search_text(driver_ref),
                    _normalize_search_text(vehicle_plate),
                ]
                plate_clean = re.sub(r"[^a-z0-9]", "", _normalize_search_text(vehicle_plate))
                search_clean = re.sub(r"[^a-z0-9]", "", norm_search)
                plate_match = bool(search_clean and search_clean in plate_clean)

                if not (any(norm_search in t for t in targets if t) or plate_match):
                    continue

            filtered.append(c)

        def _sort_key(c_item: dict[str, Any]) -> datetime:
            up = c_item.get("updated_at")
            if isinstance(up, str):
                try:
                    up = datetime.fromisoformat(up.replace("Z", "+00:00"))
                except Exception:
                    up = None
            if not isinstance(up, datetime):
                up = datetime.min.replace(tzinfo=UTC)
            elif up.tzinfo is None:
                up = up.replace(tzinfo=UTC)
            return up

        filtered.sort(key=_sort_key, reverse=True)
        total = len(filtered)
        page = filtered[offset : offset + limit]

        now = datetime.now(UTC)
        items = []
        for c in page:
            cid = str(c["id"])
            asgn = self._assignments.get(str(c.get("assignment_id", "")))
            tier = c.get("priority_tier", 2)
            assigned_id = str(c.get("assigned_analyst_id")) if c.get("assigned_analyst_id") else None
            assigned_name = None
            if assigned_id:
                if assigned_id in self._analysts:
                    assigned_name = self._analysts[assigned_id].get("display_name")
                else:
                    assigned_name = assigned_id

            active_lease = self._active_leases.get(cid) or self._active_leases.get(self._resolve_case_id(cid))
            active_lease_analyst_id = None
            active_lease_expires_at = None
            if active_lease and active_lease.get("expires_at") and active_lease["expires_at"] > now:
                active_lease_analyst_id = str(active_lease["analyst_id"])
                active_lease_expires_at = active_lease["expires_at"]

            driver_id_val = (
                str(asgn.get("driver_id"))
                if asgn and asgn.get("driver_id")
                else (str(c.get("driver_id")) if c.get("driver_id") else None)
            )
            driver_rec = self._drivers.get(driver_id_val, {}) if driver_id_val else {}
            driver_name_val = driver_rec.get("display_name") or c.get("driver_name")

            vehicle_id_val = str(asgn.get("vehicle_id")) if asgn and asgn.get("vehicle_id") else ""
            vehicle_rec = self._vehicles.get(vehicle_id_val, {}) if vehicle_id_val else {}
            vehicle_plate_val = vehicle_rec.get("registration_ref") or c.get("vehicle_plate")

            items.append(
                FraudCaseSummary(
                    id=cid,
                    trip_id=str(asgn.get("trip_id")) if asgn else None,
                    assignment_id=str(c.get("assignment_id")),
                    driver_id=driver_id_val,
                    status=c.get("status", "resolved"),
                    priority=f"P{tier}",
                    priority_score=c.get("priority_score", 0),
                    category=c.get("suspected_category") or "none",
                    confidence=c.get("confidence") or self._model_assessments.get(cid, {}).get("confidence"),
                    driver_name=driver_name_val,
                    vehicle_plate=vehicle_plate_val,
                    opened_at=c.get("created_at"),
                    updated_at=c.get("updated_at"),
                    assigned_analyst_id=assigned_id,
                    assigned_analyst_name=assigned_name,
                    active_lease_analyst_id=active_lease_analyst_id,
                    active_lease_expires_at=active_lease_expires_at,
                    version=c.get("version", 1),
                    dispute_status=c.get("dispute_status", "not_disputed"),
                    dispute_deadline=c.get("dispute_deadline"),
                    **StagedAdjudicationContext.model_validate(
                        next((a for a in self._adjudications if a["case_id"] == cid), {})
                    ).model_dump(mode="json"),
                )
            )

        return CaseListResponse(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        )

    # 3.2 Analyst Audit Profile & Activity Ledger
    async def get_analyst_audit_profile(
        self,
        analyst_id: str,
        organization_id: str,
        search: str | None = None,
        verdict: str | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> AnalystAuditProfileResponse:
        conn = self._get_db_connection()
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    # 1. Fetch principal profile & roles
                    cur.execute(
                        """
                        SELECT p.id, p.display_name, p.organization_id,
                               COALESCE(array_agg(pr.role) FILTER (WHERE pr.role IS NOT NULL), ARRAY[]::text[]) as roles
                        FROM app.principals p
                        LEFT JOIN app.principal_roles pr ON pr.principal_id = p.id
                        WHERE p.id::text = %s AND p.organization_id::text = %s
                        GROUP BY p.id, p.display_name, p.organization_id;
                        """,
                        (str(analyst_id), str(organization_id)),
                    )
                    p_row = cur.fetchone()
                    display_name = p_row["display_name"] if p_row else "Fraud Analyst"
                    roles = list(p_row["roles"]) if p_row and p_row.get("roles") else ["fraud_analyst", "analyst"]

                    # Determine governance limits
                    primary_role = "fraud_analyst"
                    if "admin" in roles:
                        primary_role = "admin"
                    elif "senior_analyst" in roles:
                        primary_role = "senior_analyst"
                    fine_limit = 5000000 if primary_role in ("senior_analyst", "admin") else 2000000
                    gov_limits = AnalystGovernanceLimits(
                        dismiss_authority="Unrestricted",
                        warning_authority="Authorized",
                        direct_fine_limit_vnd=fine_limit,
                        suspension_authority="24h / 48h Lockout",
                        role=primary_role,
                    )

                    # 2. Check active review lease
                    now = datetime.now(UTC)
                    cur.execute(
                        """
                        SELECT l.case_id, l.expires_at, c.priority_tier,
                               d.display_name as driver_name, v.registration_ref as vehicle_plate
                        FROM app.review_leases l
                        JOIN app.fraud_cases c ON c.id = l.case_id
                        LEFT JOIN app.trip_assignments a ON a.id = c.assignment_id
                        LEFT JOIN app.drivers d ON d.id = a.driver_id
                        LEFT JOIN app.vehicles v ON v.id = a.vehicle_id
                        WHERE l.analyst_id::text = %s AND c.organization_id::text = %s AND l.expires_at > now()
                        ORDER BY l.expires_at DESC
                        LIMIT 1;
                        """,
                        (str(analyst_id), str(organization_id)),
                    )
                    lease_row = cur.fetchone()
                    active_lease: ActiveReviewLeaseSummary | None = None
                    if lease_row:
                        expires_at = lease_row["expires_at"]
                        if expires_at.tzinfo is None:
                            expires_at = expires_at.replace(tzinfo=UTC)
                        rem = max(0, int((expires_at - now).total_seconds()))
                        tier = lease_row.get("priority_tier", 0)
                        active_lease = ActiveReviewLeaseSummary(
                            case_id=str(lease_row["case_id"]),
                            case_code=f"#FC-{str(lease_row['case_id'])[:8].upper()}",
                            severity=f"P{tier}",
                            driver_name=lease_row.get("driver_name"),
                            vehicle_plate=lease_row.get("vehicle_plate"),
                            expires_at=expires_at,
                            remaining_seconds=rem,
                        )

                    # 3. Adjudications / Audit Ledger
                    cur.execute(
                        """
                        SELECT adj.id, adj.case_id, adj.analyst_id, adj.outcome, adj.rationale,
                               adj.approved_at as created_at, adj.approved_at, adj.request_hash, adj.staged_context,
                               c.suspected_category, c.version as snapshot_version, c.created_at as case_created_at,
                               d.display_name as driver_name,
                               v.registration_ref as vehicle_plate,
                               p.display_name as analyst_name
                        FROM app.adjudications adj
                        JOIN app.fraud_cases c ON c.id = adj.case_id
                        LEFT JOIN app.trip_assignments a ON a.id = c.assignment_id
                        LEFT JOIN app.drivers d ON d.id = a.driver_id
                        LEFT JOIN app.vehicles v ON v.id = a.vehicle_id
                        LEFT JOIN app.principals p ON p.id = adj.analyst_id
                        WHERE adj.analyst_id::text = %s AND c.organization_id::text = %s
                        ORDER BY adj.approved_at DESC;
                        """,
                        (str(analyst_id), str(organization_id)),
                    )
                    adj_rows = cur.fetchall()

                    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                    thirty_days_ago = now - timedelta(days=30)
                    today_count = 0
                    thirty_day_count = 0
                    durations: list[float] = []
                    ledger_items: list[AnalystAuditLedgerItem] = []
                    norm_search = _normalize_search_text(search) if search and search.strip() else None

                    for r in adj_rows:
                        ts = r.get("approved_at") or r.get("created_at") or now
                        if isinstance(ts, str):
                            try:
                                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                            except Exception:
                                ts = now
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=UTC)

                        if from_date and ts < from_date.astimezone(UTC):
                            continue
                        if to_date and ts > to_date.astimezone(UTC):
                            continue

                        if ts >= today_start:
                            today_count += 1
                        if ts >= thirty_days_ago:
                            thirty_day_count += 1

                        c_created = r.get("case_created_at")
                        if isinstance(c_created, str):
                            try:
                                c_created = datetime.fromisoformat(c_created.replace("Z", "+00:00"))
                            except Exception:
                                c_created = None
                        if c_created and c_created.tzinfo is None:
                            c_created = c_created.replace(tzinfo=UTC)
                        if c_created and ts >= c_created:
                            durations.append((ts - c_created).total_seconds())

                        d_name = r.get("driver_name")
                        v_plate = r.get("vehicle_plate")
                        d_label = d_name or "Driver"
                        subj = f"{d_label} ({v_plate})" if v_plate else d_label
                        raw_outcome = str(r.get("outcome", "AGREE")).upper()
                        verdict_map = {
                            "APPROVE": "AGREE",
                            "DISMISS": "DISAGREE",
                            "AGREE": "AGREE",
                            "DISAGREE": "DISAGREE",
                        }
                        verdict_val = verdict_map.get(raw_outcome, "UNKNOWN")

                        sanction = None

                        cid_str = str(r["case_id"])
                        req_hash_raw = r.get("request_hash")
                        if isinstance(req_hash_raw, (bytes, memoryview)):
                            req_hash_str = f"sha256-{bytes(req_hash_raw).hex()[:12]}"
                        elif req_hash_raw:
                            req_hash_str = str(req_hash_raw)
                        else:
                            req_hash_str = f"sha256-{str(r['id'])[:12]}"

                        item = AnalystAuditLedgerItem(
                            id=str(r["id"]),
                            case_id=cid_str,
                            case_code=f"#FC-{cid_str[:8].upper()}",
                            timestamp=ts,
                            actor_id=str(analyst_id),
                            actor_name=r.get("analyst_name") or display_name,
                            actor_type="analyst",
                            action="adjudicate",
                            verdict=verdict_val,
                            subject_entity=subj,
                            triggered_violation=r.get("suspected_category") or "ERR-02",
                            sanction=sanction,
                            rationale=r.get("rationale") or "",
                            snapshot_version=r.get("snapshot_version", 1),
                            request_hash=req_hash_str,
                            **(r.get("staged_context") or {}),
                        )

                        if verdict and item.verdict.upper() != verdict.strip().upper():
                            continue

                        if norm_search:
                            targets = [
                                _normalize_search_text(item.case_id),
                                _normalize_search_text(item.case_code),
                                _normalize_search_text(item.subject_entity),
                                _normalize_search_text(d_name or ""),
                                _normalize_search_text(v_plate or ""),
                                _normalize_search_text(item.triggered_violation),
                                _normalize_search_text(item.rationale),
                            ]
                            plate_clean = re.sub(r"[^a-z0-9]", "", _normalize_search_text(v_plate or ""))
                            search_clean = re.sub(r"[^a-z0-9]", "", norm_search)
                            plate_match = bool(search_clean and search_clean in plate_clean)
                            if not (any(norm_search in t for t in targets if t) or plate_match):
                                continue

                        ledger_items.append(item)

                    ledger_items.sort(key=lambda x: x.timestamp, reverse=True)
                    total_ledger = len(ledger_items)
                    paged_ledger = ledger_items[offset : offset + limit]

                    avg_mttr = round(sum(durations) / len(durations), 1) if durations else None
                    metrics = AnalystDecisionMetrics(
                        today_decisions_count=today_count,
                        thirty_day_decisions_count=thirty_day_count,
                        average_mttr_seconds=avg_mttr,
                        model_agreement_pct=None,
                        quality_overturn_pct=None,
                    )

                    return AnalystAuditProfileResponse(
                        analyst_id=str(analyst_id),
                        display_name=display_name,
                        roles=roles,
                        organization_id=str(organization_id),
                        metrics=metrics,
                        governance_limits=gov_limits,
                        active_lease=active_lease,
                        ledger=paged_ledger,
                        total_ledger_count=total_ledger,
                    )
            except HTTPException:
                raise
            except Exception:
                self._require_test_fallback()
            finally:
                conn.close()

        self._require_test_fallback()
        # In-memory fallback
        now = datetime.now(UTC)
        p_data = self._principals.get(analyst_id, {})
        if not p_data:
            p_data = self._analysts.get(analyst_id, {})
        display_name = (
            p_data.get("display_name")
            or p_data.get("name")
            or self.get_principal_display_name(analyst_id)
            or "Fraud Analyst"
        )
        roles = list(p_data.get("roles") or ["fraud_analyst", "analyst"])

        # Governance limits
        primary_role = "fraud_analyst"
        if "admin" in roles:
            primary_role = "admin"
        elif "senior_analyst" in roles:
            primary_role = "senior_analyst"
        fine_limit = 5000000 if primary_role in ("senior_analyst", "admin") else 2000000
        governance_limits = AnalystGovernanceLimits(
            dismiss_authority="Unrestricted",
            warning_authority="Authorized",
            direct_fine_limit_vnd=fine_limit,
            suspension_authority="24h / 48h Lockout",
            role=primary_role,
        )

        # Active review lease
        active_lease = None
        all_leases = dict(self._active_leases)
        if hasattr(self, "_leases") and isinstance(self._leases, dict):
            all_leases.update(self._leases)
        for cid, lease in all_leases.items():
            if str(lease.get("analyst_id")) == analyst_id:
                exp = lease.get("expires_at")
                if isinstance(exp, str):
                    try:
                        exp = datetime.fromisoformat(exp.replace("Z", "+00:00"))
                    except Exception:
                        exp = None
                if exp and exp.tzinfo is None:
                    exp = exp.replace(tzinfo=UTC)
                if exp and exp > now:
                    c = self._cases.get(cid) or self._cases.get(self._resolve_case_id(cid))
                    if c and organization_id and str(c.get("organization_id")) != organization_id:
                        continue
                    tier = c.get("priority_tier", 0) if c else 0
                    asgn = self._assignments.get(str(c.get("assignment_id", ""))) if c else None
                    d_name = c.get("driver_name") if c else None
                    if not d_name and asgn and asgn.get("driver_id") in self._drivers:
                        d_name = self._drivers[asgn["driver_id"]].get("display_name")
                    v_plate = c.get("vehicle_plate") if c else None
                    if not v_plate and asgn and asgn.get("vehicle_id") in self._vehicles:
                        v_plate = self._vehicles[asgn["vehicle_id"]].get("registration_ref")
                    rem = max(0, int((exp - now).total_seconds()))
                    active_lease = ActiveReviewLeaseSummary(
                        case_id=cid,
                        case_code=f"#FC-{cid[:8].upper()}",
                        severity=f"P{tier}",
                        driver_name=d_name,
                        vehicle_plate=v_plate,
                        expires_at=exp,
                        remaining_seconds=rem,
                    )
                    break

        # Process adjudications for metrics and ledger
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        thirty_days_ago = now - timedelta(days=30)
        today_count = 0
        thirty_day_count = 0
        durations = []
        ledger_items = []
        norm_search = _normalize_search_text(search) if search and search.strip() else None

        for adj in self._adjudications:
            if str(adj.get("analyst_id")) != analyst_id:
                continue
            cid = str(adj.get("case_id"))
            c = self._cases.get(cid) or self._cases.get(self._resolve_case_id(cid)) or {}
            c_org = c.get("organization_id")
            adj_org = adj.get("organization_id")
            if organization_id:
                if c_org and str(c_org) != organization_id:
                    continue
                if adj_org and str(adj_org) != organization_id:
                    continue

            ts = adj.get("approved_at") or adj.get("created_at") or now
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except Exception:
                    ts = now
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)

            if from_date and ts < from_date.astimezone(UTC):
                continue
            if to_date and ts > to_date.astimezone(UTC):
                continue

            if ts >= today_start:
                today_count += 1
            if ts >= thirty_days_ago:
                thirty_day_count += 1

            c_created = c.get("created_at")
            if isinstance(c_created, str):
                try:
                    c_created = datetime.fromisoformat(c_created.replace("Z", "+00:00"))
                except Exception:
                    c_created = None
            if c_created and c_created.tzinfo is None:
                c_created = c_created.replace(tzinfo=UTC)
            if c_created and ts >= c_created:
                durations.append((ts - c_created).total_seconds())

            # Subject entity
            asgn = self._assignments.get(str(c.get("assignment_id", ""))) if c else None
            d_name = c.get("driver_name") if c else None
            if not d_name and asgn and asgn.get("driver_id") in self._drivers:
                d_name = self._drivers[asgn["driver_id"]].get("display_name")
            v_plate = c.get("vehicle_plate") if c else None
            if not v_plate and asgn and asgn.get("vehicle_id") in self._vehicles:
                v_plate = self._vehicles[asgn["vehicle_id"]].get("registration_ref")

            d_label = d_name or "Driver"
            subj = f"{d_label} ({v_plate})" if v_plate else d_label

            raw_outcome = str(adj.get("outcome", "AGREE")).upper()
            verdict_map = {
                "APPROVE": "AGREE",
                "DISMISS": "DISAGREE",
                "AGREE": "AGREE",
                "DISAGREE": "DISAGREE",
            }
            verdict_val = verdict_map.get(raw_outcome, "UNKNOWN")

            sanction = adj.get("sanction")

            item = AnalystAuditLedgerItem(
                id=str(adj.get("id", uuid4())),
                case_id=cid,
                case_code=f"#FC-{cid[:8].upper()}",
                timestamp=ts,
                actor_id=analyst_id,
                actor_name=display_name,
                actor_type="analyst",
                action="adjudicate",
                verdict=verdict_val,
                subject_entity=subj,
                triggered_violation=c.get("suspected_category") or "ERR-02",
                sanction=sanction,
                rationale=adj.get("rationale") or "",
                snapshot_version=c.get("version", 1),
                request_hash=adj.get("request_hash") or f"sha256-{str(adj.get('id', ''))[:12]}",
                preliminary_judgment_id=adj.get("preliminary_judgment_id"),
                preliminary_judgment=adj.get("preliminary_judgment"),
                ai_suggestion=adj.get("ai_suggestion"),
                delta=adj.get("delta"),
            )

            if verdict:
                query_verdict = verdict_map.get(verdict.strip().upper(), verdict.strip().upper())
                if item.verdict.upper() != query_verdict:
                    continue

            if norm_search:
                targets = [
                    _normalize_search_text(item.case_id),
                    _normalize_search_text(item.case_code),
                    _normalize_search_text(item.subject_entity),
                    _normalize_search_text(d_name or ""),
                    _normalize_search_text(v_plate or ""),
                    _normalize_search_text(item.triggered_violation),
                    _normalize_search_text(item.rationale),
                ]
                plate_clean = re.sub(r"[^a-z0-9]", "", _normalize_search_text(v_plate or ""))
                search_clean = re.sub(r"[^a-z0-9]", "", norm_search)
                plate_match = bool(search_clean and search_clean in plate_clean)
                if not (any(norm_search in t for t in targets if t) or plate_match):
                    continue

            ledger_items.append(item)

        ledger_items.sort(key=lambda x: x.timestamp, reverse=True)
        total_ledger = len(ledger_items)
        paged_ledger = ledger_items[offset : offset + limit]

        avg_mttr = round(sum(durations) / len(durations), 1) if durations else None
        metrics = AnalystDecisionMetrics(
            today_decisions_count=today_count,
            thirty_day_decisions_count=thirty_day_count,
            average_mttr_seconds=avg_mttr,
            model_agreement_pct=None,
            quality_overturn_pct=None,
        )

        return AnalystAuditProfileResponse(
            analyst_id=analyst_id,
            display_name=display_name,
            roles=roles,
            organization_id=organization_id,
            metrics=metrics,
            governance_limits=governance_limits,
            active_lease=active_lease,
            ledger=paged_ledger,
            total_ledger_count=total_ledger,
        )

    async def get_analytics_metrics(
        self,
        organization_id: str,
        window_days: int | None = 30,
    ) -> AnalyticsMetricsResponse:
        """Aggregate operational and queue metrics across the complete dataset for an organization."""
        now = datetime.now(UTC)
        cutoff = now - timedelta(days=window_days) if window_days else None

        conn = self._get_db_connection()
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")

                    where_clauses = ["organization_id = %s"]
                    params: list[Any] = [organization_id]
                    if cutoff:
                        where_clauses.append("created_at >= %s")
                        params.append(cutoff)
                    where_sql = " AND ".join(where_clauses)

                    cur.execute(
                        f"""
                        SELECT
                            COUNT(*) as total_cases,
                            COUNT(*) FILTER (WHERE status IN ('new', 'escalated', 'in_review')) as active_backlog,
                            COUNT(*) FILTER (WHERE status IN ('awaiting_driver_confirmation', 'driver_pending')) as pending_driver,
                            COUNT(*) FILTER (WHERE status = 'driver_confirmed_resolution') as driver_confirmed,
                            COUNT(*) FILTER (WHERE status = 'auto_dismissed') as auto_dismissed,
                            COUNT(*) FILTER (WHERE priority_tier = 0) as p0_count,
                            COUNT(*) FILTER (WHERE priority_tier = 1) as p1_count,
                            COUNT(*) FILTER (WHERE priority_tier = 2) as p2_count
                        FROM app.fraud_cases
                        WHERE {where_sql};
                        """,
                        tuple(params),
                    )
                    row = cur.fetchone()
                    total_cases = row["total_cases"] or 0
                    active_backlog = row["active_backlog"] or 0
                    pending_driver = row["pending_driver"] or 0
                    driver_confirmed = row["driver_confirmed"] or 0
                    auto_dismissed = row["auto_dismissed"] or 0
                    priority_dist = {
                        "P0": row["p0_count"] or 0,
                        "P1": row["p1_count"] or 0,
                        "P2": row["p2_count"] or 0,
                    }

                    cur.execute(
                        f"""
                        SELECT suspected_category, COUNT(*) as cnt
                        FROM app.fraud_cases
                        WHERE {where_sql} AND suspected_category IS NOT NULL
                        GROUP BY suspected_category;
                        """,
                        tuple(params),
                    )
                    cat_rows = cur.fetchall()
                    categories = {r["suspected_category"]: r["cnt"] for r in cat_rows}

                    cur.execute(
                        """
                        SELECT COUNT(*) as claimed_count
                        FROM app.review_leases l
                        JOIN app.fraud_cases c ON l.case_id = c.id
                        WHERE c.organization_id = %s AND l.expires_at > NOW();
                        """,
                        (organization_id,),
                    )
                    claimed_row = cur.fetchone()
                    claimed_cases = claimed_row["claimed_count"] if claimed_row else 0
                    available_unclaimed = max(0, active_backlog - claimed_cases)

                    adj_where = ["c.organization_id = %s"]
                    adj_params: list[Any] = [organization_id]
                    if cutoff:
                        adj_where.append("a.approved_at >= %s")
                        adj_params.append(cutoff)
                    adj_sql = " AND ".join(adj_where)

                    cur.execute(
                        f"""
                        SELECT
                            COUNT(*) as total_adj,
                            AVG(EXTRACT(EPOCH FROM (a.approved_at - c.created_at))) as avg_mttr
                        FROM app.adjudications a
                        JOIN app.fraud_cases c ON a.case_id = c.id
                        WHERE {adj_sql};
                        """,
                        tuple(adj_params),
                    )
                    adj_row = cur.fetchone()
                    analyst_total = adj_row["total_adj"] if adj_row else 0
                    avg_mttr = (
                        round(float(adj_row["avg_mttr"]), 1) if (adj_row and adj_row["avg_mttr"] is not None) else None
                    )

                    cur.execute(
                        f"""
                        SELECT outcome, COUNT(*) as cnt
                        FROM app.adjudications a
                        JOIN app.fraud_cases c ON a.case_id = c.id
                        WHERE {adj_sql}
                        GROUP BY outcome;
                        """,
                        tuple(adj_params),
                    )
                    dec_rows = cur.fetchall()
                    decisions_breakdown = {r["outcome"]: r["cnt"] for r in dec_rows}

                    hitl_ratio = 100.0 if (analyst_total > 0 or total_cases > 0) else None

                    return AnalyticsMetricsResponse(
                        scope="organization",
                        organization_id=organization_id,
                        window_days=window_days,
                        generated_at=now,
                        queue=AnalyticsQueueMetrics(
                            total_cases=total_cases,
                            active_backlog=active_backlog,
                            pending_driver_confirmation=pending_driver,
                            claimed_cases=claimed_cases,
                            available_unclaimed=available_unclaimed,
                            priority_distribution=priority_dist,
                        ),
                        dispositions=AnalyticsDispositionMetrics(
                            driver_confirmed_resolutions=driver_confirmed,
                            analyst_adjudications_total=analyst_total,
                            analyst_decisions_breakdown=decisions_breakdown,
                            auto_dismissed_count=auto_dismissed,
                        ),
                        categories=categories,
                        performance=AnalyticsPerformanceMetrics(
                            average_mttr_seconds=avg_mttr,
                            hitl_enforcement_ratio_pct=hitl_ratio,
                            reviewer_concordance_pct=None,
                        ),
                        health=AnalyticsSystemHealth(
                            database_healthy=True,
                            worker_status="active",
                            environment=self.settings.app_env,
                        ),
                    )
            except Exception as e:
                logger.warning("Database error fetching analytics metrics: %s", e)

        # In-memory fallback
        target_org = organization_id
        filtered_cases: list[dict[str, Any]] = []
        for c in self._cases.values():
            if c.get("organization_id") != target_org:
                continue
            if cutoff:
                created_at = c.get("created_at")
                if isinstance(created_at, datetime) and created_at < cutoff:
                    continue
            filtered_cases.append(c)

        total_cases = len(filtered_cases)
        active_backlog = 0
        pending_driver = 0
        driver_confirmed = 0
        auto_dismissed = 0
        p0_count = 0
        p1_count = 0
        p2_count = 0
        mem_categories: dict[str, int] = {}
        filtered_case_ids = {c.get("id") for c in filtered_cases}

        for c in filtered_cases:
            status = c.get("status")
            if status in ("new", "escalated", "in_review"):
                active_backlog += 1
            elif status in ("awaiting_driver_confirmation", "driver_pending"):
                pending_driver += 1
            elif status == "driver_confirmed_resolution":
                driver_confirmed += 1
            elif status == "auto_dismissed":
                auto_dismissed += 1

            tier = c.get("priority_tier", 1)
            if tier == 0:
                p0_count += 1
            elif tier == 1:
                p1_count += 1
            else:
                p2_count += 1

            cat = c.get("suspected_category")
            if cat:
                mem_categories[cat] = mem_categories.get(cat, 0) + 1

        claimed_cases = 0
        for case_id, lease in self._leases.items():
            if case_id in filtered_case_ids:
                exp = lease.get("expires_at")
                if isinstance(exp, datetime) and exp > now:
                    claimed_cases += 1
        available_unclaimed = max(0, active_backlog - claimed_cases)

        analyst_total = 0
        mem_decisions: dict[str, int] = {}
        durations: list[float] = []

        for adj in self._adjudications:
            adj_org = adj.get("organization_id")
            c_id = adj.get("case_id")
            if adj_org != target_org and c_id not in filtered_case_ids:
                continue
            if cutoff:
                approved_at = adj.get("approved_at") or adj.get("created_at")
                if isinstance(approved_at, datetime) and approved_at < cutoff:
                    continue
            analyst_total += 1
            outcome = adj.get("outcome", "RESOLVE")
            mem_decisions[outcome] = mem_decisions.get(outcome, 0) + 1

            case = self._cases.get(c_id) if c_id else None
            if case and case.get("created_at") and adj.get("approved_at"):
                dur = (adj["approved_at"] - case["created_at"]).total_seconds()
                if dur > 0:
                    durations.append(dur)

        avg_mttr = round(sum(durations) / len(durations), 1) if durations else None
        hitl_ratio = 100.0 if (analyst_total > 0 or total_cases > 0) else None

        return AnalyticsMetricsResponse(
            scope="organization",
            organization_id=organization_id,
            window_days=window_days,
            generated_at=now,
            queue=AnalyticsQueueMetrics(
                total_cases=total_cases,
                active_backlog=active_backlog,
                pending_driver_confirmation=pending_driver,
                claimed_cases=claimed_cases,
                available_unclaimed=available_unclaimed,
                priority_distribution={
                    "P0": p0_count,
                    "P1": p1_count,
                    "P2": p2_count,
                },
            ),
            dispositions=AnalyticsDispositionMetrics(
                driver_confirmed_resolutions=driver_confirmed,
                analyst_adjudications_total=analyst_total,
                analyst_decisions_breakdown=mem_decisions,
                auto_dismissed_count=auto_dismissed,
            ),
            categories=mem_categories,
            performance=AnalyticsPerformanceMetrics(
                average_mttr_seconds=avg_mttr,
                hitl_enforcement_ratio_pct=hitl_ratio,
                reviewer_concordance_pct=None,
            ),
            health=AnalyticsSystemHealth(
                database_healthy=conn is not None,
                worker_status="active",
                environment=self.settings.app_env,
            ),
        )

    async def get_workflow_draft(self, case_id: str, organization_id: str | None = None) -> WorkflowDraftResponse:
        return await asyncio.to_thread(self._workflow_draft_sync, case_id, organization_id)

    async def save_workflow_draft(
        self,
        case_id: str,
        request: WorkflowDraftRequest,
        *,
        analyst_id: str,
        organization_id: str | None = None,
    ) -> WorkflowDraftResponse:
        return await asyncio.to_thread(self._workflow_draft_sync, case_id, organization_id, request, analyst_id)

    def _workflow_draft_sync(
        self,
        case_id: str,
        organization_id: str | None,
        request: WorkflowDraftRequest | None = None,
        analyst_id: str | None = None,
    ) -> WorkflowDraftResponse:
        """Lock the tenant-scoped case so draft and timeline commit together."""
        _require_org_scope(organization_id, allow_unscoped=self._test_stack_unscoped())
        resolved_id = self._resolve_case_id(case_id)
        conn = self._get_db_connection() if self._is_valid_uuid(resolved_id) else None
        try:
            if conn is not None:
                with conn.cursor() as cur:
                    where = "id = %s"
                    params: list[Any] = [resolved_id]
                    if organization_id:
                        where += " AND organization_id = %s"
                        params.append(organization_id)
                    cur.execute(
                        "SELECT id, organization_id, status, assigned_analyst_id, workflow_draft, workflow_trace "
                        f"FROM app.fraud_cases WHERE {where}" + (" FOR UPDATE" if request else ""),
                        tuple(params),
                    )
                    row = cur.fetchone()
                    result, trace = self._prepare_workflow_draft(row, request, analyst_id)
                    if trace is not None:
                        cur.execute(
                            f"UPDATE app.fraud_cases SET workflow_draft = %s::jsonb, "
                            f"workflow_trace = %s::jsonb WHERE {where}",
                            (result.model_dump_json(), json.dumps(trace), *params),
                        )
                conn.commit()
                return result
            self._require_test_fallback()
            row = self._cases.get(resolved_id)
            if row and organization_id and str(row.get("organization_id")) != organization_id:
                row = None
            result, trace = self._prepare_workflow_draft(row, request, analyst_id)
            if trace is not None and row is not None:
                row["workflow_draft"] = result.model_dump(mode="json")
                row["workflow_trace"] = trace
            return result
        except HTTPException:
            if conn is not None:
                conn.rollback()
            raise
        except Exception as exc:
            if conn is not None:
                conn.rollback()
            raise HTTPException(status_code=503, detail="Workflow draft storage unavailable") from exc
        finally:
            if conn is not None:
                conn.close()

    @staticmethod
    def _prepare_workflow_draft(
        row: dict[str, Any] | None,
        request: WorkflowDraftRequest | None,
        analyst_id: str | None,
    ) -> tuple[WorkflowDraftResponse, dict[str, Any] | None]:
        if row is None:
            raise HTTPException(status_code=404, detail="Case not found")
        current = WorkflowDraftResponse.model_validate(row.get("workflow_draft") or {})
        if request is None:
            return current, None
        if row.get("status") in {"resolved", "dismissed", "suspended", "auto_dismissed"}:
            raise HTTPException(status_code=409, detail="Finalized case workflow is read-only")
        assigned = row.get("assigned_analyst_id")
        if assigned and str(assigned) != analyst_id:
            raise HTTPException(status_code=409, detail="Case is assigned to another analyst")
        # Replayed save of the same actor/content must not produce duplicate events.
        if current.text == request.text and current.updated_by == analyst_id:
            return current, None
        if request.expected_version is not None and request.expected_version != current.version:
            raise HTTPException(status_code=409, detail="Workflow draft changed; reload before saving")
        now = datetime.now(UTC)
        saved = WorkflowDraftResponse(
            text=request.text, version=current.version + 1, updated_at=now, updated_by=analyst_id
        )
        trace = dict(row.get("workflow_trace") or {})
        trace["timeline"] = [
            *(trace.get("timeline") or []),
            {
                "event_type": "workflow_draft_saved",
                "occurred_at": now.isoformat(),
                "label": "Analyst saved workflow draft",
            },
        ]
        return saved, trace

    @staticmethod
    def _read_traffic_corroboration(cur: Any, assignment_id: str | None) -> dict[str, Any] | None:
        if not assignment_id:
            return None
        cur.execute(
            """SELECT id, observed_at, valid_until, average_speed_mps, congestion_level,
                      source, is_simulated, provenance
               FROM app.traffic_observations WHERE assignment_id = %s
               ORDER BY is_simulated ASC, observed_at DESC, id DESC LIMIT 1""",
            (assignment_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        speed = row.get("average_speed_mps")
        return {
            **dict(row),
            "id": str(row["id"]),
            "observed_at": row["observed_at"].isoformat()
            if isinstance(row.get("observed_at"), datetime)
            else row.get("observed_at"),
            "valid_until": row["valid_until"].isoformat()
            if isinstance(row.get("valid_until"), datetime)
            else row.get("valid_until"),
            "status": "available" if speed is not None else "unavailable",
            "average_speed_kmh": round(float(speed) * 3.6, 2) if speed is not None else None,
        }

    # 4. Case Detail
    async def get_case_detail(self, case_id: str, organization_id: str | None = None) -> CaseDetailResponse:
        detail = await self._get_case_detail_data(case_id, organization_id)
        if detail.forensic_brief is not None:
            # Case detail is the critical route/GPS paint path. Return the
            # evidence-derived Vietnamese fallback immediately; the dedicated
            # forensic endpoint performs optional LLM narrative enhancement.
            detail.forensic_brief.motivation_assessment = assess_driver_motivation(
                trip=detail.trip,
                features=detail.features,
                telemetry=detail.telemetry_samples,
            )
        return detail

    async def _get_case_detail_data(self, case_id: str, organization_id: str | None = None) -> CaseDetailResponse:
        orig_case_id = case_id
        resolved_id = self._resolve_case_id(case_id)
        conn = self._get_db_connection() if self._is_valid_uuid(resolved_id) else None
        if conn is not None:
            _require_org_scope(organization_id, allow_unscoped=self._test_stack_unscoped())
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    where_clauses = ["c.id = %s"]
                    params: list[Any] = [resolved_id]
                    if organization_id:
                        where_clauses.append("c.organization_id = %s")
                        params.append(organization_id)
                    where_sql = " AND ".join(where_clauses)
                    cur.execute(
                        f"""
                        SELECT c.*,
                               a.trip_id, a.driver_id, a.vehicle_id, a.state as assignment_state,
                               a.cancellation_actor, a.cancellation_reason, a.arrived_at, a.ended_at,
                               t.status as trip_status,
                               t.pickup_address, t.dropoff_address, t.district as trip_district,
                               t.match_type as trip_match_type,
                               t.fare_amount_vnd as direct_fare_vnd,
                               ST_AsGeoJSON(t.pickup)::json as trip_pickup,
                               ST_AsGeoJSON(t.dropoff)::json as trip_dropoff,
                               p_an.display_name as analyst_name,
                               d.external_ref as driver_ref,
                               d.account_status as driver_status,
                               COALESCE(to_jsonb(d)->>'display_name', p_dr.display_name) as driver_name,
                               d.avatar_url as driver_avatar_url,
                               d.rating as driver_rating,
                               d.acceptance_rate as driver_acceptance_rate,
                               d.cancellation_rate as driver_cancellation_rate,
                               d.total_trips as driver_total_trips,
                               d.profile_provenance,
                               v.registration_ref as vehicle_plate,
                               COALESCE(v.model, v.vehicle_type) as vehicle_model,
                               v.vehicle_type,
                               fq.estimated_amount_minor as fare_amount_vnd,
                               fq.currency as fare_quote_currency,
                               ds.statement as driver_statement,
                               pf.statement as passenger_statement
                        FROM app.fraud_cases c
                        LEFT JOIN app.trip_assignments a ON c.assignment_id = a.id
                        LEFT JOIN app.trips t ON a.trip_id = t.id
                        LEFT JOIN app.principals p_an ON c.assigned_analyst_id = p_an.id
                        LEFT JOIN app.drivers d ON a.driver_id = d.id
                        LEFT JOIN app.principals p_dr ON d.principal_id = p_dr.id
                        LEFT JOIN app.vehicles v ON a.vehicle_id = v.id
                        LEFT JOIN LATERAL (SELECT estimated_amount_minor, currency FROM app.fare_quotes WHERE trip_id = t.id ORDER BY version DESC LIMIT 1) fq ON true
                        LEFT JOIN LATERAL (SELECT statement FROM app.driver_submissions WHERE case_id = c.id ORDER BY received_at DESC NULLS LAST LIMIT 1) ds ON true
                        LEFT JOIN LATERAL (SELECT statement FROM app.passenger_feedback WHERE assignment_id = a.id ORDER BY submitted_at DESC LIMIT 1) pf ON true
                        WHERE {where_sql};
                        """,
                        tuple(params),
                    )
                    row = cur.fetchone()
                    if not row:
                        raise HTTPException(status_code=404, detail=f"Case {orig_case_id} not found")

                    asgn_id = row["assignment_id"]

                    cur.execute(
                        """SELECT 'driver' AS role, statement AS text, received_at AS occurred_at
                           FROM app.driver_submissions WHERE case_id = %s AND statement IS NOT NULL
                           UNION ALL
                           SELECT 'customer' AS role, statement AS text, submitted_at AS occurred_at
                           FROM app.passenger_feedback WHERE assignment_id = %s AND statement IS NOT NULL
                           ORDER BY occurred_at NULLS LAST;""",
                        (resolved_id, asgn_id),
                    )
                    conversation = self._build_conversation([dict(entry) for entry in cur.fetchall()])

                    # Telemetry points (P1 issue #100: sensor passthrough from
                    # ingest payload + PostGIS drift against the route corridor)
                    cur.execute(
                        """
                        SELECT tp.event_id, ST_AsGeoJSON(tp.position)::json as position, tp.speed_mps,
                                tp.bearing_deg, tp.accuracy_m as accuracy_m,
                                tp.accuracy_m as gps_accuracy_m,
                                tp.app_state, tp.network_state, tp.gps_state, tp.mock_location_reported,
                                to_jsonb(tp)->>'anomaly_type' as anomaly_type,
                                (to_jsonb(tp)->>'anomaly_score')::double precision as anomaly_score,
                                CASE WHEN e.payload->>'ping_latency_ms' ~ '^[0-9]+(\\.[0-9]+)?$'
                                     THEN (e.payload->>'ping_latency_ms')::double precision END AS ping_latency_ms,
                                CASE WHEN COALESCE(e.payload->>'battery_level_pct', e.payload->>'battery_pct')
                                          ~ '^[0-9]+(\\.[0-9]+)?$'
                                     THEN COALESCE(e.payload->>'battery_level_pct', e.payload->>'battery_pct')::double precision END AS battery_level_pct,
                                (SELECT ROUND(ST_Distance(tp.position, rs.route)::numeric, 1)
                                 FROM app.route_snapshots rs
                                 WHERE rs.assignment_id = tp.assignment_id
                                 ORDER BY rs.calculated_at DESC LIMIT 1) AS drift_distance_m,
                                tp.occurred_at
                        FROM app.telemetry_points tp
                        LEFT JOIN app.ingest_events e ON e.event_id = tp.event_id
                        WHERE tp.assignment_id = %s
                        ORDER BY tp.occurred_at ASC
                        LIMIT 10000;
                        """,
                        (asgn_id,),
                    )
                    telemetry = [dict(tp) for tp in cur.fetchall()]
                    for tp in telemetry:
                        tp["event_id"] = str(tp["event_id"])
                        if isinstance(tp.get("occurred_at"), datetime):
                            tp["occurred_at"] = tp["occurred_at"].isoformat()

                    # Route snapshot
                    cur.execute(
                        """
                        SELECT id, COALESCE(to_jsonb(route_snapshots)->>'leg', 'destination') as leg,
                               provider, ST_AsGeoJSON(route)::json as route, distance_m, duration_s, map_version, provenance
                        FROM app.route_snapshots
                        WHERE assignment_id = %s
                        ORDER BY leg;
                        """,
                        (asgn_id,),
                    )
                    route = _source_backed_route_geometry(cur.fetchall())
                    pickup_coordinates = _valid_coordinate_pair((row.get("trip_pickup") or {}).get("coordinates"))
                    dropoff_coordinates = _valid_coordinate_pair((row.get("trip_dropoff") or {}).get("coordinates"))
                    initial_coordinates = next(
                        (
                            coords
                            for sample in telemetry
                            if isinstance(sample.get("position"), dict)
                            and (coords := _valid_coordinate_pair((sample["position"] or {}).get("coordinates")))
                        ),
                        None,
                    )
                    route = route or {}
                    route_legs = (
                        ("pickup", initial_coordinates, pickup_coordinates),
                        ("destination", pickup_coordinates, dropoff_coordinates),
                    )
                    missing_legs = [
                        (leg, start, end)
                        for leg, start, end in route_legs
                        if f"{leg}_route" not in route and start is not None and end is not None
                    ]
                    fetched = await asyncio.gather(
                        *(asyncio.to_thread(fetch_osrm_route, start, end) for _, start, end in missing_legs)
                    )
                    snapshots_written = False
                    for (leg, _, _), result in zip(missing_legs, fetched, strict=True):
                        if not result:
                            continue
                        route_geometry = result["geometry"]
                        route[f"{leg}_route"] = {
                            "id": None,
                            "provider": result["provider"],
                            "route": route_geometry,
                            "coordinates": route_geometry["coordinates"],
                            "distance_m": result["distance_m"],
                            "duration_s": result["duration_s"],
                            "map_version": "osrm-live",
                            "provenance": result["provenance"],
                            "is_shortest_path": False,
                        }
                        cur.execute(
                            """INSERT INTO app.route_snapshots
                               (id, assignment_id, leg, calculated_at, provider, routing_profile,
                                map_version, route, distance_m, duration_s, provenance)
                               VALUES (%s, %s, %s, now(), 'osrm', 'driving', 'osrm-live',
                                       st_setsrid(st_geomfromgeojson(%s), 4326)::geography,
                                       %s, %s, %s::jsonb)
                               ON CONFLICT (assignment_id, leg) DO UPDATE SET
                                   calculated_at = EXCLUDED.calculated_at,
                                   provider = EXCLUDED.provider,
                                   routing_profile = EXCLUDED.routing_profile,
                                   map_version = EXCLUDED.map_version,
                                   route = EXCLUDED.route,
                                   distance_m = EXCLUDED.distance_m,
                                   duration_s = EXCLUDED.duration_s,
                                   provenance = EXCLUDED.provenance
                               WHERE app.route_snapshots.provider = 'synthetic-straight-line'
                                  AND app.route_snapshots.provenance->>'origin' = 'synthetic'
                                  OR app.route_snapshots.provider = 'osrm-hanoi'
                                  AND app.route_snapshots.provenance->>'origin' = 'osrm'
                                  AND app.route_snapshots.provenance->>'profile' = 'car';""",
                            (
                                str(uuid4()),
                                asgn_id,
                                leg,
                                json.dumps(route_geometry),
                                result["distance_m"],
                                result["duration_s"],
                                json.dumps(result["provenance"]),
                            ),
                        )
                        snapshots_written = True
                    if snapshots_written:
                        conn.commit()
                    route = route or None

                    # Platform incident
                    cur.execute(
                        """
                        SELECT id, incident_type, state, started_at, ended_at, details
                        FROM app.platform_incidents
                        WHERE assignment_id = %s
                        LIMIT 1;
                        """,
                        (asgn_id,),
                    )
                    incident_row = cur.fetchone()
                    incident = dict(incident_row) if incident_row else {}
                    cur.execute(
                        """SELECT EXISTS (
                               SELECT 1 FROM app.traffic_observations traffic
                               WHERE traffic.assignment_id = %s AND traffic.congestion_level = 'heavy'
                           ) AS heavy_congestion;""",
                        (asgn_id,),
                    )
                    traffic_row = cur.fetchone()

                    # Evidence snapshot, features, model assessment
                    cur.execute(
                        """
                        SELECT s.id as snapshot_id, s.version, s.policy_version_id, s.dossier, s.dossier_hash,
                               fs.id as feature_set_id, fs.features, fs.davi, fs.stationary_duration_s,
                               fs.max_gap_s, fs.telemetry_coverage, fs.quality_flags,
                               ma.id as assessment_id, ma.category, ma.confidence, ma.score_semantics, ma.reason_codes, ma.forensic_brief,
                               COALESCE(to_jsonb(ma)->>'recommended_action', ma.raw_response->>'recommended_action') as recommended_action
                        FROM app.evidence_snapshots s
                        LEFT JOIN app.feature_sets fs ON fs.evidence_snapshot_id = s.id
                        LEFT JOIN app.model_assessments ma ON ma.evidence_snapshot_id = s.id
                        WHERE s.case_id = %s
                        ORDER BY s.version DESC, ma.created_at DESC
                        LIMIT 1;
                        """,
                        (resolved_id,),
                    )
                    snap_row = cur.fetchone()

                    features = None
                    assessment = None
                    if snap_row:
                        features = {
                            "id": str(snap_row["feature_set_id"]) if snap_row["feature_set_id"] else None,
                            "davi": snap_row["davi"],
                            "stationary_duration_s": snap_row["stationary_duration_s"],
                            "max_gap_s": snap_row.get("max_gap_s"),
                            "telemetry_coverage": snap_row.get("telemetry_coverage"),
                            "quality_flags": snap_row["quality_flags"],
                            "features": snap_row["features"],
                        }
                        assessment = {
                            "id": str(snap_row["assessment_id"]) if snap_row["assessment_id"] else None,
                            "category": snap_row["category"],
                            "confidence": snap_row["confidence"],
                            "score_semantics": snap_row["score_semantics"],
                            "reason_codes": snap_row["reason_codes"],
                            "forensic_brief": snap_row["forensic_brief"],
                            "recommended_action": snap_row.get("recommended_action"),
                        }

                    # Review lease
                    cur.execute(
                        """
                        SELECT analyst_id, expires_at FROM app.review_leases
                        WHERE case_id = %s AND expires_at > now()
                        LIMIT 1;
                        """,
                        (resolved_id,),
                    )
                    lease_row = cur.fetchone()
                    lease_info = None
                    if lease_row:
                        lease_info = {
                            "analyst_id": str(lease_row["analyst_id"]),
                            "expires_at": lease_row["expires_at"].isoformat()
                            if isinstance(lease_row["expires_at"], datetime)
                            else str(lease_row["expires_at"]),
                        }
                    else:
                        now = datetime.now(UTC)
                        mem_lease = self._active_leases.get(str(resolved_id)) or self._active_leases.get(
                            str(orig_case_id)
                        )
                        if mem_lease and mem_lease["expires_at"] > now:
                            lease_info = {
                                "analyst_id": str(mem_lease["analyst_id"]),
                                "expires_at": mem_lease["expires_at"].isoformat(),
                            }
                        else:
                            r = self.get_redis_client()
                            if r is not None:
                                try:
                                    raw_lock = r.get(f"review_lock:{resolved_id}") or r.get(
                                        f"review_lock:{orig_case_id}"
                                    )
                                    if raw_lock:
                                        lock_data = json.loads(raw_lock)
                                        lease_info = {
                                            "analyst_id": str(lock_data.get("analyst_id", raw_lock)),
                                            "expires_at": lock_data.get("expires_at"),
                                        }
                                except Exception:
                                    pass

                    # Guardrails evaluation
                    blocking_reasons = _blocking_guardrail_reasons(
                        incident_type=incident.get("incident_type"),
                        quality_flags=features.get("quality_flags") if features else [],
                        app_crashed=any(tp.get("app_state") == "crashed" for tp in telemetry),
                        telemetry_unavailable=any(
                            tp.get("gps_state") == "unavailable" or tp.get("network_state") == "offline"
                            for tp in telemetry
                        ),
                        heavy_congestion=bool(traffic_row and traffic_row.get("heavy_congestion")),
                    )
                    is_blocking = bool(blocking_reasons)

                    guardrails = {
                        "blocking_guardrail": is_blocking,
                        "guardrail_type": blocking_reasons[0] if blocking_reasons else "none",
                        "active_guardrails": blocking_reasons,
                        "suggested_outcome": "Disagree (System Error)" if is_blocking else None,
                        "platform_incident": incident or None,
                    }

                    # Query driver past warnings count from sanctions
                    cur.execute(
                        "SELECT count(*) as warnings_count FROM app.sanctions WHERE driver_id = %s;",
                        (row["driver_id"],),
                    )
                    warn_row = cur.fetchone()
                    warnings_count = warn_row["warnings_count"] if warn_row else 0

                    driver_disp_name = row.get("driver_name") or "Nguyễn Văn Hùng"
                    driver_plate = row.get("vehicle_plate") or "29E-123.45"
                    veh_type = row.get("vehicle_model") or row.get("vehicle_type") or "GreenCar (VF e34)"
                    if row.get("direct_fare_vnd") is not None:
                        fare_vnd = int(row["direct_fare_vnd"])
                    elif row.get("fare_amount_vnd") is not None:
                        raw_fare = row["fare_amount_vnd"]
                        fare_vnd = int(raw_fare / 100) if raw_fare > 1_000_000 else int(raw_fare)
                    else:
                        fare_vnd = 85000

                    prov = row.get("profile_provenance") or {}
                    if isinstance(prov, str):
                        try:
                            prov = json.loads(prov)
                        except Exception:
                            prov = {}

                    driver_rating = float(row.get("driver_rating") or prov.get("rating") or 4.85)
                    driver_acc = float(row.get("driver_acceptance_rate") or prov.get("acceptance_rate") or 92.5)
                    driver_cancel = float(row.get("driver_cancellation_rate") or prov.get("cancellation_rate") or 2.1)
                    driver_trips = int(row.get("driver_total_trips") or prov.get("total_trips") or 1250)
                    past_warnings = prov.get("past_warnings", warnings_count)
                    pickup_addr = row.get("pickup_address") or "Hồ Hoàn Kiếm, Tràng Tiền, Hoàn Kiếm"
                    dropoff_addr = row.get("dropoff_address") or "Sân bay Quốc tế Nội Bài, Sóc Sơn"
                    district_name = row.get("trip_district") or "Hoàn Kiếm"
                    driver_avatar = (
                        row.get("driver_avatar_url")
                        or f"https://api.dicebear.com/7.x/bottts/svg?seed={row.get('driver_ref') or driver_disp_name}"
                    )
                    match_type = row.get("trip_match_type") or "auto"

                    trip_dict = {
                        **fare_economics_from_record(
                            row.get("direct_fare_vnd"), row.get("fare_amount_vnd"), row.get("fare_quote_currency")
                        ),
                        "id": str(row["trip_id"]) if row["trip_id"] else None,
                        "status": row["trip_status"] or "completed",
                        "pickup": row["trip_pickup"],
                        "dropoff": row["trip_dropoff"],
                        "pickup_address": pickup_addr,
                        "dropoff_address": dropoff_addr,
                        "district": district_name,
                        "match_type": match_type,
                        "fare_amount_vnd": fare_vnd,
                        "driver_name": driver_disp_name,
                        "driver_avatar_url": driver_avatar,
                        "vehicle_plate": driver_plate,
                        "vehicle_type": veh_type,
                        "driver_status": row.get("driver_status") or "active",
                        "rating": driver_rating,
                        "acceptance_rate": driver_acc,
                        "cancellation_rate": driver_cancel,
                        "total_trips": driver_trips,
                        "past_warnings": past_warnings,
                        "driver_statement": row.get("driver_statement") or "",
                        "passenger_statement": row.get("passenger_statement") or "",
                        "cancellation_reason": row.get("cancellation_reason"),
                        "cancellation_actor": row.get("cancellation_actor"),
                    }

                    now_utc = datetime.now(UTC)
                    sla_due = row.get("sla_due_at")
                    sla_sec = None
                    if sla_due:
                        diff = int((sla_due - now_utc).total_seconds())
                        sla_sec = max(0, diff)

                    tier = row["priority_tier"] if row["priority_tier"] is not None else 2
                    summary = FraudCaseSummary(
                        id=orig_case_id,
                        trip_id=str(row["trip_id"]) if row["trip_id"] else None,
                        assignment_id=str(asgn_id) if asgn_id else None,
                        driver_id=str(row["driver_id"]) if row["driver_id"] else None,
                        status=row["status"] or "ready",
                        priority=f"P{tier}",
                        priority_score=row["priority_score"] or 0,
                        category=row["suspected_category"] or "none",
                        confidence=assessment.get("confidence") if assessment else None,
                        opened_at=row["created_at"],
                        updated_at=row["updated_at"],
                        assigned_analyst_id=str(row["assigned_analyst_id"]) if row["assigned_analyst_id"] else None,
                        version=row["version"] or 1,
                        driver_name=driver_disp_name,
                        vehicle_plate=driver_plate,
                        district=district_name,
                        stall_duration_s=features.get("stationary_duration_s") if features else None,
                        sla_countdown_s=sla_sec,
                        assigned_analyst_name=row.get("analyst_name"),
                        dispute_status=row.get("dispute_status") or "not_disputed",
                        dispute_deadline=row.get("dispute_deadline"),
                    )

                    # Check adjudication
                    cur.execute(
                        """
                        SELECT id, outcome, rationale, analyst_id, approved_at, staged_context
                        FROM app.adjudications
                        WHERE case_id = %s
                        LIMIT 1;
                        """,
                        (resolved_id,),
                    )
                    adj_row = cur.fetchone()
                    adjudication_info = None
                    if adj_row:
                        adjudication_info = {
                            "id": str(adj_row["id"]),
                            "outcome": adj_row["outcome"],
                            "rationale": adj_row["rationale"],
                            "analyst_id": str(adj_row["analyst_id"]),
                            "approved_at": adj_row["approved_at"].isoformat()
                            if isinstance(adj_row["approved_at"], datetime)
                            else str(adj_row["approved_at"]),
                            **(adj_row.get("staged_context") or {}),
                        }
                    # Only source-backed routes and coordinates belong in the workspace.
                    candidate_routes: list[dict[str, Any]] = []
                    cockpit_evidence = row.get("cockpit_evidence") or {}
                    traffic_corroboration = self._read_traffic_corroboration(cur, asgn_id)
                    recorded_end = row.get("ended_at")
                    if isinstance(recorded_end, datetime):
                        recorded_end = recorded_end.isoformat()
                    missingness_alerts = detect_telemetry_missingness(telemetry, end_time=recorded_end)
                    pickup = (row.get("trip_pickup") or {}).get("coordinates")
                    dropoff = (row.get("trip_dropoff") or {}).get("coordinates")
                    timeline_milestones = (
                        build_trip_timeline_milestones(
                            points=telemetry,
                            pickup_pos=pickup,
                            dropoff_pos=dropoff,
                            stall_duration_s=summary.stall_duration_s or 0,
                            alerts=missingness_alerts,
                            arrived_at=(
                                row["arrived_at"].isoformat()
                                if isinstance(row.get("arrived_at"), datetime)
                                else row.get("arrived_at")
                            ),
                            ended_at=(
                                row["ended_at"].isoformat()
                                if isinstance(row.get("ended_at"), datetime)
                                else row.get("ended_at")
                            ),
                            trip_status=row.get("trip_status"),
                            assignment_state=row.get("assignment_state"),
                        )
                        if pickup and dropoff
                        else []
                    )
                    destination = (
                        {"longitude": dropoff[0], "latitude": dropoff[1], "label": dropoff_addr} if dropoff else None
                    )

                    conversation_messages = [
                        ConversationMessage(**msg) if isinstance(msg, dict) else msg for msg in conversation
                    ]

                    forensic_brief = self.build_forensic_brief_from_data(
                        case_id=orig_case_id,
                        trip_id=summary.trip_id,
                        assignment_id=summary.assignment_id,
                        driver_id=summary.driver_id,
                        suspected_category=row.get("suspected_category"),
                        trip=trip_dict,
                        telemetry=telemetry,
                        features=features,
                        guardrails=guardrails,
                        missingness_alerts=missingness_alerts,
                    )
                    if assessment is not None:
                        assessment = {**assessment, "forensic_brief": forensic_brief.summary_text}
                    else:
                        assessment = {
                            "id": None,
                            "category": row.get("suspected_category"),
                            "confidence": None,
                            "score_semantics": None,
                            "reason_codes": [ab.code for ab in forensic_brief.abnormalities],
                            "forensic_brief": forensic_brief.summary_text,
                        }
                    case_policy = self._get_case_policy_sync(orig_case_id, organization_id=organization_id, cur=cur)

                    return CaseDetailResponse(
                        case=summary,
                        cockpit_evidence=cockpit_evidence,
                        workflow_draft=WorkflowDraftResponse.model_validate(row.get("workflow_draft") or {}),
                        conversation=conversation_messages,
                        trip=trip_dict,
                        telemetry_samples=telemetry,
                        features=features,
                        assessment=assessment,
                        forensic_brief=forensic_brief,
                        case_policy=case_policy,
                        route_geometry=route,
                        candidate_routes=candidate_routes,
                        traffic_corroboration=traffic_corroboration,
                        timeline_milestones=timeline_milestones,
                        missingness_alerts=missingness_alerts,
                        destination=destination,
                        guardrails=guardrails,
                        active_lease=lease_info,
                        adjudication=adjudication_info,
                        preliminary_judgment=self._read_preliminary_judgment(cur, resolved_id),
                    )
            except HTTPException:
                raise
            except Exception:
                self._require_test_fallback()
            finally:
                if conn:
                    conn.close()

        self._require_test_fallback()
        # In-memory fallback
        if not self._cases and self.settings.app_env != "production":
            self._load_seed_data()
            resolved_id = self._resolve_case_id(orig_case_id)
        case = self._cases.get(resolved_id) or self._cases.get(orig_case_id)
        if not case and self.settings.app_env != "production":
            try:
                from src.services.test_simulation_runner import get_simulation_runner

                runner = get_simulation_runner()
                sim_case = runner.repository.get_case(orig_case_id) or runner.repository.get_case(resolved_id)
                if not sim_case and orig_case_id.startswith("case-sim-"):
                    sim_case = runner.repository.get_case(orig_case_id.replace("case-sim-", ""))
                if not sim_case and not orig_case_id.startswith("case-sim-"):
                    sim_case = runner.repository.get_case(f"case-sim-{orig_case_id}")
                if sim_case and sim_case.get("run_id"):
                    from src.api.test_routes import publish_simulation_to_production

                    pub = await publish_simulation_to_production(UUID(str(sim_case["run_id"])), x_test_context="true")
                    if pub.case_id is not None:
                        resolved_id = self._resolve_case_id(pub.case_id)
                        case = self._cases.get(resolved_id) or self._cases.get(pub.case_id)
            except Exception:
                pass
        if not case:
            raise HTTPException(status_code=404, detail=f"Case {orig_case_id} not found")

        asgn_id = str(case.get("assignment_id", ""))
        asgn = self._assignments.get(asgn_id, {})
        trip_id = str(asgn.get("trip_id", ""))
        trip = dict(self._trips.get(trip_id, {}))
        recorded_trip_status = trip.get("status")
        driver_id = str(asgn.get("driver_id", ""))
        driver_obj = self._drivers.get(driver_id, {})
        driver_name = driver_obj.get("display_name") or "Nguyễn Văn Hùng"
        trip.setdefault("driver_name", driver_name)
        trip.setdefault("vehicle_plate", "29E-123.45")
        trip.setdefault("vehicle_type", "GreenCar (VF e34)")
        trip.setdefault(
            "driver_avatar_url",
            driver_obj.get("avatar_url") or f"https://api.dicebear.com/7.x/bottts/svg?seed={driver_name}",
        )
        trip.setdefault("rating", float(driver_obj.get("rating", 4.85)))
        trip.setdefault("acceptance_rate", float(driver_obj.get("acceptance_rate", 92.5)))
        trip.setdefault("cancellation_rate", float(driver_obj.get("cancellation_rate", 2.1)))
        trip.setdefault("total_trips", int(driver_obj.get("total_trips", 1250)))
        trip.setdefault("match_type", trip.get("match_type") or "auto")
        trip.setdefault("status", trip.get("status") or asgn.get("state") or "completed")
        trip.setdefault("fare_amount_vnd", trip.get("fare_amount_vnd") or 85000)
        trip.setdefault("pickup_address", trip.get("pickup_address") or "Hồ Hoàn Kiếm, Tràng Tiền, Hoàn Kiếm")
        trip.setdefault("dropoff_address", trip.get("dropoff_address") or "Sân bay Quốc tế Nội Bài, Sóc Sơn")
        trip.setdefault("cancellation_actor", asgn.get("cancellation_actor"))
        trip.setdefault("cancellation_reason", asgn.get("cancellation_reason"))

        telemetry = [tp for tp in self._telemetry_points if str(tp.get("assignment_id")) == asgn_id][:100]
        route = self._route_snapshots.get(asgn_id)

        snapshot = None
        for s in self._evidence_snapshots.values():
            if str(s.get("case_id")) in (str(resolved_id), str(orig_case_id)):
                snapshot = s
                break

        features = None
        assessment = None
        if snapshot:
            snap_id = str(snapshot["id"])
            for fs in self._feature_sets.values():
                if str(fs.get("evidence_snapshot_id")) == snap_id:
                    features = dict(fs)
                    break
            for ma in self._model_assessments.values():
                if str(ma.get("evidence_snapshot_id")) == snap_id:
                    assessment = dict(ma)
                    break

        incident = self._platform_incidents.get(asgn_id, {})

        blocking_reasons = _blocking_guardrail_reasons(
            incident_type=incident.get("incident_type"),
            quality_flags=features.get("quality_flags") if features else [],
            app_crashed=any(point.get("app_state") == "crashed" for point in telemetry),
            telemetry_unavailable=any(
                point.get("gps_state") == "unavailable" or point.get("network_state") == "offline"
                for point in telemetry
            ),
        )
        blocking_reasons.extend(self._recorded_guardrail_reasons(resolved_id, orig_case_id))
        blocking_reasons = list(dict.fromkeys(blocking_reasons))
        is_blocking = bool(blocking_reasons)

        guardrails = {
            "blocking_guardrail": is_blocking,
            "guardrail_type": blocking_reasons[0] if blocking_reasons else "none",
            "active_guardrails": blocking_reasons,
            "suggested_outcome": "Disagree (System Error)" if is_blocking else None,
            "platform_incident": incident or None,
        }

        now = datetime.now(UTC)
        lease_data = self._active_leases.get(str(resolved_id)) or self._active_leases.get(str(orig_case_id))
        lease_info = None
        if lease_data:
            expires_raw = lease_data.get("expires_at")
            if isinstance(expires_raw, datetime) and expires_raw > now:
                lease_info = {
                    "analyst_id": str(lease_data["analyst_id"]),
                    "expires_at": expires_raw.isoformat(),
                }
            elif isinstance(expires_raw, str):
                try:
                    exp_dt = datetime.fromisoformat(expires_raw)
                    if exp_dt > now:
                        lease_info = {
                            "analyst_id": str(lease_data["analyst_id"]),
                            "expires_at": expires_raw,
                        }
                except Exception:
                    pass

        if not lease_info:
            r = self.get_redis_client()
            if r is not None:
                try:
                    raw_lock = r.get(f"review_lock:{resolved_id}") or r.get(f"review_lock:{orig_case_id}")
                    if raw_lock:
                        lock_data = json.loads(raw_lock)
                        exp_val = lock_data.get("expires_at")
                        exp_dt = datetime.fromisoformat(exp_val) if isinstance(exp_val, str) else exp_val
                        if exp_dt and exp_dt > now:
                            lease_info = {
                                "analyst_id": str(lock_data.get("analyst_id", raw_lock)),
                                "expires_at": exp_dt.isoformat() if isinstance(exp_dt, datetime) else str(exp_dt),
                            }
                except Exception:
                    pass

        assigned_id = (lease_info["analyst_id"] if lease_info else None) or (
            str(case.get("assigned_analyst_id")) if case.get("assigned_analyst_id") else None
        )
        assigned_name = None
        if assigned_id:
            if assigned_id in self._analysts:
                assigned_name = self._analysts[assigned_id].get("display_name")
            elif str(assigned_id).lower() in ("tuấn lm", "tuan lm"):
                assigned_name = "Tuấn LM"
            else:
                assigned_name = assigned_id

        case_status = case.get("status", "ready")
        if lease_info and case_status == "ready":
            case_status = "in_review"

        tier = case.get("priority_tier", 2)
        summary = FraudCaseSummary(
            id=orig_case_id,
            trip_id=trip_id or None,
            assignment_id=asgn_id or None,
            driver_id=str(asgn.get("driver_id")) if asgn else None,
            status=case_status,
            priority=f"P{tier}",
            priority_score=case.get("priority_score", 0),
            category=case.get("suspected_category") or "none",
            confidence=assessment.get("confidence") if assessment else None,
            opened_at=case.get("created_at"),
            updated_at=case.get("updated_at"),
            assigned_analyst_id=assigned_id,
            assigned_analyst_name=assigned_name,
            version=case.get("version", 1),
            stall_duration_s=features.get("stationary_duration_s") if features else None,
            dispute_status=case.get("dispute_status", "not_disputed"),
            dispute_deadline=case.get("dispute_deadline"),
        )
        candidate_routes = self._candidate_routes.get(case_id) or []
        traffic_corroboration = self._traffic_corroborations.get(case_id)
        recorded_arrived_at = asgn.get("arrived_at")
        recorded_ended_at = asgn.get("ended_at")
        recorded_end = recorded_ended_at.isoformat() if isinstance(recorded_ended_at, datetime) else recorded_ended_at

        missingness_alerts = self._missingness_alerts.get(case_id) or []
        missingness_alerts = detect_telemetry_missingness(telemetry, end_time=recorded_end)

        timeline_milestones = self._timeline_milestones.get(case_id) or []
        if recorded_arrived_at or recorded_ended_at or not timeline_milestones:
            pickup = (trip.get("pickup") or {}).get("coordinates") if isinstance(trip.get("pickup"), dict) else None
            dropoff = (trip.get("dropoff") or {}).get("coordinates") if isinstance(trip.get("dropoff"), dict) else None
            pickup = _valid_coordinate_pair(pickup)
            dropoff = _valid_coordinate_pair(dropoff)
            timeline_milestones = build_trip_timeline_milestones(
                points=telemetry,
                pickup_pos=pickup,
                dropoff_pos=dropoff,
                stall_duration_s=summary.stall_duration_s or 0,
                alerts=missingness_alerts,
                arrived_at=recorded_arrived_at.isoformat()
                if isinstance(recorded_arrived_at, datetime)
                else recorded_arrived_at,
                ended_at=recorded_end,
                trip_status=recorded_trip_status,
                assignment_state=asgn.get("state"),
            )

        destination = self._destinations.get(case_id)
        dropoff = (trip.get("dropoff") or {}).get("coordinates") if isinstance(trip.get("dropoff"), dict) else None
        dropoff = _valid_coordinate_pair(dropoff)
        if not destination and dropoff:
            destination = {
                "latitude": dropoff[1],
                "longitude": dropoff[0],
                "label": str(trip.get("dropoff_address") or "Destination"),
            }

        forensic_brief = self.build_forensic_brief_from_data(
            case_id=orig_case_id,
            trip_id=summary.trip_id,
            assignment_id=summary.assignment_id,
            driver_id=summary.driver_id,
            suspected_category=case.get("suspected_category"),
            trip=trip,
            telemetry=telemetry,
            features=features,
            guardrails=guardrails,
            missingness_alerts=missingness_alerts,
        )
        if assessment is not None:
            assessment = {**assessment, "forensic_brief": forensic_brief.summary_text}
        else:
            assessment = {
                "id": None,
                "category": case.get("suspected_category"),
                "confidence": None,
                "score_semantics": None,
                "reason_codes": [ab.code for ab in forensic_brief.abnormalities],
                "forensic_brief": forensic_brief.summary_text,
            }
        case_policy = self._get_case_policy_sync(
            orig_case_id,
            organization_id=organization_id,
            allow_db_connect=False,
        )

        return CaseDetailResponse(
            case=summary,
            cockpit_evidence=case.get("cockpit_evidence") or {},
            workflow_draft=WorkflowDraftResponse.model_validate(case.get("workflow_draft") or {}),
            trip=trip,
            telemetry_samples=telemetry,
            features=features,
            assessment=assessment,
            forensic_brief=forensic_brief,
            case_policy=case_policy,
            route_geometry=route,
            candidate_routes=candidate_routes,
            traffic_corroboration=traffic_corroboration,
            timeline_milestones=timeline_milestones,
            missingness_alerts=missingness_alerts,
            destination=destination,
            guardrails=guardrails,
            active_lease=lease_info,
            preliminary_judgment=self._preliminary_judgments.get(resolved_id),
            adjudication=next((a for a in self._adjudications if a["case_id"] == resolved_id), None),
        )

    # 4.1 Forensic Brief Aggregation & Case-Specific Policy Adapters
    @staticmethod
    def build_forensic_brief_from_data(
        *,
        case_id: str,
        trip_id: str | None = None,
        assignment_id: str | None = None,
        driver_id: str | None = None,
        suspected_category: str | None = None,
        trip: dict[str, Any] | None = None,
        telemetry: list[dict[str, Any]] | None = None,
        features: dict[str, Any] | None = None,
        guardrails: dict[str, Any] | None = None,
        missingness_alerts: list[dict[str, Any]] | None = None,
    ) -> ForensicBriefResponse:
        """Deterministically aggregate exact observed abnormalities for a case.

        Strictly factual:
        - Never fabricates or inflates metrics.
        - Never emits a verdict, guilt judgment, or sanction recommendation.
        """
        trip_data = trip or {}
        telemetry_pts = telemetry or []
        feat_data = features or {}
        inner_feats = feat_data.get("features")
        if not isinstance(inner_feats, dict):
            inner_feats = {}
        guardrail_data = guardrails or {}
        alerts = missingness_alerts or []

        abnormalities: list[ForensicAbnormality] = []

        def _safe_float(val: Any) -> float | None:
            if val is None or isinstance(val, bool):
                return None
            try:
                return float(val)
            except (TypeError, ValueError):
                return None

        def _safe_int(val: Any) -> int | None:
            f_val = _safe_float(val)
            return int(f_val) if f_val is not None else None

        # 1. Stationary stall duration
        raw_stall = feat_data.get("stationary_duration_s")
        if raw_stall is None:
            raw_stall = inner_feats.get("stationary_duration_s")
        stationary_duration_s = _safe_int(raw_stall)
        if stationary_duration_s is not None and stationary_duration_s > 0:
            abnormalities.append(
                ForensicAbnormality(
                    code="stationary_stall",
                    category="feature",
                    metric="stationary_duration_s",
                    observed_value=stationary_duration_s,
                    description=f"Thời gian dừng đỗ tĩnh (stationary_duration_s): {stationary_duration_s}s",
                )
            )

        # 2. Directional alignment (DAVI) & pickup distance change
        raw_davi = feat_data.get("davi")
        if raw_davi is None:
            raw_davi = inner_feats.get("davi")
        parsed_davi = _safe_float(raw_davi)
        davi_val = round(parsed_davi, 3) if parsed_davi is not None else None
        dist_start = _safe_float(inner_feats.get("distance_to_pickup_start_m"))
        dist_end = _safe_float(inner_feats.get("distance_to_pickup_end_m"))

        if davi_val is not None and davi_val < 0:
            dist_note = (
                f", khoảng cách tới điểm đón tăng từ {inner_feats.get('distance_to_pickup_start_m')}m lên {inner_feats.get('distance_to_pickup_end_m')}m"
                if dist_start is not None and dist_end is not None and dist_end > dist_start
                else ""
            )
            abnormalities.append(
                ForensicAbnormality(
                    code="negative_davi",
                    category="feature",
                    metric="davi",
                    observed_value=davi_val,
                    description=f"Chỉ số hướng di chuyển DAVI âm ({davi_val}){dist_note}",
                )
            )
        elif davi_val is not None and 0 <= davi_val < 0.3:
            abnormalities.append(
                ForensicAbnormality(
                    code="low_davi",
                    category="feature",
                    metric="davi",
                    observed_value=davi_val,
                    description=f"Chỉ số hướng di chuyển DAVI thấp ({davi_val})",
                )
            )

        # 3. Quality flags & Mock Location detection
        raw_qflags = feat_data.get("quality_flags") or []
        if isinstance(raw_qflags, str):
            try:
                raw_qflags = json.loads(raw_qflags)
            except Exception:
                raw_qflags = [raw_qflags]
        qflag_codes = [
            str(f.get("code") if isinstance(f, dict) else f).strip()
            for f in (raw_qflags if isinstance(raw_qflags, list) else [])
            if f
        ]

        mock_count = sum(
            1
            for tp in telemetry_pts
            if bool(tp.get("mock_location_reported")) or str(tp.get("gps_state") or "").lower() == "mock_reported"
        )
        if mock_count > 0 or "mock_provider_active" in qflag_codes:
            obs_val: Any = mock_count if mock_count > 0 else "mock_provider_active"
            desc = (
                f"Tín hiệu định vị ghi nhận cờ mock_location_reported tại {mock_count}/{len(telemetry_pts)} mẫu telemetry"
                if mock_count > 0
                else "Ghi nhận cờ chất lượng mock_provider_active trong tập đặc trưng"
            )
            abnormalities.append(
                ForensicAbnormality(
                    code="mock_location_reported",
                    category="telemetry",
                    metric="mock_locations_detected",
                    observed_value=obs_val,
                    description=desc,
                )
            )

        # 4. Telemetry gap & coverage
        raw_gap = feat_data.get("max_gap_s")
        if raw_gap is None:
            raw_gap = inner_feats.get("max_gap_s")
        max_gap_s = _safe_int(raw_gap)
        valid_alert_gaps = [_safe_int(a.get("gap_duration_s")) for a in alerts]
        alert_max_gap = max((g for g in valid_alert_gaps if g is not None), default=None)

        if max_gap_s is not None and alert_max_gap is not None:
            effective_gap: int | None = max(max_gap_s, alert_max_gap)
        elif max_gap_s is not None:
            effective_gap = max_gap_s
        elif alert_max_gap is not None:
            effective_gap = alert_max_gap
        else:
            effective_gap = None

        if effective_gap is not None and (effective_gap > 30 or (bool(alerts) and effective_gap > 0)):
            abnormalities.append(
                ForensicAbnormality(
                    code="telemetry_gap",
                    category="telemetry",
                    metric="max_gap_s",
                    observed_value=effective_gap,
                    description=f"Khoảng trống gián đoạn tín hiệu telemetry tối đa (max_gap_s): {effective_gap}s",
                )
            )

        raw_cov = feat_data.get("telemetry_coverage")
        if raw_cov is None:
            raw_cov = inner_feats.get("telemetry_coverage")
        parsed_cov = _safe_float(raw_cov)
        telemetry_coverage = round(parsed_cov, 3) if parsed_cov is not None else None
        if telemetry_coverage is not None and telemetry_coverage < 0.8:
            abnormalities.append(
                ForensicAbnormality(
                    code="low_telemetry_coverage",
                    category="feature",
                    metric="telemetry_coverage",
                    observed_value=telemetry_coverage,
                    description=f"Độ phủ dữ liệu telemetry thấp (telemetry_coverage): {telemetry_coverage * 100:.0f}%",
                )
            )

        # 5. Telemetry device/signal states (app_state, network_state, gps_state, speed_mps)
        crashed_count = sum(1 for tp in telemetry_pts if str(tp.get("app_state") or "").lower() == "crashed")
        offline_count = sum(
            1 for tp in telemetry_pts if str(tp.get("network_state") or "").lower() in ("offline", "degraded")
        )
        gps_unavail_count = sum(1 for tp in telemetry_pts if str(tp.get("gps_state") or "").lower() == "unavailable")
        gps_jitter_count = sum(
            1
            for tp in telemetry_pts
            if str(tp.get("gps_state") or "").lower() == "jitter" or ((_safe_float(tp.get("accuracy_m")) or 0.0) > 50.0)
        )
        high_speeds = [
            spd for tp in telemetry_pts if (spd := _safe_float(tp.get("speed_mps"))) is not None and spd > 33.33
        ]

        if crashed_count > 0 or "app_crashed" in qflag_codes:
            abnormalities.append(
                ForensicAbnormality(
                    code="app_state_crashed",
                    category="telemetry",
                    metric="app_state",
                    observed_value=crashed_count if crashed_count > 0 else "app_crashed",
                    description=(
                        f"Trạng thái ứng dụng bị sập (app_state=crashed) tại {crashed_count}/{len(telemetry_pts)} mẫu telemetry"
                        if crashed_count > 0
                        else "Ghi nhận cờ trạng thái app_crashed"
                    ),
                )
            )
        if offline_count > 0:
            abnormalities.append(
                ForensicAbnormality(
                    code="network_degradation",
                    category="telemetry",
                    metric="network_state",
                    observed_value=offline_count,
                    description=f"Mất kết nối hoặc suy giảm mạng (network_state offline/degraded) tại {offline_count}/{len(telemetry_pts)} mẫu telemetry",
                )
            )
        if gps_unavail_count > 0:
            abnormalities.append(
                ForensicAbnormality(
                    code="gps_unavailable",
                    category="telemetry",
                    metric="gps_state",
                    observed_value=gps_unavail_count,
                    description=f"Mất tín hiệu GPS (gps_state=unavailable) tại {gps_unavail_count}/{len(telemetry_pts)} mẫu telemetry",
                )
            )
        if gps_jitter_count > 0:
            abnormalities.append(
                ForensicAbnormality(
                    code="gps_jitter",
                    category="telemetry",
                    metric="gps_state",
                    observed_value=gps_jitter_count,
                    description=f"Nhiễu tín hiệu định vị (gps_state=jitter hoặc sai số >50m) tại {gps_jitter_count}/{len(telemetry_pts)} mẫu telemetry",
                )
            )
        if high_speeds:
            max_spd = round(max(high_speeds), 2)
            abnormalities.append(
                ForensicAbnormality(
                    code="speed_anomaly",
                    category="telemetry",
                    metric="speed_mps",
                    observed_value=max_spd,
                    description=f"Vận tốc dịch chuyển cao bất thường: tối đa {max_spd} m/s ({round(max_spd * 3.6, 1)} km/h)",
                )
            )

        # 6. Platform incidents & active guardrails
        platform_incident = guardrail_data.get("platform_incident") or {}
        incident_type = platform_incident.get("incident_type") if isinstance(platform_incident, dict) else None
        active_guardrails = list(guardrail_data.get("active_guardrails") or [])
        if incident_type:
            details = platform_incident.get("details") if isinstance(platform_incident, dict) else {}
            exc_detail = (
                f" (chi tiết: {details.get('exception')})"
                if isinstance(details, dict) and details.get("exception")
                else ""
            )
            abnormalities.append(
                ForensicAbnormality(
                    code=f"platform_incident_{incident_type}",
                    category="incident",
                    metric="incident_type",
                    observed_value=incident_type,
                    description=f"Sự cố kỹ thuật nền tảng được ghi nhận: {incident_type}{exc_detail}",
                )
            )
        if "heavy_congestion_detected" in active_guardrails:
            abnormalities.append(
                ForensicAbnormality(
                    code="heavy_congestion_detected",
                    category="guardrail",
                    metric="congestion_level",
                    observed_value="heavy",
                    description="Mật độ giao thông trên lộ trình ở mức ùn tắc nghiêm trọng (heavy_congestion_detected)",
                )
            )

        # 7. Trip cancellation facts
        cancellation_actor = trip_data.get("cancellation_actor")
        cancellation_reason = trip_data.get("cancellation_reason")
        trip_status = str(trip_data.get("status") or "").lower()
        has_cancel_abnormality = bool(
            cancellation_actor
            or trip_status in ("cancelled", "passenger_cancelled", "driver_cancelled", "disputed")
            or (cancellation_reason and cancellation_reason != "Trip completed normally")
        )
        if has_cancel_abnormality:
            actor_part = (
                f"bởi {cancellation_actor}" if cancellation_actor else f"(trạng thái: {trip_status or 'cancelled'})"
            )
            reason_part = (
                f", lý do ghi nhận: '{cancellation_reason}'"
                if cancellation_reason and cancellation_reason != "Trip completed normally"
                else ""
            )
            abnormalities.append(
                ForensicAbnormality(
                    code="trip_cancellation",
                    category="trip",
                    metric="cancellation_actor",
                    observed_value=cancellation_actor or trip_status or "cancelled",
                    description=f"Chuyến xe bị hủy {actor_part}{reason_part}",
                )
            )

        if abnormalities:
            bullet_parts = [f"({idx}) {ab.description}" for idx, ab in enumerate(abnormalities, start=1)]
            summary_text = (
                f"Forensic Brief — Ghi nhận {len(abnormalities)} điểm bất thường thực tế trong hồ sơ: "
                + "; ".join(bullet_parts)
                + "."
            )
        else:
            summary_text = (
                f"Forensic Brief — Không ghi nhận chỉ số bất thường trong dữ liệu hành trình "
                f"({len(telemetry_pts)} mẫu telemetry)."
            )

        return ForensicBriefResponse(
            case_id=str(case_id),
            trip_id=trip_id,
            assignment_id=assignment_id,
            driver_id=driver_id,
            suspected_category=suspected_category,
            abnormalities=abnormalities,
            abnormality_count=len(abnormalities),
            has_abnormalities=bool(abnormalities),
            summary_text=summary_text,
            telemetry_point_count=len(telemetry_pts),
            stationary_duration_s=stationary_duration_s,
            davi=davi_val,
            max_gap_s=effective_gap,
            telemetry_coverage=telemetry_coverage,
            mock_locations_detected=mock_count,
            cancellation_actor=cancellation_actor,
            cancellation_reason=cancellation_reason,
            platform_incident_type=incident_type,
            active_guardrails=active_guardrails,
            motivation_assessment=assess_driver_motivation(trip=trip_data, features=feat_data, telemetry=telemetry_pts),
        )

    async def get_forensic_brief(
        self,
        case_id: str,
        organization_id: str | None = None,
    ) -> ForensicBriefResponse:
        """Retrieve the aggregated factual Forensic Brief for a specific case."""
        detail = await self._get_case_detail_data(case_id, organization_id=organization_id)
        if detail.forensic_brief is not None:
            detail.forensic_brief.motivation_assessment = await generate_motivation_assessment(
                trip=detail.trip,
                features=detail.features,
                telemetry=detail.telemetry_samples,
                evidence_scope=str(detail.case.trip_id or detail.case.id),
                organization_id=organization_id,
            )
            return detail.forensic_brief
        return self.build_forensic_brief_from_data(
            case_id=detail.case.id,
            trip_id=detail.case.trip_id,
            assignment_id=detail.case.assignment_id,
            driver_id=detail.case.driver_id,
            suspected_category=detail.case.category,
            trip=detail.trip,
            telemetry=detail.telemetry_samples,
            features=detail.features,
            guardrails=detail.guardrails,
            missingness_alerts=detail.missingness_alerts,
        )

    def _get_case_policy_sync(
        self,
        case_id: str,
        query: str | None = None,
        organization_id: str | None = None,
        cur: Any = None,
        allow_db_connect: bool = True,
    ) -> CasePolicyResponse:
        """Synchronously retrieve policy version, action matrix, and clauses for a specific case."""
        orig_case_id = str(case_id).strip()
        resolved_id = self._resolve_case_id(orig_case_id)

        suspected_category: str | None = None
        policy_version_id: str | None = None
        policy_version: str | None = None
        policy_status: str | None = None
        effective_from: str | None = None
        action_matrix: dict[str, Any] = {}
        raw_chunks: list[dict[str, Any]] = []
        related_policies: list[dict[str, Any]] = []
        found_case = False

        def _fetch_from_cursor(db_cur: Any) -> None:
            nonlocal suspected_category, policy_version_id, policy_version, policy_status
            nonlocal effective_from, action_matrix, raw_chunks, related_policies, found_case
            _require_org_scope(organization_id, allow_unscoped=self._test_stack_unscoped())
            db_cur.execute("SET search_path = app, extensions, public;")
            where_sql = "c.id = %s"
            params: list[Any] = [resolved_id]
            if organization_id:
                where_sql += " AND c.organization_id = %s"
                params.append(organization_id)
            db_cur.execute(
                f"""
                SELECT c.id, c.suspected_category, to_jsonb(c)->'workflow_trace' as workflow_trace,
                       COALESCE(es.policy_version_id, pv_fb.id) as policy_version_id,
                       COALESCE(pv.version, pv_fb.version) as policy_version,
                       COALESCE(pv.status, pv_fb.status) as policy_status,
                       COALESCE(pv.effective_from, pv_fb.effective_from) as effective_from,
                       COALESCE(pv.action_matrix, pv_fb.action_matrix) as action_matrix
                FROM app.fraud_cases c
                LEFT JOIN LATERAL (
                    SELECT id, policy_version_id
                    FROM app.evidence_snapshots
                    WHERE case_id = c.id
                    ORDER BY version DESC
                    LIMIT 1
                ) es ON true
                LEFT JOIN app.policy_versions pv ON pv.id = es.policy_version_id
                LEFT JOIN LATERAL (
                    SELECT id, version, status, effective_from, action_matrix
                    FROM app.policy_versions
                    ORDER BY effective_from DESC NULLS LAST
                    LIMIT 1
                ) pv_fb ON pv.id IS NULL
                WHERE {where_sql}
                LIMIT 1;
                """,
                tuple(params),
            )
            row = db_cur.fetchone()
            if not row:
                return
            found_case = True
            suspected_category = row.get("suspected_category")
            if row.get("policy_version_id"):
                policy_version_id = str(row["policy_version_id"])
            policy_version = row.get("policy_version")
            policy_status = row.get("policy_status")
            eff = row.get("effective_from")
            effective_from = eff.isoformat() if hasattr(eff, "isoformat") else (str(eff) if eff else None)
            am = row.get("action_matrix")
            if isinstance(am, str):
                try:
                    am = json.loads(am)
                except Exception:
                    am = {}
            if isinstance(am, dict):
                action_matrix = am

            wt = row.get("workflow_trace")
            if isinstance(wt, str):
                try:
                    wt = json.loads(wt)
                except Exception:
                    wt = None
            if isinstance(wt, dict) and isinstance(wt.get("related_policies"), list):
                related_policies = list(wt["related_policies"])

            if policy_version_id:
                db_cur.execute(
                    """
                    SELECT id, source_ref, section_ref, content
                    FROM app.policy_chunks
                    WHERE policy_version_id = %s
                    ORDER BY section_ref ASC NULLS LAST;
                    """,
                    (policy_version_id,),
                )
                raw_chunks = [dict(r) for r in db_cur.fetchall()]
            if not raw_chunks:
                db_cur.execute(
                    """
                    SELECT id, source_ref, section_ref, content
                    FROM app.policy_chunks
                    ORDER BY section_ref ASC NULLS LAST
                    LIMIT 20;
                    """
                )
                raw_chunks = [dict(r) for r in db_cur.fetchall()]

        if cur is not None and self._is_valid_uuid(resolved_id):
            try:
                _fetch_from_cursor(cur)
            except Exception as exc:
                logger.debug("Cursor policy fetch failed for %s: %s", orig_case_id, exc)
        elif allow_db_connect and self._is_valid_uuid(resolved_id):
            conn = None
            try:
                conn = self._get_db_connection()
            except HTTPException:
                conn = None
            if conn is not None:
                try:
                    with conn.cursor() as db_cur:
                        _fetch_from_cursor(db_cur)
                except Exception as exc:
                    logger.debug("Database policy fetch failed for %s: %s", orig_case_id, exc)
                finally:
                    conn.close()

        if not found_case:
            case_mem = self._cases.get(resolved_id) or self._cases.get(orig_case_id)
            if not case_mem and self.settings.app_env != "production" and not self._cases:
                self._load_seed_data()
                resolved_id = self._resolve_case_id(orig_case_id)
                case_mem = self._cases.get(resolved_id) or self._cases.get(orig_case_id)
            if not case_mem:
                raise HTTPException(status_code=404, detail=f"Case {orig_case_id} not found")
            found_case = True
            suspected_category = case_mem.get("suspected_category") or case_mem.get("category")
            wt_mem = case_mem.get("workflow_trace")
            if isinstance(wt_mem, dict) and isinstance(wt_mem.get("related_policies"), list):
                related_policies = list(wt_mem["related_policies"])
            for s in self._evidence_snapshots.values():
                if str(s.get("case_id")) in (str(resolved_id), str(orig_case_id)):
                    if s.get("policy_version_id"):
                        policy_version_id = str(s["policy_version_id"])
                    break

        if not action_matrix or not policy_version:
            seed_pv = self._raw_seed.get("policy_version") or {}
            if seed_pv:
                policy_version_id = policy_version_id or str(seed_pv.get("id") or "")
                policy_version = policy_version or seed_pv.get("version")
                policy_status = policy_status or seed_pv.get("status")
                effective_from = effective_from or seed_pv.get("effective_from")
                if isinstance(seed_pv.get("action_matrix"), dict) and not action_matrix:
                    action_matrix = dict(seed_pv["action_matrix"])

        if not raw_chunks and self._policy_chunks:
            if policy_version_id:
                raw_chunks = [
                    dict(pc) for pc in self._policy_chunks if str(pc.get("policy_version_id")) == policy_version_id
                ]
            if not raw_chunks:
                raw_chunks = [dict(pc) for pc in self._policy_chunks]

        if not raw_chunks:
            raw_chunks = [
                {
                    "id": "chunk-canonical-14.2",
                    "source_ref": "Quy chế Hợp tác Kinh doanh GreenSM 2026",
                    "section_ref": "Điều 14.2",
                    "content": "Điều 14.2 - Hành vi Cố tình Dừng cuốc để Khách hủy (Driver Induced Cancellation - DIC): Tài xế cố tình dừng yên hoặc di chuyển ngược hướng đón khách từ 180 giây trở lên nhằm ép khách hàng hủy chuyến. Mức chế tài: cảnh cáo lần đầu, phạt 200.000 VNĐ nếu tái phạm.",
                },
                {
                    "id": "chunk-canonical-15.1",
                    "source_ref": "Quy chế Hợp tác Kinh doanh GreenSM 2026",
                    "section_ref": "Điều 15.1",
                    "content": "Điều 15.1 - Gian lận GPS và Công cụ Giả lập vị trí (Fake GPS / Mock Location): Sử dụng ứng dụng mock location hoặc can thiệp phần cứng/phần mềm để truyền tọa độ giả lập lên hệ thống nền tảng GreenSM. Mức chế tài: đình chỉ tài khoản 7 ngày hoặc chấm dứt hợp tác.",
                },
                {
                    "id": "chunk-canonical-14.1",
                    "source_ref": "Quy chế Hợp tác Kinh doanh GreenSM 2026",
                    "section_ref": "Điều 14.1",
                    "content": "Điều 14.1 - Kéo dài lộ trình và gian lận khoảng cách (Fare Inflation / Detour): Cố tình đi đường vòng bất thường làm tăng giá cước so với lộ trình đề xuất khi không có sự đồng ý của khách hoặc không có yếu tố giao thông bất khả kháng.",
                },
                {
                    "id": "chunk-canonical-12.2",
                    "source_ref": "Quy chế Hợp tác Kinh doanh GreenSM 2026",
                    "section_ref": "Điều 12.2",
                    "content": "Điều 12.2 - Miễn trừ trách nhiệm do Yếu tố Ngoại cảnh và Bất khả kháng: Sự cố mất kết nối mạng viễn thông diện rộng, thời tiết mưa bão ngập lụt cực đoan, ùn tắc giao thông nghiêm trọng (vận tốc < 5 km/h được xác nhận bởi hệ thống quan trắc giao thông) được áp dụng làm căn cứ miễn trừ xử phạt cho tài xế.",
                },
            ]

        # Rank clauses matching suspected_category or query first
        cat_norm = (suspected_category or "").strip().upper()
        q_terms = [t for t in (query or "").lower().split() if len(t) > 2]

        def _chunk_priority(chunk: dict[str, Any]) -> tuple[int, str]:
            text_blob = f"{chunk.get('section_ref') or ''} {chunk.get('content') or ''}".lower()
            score = 0
            if cat_norm and cat_norm.lower() in text_blob:
                score += 10
            if q_terms:
                score += sum(2 for term in q_terms if term in text_blob)
            return (-score, str(chunk.get("section_ref") or ""))

        sorted_chunks = sorted(raw_chunks, key=_chunk_priority)
        clauses: list[CasePolicyClause] = [
            CasePolicyClause(
                id=str(c.get("id") or f"chunk-{idx}"),
                source_ref=str(c.get("source_ref") or "Quy chế Hợp tác Kinh doanh GreenSM 2026"),
                section_ref=c.get("section_ref"),
                content=str(c.get("content") or ""),
                category="case_policy",
            )
            for idx, c in enumerate(sorted_chunks, start=1)
        ]

        if not related_policies:
            try:
                from src.services.jev_precedent_service import get_jev_precedent_service

                trace = get_jev_precedent_service().get_workflow_trace(resolved_id)
                if trace and trace.related_policies:
                    related_policies = [p.model_dump(mode="json") for p in trace.related_policies]
            except Exception:
                pass

        applicable_rule = (
            action_matrix.get(cat_norm) if cat_norm and isinstance(action_matrix.get(cat_norm), dict) else None
        )

        return CasePolicyResponse(
            case_id=orig_case_id,
            suspected_category=suspected_category,
            policy_version_id=policy_version_id,
            policy_version=policy_version,
            policy_status=policy_status,
            effective_from=effective_from,
            action_matrix=action_matrix,
            applicable_action_rule=applicable_rule,
            clauses=clauses,
            related_policies=related_policies,
        )

    async def get_case_policy(
        self,
        case_id: str,
        query: str | None = None,
        organization_id: str | None = None,
    ) -> CasePolicyResponse:
        """Async wrapper to retrieve case-specific policy data (version, action_matrix, clauses, Qdrant store)."""
        policy_resp = await asyncio.to_thread(
            self._get_case_policy_sync,
            case_id,
            query=query,
            organization_id=organization_id,
        )
        # Enrich with Qdrant policy store clauses if query or suspected_category is present
        search_q = " ".join(filter(None, [policy_resp.suspected_category, query])).strip()
        if search_q:
            if not organization_id and not self._test_stack_unscoped():
                # S4-TENANT #294 P1a: Qdrant enrichment without org scope would
                # mix tenants, so fail closed instead of searching unfiltered.
                logger.warning("Optional Qdrant enrichment skipped: organization scope required")
            else:
                try:
                    from src.rag.store import QdrantPolicyStore

                    store = QdrantPolicyStore()
                    org_filter = {"organization_id": str(organization_id)} if organization_id else None
                    store_chunks = await asyncio.to_thread(store.search, search_q, 4, org_filter)
                    existing_ids = {c.id for c in policy_resp.clauses}
                    for sc in store_chunks:
                        cid = str(sc.get("id") or "")
                        content = str(sc.get("content") or "").strip()
                        if not content or cid in existing_ids:
                            continue
                        meta = sc.get("metadata") or {}
                        # Defensive post-filter: never attach a foreign-org chunk.
                        if (
                            organization_id
                            and meta.get("organization_id")
                            and str(meta.get("organization_id")) != str(organization_id)
                        ):
                            continue
                        policy_resp.clauses.append(
                            CasePolicyClause(
                                id=cid or f"qdrant-{len(policy_resp.clauses) + 1}",
                                source_ref=str(meta.get("title") or "Quy định GreenSM"),
                                section_ref=cid or None,
                                content=content,
                                category=str(meta.get("category") or "general"),
                                source_url=str(meta.get("source_url") or ""),
                            )
                        )
                        existing_ids.add(cid)
                except Exception as exc:
                    logger.debug("Optional Qdrant enrichment in get_case_policy skipped: %s", exc)
        return policy_resp

    # 5. Case Lease Claim
    async def claim_case_lease(
        self, case_id: str, req: ClaimCaseRequest, organization_id: str | None = None
    ) -> ClaimCaseResponse:
        orig_case_id = case_id
        resolved_id = self._resolve_case_id(case_id)
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=req.lease_duration_seconds)
        user_role = self.get_principal_role(req.analyst_id, req.role)

        # Enforce role permission: only analyst, senior_analyst, or admin can claim
        if user_role not in self.AUTHORIZED_REVIEW_ROLES:
            raise HTTPException(
                status_code=403,
                detail=f"Principal '{req.analyst_id}' with role '{user_role}' is not authorized to claim review cases. Required role: analyst, senior_analyst, or admin.",
            )

        # 1. Redis Review Lock Check
        lock_key = f"review_lock:{resolved_id}"
        r = self.get_redis_client()
        if r is not None:
            try:
                raw_lock = r.get(lock_key)
                if raw_lock:
                    try:
                        lock_data = json.loads(raw_lock)
                        holder_id = str(lock_data.get("analyst_id", raw_lock))
                    except Exception:
                        holder_id = str(raw_lock)

                    if holder_id != str(req.analyst_id):
                        if not (user_role == "admin" and req.force):
                            raise HTTPException(
                                status_code=409,
                                detail=f"Case {orig_case_id} is currently claimed by analyst {holder_id}",
                            )

                lock_payload = json.dumps(
                    {
                        "case_id": resolved_id,
                        "analyst_id": str(req.analyst_id),
                        "role": user_role,
                        "acquired_at": now.isoformat(),
                        "expires_at": expires_at.isoformat(),
                    }
                )
                r.set(lock_key, lock_payload, ex=req.lease_duration_seconds)
                if orig_case_id != resolved_id:
                    r.set(f"review_lock:{orig_case_id}", lock_payload, ex=req.lease_duration_seconds)
            except HTTPException:
                raise
            except Exception as e:
                logger.debug("Redis review lock error: %s", e)

        # 2. Database Review Lease (if DB connected and UUID valid)
        conn = self._get_db_connection() if self._is_valid_uuid(resolved_id) else None
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    # S4-TENANT #294 P0: persisted lease writes require server org scope.
                    _require_org_scope(organization_id, allow_unscoped=self._test_stack_unscoped())
                    # Lock the case row for the duration of this transaction
                    case_query = "SELECT id, version, status, assignment_id FROM app.fraud_cases WHERE id = %s"
                    case_params: list[Any] = [resolved_id]
                    if organization_id:
                        case_query += " AND organization_id = %s"
                        case_params.append(organization_id)
                    case_query += " FOR UPDATE;"
                    cur.execute(case_query, tuple(case_params))
                    case_row = cur.fetchone()
                    if not case_row:
                        raise HTTPException(status_code=404, detail=f"Case {orig_case_id} not found")

                    # Check existing active lease inside the same locked transaction
                    cur.execute(
                        """
                        SELECT l.analyst_id, l.expires_at, p.external_subject, p.display_name
                        FROM app.review_leases l
                        LEFT JOIN app.principals p ON l.analyst_id = p.id
                        WHERE l.case_id = %s;
                        """,
                        (resolved_id,),
                    )
                    existing_lease = cur.fetchone()
                    if existing_lease and existing_lease["expires_at"] > now:
                        holder_id = str(existing_lease["analyst_id"])
                        holder_ext = str(existing_lease.get("external_subject") or "")
                        is_holder = (
                            holder_id == str(req.analyst_id)
                            or (holder_ext and holder_ext == str(req.analyst_id))
                            or self._analyst_matches(holder_id, req.analyst_id)
                            or (holder_ext and self._analyst_matches(holder_ext, req.analyst_id))
                        )
                        if not is_holder:
                            if not (user_role == "admin" and req.force):
                                holder_label = existing_lease.get("display_name") or holder_ext or holder_id
                                raise HTTPException(
                                    status_code=409,
                                    detail=f"Case {orig_case_id} is currently claimed by analyst {holder_label}",
                                )

                    # Get evidence snapshot id
                    cur.execute(
                        "SELECT id FROM app.evidence_snapshots WHERE case_id = %s LIMIT 1;",
                        (resolved_id,),
                    )
                    snap = cur.fetchone()
                    snap_id = snap["id"] if snap else "018f2f4e-0300-7000-8000-000000000001"

                    # Verify analyst principal exists, or link default principal
                    analyst_uuid = None
                    if self._is_valid_uuid(req.analyst_id):
                        cur.execute("SELECT id FROM app.principals WHERE id = %s;", (req.analyst_id,))
                        p_row = cur.fetchone()
                        if p_row:
                            analyst_uuid = str(p_row["id"])
                    if not analyst_uuid:
                        cur.execute(
                            "SELECT id FROM app.principals WHERE external_subject = %s;", (str(req.analyst_id),)
                        )
                        p_row = cur.fetchone()
                        if p_row:
                            analyst_uuid = str(p_row["id"])
                    if not analyst_uuid:
                        cur.execute("SELECT id FROM app.principals LIMIT 1;")
                        p = cur.fetchone()
                        if p:
                            analyst_uuid = str(p["id"])
                        elif self._is_valid_uuid(req.analyst_id):
                            analyst_uuid = str(req.analyst_id)
                        else:
                            analyst_uuid = "018f2f4e-0100-7000-8000-000000000001"

                    token_hash = hashlib.sha256(f"{resolved_id}:{req.analyst_id}:{now}".encode()).digest()
                    cur.execute(
                        """
                        INSERT INTO app.review_leases (
                            case_id, analyst_id, token_hash, case_version, evidence_snapshot_id, acquired_at, expires_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (case_id) DO UPDATE SET
                            analyst_id = EXCLUDED.analyst_id,
                            token_hash = EXCLUDED.token_hash,
                            case_version = EXCLUDED.case_version,
                            acquired_at = EXCLUDED.acquired_at,
                            expires_at = EXCLUDED.expires_at;
                        """,
                        (resolved_id, analyst_uuid, token_hash, case_row["version"], snap_id, now, expires_at),
                    )

                    new_status = "in_review" if case_row["status"] == "ready" else case_row["status"]
                    update_query = """
                        UPDATE app.fraud_cases
                        SET assigned_analyst_id = %s, status = %s, updated_at = %s
                        WHERE id = %s
                        """
                    update_params: list[Any] = [analyst_uuid, new_status, now, resolved_id]
                    if organization_id:
                        update_query += " AND organization_id = %s;"
                        update_params.append(organization_id)
                    else:
                        update_query += ";"
                    cur.execute(update_query, tuple(update_params))
                    conn.commit()

                    lease_entry = {
                        "analyst_id": str(req.analyst_id),
                        "role": user_role,
                        "expires_at": expires_at,
                    }
                    self._active_leases[str(resolved_id)] = lease_entry
                    self._active_leases[str(orig_case_id)] = lease_entry

                    return ClaimCaseResponse(
                        case_id=orig_case_id,
                        analyst_id=req.analyst_id,
                        lease_expires_at=expires_at,
                        status="claimed",
                    )
            except HTTPException:
                raise
            except Exception:
                if conn:
                    conn.rollback()
                self._require_test_fallback()
            finally:
                if conn:
                    conn.close()

        # 3. In-memory fallback
        case = self._cases.get(resolved_id) or self._cases.get(orig_case_id)
        if not case:
            raise HTTPException(status_code=404, detail=f"Case {orig_case_id} not found")
        # S4-TENANT #294 P0: same-org check on the seed fallback path.
        if organization_id and str(case.get("organization_id", organization_id)) != str(organization_id):
            raise HTTPException(status_code=404, detail=f"Case {orig_case_id} not found")

        existing_lease = self._active_leases.get(resolved_id) or self._active_leases.get(orig_case_id)
        if existing_lease and existing_lease["expires_at"] > now:
            if str(existing_lease["analyst_id"]) != str(req.analyst_id):
                if not (user_role == "admin" and req.force):
                    raise HTTPException(
                        status_code=409,
                        detail=f"Case {orig_case_id} is currently claimed by analyst {existing_lease['analyst_id']}",
                    )

        lease_entry = {
            "analyst_id": str(req.analyst_id),
            "role": user_role,
            "expires_at": expires_at,
        }
        self._active_leases[resolved_id] = lease_entry
        self._active_leases[orig_case_id] = lease_entry
        case["assigned_analyst_id"] = req.analyst_id
        if case.get("status") == "ready":
            case["status"] = "in_review"
        case["updated_at"] = now.isoformat()
        self._sync_case_dict(resolved_id)

        return ClaimCaseResponse(
            case_id=orig_case_id,
            analyst_id=req.analyst_id,
            lease_expires_at=expires_at,
            status="claimed",
        )

    # 5.1 Case Lease Release
    async def release_case_lease(
        self, case_id: str, req: ReleaseCaseRequest, organization_id: str | None = None
    ) -> ReleaseCaseResponse:
        orig_case_id = case_id
        resolved_id = self._resolve_case_id(case_id)
        now = datetime.now(UTC)
        user_role = self.get_principal_role(req.analyst_id, req.role)

        if user_role not in self.AUTHORIZED_REVIEW_ROLES:
            raise HTTPException(
                status_code=403,
                detail=f"Principal '{req.analyst_id}' with role '{user_role}' is not authorized to release review cases. Required role: analyst, senior_analyst, or admin.",
            )

        lock_key = f"review_lock:{resolved_id}"
        r = self.get_redis_client()
        lock_holder: str | None = None

        # Check Redis
        if r is not None:
            try:
                raw_lock = r.get(lock_key) or r.get(f"review_lock:{orig_case_id}")
                if raw_lock:
                    try:
                        lock_holder = str(json.loads(raw_lock).get("analyst_id", raw_lock))
                    except Exception:
                        lock_holder = str(raw_lock)
            except Exception:
                pass

        # Check in-memory
        if not lock_holder:
            existing_lease = self._active_leases.get(resolved_id) or self._active_leases.get(orig_case_id)
            if existing_lease and existing_lease.get("expires_at") and existing_lease["expires_at"] > now:
                lock_holder = str(existing_lease["analyst_id"])

        # Check DB
        conn = self._get_db_connection() if self._is_valid_uuid(resolved_id) else None
        if conn is not None and not lock_holder:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    cur.execute(
                        """
                        SELECT l.analyst_id, l.expires_at, p.external_subject, p.display_name
                        FROM app.review_leases l
                        LEFT JOIN app.principals p ON l.analyst_id = p.id
                        WHERE l.case_id = %s;
                        """,
                        (resolved_id,),
                    )
                    row = cur.fetchone()
                    if row and row["expires_at"] > now:
                        holder_uuid = str(row["analyst_id"])
                        holder_ext = str(row.get("external_subject") or "")
                        is_holder = (
                            holder_uuid == str(req.analyst_id)
                            or (holder_ext and holder_ext == str(req.analyst_id))
                            or self._analyst_matches(holder_uuid, req.analyst_id)
                            or (holder_ext and self._analyst_matches(holder_ext, req.analyst_id))
                        )
                        if is_holder:
                            lock_holder = str(req.analyst_id)
                        else:
                            lock_holder = row.get("display_name") or holder_ext or holder_uuid
            except Exception:
                pass
            finally:
                conn.close()

        # Ownership validation: only holder or admin can release
        if (
            lock_holder
            and lock_holder != str(req.analyst_id)
            and not self._analyst_matches(lock_holder, req.analyst_id)
        ):
            if user_role != "admin" and not req.force:
                raise HTTPException(
                    status_code=403,
                    detail=f"Permission denied: Case {orig_case_id} is currently claimed by analyst {lock_holder}. Only the lock owner or an administrator can release this review lock.",
                )

        # 1. Release in Redis
        if r is not None:
            try:
                r.delete(lock_key)
                r.delete(f"review_lock:{orig_case_id}")
            except Exception:
                pass

        # 2. Release in DB
        if self._is_valid_uuid(resolved_id):
            conn = self._get_db_connection()
            if conn is not None:
                try:
                    with conn.cursor() as cur:
                        cur.execute("SET search_path = app, extensions, public;")
                        # S4-TENANT #294 P0: persisted release writes require server org scope.
                        _require_org_scope(organization_id, allow_unscoped=self._test_stack_unscoped())
                        cur.execute("DELETE FROM app.review_leases WHERE case_id = %s;", (resolved_id,))
                        release_query = """
                            UPDATE app.fraud_cases
                            SET status = 'ready', assigned_analyst_id = NULL, updated_at = %s
                            WHERE id = %s AND status = 'in_review'
                            """
                        release_params: list[Any] = [now, resolved_id]
                        if organization_id:
                            release_query += " AND organization_id = %s;"
                            release_params.append(organization_id)
                        else:
                            release_query += ";"
                        cur.execute(release_query, tuple(release_params))
                    conn.commit()
                except Exception:
                    if conn:
                        conn.rollback()
                finally:
                    if conn:
                        conn.close()

        # 3. Release in-memory
        self._active_leases.pop(resolved_id, None)
        self._active_leases.pop(orig_case_id, None)
        for alias, target in self._case_aliases.items():
            if target == resolved_id:
                self._active_leases.pop(alias, None)

        for cid in (resolved_id, orig_case_id):
            if cid in self._cases:
                c = self._cases[cid]
                if c.get("status") == "in_review":
                    c["status"] = "ready"
                c["assigned_analyst_id"] = None
                c["updated_at"] = now.isoformat()
        self._sync_case_dict(resolved_id)

        return ReleaseCaseResponse(
            case_id=orig_case_id,
            analyst_id=req.analyst_id,
            status="released",
            released_at=now,
        )

    # 6. Case Non-terminal Actions
    async def record_case_action(
        self, case_id: str, req: CaseActionRequest, organization_id: str | None = None
    ) -> CaseActionResponse:
        orig_case_id = case_id
        resolved_id = self._resolve_case_id(case_id)
        now = datetime.now(UTC)
        if req.action_type != "REQUEST_EVIDENCE":
            raise HTTPException(status_code=400, detail="Only REQUEST_EVIDENCE is available in the v1 workspace.")
        user_role = self.get_principal_role(req.analyst_id)
        if user_role not in self.AUTHORIZED_REVIEW_ROLES:
            raise HTTPException(
                status_code=403,
                detail=f"Principal '{req.analyst_id}' with role '{user_role}' is not authorized to record case actions.",
            )

        status_map = {
            "REQUEST_EVIDENCE": "evidence_requested",
            "ESCALATE": "escalated",
            "DEFER": "in_review",
        }
        action_code_map = {
            "REQUEST_EVIDENCE": "request_evidence",
            "ESCALATE": "escalate",
            "DEFER": "defer",
        }
        new_status = status_map[req.action_type]
        action_code = action_code_map[req.action_type]

        conn = self._get_db_connection() if self._is_valid_uuid(resolved_id) else None
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    # S4-TENANT #294 P0: persisted action writes require server org scope.
                    _require_org_scope(organization_id, allow_unscoped=self._test_stack_unscoped())
                    action_case_query = "SELECT id FROM app.fraud_cases WHERE id = %s"
                    action_case_params: list[Any] = [resolved_id]
                    if organization_id:
                        action_case_query += " AND organization_id = %s"
                        action_case_params.append(organization_id)
                    action_case_query += ";"
                    cur.execute(action_case_query, tuple(action_case_params))
                    if not cur.fetchone():
                        raise HTTPException(status_code=404, detail=f"Case {orig_case_id} not found")

                    # Get evidence snapshot
                    cur.execute("SELECT id FROM app.evidence_snapshots WHERE case_id = %s LIMIT 1;", (resolved_id,))
                    snap = cur.fetchone()
                    snap_id = snap["id"] if snap else "018f2f4e-0300-7000-8000-000000000001"

                    # Verify analyst id
                    analyst_uuid = req.analyst_id
                    try:
                        cur.execute("SELECT id FROM app.principals WHERE id = %s;", (analyst_uuid,))
                        if not cur.fetchone():
                            cur.execute("SELECT id FROM app.principals LIMIT 1;")
                            p = cur.fetchone()
                            if p:
                                analyst_uuid = str(p["id"])
                    except Exception:
                        pass

                    cur.execute(
                        """
                        INSERT INTO app.review_actions (
                            case_id, evidence_snapshot_id, actor_id, action, comment, idempotency_key, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s);
                        """,
                        (resolved_id, snap_id, analyst_uuid, action_code, req.notes or "Review action", uuid4(), now),
                    )

                    action_update_query = """
                        UPDATE app.fraud_cases
                        SET status = %s, updated_at = %s
                        WHERE id = %s
                        """
                    action_update_params: list[Any] = [new_status, now, resolved_id]
                    if organization_id:
                        action_update_query += " AND organization_id = %s;"
                        action_update_params.append(organization_id)
                    else:
                        action_update_query += ";"
                    cur.execute(action_update_query, tuple(action_update_params))
                    conn.commit()
            except HTTPException:
                raise
            except Exception:
                if conn:
                    conn.rollback()
                self._require_test_fallback()
            finally:
                if conn:
                    conn.close()

        # Update in-memory state
        for cid in (resolved_id, orig_case_id):
            if cid in self._cases:
                # S4-TENANT #294 P0: same-org check on the seed fallback path.
                if organization_id and str(self._cases[cid].get("organization_id", organization_id)) != str(
                    organization_id
                ):
                    raise HTTPException(status_code=404, detail=f"Case {orig_case_id} not found")
                self._cases[cid]["status"] = new_status
                self._cases[cid]["updated_at"] = now.isoformat()

        return CaseActionResponse(
            case_id=orig_case_id,
            action_type=req.action_type,
            status="recorded",
            recorded_at=now,
            new_case_status=new_status,
        )

    # 7. Case Terminal Adjudication
    async def record_preliminary_assessment(
        self, case_id: str, req: PreliminaryAssessmentRequest, organization_id: str | None = None
    ) -> PreliminaryJudgment:
        resolved_id = self._resolve_case_id(case_id)
        conn = self._get_db_connection() if self._is_valid_uuid(resolved_id) else None
        if conn is not None:
            try:
                _require_org_scope(organization_id, allow_unscoped=self._test_stack_unscoped())
                with conn.cursor() as cur:
                    query = "SELECT id, status FROM app.fraud_cases WHERE id = %s"
                    params: list[Any] = [resolved_id]
                    if organization_id:
                        query += " AND organization_id = %s"
                        params.append(organization_id)
                    cur.execute(query + " FOR UPDATE", params)
                    case = cur.fetchone()
                    if not case:
                        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
                    if case["status"] == "resolved":
                        raise HTTPException(status_code=409, detail="Case has already been adjudicated")
                    cur.execute(
                        "SELECT analyst_id::text FROM app.review_leases WHERE case_id = %s AND expires_at > now() FOR UPDATE",
                        (resolved_id,),
                    )
                    lease = cur.fetchone()
                    self._require_judgment_claim(lease, req.analyst_id)
                    existing = self._read_preliminary_judgment(cur, resolved_id)
                    if existing:
                        self._require_same_judgment(existing, req)
                        return existing
                    cur.execute(
                        """INSERT INTO app.preliminary_judgments (case_id, analyst_id, judgment, note)
                           VALUES (%s,%s,%s,%s) ON CONFLICT (case_id) DO NOTHING""",
                        (resolved_id, req.analyst_id, req.judgment, req.note),
                    )
                    record = self._read_preliminary_judgment(cur, resolved_id)
                    if record is None:
                        raise HTTPException(status_code=503, detail="Independent judgment could not be saved")
                    self._require_same_judgment(record, req)
                    conn.commit()
                    return record
            except HTTPException:
                conn.rollback()
                raise
            except Exception as exc:
                conn.rollback()
                logger.warning("Preliminary judgment persistence failed for case %s", resolved_id)
                raise HTTPException(status_code=503, detail="Independent judgment store unavailable") from exc
            finally:
                conn.close()

        detail = await self._get_case_detail_data(case_id, organization_id=organization_id)
        self._require_judgment_claim(detail.active_lease, req.analyst_id)
        existing = self._preliminary_judgments.get(resolved_id)
        if existing:
            self._require_same_judgment(existing, req)
            return existing
        self._require_test_fallback()
        record = PreliminaryJudgment(
            id=str(uuid4()), case_id=resolved_id, created_at=datetime.now(UTC), **req.model_dump()
        )
        self._preliminary_judgments[resolved_id] = record
        return record

    def _require_judgment_claim(self, lease: dict[str, Any] | None, analyst_id: str) -> None:
        if not lease or not self._analyst_matches(str(lease["analyst_id"]), analyst_id):
            raise HTTPException(status_code=409, detail="An active claim by this analyst is required")

    @staticmethod
    def _require_same_judgment(existing: PreliminaryJudgment, req: PreliminaryAssessmentRequest) -> None:
        if (existing.analyst_id, existing.judgment, existing.note) != (req.analyst_id, req.judgment, req.note):
            raise HTTPException(status_code=409, detail="Independent judgment has already been committed")

    @staticmethod
    def _read_preliminary_judgment(cur: Any, case_id: str) -> PreliminaryJudgment | None:
        cur.execute(
            """SELECT id::text, case_id::text, analyst_id::text, judgment, note, created_at
               FROM app.preliminary_judgments WHERE case_id = %s""",
            (case_id,),
        )
        row = cur.fetchone()
        return PreliminaryJudgment.model_validate(row) if row else None

    @staticmethod
    def _require_judgment_reference(judgment: PreliminaryJudgment | None, req: AdjudicationRequest) -> None:
        if req.preliminary_judgment_id and (
            judgment is None or judgment.id != req.preliminary_judgment_id or judgment.analyst_id != req.analyst_id
        ):
            raise HTTPException(status_code=409, detail="Preliminary judgment does not belong to this case and analyst")

    @staticmethod
    def _staged_decision_context(
        judgment: PreliminaryJudgment | None, assessment: dict[str, Any] | None
    ) -> dict[str, Any]:
        if judgment is None:
            return {}
        suggestion = {key: (assessment or {}).get(key) for key in ("category", "confidence", "recommended_action")}
        # Category alignment only; confidence and the final action never determine delta.
        aligned_choice = {
            **dict.fromkeys(("ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05"), "Nghi ngờ vi phạm"),
            "intentional_dic": "Nghi ngờ vi phạm",
            "confirmed_fraud": "Nghi ngờ vi phạm",
            "suspected_fraud": "Nghi ngờ vi phạm",
            "exonerated": "Nghi oan-bất khả kháng",
            "no_violation": "Nghi oan-bất khả kháng",
            "force_majeure": "Nghi oan-bất khả kháng",
            "insufficient_evidence": "Chưa đủ cơ sở",
        }.get(str(suggestion["category"]))
        return {
            "preliminary_judgment_id": judgment.id,
            "preliminary_judgment": judgment.model_dump(mode="json"),
            "ai_suggestion": suggestion,
            "delta": "match" if judgment.judgment == aligned_choice else "mismatch",
        }

    async def adjudicate_case(
        self, case_id: str, req: AdjudicationRequest, organization_id: str | None = None
    ) -> AdjudicationResponse:
        orig_case_id = case_id
        resolved_id = self._resolve_case_id(case_id)
        now = datetime.now(UTC)
        if req.outcome not in {"AGREE", "DISAGREE"}:
            raise HTTPException(status_code=400, detail="Only AGREE and DISAGREE are available in the workspace.")
        user_role = self.get_principal_role(req.analyst_id)

        if user_role not in self.AUTHORIZED_REVIEW_ROLES:
            raise HTTPException(
                status_code=403,
                detail=f"Principal '{req.analyst_id}' with role '{user_role}' is not authorized to adjudicate cases.",
            )

        # Check active lease conflict: if claimed by another analyst and caller is not admin -> 409
        lock_key = f"review_lock:{resolved_id}"
        r = self.get_redis_client()
        active_holder = None
        if r is not None:
            try:
                raw_lock = r.get(lock_key) or r.get(f"review_lock:{orig_case_id}")
                if raw_lock:
                    try:
                        active_holder = str(json.loads(raw_lock).get("analyst_id", raw_lock))
                    except Exception:
                        active_holder = str(raw_lock)
            except Exception:
                pass

        if not active_holder:
            existing_lease = self._active_leases.get(resolved_id) or self._active_leases.get(orig_case_id)
            if existing_lease and existing_lease.get("expires_at") and existing_lease["expires_at"] > now:
                active_holder = str(existing_lease["analyst_id"])

        if active_holder and not self._analyst_matches(active_holder, req.analyst_id) and user_role not in ("admin",):
            raise HTTPException(
                status_code=409,
                detail=f"Case {orig_case_id} is currently claimed by analyst {active_holder}. Only the claiming analyst or an administrator can adjudicate.",
            )

        # Check assigned analyst: if case is pre-assigned to another analyst and caller is not admin -> 409
        case_mem = self._cases.get(resolved_id) or self._cases.get(orig_case_id)
        assigned_to = (
            str(case_mem.get("assigned_analyst_id", "")) if case_mem and case_mem.get("assigned_analyst_id") else None
        )
        if not assigned_to and active_holder:
            assigned_to = active_holder

        if assigned_to and not self._analyst_matches(assigned_to, req.analyst_id) and user_role not in ("admin",):
            raise HTTPException(
                status_code=409,
                detail=f"Case {orig_case_id} is assigned to analyst {assigned_to}. Only the assigned analyst or an administrator can adjudicate.",
            )

        conn = self._get_db_connection() if self._is_valid_uuid(resolved_id) else None
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    # S4-TENANT #294 P0: persisted adjudication reads/writes require server org scope.
                    _require_org_scope(organization_id, allow_unscoped=self._test_stack_unscoped())
                    adjudicate_case_query = """
                        SELECT c.*, a.driver_id,
                               i.incident_type,
                               fs.quality_flags,
                               EXISTS (SELECT 1 FROM app.telemetry_points tp
                                       WHERE tp.assignment_id = a.id AND tp.app_state = 'crashed') AS app_crashed,
                               EXISTS (SELECT 1 FROM app.telemetry_points tp
                                       WHERE tp.assignment_id = a.id
                                         AND (tp.gps_state = 'unavailable' OR tp.network_state = 'offline')) AS telemetry_unavailable,
                               EXISTS (SELECT 1 FROM app.traffic_observations traffic
                                       WHERE traffic.assignment_id = a.id
                                         AND traffic.congestion_level = 'heavy') AS heavy_congestion
                        FROM app.fraud_cases c
                        LEFT JOIN app.trip_assignments a ON c.assignment_id = a.id
                        LEFT JOIN app.platform_incidents i ON i.assignment_id = a.id
                        LEFT JOIN LATERAL (
                            SELECT fs.quality_flags
                            FROM app.evidence_snapshots es
                            JOIN app.feature_sets fs ON fs.evidence_snapshot_id = es.id
                            WHERE es.case_id = c.id
                            ORDER BY es.version DESC
                            LIMIT 1
                        ) fs ON true
                        WHERE c.id = %s
                        """
                    adjudicate_case_params: list[Any] = [resolved_id]
                    if organization_id:
                        adjudicate_case_query += " AND c.organization_id = %s"
                        adjudicate_case_params.append(organization_id)
                    adjudicate_case_query += " FOR UPDATE OF c;"
                    cur.execute(adjudicate_case_query, tuple(adjudicate_case_params))
                    case_row = cur.fetchone()
                    if not case_row:
                        # Do NOT close conn here — the finally block handles cleanup.
                        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")

                    judgment = self._read_preliminary_judgment(cur, resolved_id)
                    self._require_judgment_reference(judgment, req)
                    cur.execute(
                        """SELECT ma.category, ma.confidence,
                                  COALESCE(to_jsonb(ma)->>'recommended_action', ma.raw_response->>'recommended_action') as recommended_action
                           FROM app.evidence_snapshots es
                           JOIN app.model_assessments ma ON ma.evidence_snapshot_id = es.id
                           WHERE es.case_id = %s ORDER BY es.version DESC, ma.created_at DESC LIMIT 1""",
                        (resolved_id,),
                    )
                    staged_context = self._staged_decision_context(judgment, cur.fetchone())

                    correlation_trace_id = None
                    if req.agent_turn_id:
                        cur.execute(
                            """SELECT 1
                               FROM app.case_agent_sessions s
                               JOIN app.case_agent_messages m ON m.session_id = s.id
                               WHERE s.case_id = %s
                                 AND s.organization_id = %s
                                 AND m.turn_id = %s
                                 AND m.role = 'assistant'
                               LIMIT 1""",
                            (resolved_id, case_row["organization_id"], str(req.agent_turn_id)),
                        )
                        if not cur.fetchone():
                            raise HTTPException(status_code=409, detail="Agent turn is not part of this case")
                        from src.rag.cockpit_agent import DEFAULT_GEN_MODEL, get_cockpit_prompt_version
                        from src.services.agent_tracing import make_trace_identity

                        settings = get_settings()
                        correlation_trace_id = make_trace_identity(
                            case_id=resolved_id,
                            run_id=str(req.agent_turn_id),
                            request_id=str(uuid4()),
                            environment=settings.app_env,
                            model=DEFAULT_GEN_MODEL,
                            prompt_version=get_cockpit_prompt_version(),
                        )["trace_id"]

                    assigned_db = str(case_row["assigned_analyst_id"]) if case_row.get("assigned_analyst_id") else None
                    if (
                        assigned_db
                        and not self._analyst_matches(assigned_db, req.analyst_id)
                        and user_role not in ("admin",)
                    ):
                        raise HTTPException(
                            status_code=409,
                            detail=f"Case {case_id} is assigned to analyst {assigned_db}. Only the assigned analyst or an administrator can adjudicate.",
                        )

                    current_version = case_row["version"]
                    if case_row["status"] == "resolved":
                        # Do NOT close conn here — the finally block handles cleanup.
                        raise HTTPException(
                            status_code=409,
                            detail=f"Case {case_id} is already resolved and adjudicated (terminal state)",
                        )

                    cur.execute("SELECT id FROM app.adjudications WHERE case_id = %s LIMIT 1;", (case_id,))
                    if cur.fetchone():
                        # Do NOT close conn here — the finally block handles cleanup.
                        raise HTTPException(
                            status_code=409,
                            detail=f"Case {case_id} already has a recorded adjudication",
                        )

                    if req.expected_case_version != current_version:
                        # Do NOT close conn here — the finally block handles cleanup.
                        raise HTTPException(
                            status_code=409,
                            detail=f"Version mismatch: current case version is {current_version}, expected {req.expected_case_version}",
                        )

                    blocking_reasons = _blocking_guardrail_reasons(
                        incident_type=case_row.get("incident_type"),
                        quality_flags=case_row.get("quality_flags"),
                        app_crashed=bool(case_row.get("app_crashed")),
                        telemetry_unavailable=bool(case_row.get("telemetry_unavailable")),
                        heavy_congestion=bool(case_row.get("heavy_congestion")),
                    )

                    cur.execute(
                        """
                        SELECT id, policy_version_id
                        FROM app.evidence_snapshots
                        WHERE case_id = %s
                        ORDER BY version DESC
                        LIMIT 1;
                        """,
                        (case_id,),
                    )
                    snap = cur.fetchone()
                    snap_id = snap["id"] if snap else "018f2f4e-0300-7000-8000-000000000001"
                    policy_id = snap["policy_version_id"] if snap else "018f2f4e-6000-7000-8000-000000000001"

                    analyst_uuid = req.analyst_id
                    is_valid_uuid = False
                    if analyst_uuid:
                        try:
                            UUID(str(analyst_uuid))
                            is_valid_uuid = True
                        except (ValueError, TypeError):
                            is_valid_uuid = False

                    if is_valid_uuid:
                        cur.execute("SELECT id FROM app.principals WHERE id = %s;", (analyst_uuid,))
                        p = cur.fetchone()
                        if not p:
                            cur.execute("SELECT id FROM app.principals LIMIT 1;")
                            p = cur.fetchone()
                        if p:
                            analyst_uuid = str(p["id"])
                    else:
                        cur.execute("SELECT id FROM app.principals WHERE display_name = %s LIMIT 1;", (analyst_uuid,))
                        p = cur.fetchone()
                        if not p:
                            cur.execute("SELECT id FROM app.principals LIMIT 1;")
                            p = cur.fetchone()
                        if p:
                            analyst_uuid = str(p["id"])

                    now = datetime.now(UTC)
                    req_hash = hashlib.sha256(f"{case_id}:{req.outcome}:{req.rationale}".encode()).digest()
                    adj_id = uuid4()

                    cur.execute(
                        """
                        INSERT INTO app.adjudications (
                            id, case_id, evidence_snapshot_id, policy_version_id, analyst_id,
                            outcome, rationale, explicit_human_approval, idempotency_key, request_hash, approved_at, staged_context
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb);
                        """,
                        (
                            adj_id,
                            case_id,
                            snap_id,
                            policy_id,
                            analyst_uuid,
                            req.outcome.lower(),
                            req.rationale,
                            True,
                            uuid4(),
                            req_hash,
                            now,
                            json.dumps(staged_context, ensure_ascii=False),
                        ),
                    )

                    new_version = current_version + 1
                    adjudicate_update_query = """
                        UPDATE app.fraud_cases
                        SET status = 'resolved', version = %s, updated_at = %s, resolved_at = %s
                        WHERE id = %s
                        """
                    adjudicate_update_params: list[Any] = [new_version, now, now, resolved_id]
                    if organization_id:
                        adjudicate_update_query += " AND organization_id = %s;"
                        adjudicate_update_params.append(organization_id)
                    else:
                        adjudicate_update_query += ";"
                    cur.execute(adjudicate_update_query, tuple(adjudicate_update_params))

                    # Synthesize and persist workflow trace
                    try:
                        from src.services.jev_precedent_service import get_jev_precedent_service

                        jev_svc = get_jev_precedent_service()
                        trace = jev_svc.synthesize_workflow_trace(
                            case_id,
                            decision_data={
                                "verdict": "agree" if req.outcome == "AGREE" else "disagree",
                                "rationale": req.rationale,
                                "decided_by": req.analyst_id,
                                "decided_at": now.isoformat(),
                                "trace_id": correlation_trace_id,
                                "agent_run_id": str(req.agent_turn_id) if req.agent_turn_id else None,
                            },
                        )
                        cur.execute(
                            "UPDATE app.fraud_cases SET workflow_trace = %s::jsonb WHERE id = %s;",
                            (json.dumps(trace.model_dump(), ensure_ascii=False), case_id),
                        )
                    except Exception as err:
                        logger.warning("Could not persist workflow_trace on DB adjudication: %s", err)

                    # Publish the immutable solved-case context in this transaction.
                    # Failure rolls back the decision instead of leaving an untraceable
                    # finalized case.
                    from src.services.precedent_repository import publish_finalized

                    publish_finalized(
                        conn,
                        case_id=str(case_id),
                        organization_id=str(case_row["organization_id"]),
                        published_by=str(analyst_uuid),
                    )

                    sanction = None

                    # Release review lease in DB
                    cur.execute("DELETE FROM app.review_leases WHERE case_id = %s;", (resolved_id,))
                    conn.commit()

                    # Release review lock in Redis and in-memory
                    if r is not None:
                        try:
                            r.delete(lock_key)
                            r.delete(f"review_lock:{orig_case_id}")
                        except Exception:
                            pass
                    self._active_leases.pop(resolved_id, None)
                    self._active_leases.pop(orig_case_id, None)

                    for cid in (resolved_id, orig_case_id):
                        if cid in self._cases:
                            self._cases[cid]["status"] = "resolved"
                            self._cases[cid]["version"] = new_version
                            self._cases[cid]["updated_at"] = now.isoformat()

                    return AdjudicationResponse(
                        case_id=orig_case_id,
                        outcome=req.outcome,
                        status="adjudicated",
                        sanction_applied=sanction,
                        adjudicated_at=now,
                        new_version=new_version,
                        **staged_context,
                    )
            except HTTPException:
                raise
            except Exception as e:
                logger.warning(f"Database error in adjudicate_case for {case_id}: {e}")
                if conn:
                    conn.rollback()
                self._require_test_fallback()
            finally:
                if conn:
                    conn.close()

        # In-memory fallback
        case = self._cases.get(resolved_id) or self._cases.get(orig_case_id)
        if not case:
            raise HTTPException(status_code=404, detail=f"Case {orig_case_id} not found")
        # S4-TENANT #294 P0: same-org check on the seed fallback path.
        if organization_id and str(case.get("organization_id", organization_id)) != str(organization_id):
            raise HTTPException(status_code=404, detail=f"Case {orig_case_id} not found")

        judgment = self._preliminary_judgments.get(resolved_id)
        self._require_judgment_reference(judgment, req)
        detail = await self._get_case_detail_data(orig_case_id, organization_id=organization_id)
        staged_context = self._staged_decision_context(judgment, detail.assessment)

        current_version = case.get("version", 1)
        if case.get("status") == "resolved" or any(a["case_id"] == resolved_id for a in self._adjudications):
            raise HTTPException(status_code=409, detail="Case already has a recorded adjudication")
        if req.expected_case_version != current_version:
            raise HTTPException(
                status_code=409,
                detail=f"Version mismatch: current case version is {current_version}, expected {req.expected_case_version}",
            )

        asgn_id = str(case.get("assignment_id", ""))
        incident = self._platform_incidents.get(asgn_id, {})

        blocking_reasons = _blocking_guardrail_reasons(incident_type=incident.get("incident_type"))
        blocking_reasons.extend(self._recorded_guardrail_reasons(resolved_id, orig_case_id))

        now = datetime.now(UTC)
        for cid in (resolved_id, orig_case_id):
            if cid in self._cases:
                c = self._cases[cid]
                c["status"] = "resolved"
                c["version"] = current_version + 1
                c["updated_at"] = now.isoformat()
                c["resolved_at"] = now.isoformat()

        # In-memory workflow trace synthesis
        try:
            from src.services.jev_precedent_service import get_jev_precedent_service

            jev_svc = get_jev_precedent_service()
            trace = jev_svc.synthesize_workflow_trace(
                resolved_id,
                decision_data={
                    "verdict": "agree" if req.outcome == "AGREE" else "disagree",
                    "rationale": req.rationale,
                    "decided_by": req.analyst_id,
                    "decided_at": now.isoformat(),
                    "explicit_human_approval": True,
                },
            )
            for cid in (resolved_id, orig_case_id):
                if cid in self._cases:
                    self._cases[cid]["workflow_trace"] = trace.model_dump()
        except Exception as err:
            logger.warning("Could not synthesize in-memory workflow_trace: %s", err)

        sanction = None

        # Release review lock
        if r is not None:
            try:
                r.delete(lock_key)
                r.delete(f"review_lock:{orig_case_id}")
            except Exception:
                pass
        self._active_leases.pop(resolved_id, None)
        self._active_leases.pop(orig_case_id, None)
        for alias, target in self._case_aliases.items():
            if target == resolved_id:
                self._active_leases.pop(alias, None)
        self._sync_case_dict(resolved_id)

        self._adjudications.append(
            {
                "id": str(uuid4()),
                "case_id": resolved_id,
                "analyst_id": req.analyst_id,
                "organization_id": organization_id,
                "outcome": req.outcome,
                "rationale": req.rationale,
                "approved_at": now.isoformat(),
                "sanction": sanction,
                **staged_context,
            }
        )

        return AdjudicationResponse(
            case_id=orig_case_id,
            outcome=req.outcome,
            status="adjudicated",
            sanction_applied=sanction,
            adjudicated_at=now,
            new_version=case["version"],
            **staged_context,
        )

    # 8. Case Progress SSE Stream
    async def stream_case_progress(self, case_id: str, organization_id: str | None = None) -> AsyncGenerator[str, None]:
        case_found = False
        conn = self._get_db_connection()
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    # S4-TENANT #294 P0: persisted progress reads require server org scope.
                    _require_org_scope(organization_id, allow_unscoped=self._test_stack_unscoped())
                    progress_query = "SELECT id, status FROM app.fraud_cases WHERE id = %s"
                    progress_params: list[Any] = [case_id]
                    if organization_id:
                        progress_query += " AND organization_id = %s"
                        progress_params.append(organization_id)
                    progress_query += ";"
                    cur.execute(progress_query, tuple(progress_params))
                    if cur.fetchone():
                        case_found = True
            except HTTPException:
                raise
            except Exception:
                pass
            finally:
                conn.close()

        if not case_found and case_id in self._cases:
            # S4-TENANT #294 P0: same-org check on the seed fallback path.
            seed_case = self._cases[case_id]
            if organization_id and str(seed_case.get("organization_id", organization_id)) != str(organization_id):
                raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
            case_found = True

        if not case_found:
            raise HTTPException(status_code=404, detail=f"Case {case_id} not found")

        stages = [
            ("telemetry_ingested", 20, "Telemetry frames aligned"),
            ("features_extracted", 50, "Spatial-temporal features computed"),
            ("guardrails_checked", 75, "Guardrails and platform incidents evaluated"),
            ("ready", 100, "Case ready for analyst review"),
        ]

        for status, progress, message in stages:
            data = {
                "case_id": case_id,
                "status": status,
                "progress": progress,
                "message": message,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            yield f"event: case_progress\ndata: {json.dumps(data)}\n\n"
            await asyncio.sleep(0.01)

    def _case_agent_session(
        self,
        case_id: str,
        organization_id: str | None,
        roles: Sequence[str] | set[str] | None = ("user", "assistant"),
    ) -> dict[str, Any]:
        try:
            conn = self._get_db_connection()
        except HTTPException:
            conn = None
        if conn is None:
            if not getattr(self, "_in_memory_sessions", False) and self.settings.app_env not in ("test", "development"):
                raise HTTPException(status_code=503, detail="Case agent session database unavailable")
            session = self._agent_sessions.get(str(case_id))
            if not session:
                return {"session_id": None, "messages": []}
            session_id = session["session_id"]
            messages = self._agent_messages.get(session_id, [])
            if roles is not None:
                messages = [m for m in messages if m.get("role") in roles]
            return {
                "session_id": session_id,
                "messages": messages,
            }
        try:
            with conn.cursor() as cur:
                cur.execute("SET search_path = app, extensions, public;")
                _require_org_scope(organization_id, allow_unscoped=self._test_stack_unscoped())
                query = """SELECT s.id AS session_id, m.id, m.turn_id, m.role, m.content, m.created_at
                           FROM app.case_agent_sessions s
                           LEFT JOIN app.case_agent_messages m ON m.session_id = s.id"""
                params: list[Any] = []
                if roles is not None:
                    query += " AND m.role = ANY(%s)"
                    params.append(list(roles))
                query += " WHERE s.case_id = %s"
                params.append(case_id)
                if organization_id:
                    query += " AND s.organization_id = %s"
                    params.append(organization_id)
                query += " ORDER BY m.sequence ASC"
                cur.execute(query, tuple(params))
                rows = [dict(row) for row in cur.fetchall()]
                if not rows:
                    case_query = "SELECT id FROM app.fraud_cases WHERE id = %s"
                    case_params: tuple[Any, ...] = (case_id,)
                    if organization_id:
                        case_query += " AND organization_id = %s"
                        case_params = (case_id, organization_id)
                    cur.execute(case_query, case_params)
                    if not cur.fetchone():
                        if str(case_id) in self._cases:
                            session = self._agent_sessions.get(str(case_id))
                            if not session:
                                return {"session_id": None, "messages": []}
                            session_id = session["session_id"]
                            messages = self._agent_messages.get(session_id, [])
                            if roles is not None:
                                messages = [m for m in messages if m.get("role") in roles]
                            return {
                                "session_id": session_id,
                                "messages": messages,
                            }
                        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
                    return {"session_id": None, "messages": []}
                return {
                    "session_id": str(rows[0]["session_id"]),
                    "messages": [
                        {
                            "id": str(row["id"]),
                            "turn_id": str(row["turn_id"]),
                            "role": row["role"],
                            "content": row["content"],
                            "created_at": row["created_at"].isoformat()
                            if hasattr(row["created_at"], "isoformat")
                            else str(row["created_at"]),
                        }
                        for row in rows
                        if row["id"] is not None
                    ],
                }
        finally:
            conn.close()

    def _begin_case_agent_turn(
        self,
        req: PolicyChatRequest,
        organization_id: str | None,
        actor_id: str | None,
    ) -> dict[str, Any]:
        try:
            conn = self._get_db_connection()
        except HTTPException:
            conn = None
        if conn is None:
            if not getattr(self, "_in_memory_sessions", False) and self.settings.app_env not in ("test", "development"):
                raise HTTPException(status_code=503, detail="Case agent session database unavailable")
            # S4-TENANT #294 P0: fail closed on missing org. Never fall back
            # to a default org; only the /test/* stack may proceed unscoped.
            scoped_org = _require_org_scope(organization_id, allow_unscoped=self._test_stack_unscoped())
            case_id_str = str(req.case_id)
            if case_id_str not in self._agent_sessions:
                self._agent_sessions[case_id_str] = {
                    "session_id": str(uuid4()),
                    "case_id": case_id_str,
                    # In-memory /test/* stack tenant only (conn None path above
                    # is gated to test/development). Production uses DB org.
                    "organization_id": scoped_org,
                }
            session_id = self._agent_sessions[case_id_str]["session_id"]
            messages = self._agent_messages.setdefault(session_id, [])
            for m in messages:
                if m.get("turn_id") == str(req.turn_id) and m.get("role") == "assistant":
                    return {
                        "session_id": session_id,
                        "driver_id": None,
                        "history": [],
                        "existing_answer": m.get("content", ""),
                    }
            if req.reset_context:
                history = []
            else:
                history = [
                    {"role": m["role"], "content": m["content"]}
                    for m in messages
                    if m.get("role") in ("user", "assistant")
                ][-12:]
            from datetime import datetime

            messages.append(
                {
                    "id": str(uuid4()),
                    "turn_id": str(req.turn_id),
                    "role": "user",
                    "content": req.query.strip(),
                    "created_at": datetime.now(UTC).isoformat(),
                }
            )
            history.append({"role": "user", "content": req.query.strip()})
            return {
                "session_id": session_id,
                "driver_id": None,
                "history": history,
            }
        try:
            with conn.cursor() as cur:
                cur.execute("SET search_path = app, extensions, public;")
                _require_org_scope(organization_id, allow_unscoped=self._test_stack_unscoped())
                case_query = """SELECT c.organization_id, a.driver_id
                               FROM app.fraud_cases c
                               LEFT JOIN app.trip_assignments a ON a.id = c.assignment_id
                               WHERE c.id = %s"""
                case_params: list[Any] = [str(req.case_id)]
                if organization_id:
                    case_query += " AND c.organization_id = %s"
                    case_params.append(organization_id)
                cur.execute(case_query, tuple(case_params))
                case_row = cur.fetchone()
                if not case_row:
                    raise HTTPException(status_code=404, detail=f"Case {req.case_id} not found")
                case_org_id = str(case_row["organization_id"])
                cur.execute(
                    """INSERT INTO app.case_agent_sessions (organization_id, case_id, created_by)
                       VALUES (%s, %s, %s) ON CONFLICT (case_id) DO NOTHING""",
                    (case_org_id, str(req.case_id), actor_id),
                )
                cur.execute(
                    "SELECT id FROM app.case_agent_sessions WHERE case_id = %s AND organization_id = %s",
                    (str(req.case_id), case_org_id),
                )
                session_row = cur.fetchone()
                if not session_row:
                    raise HTTPException(status_code=404, detail=f"Case {req.case_id} not found")
                session_id = str(session_row["id"])
                cur.execute(
                    """SELECT id, role, content FROM app.case_agent_messages
                       WHERE session_id = %s AND turn_id = %s AND role = 'assistant'""",
                    (session_id, str(req.turn_id)),
                )
                prior_answer = cur.fetchone()
                if prior_answer:
                    conn.commit()
                    return {
                        "session_id": session_id,
                        "driver_id": str(case_row["driver_id"]) if case_row["driver_id"] else None,
                        "history": [],
                        "existing_answer": prior_answer["content"],
                    }
                if req.reset_context:
                    history = []
                else:
                    cur.execute(
                        """SELECT role, content FROM app.case_agent_messages
                           WHERE session_id = %s AND role IN ('user', 'assistant')
                           ORDER BY sequence DESC LIMIT 12""",
                        (session_id,),
                    )
                    history = [dict(row) for row in reversed(cur.fetchall())]
                cur.execute(
                    """INSERT INTO app.case_agent_messages (session_id, turn_id, role, content)
                       VALUES (%s, %s, 'user', %s) ON CONFLICT (session_id, turn_id, role) DO NOTHING""",
                    (session_id, str(req.turn_id), req.query.strip()),
                )
            conn.commit()
            history.append({"role": "user", "content": req.query.strip()})
            return {
                "session_id": session_id,
                "driver_id": str(case_row["driver_id"]) if case_row["driver_id"] else None,
                "history": history,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _append_case_agent_reply(self, session_id: str, turn_id: str, content: str) -> None:
        try:
            conn = self._get_db_connection()
        except HTTPException:
            conn = None
        if conn is None:
            if not getattr(self, "_in_memory_sessions", False) and self.settings.app_env not in ("test", "development"):
                raise HTTPException(status_code=503, detail="Case agent session database unavailable")
            from datetime import datetime

            self._agent_messages.setdefault(session_id, []).append(
                {
                    "id": str(uuid4()),
                    "turn_id": str(turn_id),
                    "role": "assistant",
                    "content": content,
                    "created_at": datetime.now(UTC).isoformat(),
                }
            )
            return
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO app.case_agent_messages (session_id, turn_id, role, content)
                       VALUES (%s, %s, 'assistant', %s) ON CONFLICT (session_id, turn_id, role) DO NOTHING""",
                    (session_id, turn_id, content),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    async def get_case_agent_session(
        self,
        case_id: str,
        organization_id: str | None = None,
        roles: Sequence[str] | set[str] | None = ("user", "assistant"),
    ) -> dict[str, Any]:
        resolved_id = self._resolve_case_id(case_id)
        if not self._is_valid_uuid(resolved_id):
            raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
        return await asyncio.to_thread(self._case_agent_session, resolved_id, organization_id, roles)

    # 9. Policy Chat SSE Stream (case-scoped ReAct agent)
    async def stream_policy_chat(
        self,
        req: PolicyChatRequest,
        organization_id: str | None = None,
        actor_id: str | None = None,
    ) -> AsyncGenerator[str, None]:
        from src.rag.cockpit_agent import DEFAULT_GEN_MODEL, CockpitRAGAgent, get_cockpit_prompt_version

        try:
            turn = await asyncio.to_thread(self._begin_case_agent_turn, req, organization_id, actor_id)
        except HTTPException as exc:
            yield f"event: error\ndata: {json.dumps({'message': exc.detail})}\n\n"
            return
        session_id = turn["session_id"]
        yield f"event: session\ndata: {json.dumps({'session_id': session_id, 'turn_id': str(req.turn_id)})}\n\n"

        if turn.get("existing_answer"):
            answer_text = turn["existing_answer"]
            for start in range(0, len(answer_text), 32):
                delta = answer_text[start : start + 32]
                yield f"event: text_delta\ndata: {json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"
            yield f"event: done\ndata: {json.dumps({'status': 'completed'})}\n\n"
            return

        yield f"event: thinking\ndata: {json.dumps({'status': 'thinking', 'label': 'Reviewing case evidence and relevant policy'})}\n\n"
        loop = asyncio.get_running_loop()
        tool_queue: asyncio.Queue[str] = asyncio.Queue()

        def announce_tool(tool_name: str) -> None:
            loop.call_soon_threadsafe(tool_queue.put_nowait, tool_name)

        agent = CockpitRAGAgent()
        from src.services.agent_tracing import end_trace, make_trace_identity, trace_tool, trace_turn
        from src.services.observability_metrics import record_run

        def record_metrics(**values: Any) -> None:
            try:
                record_run(**values)
            except Exception as exc:
                logger.warning(
                    "Operational metrics could not be recorded; agent result is unchanged (%s)", type(exc).__name__
                )

        settings = get_settings()
        trace_identity = make_trace_identity(
            case_id=str(req.case_id),
            run_id=str(req.turn_id),
            request_id=str(uuid4()),
            environment=settings.app_env,
            model=getattr(agent, "model_name", DEFAULT_GEN_MODEL),
            prompt_version=get_cockpit_prompt_version(),
        )
        run_metrics: dict[str, Any] = {}

        def execute_traced_agent():
            started_at = time.monotonic()
            tool_scopes = []

            def traced_tool_call(tool_name: str) -> None:
                announce_tool(tool_name)
                tool_identity = {
                    **trace_identity,
                    "tool_call_id": str(uuid4()),
                    "parent_span_id": trace_identity["span_id"],
                    "span_id": uuid4().hex[:16],
                }
                scope = trace_tool(tool_identity, tool_name)
                tool_scopes.append((scope, scope.__enter__()))

            with trace_turn(trace_identity, name="analyst.cockpit.turn") as agent_trace:
                try:
                    response = agent.execute_turn(
                        question=req.query,
                        driver_id=turn["driver_id"],
                        case_id=str(req.case_id),
                        conversation_history=turn["history"],
                        on_tool_call=traced_tool_call,
                    )
                except BaseException as exc:
                    for scope, tool_trace in reversed(tool_scopes):
                        end_trace(tool_trace, error=type(exc).__name__)
                        try:
                            scope.__exit__(type(exc), exc, exc.__traceback__)
                        except Exception:
                            logger.warning("Tool trace cleanup failed after agent error")
                    end_trace(agent_trace, error=type(exc).__name__)
                    record_metrics(
                        trace_id=trace_identity["trace_id"],
                        run_id=trace_identity["run_id"],
                        latency_ms=max(0, int((time.monotonic() - started_at) * 1000)),
                        status="failed",
                        timed_out=isinstance(exc, TimeoutError),
                        tool_count=len(tool_scopes),
                        tool_success_count=0,
                        tool_failure_count=len(tool_scopes),
                        input_tokens=getattr(agent, "input_tokens", None),
                        output_tokens=getattr(agent, "output_tokens", None),
                        model=getattr(agent, "model_name", DEFAULT_GEN_MODEL),
                        grounding_errors=None,
                        grounding_sample_count=0,
                        guardrail_violations=None,
                        guardrail_sample_count=0,
                    )
                    raise

                for scope, tool_trace in reversed(tool_scopes):
                    end_trace(tool_trace, outputs={"status": response.status})
                    try:
                        scope.__exit__(None, None, None)
                    except Exception:
                        logger.warning("Tool trace cleanup failed")

                end_trace(agent_trace, outputs={"status": response.status, "tool_count": len(tool_scopes)})
                raw_tool_data = getattr(response, "raw_tool_data", None) or {}
                grounding_sample_count = int(
                    getattr(response, "tool_called", None) in {"search_policy", "search_policy_documents"}
                )
                guardrail_data = raw_tool_data.get("guardrail_violations")
                guardrail_sample_count = int("guardrail_violations" in raw_tool_data)
                guardrail_violations = (
                    len(guardrail_data)
                    if isinstance(guardrail_data, list)
                    else int(guardrail_data)
                    if isinstance(guardrail_data, int)
                    else None
                )
                tool_succeeded = bool(tool_scopes) and response.status == "success"
                run_metrics.update(
                    status="completed" if response.status == "success" else response.status,
                    tool_count=len(tool_scopes),
                    tool_success_count=int(tool_succeeded),
                    tool_failure_count=len(tool_scopes) - int(tool_succeeded),
                    grounding_errors=int(grounding_sample_count > 0 and not response.citations),
                    grounding_sample_count=grounding_sample_count,
                    guardrail_violations=guardrail_violations,
                    guardrail_sample_count=guardrail_sample_count,
                )
                return response

        request_started_at = time.monotonic()
        agent_task = asyncio.create_task(asyncio.to_thread(execute_traced_agent))
        announced_tool: str | None = None
        while not agent_task.done():
            try:
                announced_tool = await asyncio.wait_for(tool_queue.get(), timeout=0.05)
                yield f"event: tool_call\ndata: {json.dumps({'tool': announced_tool, 'status': 'running'})}\n\n"
            except TimeoutError:
                continue
        try:
            agent_resp = await agent_task
        except Exception:
            logger.exception("Agent execution in stream_policy_chat failed")
            yield f"event: error\ndata: {json.dumps({'message': 'Agent request failed'})}\n\n"
            return
        while not tool_queue.empty():
            announced_tool = tool_queue.get_nowait()
            yield f"event: tool_call\ndata: {json.dumps({'tool': announced_tool, 'status': 'running'})}\n\n"
        if announced_tool:
            yield f"event: tool_done\ndata: {json.dumps({'tool': announced_tool, 'tool_called': announced_tool, 'status': agent_resp.status or 'completed'})}\n\n"
        full_thought = ""
        if getattr(agent_resp, "thought_process", None):
            full_thought = "\n".join(agent_resp.thought_process)
        elif getattr(agent_resp, "reasoning", None):
            full_thought = agent_resp.reasoning
        elif getattr(agent_resp, "thinking_process", None):
            full_thought = agent_resp.thinking_process

        if full_thought:
            yield f"event: thinking\ndata: {json.dumps({'status': 'completed', 'thought': full_thought, 'label': full_thought}, ensure_ascii=False)}\n\n"
        else:
            yield f"event: thinking\ndata: {json.dumps({'status': 'thinking', 'thought': '', 'label': 'Preparing response'})}\n\n"

        if (
            agent_resp.status == "success"
            and getattr(agent_resp, "tool_called", None)
            and agent_resp.tool_called not in {"search_policy", "search_policy_documents"}
            and hasattr(agent, "continue_from_tool_result")
        ):
            try:
                followup_identity = {
                    **trace_identity,
                    "parent_span_id": trace_identity["span_id"],
                    "span_id": uuid4().hex[:16],
                }

                def synthesize_traced_answer():
                    with trace_turn(followup_identity, name="analyst.cockpit.answer-synthesis") as followup_trace:
                        final = agent.continue_from_tool_result(
                            question=req.query,
                            tool_answer=agent_resp.answer,
                            conversation_history=turn["history"],
                        )
                        end_trace(followup_trace, outputs={"status": "completed"})
                        return final

                final_answer = await asyncio.to_thread(synthesize_traced_answer)
                agent_resp = agent_resp.model_copy(update={"answer": final_answer})
            except Exception:
                logger.exception("Agent tool-result synthesis failed")

        record_metrics(
            trace_id=trace_identity["trace_id"],
            run_id=trace_identity["run_id"],
            latency_ms=max(0, int((time.monotonic() - request_started_at) * 1000)),
            status=run_metrics.get("status", "failed"),
            timed_out=False,
            tool_count=run_metrics.get("tool_count", 0),
            tool_success_count=run_metrics.get("tool_success_count", 0),
            tool_failure_count=run_metrics.get("tool_failure_count", 0),
            input_tokens=getattr(agent, "input_tokens", None),
            output_tokens=getattr(agent, "output_tokens", None),
            model=getattr(agent, "model_name", DEFAULT_GEN_MODEL),
            grounding_errors=run_metrics.get("grounding_errors"),
            grounding_sample_count=run_metrics.get("grounding_sample_count", 0),
            guardrail_violations=run_metrics.get("guardrail_violations"),
            guardrail_sample_count=run_metrics.get("guardrail_sample_count", 0),
        )

        for citation in agent_resp.citations:
            payload = {
                "source": citation.document_title,
                "section": citation.doc_id,
                "content": citation.snippet,
            }
            yield f"event: citation\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        answer_text = (agent_resp.answer or "").strip()
        if not answer_text:
            yield f"event: error\ndata: {json.dumps({'message': 'Agent returned no response'})}\n\n"
            return
        try:
            await asyncio.to_thread(self._append_case_agent_reply, session_id, str(req.turn_id), answer_text)
        except HTTPException as exc:
            yield f"event: error\ndata: {json.dumps({'message': exc.detail})}\n\n"
            return
        for start in range(0, len(answer_text), 32):
            delta = answer_text[start : start + 32]
            yield f"event: text_delta\ndata: {json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"
        yield f"event: done\ndata: {json.dumps({'status': 'completed'})}\n\n"


_case_service_instance: CaseService | None = None


def get_case_service() -> CaseService:
    global _case_service_instance
    if _case_service_instance is None:
        _case_service_instance = CaseService()
    return _case_service_instance
