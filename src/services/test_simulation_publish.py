"""Submit owned simulation evidence through the canonical telemetry processor."""

from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import HTTPException

from src.models.test_simulation import ProductionPublishResponse, PublishProductionPayload
from src.services.case_service import CaseService
from src.services.telemetry_queue_worker import process_telemetry_event
from src.services.test_simulation_repository import TestSimulationRepository


def _snapshot_coordinates(snapshot: object, label: str) -> dict[str, list[float]]:
    if snapshot is None:
        raise HTTPException(status_code=409, detail=f"Simulation definition has no recorded {label} snapshot")
    location = getattr(snapshot, "location", None)
    if location is None:
        raise HTTPException(status_code=409, detail=f"Simulation definition has no recorded {label} snapshot")
    return {"coordinates": [location.longitude, location.latitude]}


def _publish_identity(organization_id: str, run_id: UUID, kind: str) -> str:
    """Return a stable identity so a client retry replays the same ingestion."""
    return str(uuid5(NAMESPACE_URL, f"greensentinel:test-console:publish:{organization_id}:{run_id}:{kind}"))


async def publish_simulation(
    repository: TestSimulationRepository,
    run_id: UUID,
    payload: PublishProductionPayload | None,
    organization_id: str,
    service: CaseService,
) -> ProductionPublishResponse:
    async with repository.publish_lock(run_id, organization_id):
        return await _publish_simulation_locked(repository, run_id, payload, organization_id, service)


async def _publish_simulation_locked(
    repository: TestSimulationRepository,
    run_id: UUID,
    payload: PublishProductionPayload | None,
    organization_id: str,
    service: CaseService,
) -> ProductionPublishResponse:
    run = repository.get_run(run_id, organization_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Simulation run not found")
    if run.status not in {"COMPLETED", "CANCELLED"}:
        raise HTTPException(status_code=409, detail="Simulation run must be terminal before publishing")
    prior = repository.get_publish_submission(run_id, organization_id)
    if prior is not None:
        return ProductionPublishResponse.model_validate(prior)
    if payload is None or not all(
        [payload.driver_id, payload.passenger_id, payload.vehicle_id, payload.policy_version_id]
    ):
        raise HTTPException(
            status_code=422, detail="driver_id, passenger_id, vehicle_id and policy_version_id are required"
        )
    # The canonical processor accepts bounded manual submissions. Request one
    # sentinel row so oversized runs are rejected instead of silently losing
    # recorded evidence at the 2,000-row boundary.
    samples = repository.get_samples(run_id, limit=2001)
    if not samples:
        raise HTTPException(status_code=409, detail="Simulation has no recorded telemetry")
    if len(samples) > 2000:
        raise HTTPException(status_code=413, detail="Simulation telemetry exceeds the 2,000-sample limit")
    definition = repository.get_definition_revision(run.definition_revision_id, organization_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="Definition revision not found")
    points = [
        {
            "occurred_at": s.emitted_at.isoformat(),
            "latitude": s.latitude,
            "longitude": s.longitude,
            "speed_mps": s.speed_mps,
            "heading_deg": s.heading_deg,
        }
        for s in samples
    ]
    lifecycle_state = "cancelled" if run.status == "CANCELLED" else "completed"
    pickup_address = payload.pickup_address or (
        definition.pickup_snapshot.address if definition.pickup_snapshot else None
    )
    dropoff_address = payload.dropoff_address or (
        definition.destination_snapshot.address if definition.destination_snapshot else None
    )
    event = {
        "event_id": _publish_identity(organization_id, run_id, "event"),
        "trip_id": run.trip_id or _publish_identity(organization_id, run_id, "trip"),
        "assignment_id": _publish_identity(organization_id, run_id, "assignment"),
        "organization_id": organization_id,
        "driver_id": payload.driver_id,
        "passenger_id": payload.passenger_id,
        "vehicle_id": payload.vehicle_id,
        "policy_version_id": payload.policy_version_id,
        "lifecycle_state": lifecycle_state,
        "points": points,
        "pickup": _snapshot_coordinates(definition.pickup_snapshot, "pickup"),
        "dropoff": _snapshot_coordinates(definition.destination_snapshot, "destination"),
        "pickup_address": pickup_address,
        "dropoff_address": dropoff_address,
        "messages": [
            {"role": m.sender_role.lower(), "text": m.content, "offset_seconds": m.offset_seconds}
            for m in definition.messages
        ],
    }
    if run.cancellation_actor:
        event["cancellation_actor"] = run.cancellation_actor
    if run.cancellation_reason:
        event["cancellation_reason"] = run.cancellation_reason
    try:
        result = await process_telemetry_event(event, service, organization_id=organization_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Telemetry submission failed") from exc
    if result.get("status") != "processed":
        raise HTTPException(status_code=503, detail="Telemetry submission was not persisted")
    case_id = str(result["case_id"]) if result.get("case_id") else None
    response = ProductionPublishResponse(
        status="published",
        run_id=str(run_id),
        trip_id=str(result["trip_id"]),
        case_id=case_id,
        destination=f"/workplace?caseId={case_id}" if case_id else "/workplace",
    )
    repository.save_publish_submission(
        run_id,
        organization_id,
        {"response": response.model_dump(mode="json"), "result": result},
    )
    return response
