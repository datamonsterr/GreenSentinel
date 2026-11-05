"""Service layer for preset batch runs, scheduling, and SSE event streaming (Issue #458)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, TypeVar
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import HTTPException

from src.models.test_simulation import (
    DriverSimConfig,
    GeoJsonLineString,
    LatLon,
    PassengerSimConfig,
    PresetBatchEvent,
    PresetBatchRunCreate,
    TestDefinitionRevisionCreate,
    TestPlanCreate,
    TestRunCreate,
    TestStopSnapshot,
    TestTelemetrySample,
)
from src.services.case_service import CaseService, get_case_service
from src.services.telemetry_queue_worker import DEFAULT_POLICY_ID, process_telemetry_event
from src.services.test_presets import (
    materialize_preset_simulation_input,
)
from src.services.test_simulation_repository import TestSimulationRepository

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Injectable sleep callable for fast testing
_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


def validate_preset_batch_run_params(params: PresetBatchRunCreate, available_trips: int) -> int:
    """Validate preset batch parameters and return the effective trip limit (1..available)."""
    if params.trips_per_batch < 1:
        raise HTTPException(status_code=422, detail="trips_per_batch must be at least 1")
    if params.interval_s <= 0:
        raise HTTPException(status_code=422, detail="interval_s must be greater than 0")

    if params.trip_limit is None:
        return available_trips

    if params.trip_limit < 1 or params.trip_limit > available_trips:
        raise HTTPException(
            status_code=422,
            detail=f"trip_limit must be between 1 and {available_trips} available trips",
        )
    return params.trip_limit


def build_trip_compact_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    """Build a compact per-trip snapshot: conversation, GPS summary, speed stats."""
    conversation = [
        {
            "role": str(msg.get("role", "customer")),
            "text": str(msg.get("text") or msg.get("content") or ""),
            "sent_at_offset_s": int(msg.get("sent_at_offset_s") or msg.get("offset_seconds") or 0),
        }
        for msg in (record.get("conversation") or [])
    ]

    telemetry = record.get("telemetry") or []
    mock_location_count = sum(1 for pt in telemetry if pt.get("mock_location_reported"))
    accuracies = [float(pt["accuracy_m"]) for pt in telemetry if pt.get("accuracy_m") is not None]
    max_accuracy_m = max(accuracies) if accuracies else None

    lats = [float(pt["latitude"]) for pt in telemetry if pt.get("latitude") is not None]
    lons = [float(pt["longitude"]) for pt in telemetry if pt.get("longitude") is not None]

    bbox = (
        {
            "min_lat": min(lats),
            "max_lat": max(lats),
            "min_lon": min(lons),
            "max_lon": max(lons),
        }
        if lats and lons
        else None
    )

    speeds = [float(pt["speed_mps"]) for pt in telemetry if pt.get("speed_mps") is not None]
    min_mps = round(min(speeds), 2) if speeds else 0.0
    avg_mps = round(sum(speeds) / len(speeds), 2) if speeds else 0.0
    max_mps = round(max(speeds), 2) if speeds else 0.0

    return {
        "conversation": conversation,
        "gps_summary": {
            "points": len(telemetry),
            "bbox": bbox,
            "mock_location_count": mock_location_count,
            "max_accuracy_m": max_accuracy_m,
        },
        "speed_stats": {
            "min_mps": min_mps,
            "avg_mps": avg_mps,
            "max_mps": max_mps,
        },
    }


def _ensure_tenant_actors(
    service: CaseService,
    organization_id: str,
    passenger_id: str,
    vehicle_id: str,
) -> tuple[str, str]:
    """Ensure passenger and vehicle actor rows exist for this tenant when database is active.

    Note: Synthetic driver creation is strictly prohibited. Real Clerk-linked drivers
    must already exist in app.drivers.
    """
    conn = service._get_db_connection()
    if conn is None:
        return passenger_id, vehicle_id
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO app.organizations (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING;",
                    (organization_id, f"Org {organization_id}"),
                )
                cur.execute(
                    """
                    INSERT INTO app.passengers (id, organization_id, external_ref, is_synthetic)
                    VALUES (%s, %s, %s, TRUE)
                    ON CONFLICT (id) DO NOTHING;
                    """,
                    (passenger_id, organization_id, f"pax-sim-{passenger_id}"),
                )
                cur.execute(
                    """
                    INSERT INTO app.vehicles (id, organization_id, registration_ref, vehicle_type, service_class, telemetry_source)
                    VALUES (%s, %s, %s, 'car', 'GreenCar Standard', 'simulator')
                    ON CONFLICT (id) DO NOTHING;
                    """,
                    (vehicle_id, organization_id, f"SIM-{vehicle_id[:8]}"),
                )
        return passenger_id, vehicle_id
    except Exception as exc:
        logger.debug("Failed to ensure tenant actors directly: %s", exc)
        return passenger_id, vehicle_id
    finally:
        conn.close()


async def schedule_rate_limited_batches(
    items: list[T],
    trips_per_batch: int,
    interval_s: float,
    processor: Callable[[T], Awaitable[None]],
    sleeper: Callable[[float], Awaitable[None]] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> list[T]:
    """Execute items in rate-limited batches of size trips_per_batch every interval_s seconds.

    Returns any remaining unexecuted items if cancelled early.
    """
    actual_sleeper = sleeper if sleeper is not None else _sleep
    total = len(items)
    for i in range(0, total, trips_per_batch):
        if is_cancelled and is_cancelled():
            return items[i:]

        chunk = items[i : i + trips_per_batch]
        for item in chunk:
            if is_cancelled and is_cancelled():
                return items[items.index(item) :]
            await processor(item)

        # Sleep between batches if more items remain and not cancelled
        if i + trips_per_batch < total:
            if is_cancelled and is_cancelled():
                return items[i + trips_per_batch :]
            await actual_sleeper(interval_s)

    return []


async def run_preset_batch(
    batch_id: UUID,
    organization_id: str,
    preset_id: str,
    trips: list[tuple[UUID, str, dict[str, Any]]],
    repository: TestSimulationRepository,
    case_service: CaseService | None = None,
    sleeper: Callable[[float], Awaitable[None]] | None = None,
) -> None:
    """Background async worker that drives each preset batch trip through publish -> classifier."""
    actual_sleeper = sleeper if sleeper is not None else _sleep
    service = case_service or get_case_service()
    now = datetime.now(UTC)

    # Transition batch to RUNNING
    repository.update_preset_batch_status(batch_id, "RUNNING", started_at=now)

    batch = repository.get_preset_batch_run(batch_id, organization_id)
    if not batch:
        return

    params = batch.params or {}
    trips_per_batch = int(params.get("trips_per_batch", 1))
    interval_s = float(params.get("interval_s", 1.0))

    counters = dict(batch.counters)

    def is_cancelled() -> bool:
        b = repository.get_preset_batch_run(batch_id, organization_id)
        return b is not None and b.status == "CANCELLED"

    async def process_single_trip(trip_info: Any) -> None:
        if len(trip_info) >= 4:
            trip_id, trip_ref, record, assigned_driver = trip_info[:4]
        else:
            trip_id, trip_ref, record = trip_info[:3]
            from src.services.driver_directory import get_driver_directory

            active = get_driver_directory().list_active_drivers(organization_id)
            assigned_driver = active[0] if active else None

        from src.services.driver_directory import DriverRecord

        if assigned_driver is None:
            assigned_driver = DriverRecord(
                driver_id=uuid4(),
                organization_id=organization_id,
                principal_id=uuid4(),
                external_subject="user_unknown",
                display_name="Unknown Driver",
            )

        assigned_driver_id = str(assigned_driver.driver_id)
        assigned_driver_name = assigned_driver.display_name

        reached_classifier = False
        t_now = datetime.now(UTC)

        # 1. Update trip status -> RUNNING
        repository.update_preset_batch_trip(batch_id, trip_id, status="RUNNING", started_at=t_now)
        counters["running"] = counters.get("running", 0) + 1
        if counters.get("queued", 0) > 0:
            counters["queued"] -= 1

        # Emit trip.started
        repository.save_preset_batch_event(
            batch_id,
            PresetBatchEvent(
                event_type="trip.started",
                batch_id=batch_id,
                trip_ref=trip_ref,
                driver_id=assigned_driver_id,
                driver_name=assigned_driver_name,
                reached_classifier=False,
                data={"driver_id": assigned_driver_id, "driver_name": assigned_driver_name},
            ),
        )

        try:
            # 2. Telemetry loaded
            materialized = materialize_preset_simulation_input(
                record, organization_id=organization_id, preset_id=preset_id
            )
            repository.save_preset_batch_event(
                batch_id,
                PresetBatchEvent(
                    event_type="trip.telemetry_loaded",
                    batch_id=batch_id,
                    trip_ref=trip_ref,
                    driver_id=assigned_driver_id,
                    driver_name=assigned_driver_name,
                    reached_classifier=False,
                    data={"driver_id": assigned_driver_id, "driver_name": assigned_driver_name},
                ),
            )

            # 3. Create canonical plan & definition & completed test_run with source="preset_batch"
            coords = materialized["route_geometry"]["coordinates"]
            initial_snap = TestStopSnapshot(
                location=LatLon(latitude=coords[0][1], longitude=coords[0][0]),
                address=(materialized.get("pickup") or {}).get("address") or "Origin",
            )
            pickup_snap = TestStopSnapshot(
                location=LatLon(latitude=coords[0][1], longitude=coords[0][0]),
                address=(materialized.get("pickup") or {}).get("address") or "Pickup",
            )
            dest_snap = TestStopSnapshot(
                location=LatLon(latitude=coords[-1][1], longitude=coords[-1][0]),
                address=(materialized.get("dropoff") or {}).get("address") or "Dropoff",
            )

            plan_create = TestPlanCreate(
                name=f"Batch {preset_id} · {trip_ref}",
                description=f"Automated run from preset batch {batch_id}",
            )
            plan = repository.create_plan(plan_create, organization_id=organization_id)

            assigned_vehicle_id = (
                str(assigned_driver.vehicle_id) if assigned_driver.vehicle_id else materialized["vehicle_id"]
            )
            assigned_vehicle_plate = assigned_driver.license_plate or "29A-888.88"

            def_create = TestDefinitionRevisionCreate(
                plan_id=plan.id,
                route_geometry=GeoJsonLineString(**materialized["route_geometry"]),
                driver_config=DriverSimConfig(
                    driver_id=assigned_driver_id,
                    vehicle_plate=assigned_vehicle_plate,
                    speed_mps=12.0,
                ),
                passenger_config=PassengerSimConfig(
                    passenger_id=materialized["passenger_id"],
                ),
                initial_snapshot=initial_snap,
                pickup_snapshot=pickup_snap,
                destination_snapshot=dest_snap,
            )
            definition = repository.create_definition_revision(def_create, organization_id=organization_id)

            telemetry = materialized.get("telemetry") or []
            expected_label = materialized.get("label") or record.get("label")
            run_resp = repository.create_run(
                TestRunCreate(
                    definition_revision_id=definition.id,
                    title=f"Batch {preset_id} · {trip_ref}",
                    expected_label=expected_label,
                    source="preset_batch",
                ),
                total_steps=len(telemetry),
                organization_id=organization_id,
                source="preset_batch",
            )

            # Persist samples into test repository
            for idx, pt in enumerate(telemetry):
                repository.save_sample(
                    TestTelemetrySample(
                        run_id=run_resp.id,
                        step_index=idx,
                        latitude=float(pt["latitude"]),
                        longitude=float(pt["longitude"]),
                        speed_mps=float(pt.get("speed_mps", 0.0)),
                        heading_deg=float(pt.get("bearing_deg", 0.0)),
                        emitted_at=t_now,
                    )
                )

            # Fast-complete the run
            repository.update_run_status(run_resp.id, "COMPLETED")

            # Emit trip.published
            repository.save_preset_batch_event(
                batch_id,
                PresetBatchEvent(
                    event_type="trip.published",
                    batch_id=batch_id,
                    trip_ref=trip_ref,
                    driver_id=assigned_driver_id,
                    driver_name=assigned_driver_name,
                    reached_classifier=False,
                    data={"driver_id": assigned_driver_id, "driver_name": assigned_driver_name},
                ),
            )

            # 4. Ingest through telemetry processor -> classifier
            points = [
                {
                    "occurred_at": pt.get("occurred_at") or t_now.isoformat(),
                    "latitude": float(pt["latitude"]),
                    "longitude": float(pt["longitude"]),
                    "speed_mps": float(pt.get("speed_mps", 0.0)),
                    "bearing_deg": float(pt.get("bearing_deg", 0.0)),
                    "accuracy_m": float(pt["accuracy_m"]) if pt.get("accuracy_m") is not None else 5.0,
                    "mock_location_reported": bool(pt.get("mock_location_reported", False)),
                }
                for pt in telemetry
            ]

            passenger_id, vehicle_id = _ensure_tenant_actors(
                service=service,
                organization_id=organization_id,
                passenger_id=materialized["passenger_id"],
                vehicle_id=assigned_vehicle_id,
            )

            event_trip_id = str(uuid5(NAMESPACE_URL, f"p063:preset-batch:{batch_id}:{trip_ref}:trip"))

            event_payload = {
                "event_id": str(uuid4()),
                "trip_id": event_trip_id,
                "assignment_id": str(uuid4()),
                "organization_id": organization_id,
                "driver_id": assigned_driver_id,
                "passenger_id": passenger_id,
                "vehicle_id": vehicle_id,
                "policy_version_id": DEFAULT_POLICY_ID,
                "lifecycle_state": "cancelled" if materialized.get("cancellation_actor") else "completed",
                "points": points,
                "pickup": {"coordinates": [coords[0][0], coords[0][1]]},
                "dropoff": {"coordinates": [coords[-1][0], coords[-1][1]]},
                "messages": [
                    {
                        "role": m.get("role", "customer").lower(),
                        "text": m.get("text", ""),
                        "offset_seconds": int(m.get("sent_at_offset_s", 0)),
                    }
                    for m in materialized.get("conversation", [])
                ],
            }
            if materialized.get("cancellation_actor"):
                event_payload["cancellation_actor"] = materialized["cancellation_actor"]
            if materialized.get("cancellation_reason"):
                event_payload["cancellation_reason"] = materialized["cancellation_reason"]

            # Emit trip.classifier_received
            reached_classifier = True
            counters["reached_classifier"] = counters.get("reached_classifier", 0) + 1
            repository.save_preset_batch_event(
                batch_id,
                PresetBatchEvent(
                    event_type="trip.classifier_received",
                    batch_id=batch_id,
                    trip_ref=trip_ref,
                    driver_id=assigned_driver_id,
                    driver_name=assigned_driver_name,
                    reached_classifier=True,
                    data={"driver_id": assigned_driver_id, "driver_name": assigned_driver_name},
                ),
            )

            # Call classifier pipeline
            result = await process_telemetry_event(event_payload, service, organization_id=organization_id)

            predicted_label = result.get("category")
            confidence = float(result.get("confidence") or 0.0)
            case_id = str(result["case_id"]) if result.get("case_id") else None

            # Record published submission so GET /runs enrichment finds predicted_label, confidence, case_id
            repository.save_publish_submission(
                run_resp.id,
                organization_id,
                {
                    "response": {
                        "status": "published",
                        "run_id": str(run_resp.id),
                        "trip_id": str(result.get("trip_id") or event_trip_id),
                        "case_id": case_id,
                        "destination": f"/workplace?caseId={case_id}" if case_id else "/workplace",
                    },
                    "result": {
                        **result,
                        "category": predicted_label,
                        "confidence": confidence,
                        "case_id": case_id,
                    },
                },
            )

            # Mark trip completed
            repository.update_preset_batch_trip(
                batch_id,
                trip_id,
                status="COMPLETED",
                predicted_label=predicted_label,
                confidence=confidence,
                case_id=case_id,
                run_id=run_resp.id,
                completed_at=datetime.now(UTC),
            )
            counters["completed"] = counters.get("completed", 0) + 1
            if counters.get("running", 0) > 0:
                counters["running"] -= 1

            # Emit trip.classified
            repository.save_preset_batch_event(
                batch_id,
                PresetBatchEvent(
                    event_type="trip.classified",
                    batch_id=batch_id,
                    trip_ref=trip_ref,
                    driver_id=assigned_driver_id,
                    driver_name=assigned_driver_name,
                    label=predicted_label,
                    confidence=confidence,
                    reached_classifier=True,
                    data={"driver_id": assigned_driver_id, "driver_name": assigned_driver_name},
                ),
            )

            # Emit trip.case_created if applicable
            if case_id:
                repository.save_preset_batch_event(
                    batch_id,
                    PresetBatchEvent(
                        event_type="trip.case_created",
                        batch_id=batch_id,
                        trip_ref=trip_ref,
                        case_id=case_id,
                        reached_classifier=True,
                    ),
                )

        except Exception as exc:
            logger.warning("Preset batch trip %s execution failed: %s", trip_ref, exc)
            repository.update_preset_batch_trip(
                batch_id,
                trip_id,
                status="FAILED",
                error=str(exc),
                completed_at=datetime.now(UTC),
            )
            counters["failed"] = counters.get("failed", 0) + 1
            if counters.get("running", 0) > 0:
                counters["running"] -= 1

            repository.save_preset_batch_event(
                batch_id,
                PresetBatchEvent(
                    event_type="trip.failed",
                    batch_id=batch_id,
                    trip_ref=trip_ref,
                    reason=str(exc),
                    reached_classifier=reached_classifier,
                ),
            )

    # Run scheduler
    skipped = await schedule_rate_limited_batches(
        items=trips,
        trips_per_batch=trips_per_batch,
        interval_s=interval_s,
        processor=process_single_trip,
        sleeper=actual_sleeper,
        is_cancelled=is_cancelled,
    )

    # Handle any skipped trips
    for trip_id, trip_ref, _ in skipped:
        repository.update_preset_batch_trip(
            batch_id,
            trip_id,
            status="SKIPPED",
            completed_at=datetime.now(UTC),
        )
        counters["skipped"] = counters.get("skipped", 0) + 1
        if counters.get("queued", 0) > 0:
            counters["queued"] -= 1

        repository.save_preset_batch_event(
            batch_id,
            PresetBatchEvent(
                event_type="trip.skipped",
                batch_id=batch_id,
                trip_ref=trip_ref,
                reason="Batch cancelled by operator",
                reached_classifier=False,
            ),
        )

    end_now = datetime.now(UTC)
    if is_cancelled():
        repository.update_preset_batch_status(batch_id, "CANCELLED", counters=counters, cancelled_at=end_now)
        repository.save_preset_batch_event(
            batch_id,
            PresetBatchEvent(
                event_type="batch.cancelled",
                batch_id=batch_id,
                reached_classifier=False,
            ),
        )
    else:
        repository.update_preset_batch_status(batch_id, "COMPLETED", counters=counters, completed_at=end_now)
        repository.save_preset_batch_event(
            batch_id,
            PresetBatchEvent(
                event_type="batch.completed",
                batch_id=batch_id,
                reached_classifier=False,
            ),
        )
