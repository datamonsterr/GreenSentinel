"""Repository layer for SPEC-0130 Tester Trip Simulation."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from threading import RLock
from typing import Any
from uuid import UUID, uuid4

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]

from src.config import Settings, get_settings
from src.models.test_simulation import (
    DriverSimConfig,
    GeoJsonLineString,
    PassengerSimConfig,
    PresetBatchEvent,
    PresetBatchRunDetailResponse,
    PresetBatchRunResponse,
    PresetBatchTripResponse,
    TestDefinitionRevisionCreate,
    TestDefinitionRevisionResponse,
    TestPlanCreate,
    TestPlanResponse,
    TestRunCreate,
    TestRunResponse,
    TestRunStatus,
    TestRunSummary,
    TestStopSnapshot,
    TestTelemetrySample,
)

logger = logging.getLogger(__name__)


def _stop_snapshots(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    raw = value if isinstance(value, dict) else json.loads(value)
    return {
        f"{key}_snapshot": TestStopSnapshot(**item) if item else None
        for key, item in raw.items()
        if key in {"initial", "pickup", "destination"}
    }


def _run_from_row(row: dict[str, Any]) -> TestRunResponse:
    """Map a test_runs row to the API model, tolerating pre-migration columns."""
    keys = row.keys()

    def col(name: str) -> Any:
        return row[name] if name in keys else None

    return TestRunResponse(
        id=row["id"],
        definition_revision_id=row["definition_revision_id"],
        status=row["status"],
        current_step=row["current_step"],
        total_steps=row["total_steps"],
        simulation_clock=row["simulation_clock"],
        speed_factor=row["speed_factor"],
        created_at=row["created_at"],
        started_at=col("started_at"),
        completed_at=col("completed_at"),
        title=col("title"),
        trip_id=str(col("trip_id")) if col("trip_id") is not None else None,
        cancelled_at=col("cancelled_at"),
        cancellation_actor=col("cancellation_actor"),
        cancellation_reason=col("cancellation_reason"),
        expected_label=col("expected_label"),
        source=col("source"),
    )


def enforce_fail_closed_credential_safeguards() -> None:
    """Strict Enforcement Rule 2: Throw explicit error if production notification keys loaded."""
    prod_keys = [
        "TWILIO_AUTH_TOKEN",
        "TWILIO_ACCOUNT_SID",
        "FIREBASE_SERVER_KEY",
        "FIREBASE_PROJECT_ID",
        "APNS_KEY",
        "APNS_KEY_ID",
    ]
    loaded = [k for k in prod_keys if os.getenv(k)]
    if loaded:
        raise RuntimeError(
            f"FAIL-CLOSED CREDENTIAL SAFEGUARD: Production credentials detected in test simulation environment: {loaded}. "
            "Synthetic tests must strictly use isolated sandbox mocks (test_notifications)."
        )


class TestSimulationRepository:
    """Provides atomic operations for simulation plans, revisions, runs, and samples."""

    __test__ = False

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        enforce_fail_closed_credential_safeguards()
        if self.settings.app_env not in {"test", "development"} and not self.settings.test_database_url:
            raise RuntimeError("TEST_DATABASE_URL is required before enabling hosted test simulation")
        if self.settings.test_database_url and self.settings.test_database_url == self.settings.database_url:
            raise RuntimeError("TEST_DATABASE_URL must be isolated from DATABASE_URL")
        self._lock = RLock()
        self._publish_locks: dict[tuple[str, UUID], asyncio.Lock] = {}
        # In-memory stores for dev/test mode without live Postgres
        self._plans: dict[UUID, TestPlanResponse] = {}
        self._plan_org: dict[UUID, str] = {}
        self._definitions: dict[UUID, TestDefinitionRevisionResponse] = {}
        self._definition_org: dict[UUID, str] = {}
        self._runs: dict[UUID, TestRunResponse] = {}
        self._run_org: dict[UUID, str] = {}
        self._controls: list[dict[str, Any]] = []
        self._samples: list[dict[str, Any]] = []
        self._events: list[dict[str, Any]] = []
        self._notifications: list[dict[str, Any]] = []
        self._cases: dict[str, dict[str, Any]] = {}
        self._outbox: list[dict[str, Any]] = []
        self._idempotency_keys: dict[tuple[str, str], UUID] = {}
        self._submissions: dict[tuple[str, UUID], dict[str, Any]] = {}
        self._preset_batches: dict[UUID, PresetBatchRunResponse] = {}
        self._preset_batch_trips: dict[UUID, list[PresetBatchTripResponse]] = {}
        self._preset_batch_events: dict[UUID, list[PresetBatchEvent]] = {}
        self._preset_batch_subscribers: dict[UUID, list[asyncio.Queue[PresetBatchEvent]]] = {}

    def _get_db(self) -> Any | None:
        db_url = self.settings.test_database_url
        if not db_url:
            return None
        if psycopg is None:
            raise RuntimeError("psycopg is required for configured TEST_DATABASE_URL")
        with self._lock:
            cached = getattr(self, "_cached_db", None)
            if cached is not None:
                try:
                    if not cached.closed:
                        cached.execute("SELECT 1;")
                        return cached
                except Exception:
                    try:
                        cached.close()
                    except Exception:
                        pass
                    self._cached_db = None
            try:
                conn = psycopg.connect(
                    db_url,
                    row_factory=dict_row,
                    autocommit=True,
                    connect_timeout=3,
                    options="-c search_path=app,extensions,public",
                )
                self._cached_db = conn
                return conn
            except Exception as exc:
                # A configured hosted test database is authoritative. Falling
                # back to process memory would report false success and cross
                # request boundaries, so fail closed.
                if self.settings.test_database_url:
                    raise RuntimeError("Configured TEST_DATABASE_URL is unavailable") from exc
                return None

    def close(self) -> None:
        """Explicit cleanup method to close cached database connection."""
        with self._lock:
            cached = getattr(self, "_cached_db", None)
            if cached is not None:
                try:
                    if not cached.closed:
                        cached.close()
                except Exception:
                    pass
                self._cached_db = None

    @asynccontextmanager
    async def publish_lock(self, run_id: UUID, organization_id: str) -> AsyncIterator[None]:
        """Serialize receipt lookup, processing and acknowledgement across API processes."""
        if self.settings.test_database_url:
            if psycopg is None:
                raise RuntimeError("psycopg is required for configured simulation storage")
            # A dedicated async session keeps a waiting request from blocking the
            # event loop or sharing another request's transaction/lock lifetime.
            async with await psycopg.AsyncConnection.connect(self.settings.test_database_url, autocommit=True) as conn:
                key = f"test-console:publish:{organization_id}:{run_id}"
                await conn.execute("SET lock_timeout = '30s'")
                await conn.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", (key,))
                try:
                    yield
                finally:
                    await conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (key,))
        else:
            lock = self._publish_locks.setdefault((organization_id, run_id), asyncio.Lock())
            async with lock:
                yield

    def get_publish_submission(
        self, run_id: UUID, organization_id: str, *, include_processing: bool = False
    ) -> dict[str, Any] | None:
        """Return the durable production publish receipt for an owned run."""
        conn = self._get_db()
        if conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT s.result FROM test_run_submissions s
                        JOIN test_runs r ON r.id = s.run_id
                        JOIN test_definition_revisions d ON d.id = r.definition_revision_id
                        JOIN test_plans p ON p.id = d.plan_id
                        WHERE s.run_id = %s AND p.organization_id = %s;""",
                        (run_id, organization_id),
                    )
                    row = cur.fetchone()
                    stored = row["result"] if row else None
                    if isinstance(stored, dict) and "response" in stored and not include_processing:
                        return stored["response"]
                    return stored
        with self._lock:
            result = self._submissions.get((organization_id, run_id))
            if isinstance(result, dict) and "response" in result and not include_processing:
                return dict(result["response"])
            return dict(result) if result else None

    def save_publish_submission(self, run_id: UUID, organization_id: str, result: dict[str, Any]) -> None:
        """Persist a publish receipt; duplicate writes are harmless."""
        conn = self._get_db()
        if conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO test_run_submissions (run_id, organization_id, result, created_at)
                        VALUES (%s, %s, %s, %s) ON CONFLICT (run_id) DO NOTHING;""",
                        (run_id, organization_id, json.dumps(result), datetime.now(UTC)),
                    )
            return
        with self._lock:
            self._submissions.setdefault((organization_id, run_id), dict(result))

    # -----------------------------------------------------------------------
    # Plans
    # -----------------------------------------------------------------------
    def create_plan(
        self, data: TestPlanCreate, organization_id: str | None = None, created_by: str | None = None
    ) -> TestPlanResponse:
        plan_id = uuid4()
        now = datetime.now(UTC)
        conn = self._get_db()
        if conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO test_plans (id, name, description, organization_id, created_by, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING id, name, description, created_at, updated_at;
                        """,
                        (plan_id, data.name, data.description, organization_id, created_by, now, now),
                    )
                    row = cur.fetchone()
                    return TestPlanResponse(
                        id=row["id"],
                        name=row["name"],
                        description=row["description"],
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                    )

        with self._lock:
            resp = TestPlanResponse(
                id=plan_id,
                name=data.name,
                description=data.description,
                created_at=now,
                updated_at=now,
            )
            self._plans[plan_id] = resp
            if organization_id:
                self._plan_org[plan_id] = organization_id
            return resp

    def get_plan(self, plan_id: UUID, organization_id: str | None = None) -> TestPlanResponse | None:
        conn = self._get_db()
        if conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT * FROM test_plans WHERE id = %s AND organization_id = %s;", (plan_id, organization_id)
                    )
                    row = cur.fetchone()
                    if row:
                        return TestPlanResponse(
                            id=row["id"],
                            name=row["name"],
                            description=row["description"],
                            created_at=row["created_at"],
                            updated_at=row["updated_at"],
                        )
                    return None

        with self._lock:
            if organization_id and self._plan_org.get(plan_id) != organization_id:
                return None
            return self._plans.get(plan_id)

    def list_plans(self, organization_id: str | None = None) -> list[TestPlanResponse]:
        conn = self._get_db()
        if conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT * FROM test_plans WHERE organization_id = %s ORDER BY created_at DESC;",
                        (organization_id,),
                    )
                    rows = cur.fetchall()
                    return [
                        TestPlanResponse(
                            id=r["id"],
                            name=r["name"],
                            description=r["description"],
                            created_at=r["created_at"],
                            updated_at=r["updated_at"],
                        )
                        for r in rows
                    ]

        with self._lock:
            return [
                p for pid, p in self._plans.items() if not organization_id or self._plan_org.get(pid) == organization_id
            ]

    # -----------------------------------------------------------------------
    # Definitions
    # -----------------------------------------------------------------------
    def create_definition_revision(
        self, data: TestDefinitionRevisionCreate, organization_id: str | None = None
    ) -> TestDefinitionRevisionResponse:
        rev_id = uuid4()
        now = datetime.now(UTC)
        conn = self._get_db()

        with self._lock:
            existing_revs = [d for d in self._definitions.values() if d.plan_id == data.plan_id]
            rev_number = len(existing_revs) + 1

        if conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT coalesce(max(revision_number), 0) + 1 AS next_revision FROM test_definition_revisions WHERE plan_id = %s;",
                        (data.plan_id,),
                    )
                    rev_number = cur.fetchone()["next_revision"]
                    cur.execute(
                        """
                        INSERT INTO test_definition_revisions (
                            id, plan_id, revision_number, route_geometry, driver_config, passenger_config, fault_configs, messages, stop_snapshots, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id, plan_id, revision_number, route_geometry, driver_config, passenger_config, fault_configs, messages, created_at;
                        """,
                        (
                            rev_id,
                            data.plan_id,
                            rev_number,
                            json.dumps(data.route_geometry.model_dump()),
                            json.dumps(data.driver_config.model_dump()),
                            json.dumps(data.passenger_config.model_dump()),
                            json.dumps([f.model_dump() for f in data.fault_configs]),
                            json.dumps([m.model_dump() for m in data.messages]),
                            json.dumps(
                                {
                                    k: v.model_dump()
                                    for k, v in {
                                        "initial": data.initial_snapshot,
                                        "pickup": data.pickup_snapshot,
                                        "destination": data.destination_snapshot,
                                    }.items()
                                    if v is not None
                                }
                            ),
                            now,
                        ),
                    )
                    row = cur.fetchone()
                    return TestDefinitionRevisionResponse(
                        id=row["id"],
                        plan_id=row["plan_id"],
                        revision_number=row["revision_number"],
                        route_geometry=GeoJsonLineString(**row["route_geometry"]),
                        driver_config=DriverSimConfig(**row["driver_config"]),
                        passenger_config=PassengerSimConfig(**row["passenger_config"]),
                        fault_configs=row["fault_configs"],
                        messages=row.get("messages", []),
                        **_stop_snapshots(row.get("stop_snapshots")),
                        created_at=row["created_at"],
                    )

        with self._lock:
            resp = TestDefinitionRevisionResponse(
                id=rev_id,
                plan_id=data.plan_id,
                revision_number=rev_number,
                route_geometry=data.route_geometry,
                driver_config=data.driver_config,
                passenger_config=data.passenger_config,
                fault_configs=data.fault_configs,
                messages=data.messages,
                initial_snapshot=data.initial_snapshot,
                pickup_snapshot=data.pickup_snapshot,
                destination_snapshot=data.destination_snapshot,
                created_at=now,
            )
            self._definitions[rev_id] = resp
            if organization_id:
                self._definition_org[rev_id] = organization_id
            return resp

    def get_definition_revision(
        self, rev_id: UUID, organization_id: str | None = None
    ) -> TestDefinitionRevisionResponse | None:
        conn = self._get_db()
        if conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT d.* FROM test_definition_revisions d
                        JOIN test_plans p ON p.id = d.plan_id
                        WHERE d.id = %s AND (%s::text IS NULL OR p.organization_id::text = %s);""",
                        (rev_id, organization_id, organization_id),
                    )
                    row = cur.fetchone()
                    if row:
                        return TestDefinitionRevisionResponse(
                            id=row["id"],
                            plan_id=row["plan_id"],
                            revision_number=row["revision_number"],
                            route_geometry=GeoJsonLineString(**row["route_geometry"])
                            if isinstance(row["route_geometry"], dict)
                            else GeoJsonLineString(**json.loads(row["route_geometry"])),
                            driver_config=DriverSimConfig(**row["driver_config"])
                            if isinstance(row["driver_config"], dict)
                            else DriverSimConfig(**json.loads(row["driver_config"])),
                            passenger_config=PassengerSimConfig(**row["passenger_config"])
                            if isinstance(row["passenger_config"], dict)
                            else PassengerSimConfig(**json.loads(row["passenger_config"])),
                            fault_configs=row["fault_configs"]
                            if isinstance(row["fault_configs"], list)
                            else json.loads(row["fault_configs"]),
                            messages=row.get("messages", []),
                            **_stop_snapshots(row.get("stop_snapshots")),
                            created_at=row["created_at"],
                        )
                    return None

        with self._lock:
            if organization_id and self._definition_org.get(rev_id) != organization_id:
                return None
            return self._definitions.get(rev_id)

    # -----------------------------------------------------------------------
    # Runs
    # -----------------------------------------------------------------------
    def create_run(
        self,
        data: TestRunCreate,
        total_steps: int,
        organization_id: str | None = None,
        source: str | None = None,
    ) -> TestRunResponse:
        now = datetime.now(UTC)
        title = (data.title or "").strip() or f"Trip {now:%b %d %H:%M}"
        trip_id = uuid4()
        with self._lock:
            idem_key = (organization_id or "", data.idempotency_key or "")
            if data.idempotency_key and idem_key in self._idempotency_keys:
                existing_run_id = self._idempotency_keys[idem_key]
                existing = self._runs.get(existing_run_id)
                if existing:
                    if (
                        existing.definition_revision_id != data.definition_revision_id
                        or existing.speed_factor != data.speed_factor
                    ):
                        raise ValueError("Idempotency key already used for a different request")
                    return existing

        run_id = uuid4()
        conn = self._get_db()
        if conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    if data.idempotency_key:
                        # Serialize the same org/key across processes; the row is committed with its run.
                        cur.execute(
                            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0));",
                            (f"{organization_id}:{data.idempotency_key}",),
                        )
                        cur.execute(
                            "SELECT run_id FROM test_run_requests WHERE organization_id = %s AND key = %s;",
                            (organization_id, data.idempotency_key),
                        )
                        found = cur.fetchone()
                        if found:
                            cur.execute("SELECT * FROM test_runs WHERE id = %s;", (found["run_id"],))
                            r = cur.fetchone()
                            if (
                                r["definition_revision_id"] != data.definition_revision_id
                                or r["speed_factor"] != data.speed_factor
                            ):
                                raise ValueError("Idempotency key already used for a different request")
                            return _run_from_row(r)

                    # Resolve source if omitted
                    run_source = source or data.source
                    if not run_source:
                        try:
                            cur.execute(
                                """SELECT p.description FROM test_plans p
                                JOIN test_definition_revisions d ON d.plan_id = p.id
                                WHERE d.id = %s;""",
                                (data.definition_revision_id,),
                            )
                            p_row = cur.fetchone()
                            if p_row and p_row.get("description"):
                                p_desc = str(p_row["description"]).lower()
                                if "preset_batch" in p_desc:
                                    run_source = "preset_batch"
                                elif "preset" in p_desc:
                                    run_source = "preset"
                        except Exception:
                            pass
                        if not run_source:
                            run_source = "manual"

                    cur.execute(
                        """
                        INSERT INTO test_runs (
                            id, definition_revision_id, status, current_step, total_steps, simulation_clock, speed_factor, created_at, title, trip_id, expected_label, source
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING *;
                        """,
                        (
                            run_id,
                            data.definition_revision_id,
                            "QUEUED",
                            0,
                            total_steps,
                            now,
                            data.speed_factor,
                            now,
                            title,
                            trip_id,
                            data.expected_label,
                            run_source,
                        ),
                    )
                    row = cur.fetchone()
                    if data.idempotency_key:
                        cur.execute(
                            "INSERT INTO test_run_requests (organization_id, key, run_id, created_at) VALUES (%s, %s, %s, %s);",
                            (organization_id, data.idempotency_key, run_id, now),
                        )
                    return _run_from_row(row)

        with self._lock:
            # Re-check after database resolution.  _get_db() can release the
            # lock while probing the connection, so the first check above
            # cannot reserve an in-memory idempotency key by itself.
            idem_key = (organization_id or "", data.idempotency_key or "")
            if data.idempotency_key and idem_key in self._idempotency_keys:
                existing_run_id = self._idempotency_keys[idem_key]
                existing = self._runs.get(existing_run_id)
                if existing:
                    if (
                        existing.definition_revision_id != data.definition_revision_id
                        or existing.speed_factor != data.speed_factor
                    ):
                        raise ValueError("Idempotency key already used for a different request")
                    return existing

            source = source or data.source
            if not source:
                defn = self._definitions.get(data.definition_revision_id)
                if defn:
                    p = self._plans.get(defn.plan_id)
                    if p and p.description:
                        p_desc = str(p.description).lower()
                        if "preset_batch" in p_desc:
                            source = "preset_batch"
                        elif "preset" in p_desc:
                            source = "preset"
                if not source:
                    source = "manual"

            resp = TestRunResponse(
                id=run_id,
                definition_revision_id=data.definition_revision_id,
                status="QUEUED",
                current_step=0,
                total_steps=total_steps,
                simulation_clock=now,
                speed_factor=data.speed_factor,
                created_at=now,
                started_at=None,
                completed_at=None,
                title=title,
                trip_id=str(trip_id),
                expected_label=data.expected_label,
                source=source,
            )
            self._runs[run_id] = resp
            if organization_id:
                self._run_org[run_id] = organization_id
            if data.idempotency_key:
                self._idempotency_keys[(organization_id or "", data.idempotency_key)] = run_id
            return resp

    def get_run(self, run_id: UUID | str, organization_id: str | None = None) -> TestRunResponse | None:
        if isinstance(run_id, str):
            run_id = UUID(run_id)
        conn = self._get_db()
        if conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT r.* FROM test_runs r
                        JOIN test_definition_revisions d ON d.id = r.definition_revision_id
                        JOIN test_plans p ON p.id = d.plan_id
                        WHERE r.id = %s AND (%s::text IS NULL OR p.organization_id::text = %s);""",
                        (run_id, organization_id, organization_id),
                    )
                    row = cur.fetchone()
                    if row:
                        return _run_from_row(row)
                    return None

        with self._lock:
            if organization_id and self._run_org.get(run_id) != organization_id:
                return None
            return self._runs.get(run_id)

    def list_runs(self, organization_id: str | None = None, limit: int = 50) -> list[TestRunSummary]:
        """Console history: org-owned runs newest first. Never returns another tenant's runs."""
        conn = self._get_db()
        if conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT r.* FROM test_runs r
                        JOIN test_definition_revisions d ON d.id = r.definition_revision_id
                        JOIN test_plans p ON p.id = d.plan_id
                        WHERE (%s::text IS NULL OR p.organization_id::text = %s)
                        ORDER BY r.created_at DESC
                        LIMIT %s;""",
                        (organization_id, organization_id, limit),
                    )
                    rows = cur.fetchall()
            return [self._run_summary(_run_from_row(r), organization_id) for r in rows]

        with self._lock:
            runs = [
                r for rid, r in self._runs.items() if not organization_id or self._run_org.get(rid) == organization_id
            ]
            runs.sort(key=lambda r: r.created_at, reverse=True)
            page = runs[:limit]
        return [self._run_summary(r, organization_id) for r in page]

    def _lookup_driver_name(self, driver_id: str | None, organization_id: str | None) -> str | None:
        if not driver_id:
            return None
        try:
            from src.services.driver_directory import get_driver_directory

            rec = get_driver_directory().get_active_driver(organization_id or "", driver_id)
            if rec and rec.display_name:
                return rec.display_name
        except Exception:
            pass
        conn = self._get_db()
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT COALESCE(display_name, external_ref) AS name
                        FROM app.drivers
                        WHERE (id::text = %s OR external_ref = %s)
                          AND (%s::text IS NULL OR organization_id::text = %s);""",
                        (driver_id, driver_id, organization_id, organization_id),
                    )
                    row = cur.fetchone()
                    if row and row.get("name"):
                        return str(row["name"])
            except Exception:
                pass
        try:
            from src.services.case_service import get_case_service

            cs = get_case_service()
            drv = getattr(cs, "_drivers", {}).get(driver_id)
            if drv and isinstance(drv, dict):
                return drv.get("display_name") or drv.get("driver_name") or drv.get("external_ref")
        except Exception:
            pass
        return None

    def _run_summary(self, run: TestRunResponse, organization_id: str | None = None) -> TestRunSummary:
        org = organization_id or self._run_org.get(run.id)
        definition = (
            self.get_definition_revision(run.definition_revision_id, org)
            if self.settings.test_database_url
            else self._definitions.get(run.definition_revision_id)
        )
        origin_address = None
        pickup_address = None
        destination_address = None
        license_plate = None
        driver_name = None

        if definition:
            if definition.initial_snapshot:
                origin_address = definition.initial_snapshot.address
            if definition.pickup_snapshot:
                pickup_address = definition.pickup_snapshot.address
            if definition.destination_snapshot:
                destination_address = definition.destination_snapshot.address
            if definition.driver_config:
                license_plate = definition.driver_config.vehicle_plate
                driver_name = self._lookup_driver_name(definition.driver_config.driver_id, org)

        # Lookup publish receipt
        predicted_label = None
        error_type = None
        confidence = None
        case_id = None

        receipt = self.get_publish_submission(run.id, org or "", include_processing=True) if org else None
        if receipt:
            resp_data = receipt.get("response") or {}
            proc_data = receipt.get("result") or {}
            assessment = proc_data.get("assessment") or {}
            case_id = resp_data.get("case_id") or proc_data.get("case_id")
            cat = proc_data.get("category") or assessment.get("category")
            conf = proc_data.get("confidence") or assessment.get("confidence")
            predicted_label = cat
            confidence = float(conf) if conf is not None else None
            if cat and cat != "no_violation":
                error_type = proc_data.get("error_type") or cat

        if not case_id and org:
            cases = self.list_cases(run_id=str(run.id), organization_id=org)
            if cases:
                first_case = cases[0]
                case_id = first_case.get("id")
                anomalies = first_case.get("anomaly_types") or []
                if not predicted_label and anomalies:
                    predicted_label = anomalies[0]
                    error_type = anomalies[0]
                if confidence is None and first_case.get("risk_score") is not None:
                    confidence = float(first_case["risk_score"])

        return TestRunSummary(
            id=run.id,
            title=run.title,
            status=run.status,
            trip_id=run.trip_id,
            created_at=run.created_at,
            completed_at=run.completed_at,
            cancellation_actor=run.cancellation_actor,
            cancellation_reason=run.cancellation_reason,
            source=run.source,
            expected_label=run.expected_label,
            predicted_label=predicted_label,
            error_type=error_type,
            confidence=confidence,
            case_id=case_id,
            license_plate=license_plate,
            driver_name=driver_name,
            origin_address=origin_address,
            pickup_address=pickup_address,
            destination_address=destination_address,
        )

    def update_run_title(self, run_id: UUID, title: str, organization_id: str | None = None) -> TestRunResponse | None:
        cleaned = title.strip()
        if not cleaned:
            raise ValueError("Title must not be blank")
        conn = self._get_db()
        if conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """UPDATE test_runs r SET title = %s
                        WHERE r.id = %s AND EXISTS (
                            SELECT 1 FROM test_definition_revisions d
                            JOIN test_plans p ON p.id = d.plan_id
                            WHERE d.id = r.definition_revision_id
                              AND (%s::text IS NULL OR p.organization_id::text = %s)
                        )
                        RETURNING *;""",
                        (cleaned, run_id, organization_id, organization_id),
                    )
                    row = cur.fetchone()
                    return _run_from_row(row) if row else None

        with self._lock:
            if organization_id and self._run_org.get(run_id) != organization_id:
                return None
            r = self._runs.get(run_id)
            if not r:
                return None
            updated = r.model_copy(update={"title": cleaned})
            self._runs[run_id] = updated
            return updated

    def update_run_status(
        self,
        run_id: UUID | str,
        status: TestRunStatus,
        current_step: int | None = None,
        simulation_clock: datetime | None = None,
        cancellation_actor: str | None = None,
        cancellation_reason: str | None = None,
    ) -> None:
        if isinstance(run_id, str):
            run_id = UUID(run_id)
        conn = self._get_db()
        now = datetime.now(UTC)
        started_at = now if status == "RUNNING" else None
        completed_at = now if status in ("COMPLETED", "CANCELLED", "FAILED") else None
        cancelled_at = now if status == "CANCELLED" else None

        if conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE test_runs
                        SET status = %s,
                            current_step = coalesce(%s, current_step),
                            simulation_clock = coalesce(%s, simulation_clock),
                            started_at = coalesce(started_at, %s),
                            completed_at = coalesce(completed_at, %s),
                            cancelled_at = coalesce(cancelled_at, %s),
                            cancellation_actor = coalesce(%s, cancellation_actor),
                            cancellation_reason = coalesce(%s, cancellation_reason)
                        WHERE id = %s;
                        """,
                        (
                            status,
                            current_step,
                            simulation_clock,
                            started_at,
                            completed_at,
                            cancelled_at,
                            cancellation_actor,
                            cancellation_reason,
                            run_id,
                        ),
                    )
            return

        with self._lock:
            r = self._runs.get(run_id)
            if r:
                updates: dict[str, Any] = {
                    "status": status,
                    "current_step": current_step if current_step is not None else r.current_step,
                    "simulation_clock": simulation_clock if simulation_clock is not None else r.simulation_clock,
                    "started_at": now if status == "RUNNING" and not r.started_at else r.started_at,
                    "completed_at": now
                    if status in ("COMPLETED", "CANCELLED", "FAILED") and not r.completed_at
                    else r.completed_at,
                }
                if cancelled_at and not r.cancelled_at:
                    updates["cancelled_at"] = cancelled_at
                if cancellation_actor:
                    updates["cancellation_actor"] = cancellation_actor
                if cancellation_reason:
                    updates["cancellation_reason"] = cancellation_reason
                self._runs[run_id] = r.model_copy(update=updates)

    def claim_next_queued_run(self) -> TestRunResponse | None:
        """Atomic leasing with SELECT FOR UPDATE SKIP LOCKED where possible."""
        conn = self._get_db()
        if conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT * FROM test_runs
                        WHERE status = 'QUEUED'
                        ORDER BY created_at ASC
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED;
                        """
                    )
                    row = cur.fetchone()
                    if row:
                        cur.execute("UPDATE test_runs SET status = 'RUNNING' WHERE id = %s;", (row["id"],))
                        row["status"] = "RUNNING"
                        row["started_at"] = datetime.now(UTC)
                        return _run_from_row(row)
                    return None

        with self._lock:
            for r in self._runs.values():
                if r.status == "QUEUED":
                    updated = r.model_copy(update={"status": "RUNNING", "started_at": datetime.now(UTC)})
                    self._runs[r.id] = updated
                    return updated
            return None

    # -----------------------------------------------------------------------
    # Controls & Samples
    # -----------------------------------------------------------------------
    def append_control(self, run_id: UUID, command: str, payload: dict[str, Any]) -> None:
        ctrl_id = uuid4()
        now = datetime.now(UTC)
        conn = self._get_db()
        if conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO test_controls (id, run_id, command, payload, executed_at) VALUES (%s, %s, %s, %s, %s);",
                        (ctrl_id, run_id, command, json.dumps(payload), now),
                    )
            return

        with self._lock:
            self._controls.append(
                {
                    "id": ctrl_id,
                    "run_id": run_id,
                    "command": command,
                    "payload": payload,
                    "executed_at": now,
                }
            )

    def save_sample(self, sample: TestTelemetrySample) -> None:
        conn = self._get_db()
        if conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO test_samples (
                            id, run_id, step_index, latitude, longitude, speed_mps, heading_deg, is_fault_injected, fault_type, emitted_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                        """,
                        (
                            uuid4(),
                            sample.run_id,
                            sample.step_index,
                            sample.latitude,
                            sample.longitude,
                            sample.speed_mps,
                            sample.heading_deg,
                            sample.is_fault_injected,
                            sample.fault_type,
                            sample.emitted_at,
                        ),
                    )
            return

        with self._lock:
            self._samples.append(sample.model_dump())

    def get_samples(self, run_id: UUID | str, limit: int = 100) -> list[TestTelemetrySample]:
        if isinstance(run_id, str):
            run_id = UUID(run_id)
        conn = self._get_db()
        if conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT * FROM test_samples WHERE run_id = %s ORDER BY step_index ASC LIMIT %s;",
                        (run_id, limit),
                    )
                    rows = cur.fetchall()
                    return [TestTelemetrySample(**r) for r in rows]

        with self._lock:
            matching = [s for s in self._samples if s["run_id"] == run_id]
            matching.sort(key=lambda x: x["step_index"])
            return [TestTelemetrySample(**s) for s in matching[:limit]]

    def record_notification(
        self, run_id: UUID, recipient_type: str, recipient_id: str, channel: str, body: str
    ) -> None:
        """Sandbox Mock Sink logging."""
        conn = self._get_db()
        now = datetime.now(UTC)
        if conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO test_notifications (id, run_id, recipient_type, recipient_id, channel, body, intercepted_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s);
                        """,
                        (uuid4(), run_id, recipient_type, recipient_id, channel, body, now),
                    )
            return

        with self._lock:
            self._notifications.append(
                {
                    "id": uuid4(),
                    "run_id": run_id,
                    "recipient_type": recipient_type,
                    "recipient_id": recipient_id,
                    "channel": channel,
                    "body": body,
                    "intercepted_at": now,
                }
            )

    def get_notifications(self, run_id: UUID) -> list[dict[str, Any]]:
        """Returns intercepted sandbox mock notifications for a simulation run."""
        conn = self._get_db()
        if conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, run_id, recipient_type, recipient_id, channel, body, intercepted_at
                        FROM test_notifications
                        WHERE run_id = %s
                        ORDER BY intercepted_at ASC;
                        """,
                        (run_id,),
                    )
                    return [
                        {
                            "id": str(r["id"]),
                            "run_id": str(r["run_id"]),
                            "recipient_type": r["recipient_type"],
                            "recipient_id": r["recipient_id"],
                            "channel": r["channel"],
                            "body": r["body"],
                            "intercepted_at": r["intercepted_at"].isoformat()
                            if hasattr(r["intercepted_at"], "isoformat")
                            else str(r["intercepted_at"]),
                        }
                        for r in cur.fetchall()
                    ]

        with self._lock:
            return [
                {
                    "id": str(n["id"]),
                    "run_id": str(n["run_id"]),
                    "recipient_type": n["recipient_type"],
                    "recipient_id": n["recipient_id"],
                    "channel": n["channel"],
                    "body": n["body"],
                    "intercepted_at": n["intercepted_at"].isoformat()
                    if hasattr(n["intercepted_at"], "isoformat")
                    else str(n["intercepted_at"]),
                }
                for n in self._notifications
                if str(n["run_id"]) == str(run_id)
            ]

    # -----------------------------------------------------------------------
    # Transactional Outbox Pattern
    # -----------------------------------------------------------------------
    def create_outbox_event(self, aggregate_type: str, aggregate_id: str, payload: dict[str, Any]) -> None:
        outbox_id = uuid4()
        now = datetime.now(UTC)
        conn = self._get_db()
        if conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO test_outbox (id, aggregate_type, aggregate_id, payload, processed, created_at)
                        VALUES (%s, %s, %s, %s, false, %s);
                        """,
                        (outbox_id, aggregate_type, aggregate_id, json.dumps(payload), now),
                    )
            return

        with self._lock:
            self._outbox.append(
                {
                    "id": outbox_id,
                    "aggregate_type": aggregate_type,
                    "aggregate_id": aggregate_id,
                    "payload": payload,
                    "processed": False,
                    "created_at": now,
                }
            )

    def fetch_unprocessed_outbox(self, limit: int = 50) -> list[dict[str, Any]]:
        conn = self._get_db()
        if conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, aggregate_type, aggregate_id, payload, created_at
                        FROM test_outbox
                        WHERE processed = false
                        ORDER BY created_at ASC
                        LIMIT %s
                        FOR UPDATE SKIP LOCKED;
                        """,
                        (limit,),
                    )
                    return cur.fetchall()  # type: ignore[no-any-return]

        with self._lock:
            return [item for item in self._outbox if not item["processed"]][:limit]

    def mark_outbox_processed(self, outbox_id: UUID) -> None:
        conn = self._get_db()
        if conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("UPDATE test_outbox SET processed = true WHERE id = %s;", (outbox_id,))
            return

        with self._lock:
            for item in self._outbox:
                if item["id"] == outbox_id:
                    item["processed"] = True
                    break

    def create_case(self, case_data: dict[str, Any]) -> dict[str, Any]:
        """Persist an isolated case snapshot anchored to its owned simulation run."""
        cid = str(case_data["id"])
        conn = self._get_db()
        if conn:
            conn.execute(
                "INSERT INTO test_cases (id, run_id, payload) VALUES (%s, %s, %s::jsonb) "
                "ON CONFLICT (id) DO UPDATE SET payload = EXCLUDED.payload WHERE test_cases.run_id = EXCLUDED.run_id",
                (cid, case_data["run_id"], json.dumps(case_data, default=str)),
            )
        else:
            with self._lock:
                self._cases[cid] = dict(case_data)
        return case_data

    def get_case(self, case_id: str, organization_id: str | None = None) -> dict[str, Any] | None:
        conn = self._get_db()
        if conn:
            row = conn.execute(
                """SELECT c.payload FROM test_cases c
                JOIN test_runs r ON r.id = c.run_id
                JOIN test_definition_revisions d ON d.id = r.definition_revision_id
                JOIN test_plans p ON p.id = d.plan_id
                WHERE c.id = %s AND (%s::text IS NULL OR p.organization_id::text = %s)""",
                (case_id, organization_id, organization_id),
            ).fetchone()
            return dict(row["payload"]) if row else None
        with self._lock:
            case = self._cases.get(case_id)
            if not case:
                return None
            if organization_id and self._run_org.get(UUID(str(case["run_id"]))) != organization_id:
                return None
            return dict(case)

    def list_cases(
        self,
        run_id: str | None = None,
        trip_id: str | None = None,
        status: str | None = None,
        anomaly_types: list[str] | None = None,
        risk_score_min: float | None = None,
        limit: int = 100,
        organization_id: str | None = None,
    ) -> list[dict[str, Any]]:
        conn = self._get_db()
        if conn:
            rows = conn.execute(
                """SELECT c.payload FROM test_cases c
                JOIN test_runs r ON r.id = c.run_id
                JOIN test_definition_revisions d ON d.id = r.definition_revision_id
                JOIN test_plans p ON p.id = d.plan_id
                WHERE (%s::text IS NULL OR p.organization_id::text = %s)""",
                (organization_id, organization_id),
            ).fetchall()
            cases = [dict(row["payload"]) for row in rows]
        else:
            with self._lock:
                cases = [
                    dict(c)
                    for c in self._cases.values()
                    if not organization_id or self._run_org.get(UUID(str(c["run_id"]))) == organization_id
                ]
        result = []
        for case in cases:
            if run_id and str(case.get("run_id")) != str(run_id):
                continue
            if trip_id and str(case.get("trip_id")) != str(trip_id):
                continue
            if status and case.get("status") != status:
                continue
            if risk_score_min is not None and float(case.get("risk_score", 0)) < risk_score_min:
                continue
            if anomaly_types and not any(a in case.get("anomaly_types", []) for a in anomaly_types):
                continue
            result.append(case)
        result.sort(key=lambda c: str(c.get("created_at", "")), reverse=True)
        return result[:limit]

    def triage_case(
        self, case_id: str, decision: str, rationale: str, organization_id: str | None = None
    ) -> dict[str, Any]:
        case = self.get_case(case_id, organization_id)
        if case is None:
            raise ValueError("Test case not found")
        new_status = {"INVESTIGATE": "UNDER_REVIEW", "APPROVE_LEGITIMATE": "CLOSED", "SANCTION_SUSPEND": "CLOSED"}[
            decision
        ]
        timestamp = datetime.now(UTC)
        result = {
            "case_id": case_id,
            "decision": decision,
            "new_status": new_status,
            "rationale": rationale,
            "audit_event_id": str(uuid4()),
            "timestamp": timestamp,
        }
        case["status"] = new_status
        case.setdefault("triage_history", []).append({**result, "timestamp": timestamp.isoformat()})
        self.create_case(case)
        return result

    # -----------------------------------------------------------------------
    # Preset Batch Runs & Trips (Issue #458)
    # -----------------------------------------------------------------------
    @staticmethod
    def _preset_batch_run_from_row(row: dict[str, Any]) -> PresetBatchRunResponse:
        params = row["params"] if isinstance(row["params"], dict) else json.loads(row["params"])
        counters = row["counters"] if isinstance(row["counters"], dict) else json.loads(row["counters"])
        return PresetBatchRunResponse(
            id=row["id"],
            organization_id=str(row["organization_id"]),
            preset_id=row["preset_id"],
            params=params,
            status=row["status"],
            counters=counters,
            created_at=row["created_at"],
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
            cancelled_at=row.get("cancelled_at"),
        )

    @staticmethod
    def _preset_batch_trip_from_row(row: dict[str, Any]) -> PresetBatchTripResponse:
        snapshot = row["snapshot"] if isinstance(row["snapshot"], dict) else json.loads(row["snapshot"])
        trip_order = row.get("trip_order") if "trip_order" in row else row.get("order", 0)
        raw_driver_id = row.get("driver_id") or snapshot.get("driver_id")
        driver_id = str(raw_driver_id) if raw_driver_id else None
        driver_name = row.get("driver_name") or snapshot.get("driver_name")
        return PresetBatchTripResponse(
            id=row["id"],
            batch_id=row["batch_id"],
            trip_ref=row["trip_ref"],
            trip_order=trip_order,
            status=row["status"],
            driver_id=driver_id,
            driver_name=driver_name,
            expected_label=row.get("expected_label"),
            predicted_label=row.get("predicted_label"),
            confidence=row.get("confidence"),
            case_id=row.get("case_id"),
            run_id=row.get("run_id"),
            error=row.get("error"),
            created_at=row["created_at"],
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
            snapshot=snapshot,
        )

    def create_preset_batch_run(
        self,
        batch_id: UUID,
        organization_id: str,
        preset_id: str,
        params: dict[str, Any],
        total_trips: int,
    ) -> PresetBatchRunResponse:
        now = datetime.now(UTC)
        counters = {
            "total_trips": total_trips,
            "queued": total_trips,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "skipped": 0,
            "cancelled": 0,
            "reached_classifier": 0,
        }
        conn = self._get_db()
        if conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO preset_batch_runs (
                            id, organization_id, preset_id, params, status, counters, created_at
                        ) VALUES (%s, %s, %s, %s, 'QUEUED', %s, %s)
                        RETURNING *;
                        """,
                        (batch_id, str(organization_id), preset_id, json.dumps(params), json.dumps(counters), now),
                    )
                    row = cur.fetchone()
                    return self._preset_batch_run_from_row(row)

        with self._lock:
            resp = PresetBatchRunResponse(
                id=batch_id,
                organization_id=str(organization_id),
                preset_id=preset_id,
                params=params,
                status="QUEUED",
                counters=counters,
                created_at=now,
            )
            self._preset_batches[batch_id] = resp
            self._preset_batch_trips[batch_id] = []
            return resp

    def get_preset_batch_run(self, batch_id: UUID, organization_id: str | None = None) -> PresetBatchRunResponse | None:
        conn = self._get_db()
        if conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT * FROM preset_batch_runs
                        WHERE id = %s AND (%s::text IS NULL OR organization_id::text = %s);
                        """,
                        (
                            batch_id,
                            str(organization_id) if organization_id else None,
                            str(organization_id) if organization_id else None,
                        ),
                    )
                    row = cur.fetchone()
                    if row:
                        return self._preset_batch_run_from_row(row)
                    return None

        with self._lock:
            batch = self._preset_batches.get(batch_id)
            if not batch:
                return None
            if organization_id and str(batch.organization_id) != str(organization_id):
                return None
            return batch

    def create_preset_batch_trip(
        self,
        trip_id: UUID,
        batch_id: UUID,
        organization_id: str,
        trip_ref: str,
        trip_order: int | None = None,
        expected_label: str | None = None,
        snapshot: dict[str, Any] | None = None,
        driver_id: UUID | str | None = None,
        driver_name: str | None = None,
        *,
        order: int | None = None,
    ) -> PresetBatchTripResponse:
        now = datetime.now(UTC)
        effective_order = trip_order if trip_order is not None else (order if order is not None else 0)
        snapshot_dict = dict(snapshot or {})
        d_id = str(driver_id) if driver_id else None
        if d_id:
            snapshot_dict["driver_id"] = d_id
        if driver_name:
            snapshot_dict["driver_name"] = driver_name
        conn = self._get_db()
        if conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    try:
                        cur.execute(
                            """
                            INSERT INTO preset_batch_trips (
                                id, batch_id, organization_id, trip_ref, trip_order, status, expected_label, snapshot, driver_id, driver_name, created_at
                            ) VALUES (%s, %s, %s, %s, %s, 'QUEUED', %s, %s, %s, %s, %s)
                            RETURNING *;
                            """,
                            (
                                trip_id,
                                batch_id,
                                str(organization_id),
                                trip_ref,
                                effective_order,
                                expected_label,
                                json.dumps(snapshot_dict),
                                d_id,
                                driver_name,
                                now,
                            ),
                        )
                        row = cur.fetchone()
                        return self._preset_batch_trip_from_row(row)
                    except Exception:
                        cur.execute(
                            """
                            INSERT INTO preset_batch_trips (
                                id, batch_id, organization_id, trip_ref, trip_order, status, expected_label, snapshot, created_at
                            ) VALUES (%s, %s, %s, %s, %s, 'QUEUED', %s, %s, %s)
                            RETURNING *;
                            """,
                            (
                                trip_id,
                                batch_id,
                                str(organization_id),
                                trip_ref,
                                effective_order,
                                expected_label,
                                json.dumps(snapshot_dict),
                                now,
                            ),
                        )
                        row = cur.fetchone()
                        return self._preset_batch_trip_from_row(row)

        with self._lock:
            trip_resp = PresetBatchTripResponse(
                id=trip_id,
                batch_id=batch_id,
                trip_ref=trip_ref,
                trip_order=effective_order,
                status="QUEUED",
                driver_id=d_id,
                driver_name=driver_name,
                expected_label=expected_label,
                snapshot=snapshot_dict,
                created_at=now,
            )
            self._preset_batch_trips.setdefault(batch_id, []).append(trip_resp)
            return trip_resp

    def list_preset_batch_trips(
        self, batch_id: UUID, organization_id: str | None = None
    ) -> list[PresetBatchTripResponse]:
        conn = self._get_db()
        if conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT t.* FROM preset_batch_trips t
                        JOIN preset_batch_runs b ON b.id = t.batch_id
                        WHERE t.batch_id = %s AND (%s::text IS NULL OR b.organization_id::text = %s)
                        ORDER BY t.trip_order ASC;
                        """,
                        (
                            batch_id,
                            str(organization_id) if organization_id else None,
                            str(organization_id) if organization_id else None,
                        ),
                    )
                    rows = cur.fetchall()
                    return [self._preset_batch_trip_from_row(r) for r in rows]

        with self._lock:
            batch = self._preset_batches.get(batch_id)
            if not batch or (organization_id and str(batch.organization_id) != str(organization_id)):
                return []
            trips = self._preset_batch_trips.get(batch_id, [])
            return sorted(trips, key=lambda t: t.trip_order)

    def update_preset_batch_trip(
        self,
        batch_id: UUID,
        trip_id: UUID,
        *,
        status: str | None = None,
        predicted_label: str | None = None,
        confidence: float | None = None,
        case_id: str | None = None,
        run_id: UUID | None = None,
        error: str | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        conn = self._get_db()
        if conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    updates = []
                    params = []
                    if status is not None:
                        updates.append("status = %s")
                        params.append(status)
                    if predicted_label is not None:
                        updates.append("predicted_label = %s")
                        params.append(predicted_label)
                    if confidence is not None:
                        updates.append("confidence = %s")
                        params.append(confidence)
                    if case_id is not None:
                        updates.append("case_id = %s")
                        params.append(case_id)
                    if run_id is not None:
                        updates.append("run_id = %s")
                        params.append(run_id)
                    if error is not None:
                        updates.append("error = %s")
                        params.append(error)
                    if started_at is not None:
                        updates.append("started_at = %s")
                        params.append(started_at)
                    if completed_at is not None:
                        updates.append("completed_at = %s")
                        params.append(completed_at)
                    if updates:
                        sql = f"UPDATE preset_batch_trips SET {', '.join(updates)} WHERE id = %s AND batch_id = %s;"
                        params.extend([trip_id, batch_id])
                        cur.execute(sql, tuple(params))
            return

        with self._lock:
            trips = self._preset_batch_trips.get(batch_id, [])
            for t in trips:
                if t.id == trip_id:
                    if status is not None:
                        t.status = status
                    if predicted_label is not None:
                        t.predicted_label = predicted_label
                    if confidence is not None:
                        t.confidence = confidence
                    if case_id is not None:
                        t.case_id = case_id
                    if run_id is not None:
                        t.run_id = run_id
                    if error is not None:
                        t.error = error
                    if started_at is not None:
                        t.started_at = started_at
                    if completed_at is not None:
                        t.completed_at = completed_at
                    break

    def update_preset_batch_status(
        self,
        batch_id: UUID,
        status: str,
        *,
        counters: dict[str, Any] | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        cancelled_at: datetime | None = None,
    ) -> None:
        conn = self._get_db()
        if conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    updates = ["status = %s"]
                    params: list[Any] = [status]
                    if counters is not None:
                        updates.append("counters = %s")
                        params.append(json.dumps(counters))
                    if started_at is not None:
                        updates.append("started_at = %s")
                        params.append(started_at)
                    if completed_at is not None:
                        updates.append("completed_at = %s")
                        params.append(completed_at)
                    if cancelled_at is not None:
                        updates.append("cancelled_at = %s")
                        params.append(cancelled_at)
                    sql = f"UPDATE preset_batch_runs SET {', '.join(updates)} WHERE id = %s;"
                    params.append(batch_id)
                    cur.execute(sql, tuple(params))
            return

        with self._lock:
            batch = self._preset_batches.get(batch_id)
            if batch:
                batch.status = status
                if counters is not None:
                    batch.counters = counters
                if started_at is not None:
                    batch.started_at = started_at
                if completed_at is not None:
                    batch.completed_at = completed_at
                if cancelled_at is not None:
                    batch.cancelled_at = cancelled_at

    def get_preset_batch_detail(
        self, batch_id: UUID, organization_id: str | None = None
    ) -> PresetBatchRunDetailResponse | None:
        batch = self.get_preset_batch_run(batch_id, organization_id)
        if not batch:
            return None
        trips = self.list_preset_batch_trips(batch_id, organization_id)
        return PresetBatchRunDetailResponse(
            id=batch.id,
            organization_id=batch.organization_id,
            preset_id=batch.preset_id,
            params=batch.params,
            status=batch.status,
            counters=batch.counters,
            created_at=batch.created_at,
            started_at=batch.started_at,
            completed_at=batch.completed_at,
            cancelled_at=batch.cancelled_at,
            trips=trips,
        )

    def save_preset_batch_event(self, batch_id: UUID, event: PresetBatchEvent) -> None:
        with self._lock:
            events = self._preset_batch_events.setdefault(batch_id, [])
            events.append(event)
            subs = self._preset_batch_subscribers.get(batch_id, [])
            for q in subs:
                q.put_nowait(event)

    def get_preset_batch_events(self, batch_id: UUID, after_event_id: str | None = None) -> list[PresetBatchEvent]:
        with self._lock:
            events = list(self._preset_batch_events.get(batch_id, []))
            if not after_event_id:
                return events
            idx = -1
            for i, ev in enumerate(events):
                if str(ev.event_id) == str(after_event_id):
                    idx = i
                    break
            if idx >= 0:
                return events[idx + 1 :]
            return events

    def subscribe_preset_batch_stream(
        self, batch_id: UUID, last_event_id: str | None = None
    ) -> asyncio.Queue[PresetBatchEvent]:
        q: asyncio.Queue[PresetBatchEvent] = asyncio.Queue()
        with self._lock:
            events = self.get_preset_batch_events(batch_id, after_event_id=last_event_id)
            for ev in events:
                q.put_nowait(ev)
            self._preset_batch_subscribers.setdefault(batch_id, []).append(q)
        return q

    def unsubscribe_preset_batch_stream(self, batch_id: UUID, queue: asyncio.Queue[PresetBatchEvent]) -> None:
        with self._lock:
            subs = self._preset_batch_subscribers.get(batch_id, [])
            if queue in subs:
                subs.remove(queue)
