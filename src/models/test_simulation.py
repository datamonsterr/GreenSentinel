"""Pydantic V2 schemas for SPEC-0130: Tester Trip Simulation & Evaluation Architecture."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class LatLon(BaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)


class GeoJsonLineString(BaseModel):
    type: Literal["LineString"] = "LineString"
    coordinates: list[list[float]] = Field(
        ...,
        min_length=2,
        description="List of [longitude, latitude] coordinate pairs",
    )


class GeoJsonMultiLineString(BaseModel):
    """Disjoint provider geometry; consumers must never flatten separate runs."""

    type: Literal["MultiLineString"] = "MultiLineString"
    coordinates: list[list[list[float]]] = Field(..., min_length=1)


class TestStopSnapshot(BaseModel):
    """User-selected stop evidence captured with a simulation definition."""

    __test__ = False

    location: LatLon
    address: str | None = None


# ---------------------------------------------------------------------------
# Fault Specifications
# ---------------------------------------------------------------------------
class JumpFault(BaseModel):
    kind: Literal["JUMP"] = "JUMP"
    at_offset_s: int = Field(..., ge=0, description="Offset in seconds from simulation start")
    displacement_m: float = Field(..., gt=0.0, description="Shift distance in meters")
    bearing_deg: float = Field(..., ge=0.0, lt=360.0, description="Bearing angle of displacement")


class OffsetNoiseFault(BaseModel):
    kind: Literal["OFFSET_NOISE"] = "OFFSET_NOISE"
    at_offset_s: int = Field(..., ge=0)
    duration_s: int = Field(..., gt=0)
    offset_m: float = Field(..., ge=0.0)
    noise_std_dev_m: float = Field(..., gt=0.0)
    seed: int | None = None


class DropoutFault(BaseModel):
    kind: Literal["DROPOUT"] = "DROPOUT"
    at_offset_s: int = Field(..., ge=0)
    duration_s: int = Field(..., gt=0)


FaultConfig = Annotated[
    JumpFault | OffsetNoiseFault | DropoutFault,
    Field(discriminator="kind"),
]


# ---------------------------------------------------------------------------
# Driver, Passenger, Dialogue Configurations
# ---------------------------------------------------------------------------
class DriverSimConfig(BaseModel):
    speed_mps: float = Field(default=12.0, ge=0.0, le=50.0, description="Average travel speed in m/s")
    update_cadence_s: float = Field(default=1.0, ge=0.1, le=60.0, description="Seconds between fixes")
    driver_id: str = Field(default="drv-sim-001")
    vehicle_plate: str = Field(default="29A-888.88")


class PassengerSimConfig(BaseModel):
    passenger_id: str = Field(default="pass-sim-001")
    name: str = Field(default="Test Passenger")


class SimDialogueMessage(BaseModel):
    sender_role: Literal["DRIVER", "PASSENGER", "SYSTEM"]
    content: str = Field(..., min_length=1, max_length=5000)
    offset_seconds: int = Field(..., ge=0)


# ---------------------------------------------------------------------------
# Scenario Plans & Revisions
# ---------------------------------------------------------------------------
class TestPlanCreate(BaseModel):
    __test__ = False

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class TestPlanResponse(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime


class TestDefinitionRevisionCreate(BaseModel):
    __test__ = False

    plan_id: UUID
    route_geometry: GeoJsonLineString
    driver_config: DriverSimConfig = Field(default_factory=DriverSimConfig)
    passenger_config: PassengerSimConfig = Field(default_factory=PassengerSimConfig)
    fault_configs: list[FaultConfig] = Field(default_factory=list)
    messages: list[SimDialogueMessage] = Field(default_factory=list)
    initial_snapshot: TestStopSnapshot | None = None
    pickup_snapshot: TestStopSnapshot | None = None
    destination_snapshot: TestStopSnapshot | None = None


class TestDefinitionRevisionResponse(BaseModel):
    id: UUID
    plan_id: UUID
    revision_number: int
    route_geometry: GeoJsonLineString
    driver_config: DriverSimConfig
    passenger_config: PassengerSimConfig
    fault_configs: list[FaultConfig]
    messages: list[SimDialogueMessage] = Field(default_factory=list)
    created_at: datetime
    initial_snapshot: TestStopSnapshot | None = None
    pickup_snapshot: TestStopSnapshot | None = None
    destination_snapshot: TestStopSnapshot | None = None


# ---------------------------------------------------------------------------
# Simulation Run Lifecycle
# ---------------------------------------------------------------------------
TestRunStatus = Literal[
    "QUEUED",
    "RUNNING",
    "PAUSED",
    "STOP_MOVEMENT",
    "CANCELLING",
    "CANCELLED",
    "COMPLETED",
    "FAILED",
]

MAX_START_TO_PICKUP_M: int = 4000

ExpectedLabel = Literal[
    "no_violation",
    "ERR-01",
    "ERR-02",
    "ERR-03",
    "ERR-04",
    "ERR-05",
    "insufficient_evidence",
]


class TestRunCreate(BaseModel):
    __test__ = False

    definition_revision_id: UUID
    speed_factor: float = Field(default=1.0, gt=0.0, le=100.0)
    idempotency_key: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=120)
    expected_label: ExpectedLabel | None = None
    source: Literal["manual", "preset", "preset_batch"] | None = None


class TestRunResponse(BaseModel):
    id: UUID
    definition_revision_id: UUID
    status: TestRunStatus
    current_step: int
    total_steps: int
    simulation_clock: datetime
    speed_factor: float
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    title: str | None = None
    trip_id: str | None = None
    cancelled_at: datetime | None = None
    cancellation_actor: str | None = None
    cancellation_reason: str | None = None
    expected_label: str | None = None
    source: Literal["manual", "preset", "preset_batch"] | None = None


class TestRunSummary(BaseModel):
    """Compact history row; enough for the console History list without samples."""

    id: UUID
    title: str | None = None
    status: TestRunStatus
    trip_id: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    cancellation_actor: str | None = None
    cancellation_reason: str | None = None
    source: Literal["manual", "preset", "preset_batch"] | None = None
    expected_label: str | None = None
    predicted_label: str | None = None
    error_type: str | None = None
    confidence: float | None = None
    case_id: str | None = None
    license_plate: str | None = None
    driver_name: str | None = None
    origin_address: str | None = None
    pickup_address: str | None = None
    destination_address: str | None = None


class TestRunTitleUpdate(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)


class TestRunTraceStage(BaseModel):
    stage: str
    state: Literal["done", "waiting", "skipped", "active", "pending"] = "waiting"
    occurred_at: datetime | None = None
    detail: dict[str, Any] | str | None = None


class TestPipelineStage(BaseModel):
    key: str
    label: str
    count: int
    state: Literal["done", "active", "waiting", "unknown"] = "unknown"


class TestRunOverview(BaseModel):
    """Recorded pipeline evidence for one run: input, model throughput, label split."""

    run_id: UUID
    status: TestRunStatus
    trips_input: int = 0
    trips_processed: int = 0
    trips_classified: int = 0
    classification_counts: dict[str, int] = Field(default_factory=dict)
    stages: list[TestPipelineStage] = Field(default_factory=list)


class TestPresetTrip(BaseModel):
    trip_ref: str
    label: str
    source: str | None = None
    pickup_name: str | None = None
    dropoff_name: str | None = None
    driver_display_name: str | None = None
    driver_name: str | None = None
    license_plate: str | None = None
    city: str | None = None
    severity: str | None = None
    scenario: str | None = None
    distance_m: float | None = None
    duration_s: float | None = None
    telemetry_points: int = 0
    cancellation_actor: str | None = None
    cancellation_reason: str | None = None


class TestPreset(BaseModel):
    id: str
    title: str
    description: str
    kind: Literal["default", "normal", "wrong_direction", "violation", "vietnam"]
    available: bool = True
    unavailable_reason: str | None = None
    source_label: str | None = None
    selection_size: int | None = None
    available_trips: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    sample_trips: list[TestPresetTrip] = Field(default_factory=list)


class GroupedLabelCounts(BaseModel):
    fraud: int = 0
    no_violation: int = 0
    insufficient_evidence: int = 0
    grouped: dict[str, int] = Field(default_factory=dict)
    per_code: dict[str, int] = Field(default_factory=dict)


class PresetDistributions(BaseModel):
    total_records: int
    by_label: GroupedLabelCounts
    per_code: dict[str, int] = Field(default_factory=dict)
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_scenario: dict[str, int] = Field(default_factory=dict)
    by_city: dict[str, int] = Field(default_factory=dict)
    by_cancellation_actor: dict[str, int] = Field(default_factory=dict)


class TestPresetDetailResponse(TestPreset):
    __test__ = False
    source_release: str | None = None
    revision: str | None = None
    trips_sha256: str | None = None
    license: str | None = None
    trip_count: int
    published_release_counts: dict[str, Any] = Field(default_factory=dict)
    distributions: PresetDistributions
    info: dict[str, Any] = Field(default_factory=dict)


class ClerkLinkedDriverResponse(BaseModel):
    driver_id: str
    display_name: str
    email: str
    principal_id: str
    vehicle_id: str | None = None
    license_plate: str | None = None


class PresetBatchRunCreate(BaseModel):
    trip_limit: int | None = Field(default=None, description="null = 100%")
    trips_per_batch: int = Field(default=1, ge=1, description="trips released per interval")
    interval_s: float = Field(default=1.0, gt=0.0, description="seconds between batch releases")
    driver_ids: list[UUID] = Field(..., min_length=1, description="List of active Clerk-linked driver UUIDs in the org")


class PresetBatchTripResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    batch_id: UUID
    trip_ref: str
    trip_order: int = Field(validation_alias=AliasChoices("trip_order", "order"))
    status: str
    driver_id: str | None = None
    driver_name: str | None = None
    expected_label: str | None = None
    predicted_label: str | None = None
    confidence: float | None = None
    case_id: str | None = None
    run_id: UUID | None = None
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    snapshot: dict[str, Any] = Field(default_factory=dict)

    @property
    def order(self) -> int:
        return self.trip_order


class PresetBatchRunResponse(BaseModel):
    id: UUID
    organization_id: str
    preset_id: str
    params: dict[str, Any]
    status: str
    counters: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None


class PresetBatchRunDetailResponse(PresetBatchRunResponse):
    trips: list[PresetBatchTripResponse] = Field(default_factory=list)


class PresetBatchEvent(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    event_type: str
    batch_id: UUID
    trip_ref: str | None = None
    driver_id: str | None = None
    driver_name: str | None = None
    reached_classifier: bool = False
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    label: str | None = None
    confidence: float | None = None
    case_id: str | None = None
    reason: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class TestPresetListResponse(BaseModel):
    presets: list[TestPreset]
    source: dict[str, Any] = Field(default_factory=dict)


class TestPresetPlanRequest(BaseModel):
    preset_id: str = Field(..., alias="preset_key", description="Preset ID or key")
    trip_ref: str | None = Field(default=None, description="Optional trip reference within the preset")
    driver_id: str | None = Field(default=None, description="Optional active Clerk-linked driver ID")
    title: str | None = Field(default=None, max_length=255, description="Optional custom plan title")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class TestPresetPlanResponse(BaseModel):
    plan: TestPlanResponse
    definition: TestDefinitionRevisionResponse
    preset_id: str
    trip_ref: str
    label: str
    distance_m: float
    telemetry_points: int
    initial_snapshot: TestStopSnapshot | None = None
    pickup_snapshot: TestStopSnapshot | None = None
    destination_snapshot: TestStopSnapshot | None = None
    telemetry: list[dict[str, Any]] = Field(default_factory=list)


class TestControlCommand(BaseModel):
    command: Literal["PAUSE", "RESUME", "STOP_MOVEMENT", "INJECT_FAULT", "CANCEL", "SET_SPEED_FACTOR", "FAST_COMPLETE"]
    payload: dict[str, Any] = Field(default_factory=dict)


class TestCancellationRequest(BaseModel):
    """Participant-initiated early termination. Platform cancel uses TestControlCommand."""

    actor: Literal["passenger", "driver"]
    reason: str = Field(..., min_length=1, max_length=500)


class TestTelemetrySample(BaseModel):
    __test__ = False
    run_id: UUID
    step_index: int
    latitude: float
    longitude: float
    speed_mps: float
    heading_deg: float
    is_fault_injected: bool = False
    fault_type: str | None = None
    emitted_at: datetime


class TestStreamEvent(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    state_before: TestRunStatus | None = None
    event_type: Literal[
        "step.progress",
        "fault.applied",
        "fault.injected",
        "dialogue.spoken",
        "run.completed",
        "run.fast_completed",
        "run.paused",
        "run.resumed",
        "run.cancelled",
        "run.failed",
    ]
    run_id: UUID
    step_index: int
    simulation_clock: datetime
    sample: TestTelemetrySample | None = None
    active_fault: str | None = None
    message: str | None = None
    cancellation_actor: str | None = None
    cancellation_reason: str | None = None


# ---------------------------------------------------------------------------
# Case Triage (§6.7)
# ---------------------------------------------------------------------------
class TestCaseResponse(BaseModel):
    id: str
    trip_id: str | None = None
    run_id: str | None = None
    risk_score: float
    anomaly_types: list[str]
    status: Literal["OPEN", "UNDER_REVIEW", "CLOSED"]
    created_at: datetime


class TestTriageRequest(BaseModel):
    decision: Literal["INVESTIGATE", "APPROVE_LEGITIMATE", "SANCTION_SUSPEND"]
    rationale: str = Field(..., min_length=1, max_length=2000)
    lease_id: str | None = None


class TestTriageResponse(BaseModel):
    case_id: str
    decision: str
    new_status: str
    rationale: str
    audit_event_id: str
    timestamp: datetime


class TestNotificationResponse(BaseModel):
    id: str
    run_id: str
    recipient_type: str
    recipient_id: str
    channel: str
    body: str
    intercepted_at: str


class RouteWaypoint(BaseModel):
    lon: float
    lat: float
    leg: Literal["pickup", "destination"] = "pickup"


class RouteResolveRequest(BaseModel):
    origin: list[float] = Field(..., min_length=2, max_length=2, description="[longitude, latitude]")
    pickup: list[float] = Field(..., min_length=2, max_length=2, description="[longitude, latitude]")
    destination: list[float] = Field(..., min_length=2, max_length=2, description="[longitude, latitude]")
    waypoints: list[RouteWaypoint | list[float]] = Field(
        default_factory=list,
        description="Optional list of waypoints as [{lon, lat, leg}] or legacy [[lon, lat]]",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_waypoints(cls, data: Any) -> Any:
        if isinstance(data, dict) and "waypoints" in data:
            raw_wps = data["waypoints"]
            if isinstance(raw_wps, list):
                normalized = []
                for wp in raw_wps:
                    if isinstance(wp, (list, tuple)) and len(wp) >= 2:
                        normalized.append({"lon": float(wp[0]), "lat": float(wp[1]), "leg": "pickup"})
                    elif isinstance(wp, dict):
                        normalized.append(
                            {
                                "lon": float(wp.get("lon", 0.0)),
                                "lat": float(wp.get("lat", 0.0)),
                                "leg": wp.get("leg", "pickup"),
                            }
                        )
                    else:
                        normalized.append(wp)
                data["waypoints"] = normalized
        return data


class RouteLegDetails(BaseModel):
    coordinates: list[list[float]] | list[list[list[float]]]
    distance_m: int
    duration_s: int | float
    provider: str
    traffic_model: Literal["free_flow", "approximated"] = "free_flow"
    provenance: dict[str, Any] = Field(default_factory=dict)


class RouteResolveResponse(BaseModel):
    route_geometry: Annotated[GeoJsonLineString | GeoJsonMultiLineString, Field(discriminator="type")]
    pickup_route: RouteLegDetails
    destination_route: RouteLegDetails
    provider: str
    waypoints: list[RouteWaypoint] = Field(default_factory=list)
    max_start_to_pickup_m: int = MAX_START_TO_PICKUP_M


class TestCaseSaveRequest(BaseModel):
    risk_score: float | None = Field(default=None, ge=0.0, le=1.0)
    anomaly_types: list[str] | None = None
    notes: str | None = None


class GeocodeResult(BaseModel):
    formatted: str
    lat: float
    lon: float
    address_line1: str | None = None
    city: str | None = None


class GeocodeResponse(BaseModel):
    results: list[GeocodeResult]


class PublishProductionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passenger_id: str | None = None
    vehicle_id: str | None = None
    policy_version_id: str | None = None
    points: list[dict[str, Any]] | None = None
    pickup: dict[str, Any] | None = None
    dropoff: dict[str, Any] | None = None
    pickup_address: str | None = None
    dropoff_address: str | None = None
    messages: list[dict[str, Any]] | None = None
    driver_id: str | None = None
    vehicle_plate: str | None = None
    speed_mps: float | None = None
    organization_id: str | None = None


class ProductionPublishResponse(BaseModel):
    status: str
    run_id: str
    trip_id: str
    case_id: str | None
    destination: str = "/workplace"
