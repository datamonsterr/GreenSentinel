"""Background execution daemon, outbox worker, and state machine for SPEC-0130 Tester Trip Simulation."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from src.config import Settings, get_settings
from src.models.test_simulation import (
    DropoutFault,
    FaultConfig,
    JumpFault,
    OffsetNoiseFault,
    TestControlCommand,
    TestDefinitionRevisionResponse,
    TestRunResponse,
    TestStreamEvent,
)
from src.services.telemetry_queue import ReliableTelemetryQueue
from src.services.test_simulation_repository import (
    TestSimulationRepository,
    enforce_fail_closed_credential_safeguards,
)
from src.services.test_simulation_service import SimulationKinematicsEngine

logger = logging.getLogger(__name__)


class SimulationRunner:
    """Distributed lock-aware background worker that leases and executes simulation runs."""

    def __init__(
        self,
        repository: TestSimulationRepository | None = None,
        queue: ReliableTelemetryQueue | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        enforce_fail_closed_credential_safeguards()
        self.repository = repository or TestSimulationRepository(self.settings)
        self.queue = queue or ReliableTelemetryQueue(prefix="test:queue:telemetry")
        self._active_tasks: dict[UUID, asyncio.Task[None]] = {}
        self._event_subscribers: dict[UUID, list[asyncio.Queue[TestStreamEvent]]] = {}
        self._event_history: dict[UUID, list[TestStreamEvent]] = {}
        self._engines: dict[UUID, SimulationKinematicsEngine] = {}
        self._current_steps: dict[UUID, int] = {}
        self._controls: dict[UUID, asyncio.Event] = {}  # Set when running, cleared when paused
        self._stop_movement: dict[UUID, bool] = {}
        self._speed_factors: dict[UUID, float] = {}
        self._fast_forward: dict[UUID, bool] = {}

    def subscribe_stream(self, run_id: UUID, last_event_id: str | None = None) -> asyncio.Queue[TestStreamEvent]:
        """Subscribes an SSE listener queue to real-time events for a simulation run."""
        q: asyncio.Queue[TestStreamEvent] = asyncio.Queue(maxsize=2000)
        # Replay event history so late-joining subscribers receive all prior steps
        history = self._event_history.get(run_id, [])
        start = 0
        if last_event_id:
            for index, event in enumerate(history):
                if str(event.event_id) == last_event_id:
                    start = index + 1
                    break
        for past_event in history[start:]:
            try:
                q.put_nowait(past_event)
            except asyncio.QueueFull:
                break
        if run_id not in self._event_subscribers:
            self._event_subscribers[run_id] = []
        self._event_subscribers[run_id].append(q)
        return q

    def unsubscribe_stream(self, run_id: UUID, q: asyncio.Queue[TestStreamEvent]) -> None:
        if run_id in self._event_subscribers and q in self._event_subscribers[run_id]:
            self._event_subscribers[run_id].remove(q)

    async def broadcast_event(self, run_id: UUID, event: TestStreamEvent) -> None:
        history = self._event_history.setdefault(run_id, [])
        if len(history) < 2000:
            history.append(event)
        subscribers = self._event_subscribers.get(run_id, [])
        for q in subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    async def flush_outbox(self) -> int:
        """Transactional Outbox worker: routes pending outbox telemetry payloads to isolated Redis queue."""
        unprocessed = self.repository.fetch_unprocessed_outbox(limit=100)
        dispatched_count = 0
        for item in unprocessed:
            payload = item["payload"]
            try:
                await self.queue.enqueue(payload)
                self.repository.mark_outbox_processed(item["id"])
                dispatched_count += 1
            except Exception as exc:
                logger.warning("Failed to dispatch outbox item %s: %s", item["id"], exc)
                break
        return dispatched_count

    async def start_run(self, run_id: UUID) -> None:
        """Launches background task for the simulation run."""
        if run_id in self._active_tasks and not self._active_tasks[run_id].done():
            return

        run = self.repository.get_run(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")

        if run.status in {"COMPLETED", "CANCELLED", "FAILED"}:
            return

        definition = self.repository.get_definition_revision(run.definition_revision_id)
        if not definition:
            raise ValueError(f"Definition revision {run.definition_revision_id} not found")

        pause_event = asyncio.Event()
        pause_event.set()  # Running initially
        self._controls[run_id] = pause_event
        self._stop_movement[run_id] = False
        self._speed_factors[run_id] = max(0.1, run.speed_factor)

        start_time = datetime.now(UTC)
        trip_id = UUID(run.trip_id) if run.trip_id else uuid4()
        driver_id = uuid4()

        # A run produces telemetry only. Cases and risk are detector outputs and
        # must never be fabricated from configured faults or simulation setup.

        # Record pre-configured dialogue messages in sandbox mock notification sink
        for msg in definition.messages:
            self.repository.record_notification(
                run_id=run_id,
                recipient_type="driver" if msg.sender_role == "DRIVER" else "passenger",
                recipient_id=definition.driver_config.driver_id if msg.sender_role == "DRIVER" else "passenger-001",
                channel="APP_INBOX",
                body=msg.content,
            )

        task = asyncio.create_task(self._run_loop(run, definition, pause_event, trip_id, driver_id, start_time))
        self._active_tasks[run_id] = task

    async def apply_control(self, run_id: UUID, control: TestControlCommand) -> None:
        """Applies real-time execution signal (PAUSE, RESUME, STOP_MOVEMENT, CANCEL, INJECT_FAULT, SET_SPEED_FACTOR)."""
        self.repository.append_control(run_id, control.command, control.payload)

        if control.payload and "speed_factor" in control.payload:
            try:
                factor = float(control.payload["speed_factor"])
                self._speed_factors[run_id] = max(0.1, factor)
            except (ValueError, TypeError):
                pass

        if control.payload and "speed_mps" in control.payload:
            try:
                new_speed = float(control.payload["speed_mps"])
                engine = self._engines.get(run_id)
                if engine and new_speed > 0:
                    engine.speed_mps = new_speed
                    engine.distance_per_step = new_speed * engine.cadence_s
            except (ValueError, TypeError):
                pass

        if control.command == "PAUSE":
            if run_id in self._controls:
                self._controls[run_id].clear()
            self.repository.update_run_status(run_id, "PAUSED")
            await self.broadcast_event(
                run_id,
                TestStreamEvent(
                    event_type="run.paused",
                    run_id=run_id,
                    step_index=0,
                    simulation_clock=datetime.now(UTC),
                    message="Simulation paused",
                ),
            )

        elif control.command == "RESUME":
            if run_id in self._controls:
                self._controls[run_id].set()
            self.repository.update_run_status(run_id, "RUNNING")
            await self.broadcast_event(
                run_id,
                TestStreamEvent(
                    event_type="run.resumed",
                    run_id=run_id,
                    step_index=0,
                    simulation_clock=datetime.now(UTC),
                    message="Simulation resumed",
                ),
            )

        elif control.command == "STOP_MOVEMENT":
            self._stop_movement[run_id] = True
            self.repository.update_run_status(run_id, "STOP_MOVEMENT")

        elif control.command == "CANCEL":
            current_run = self.repository.get_run(run_id)
            state_before = current_run.status if current_run else None
            payload = control.payload or {}
            actor = payload.get("actor")
            if actor not in ("passenger", "driver", "platform"):
                actor = "platform"
            reason_raw = payload.get("reason")
            reason = (
                reason_raw.strip() if isinstance(reason_raw, str) and reason_raw.strip() else "Cancelled by operator"
            )
            self.repository.update_run_status(
                run_id,
                "CANCELLED",
                cancellation_actor=actor,
                cancellation_reason=reason,
            )
            if run_id in self._active_tasks:
                self._active_tasks[run_id].cancel()
            await self.broadcast_event(
                run_id,
                TestStreamEvent(
                    event_type="run.cancelled",
                    run_id=run_id,
                    step_index=self._current_steps.get(run_id, 0),
                    simulation_clock=datetime.now(UTC),
                    message=f"Simulation cancelled by {actor}",
                    cancellation_actor=actor,
                    cancellation_reason=reason,
                    state_before=state_before,
                ),
            )

        elif control.command == "INJECT_FAULT":
            payload = control.payload or {}
            kind = payload.get("kind")
            engine = self._engines.get(run_id)
            current_step = self._current_steps.get(run_id, 0)
            cadence_s = engine.cadence_s if engine else 1.0
            current_elapsed_s = int(payload.get("at_offset_s", int(current_step * cadence_s)))

            injected_fault: FaultConfig | None = None
            if kind == "JUMP":
                injected_fault = JumpFault(
                    kind="JUMP",
                    at_offset_s=current_elapsed_s,
                    displacement_m=float(payload.get("displacement_m", 200.0)),
                    bearing_deg=float(payload.get("bearing_deg", 90.0)),
                )
            elif kind == "OFFSET_NOISE":
                injected_fault = OffsetNoiseFault(
                    kind="OFFSET_NOISE",
                    at_offset_s=current_elapsed_s,
                    duration_s=int(payload.get("duration_s", 5)),
                    offset_m=float(payload.get("offset_m", 30.0)),
                    noise_std_dev_m=float(payload.get("noise_std_dev_m", 15.0)),
                )
            elif kind == "DROPOUT":
                injected_fault = DropoutFault(
                    kind="DROPOUT",
                    at_offset_s=current_elapsed_s,
                    duration_s=int(payload.get("duration_s", 5)),
                )

            if injected_fault and engine:
                engine.fault_configs.append(injected_fault)
                await self.broadcast_event(
                    run_id,
                    TestStreamEvent(
                        event_type="fault.injected",
                        run_id=run_id,
                        step_index=current_step,
                        simulation_clock=datetime.now(UTC),
                        active_fault=kind,
                        message=f"Dynamically injected fault {kind} at step {current_step} ({current_elapsed_s}s)",
                    ),
                )

        elif control.command == "FAST_COMPLETE":
            self._fast_forward[run_id] = True
            if run_id in self._controls:
                self._controls[run_id].set()
            await self.broadcast_event(
                run_id,
                TestStreamEvent(
                    event_type="run.fast_completed",
                    run_id=run_id,
                    step_index=self._current_steps.get(run_id, 0),
                    simulation_clock=datetime.now(UTC),
                    message="Fast-completing simulation run",
                ),
            )

        elif control.command == "SET_SPEED_FACTOR":
            pass

    async def _run_loop(
        self,
        run: TestRunResponse,
        definition: TestDefinitionRevisionResponse,
        pause_event: asyncio.Event,
        trip_id: UUID,
        driver_id: UUID,
        start_time: datetime,
    ) -> None:
        run_id = run.id
        engine = SimulationKinematicsEngine(
            geometry=definition.route_geometry,
            speed_mps=definition.driver_config.speed_mps,
            cadence_s=definition.driver_config.update_cadence_s,
            fault_configs=list(definition.fault_configs),
        )
        self._engines[run_id] = engine
        self._current_steps[run_id] = 0

        assignment_id = uuid4()
        total_steps = engine.total_steps

        self.repository.update_run_status(run_id, "RUNNING", current_step=0, simulation_clock=start_time)

        try:
            stopped_distance: float | None = None
            for step in range(total_steps):
                is_ff = self._fast_forward.get(run_id, False)
                if not is_ff:
                    # Wait if paused
                    await pause_event.wait()
                    # Dynamic step interval derived from active speed factor
                    current_speed_factor = self._speed_factors.get(run_id, max(0.1, run.speed_factor))
                    step_interval = definition.driver_config.update_cadence_s / max(0.1, current_speed_factor)
                else:
                    step_interval = 0.0

                # Check if movement stopped
                if self._stop_movement.get(run_id, False):
                    if stopped_distance is None:
                        stopped_distance = max(0.0, (step - 1) * engine.distance_per_step)
                else:
                    stopped_distance = None

                sample = engine.compute_step(run_id, step, start_time, distance_override_m=stopped_distance)

                if sample is not None:
                    self.repository.save_sample(sample)

                    # Adapt to standard production TelemetryEventEnvelope
                    envelope = engine.to_telemetry_envelope(
                        sample,
                        trip_id=trip_id,
                        driver_id=driver_id,
                        assignment_id=assignment_id,
                    )

                    # Persist via Transactional Outbox pattern
                    envelope_dict = envelope.model_dump(mode="json")
                    self.repository.create_outbox_event(
                        aggregate_type="trip.telemetry",
                        aggregate_id=str(trip_id),
                        payload=envelope_dict,
                    )

                    # Dispatch to isolated Redis queue (test:queue:telemetry) in background
                    asyncio.create_task(self.flush_outbox())

                    # Broadcast progress over SSE
                    event = TestStreamEvent(
                        event_type="fault.applied" if sample.is_fault_injected else "step.progress",
                        run_id=run_id,
                        step_index=step,
                        simulation_clock=sample.emitted_at,
                        sample=sample,
                        active_fault=sample.fault_type,
                    )
                    await self.broadcast_event(run_id, event)

                self._current_steps[run_id] = step
                self.repository.update_run_status(
                    run_id,
                    "RUNNING",
                    current_step=step,
                    simulation_clock=start_time if sample is None else sample.emitted_at,
                )

                # Step delay matching simulation cadence adjusted by speed_factor
                if step_interval > 0.0:
                    await asyncio.sleep(step_interval)
                else:
                    await asyncio.sleep(0)

            self.repository.update_run_status(run_id, "COMPLETED", current_step=total_steps)
            await self.broadcast_event(
                run_id,
                TestStreamEvent(
                    event_type="run.completed",
                    run_id=run_id,
                    step_index=total_steps,
                    simulation_clock=datetime.now(UTC),
                    message="Simulation path completed successfully",
                ),
            )

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Simulation run %s failed: %s", run_id, exc, exc_info=True)
            self.repository.update_run_status(run_id, "FAILED")
            await self.broadcast_event(
                run_id,
                TestStreamEvent(
                    event_type="run.failed",
                    run_id=run_id,
                    step_index=0,
                    simulation_clock=datetime.now(UTC),
                    message=str(exc),
                ),
            )
        finally:
            self._active_tasks.pop(run_id, None)
            self._controls.pop(run_id, None)
            self._stop_movement.pop(run_id, None)
            self._speed_factors.pop(run_id, None)
            self._engines.pop(run_id, None)
            self._current_steps.pop(run_id, None)
            self._fast_forward.pop(run_id, None)


_runner_instance: SimulationRunner | None = None


def get_simulation_runner() -> SimulationRunner:
    global _runner_instance
    if _runner_instance is None:
        _runner_instance = SimulationRunner()
    return _runner_instance
