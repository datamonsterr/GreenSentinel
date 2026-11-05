"""Kinematics and fault transformation engine for SPEC-0130 Tester Trip Simulation."""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from src.models.schemas import (
    TelemetryEventEnvelope,
    TelemetryPayload,
    TelemetryPosition,
)
from src.models.test_simulation import (
    DropoutFault,
    FaultConfig,
    GeoJsonLineString,
    JumpFault,
    OffsetNoiseFault,
    TestTelemetrySample,
)

EARTH_RADIUS_M = 6371000.0


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate Great Circle distance in meters between two coordinates."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_M * c


def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate initial compass bearing in degrees [0, 360) from point 1 to point 2."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_lambda = math.radians(lon2 - lon1)

    y = math.sin(delta_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)
    initial_bearing = math.degrees(math.atan2(y, x))
    return (initial_bearing + 360.0) % 360.0


def destination_point(lat: float, lon: float, distance_m: float, bearing_deg: float) -> tuple[float, float]:
    """Calculate destination coordinate given starting point, distance in meters and bearing."""
    delta = distance_m / EARTH_RADIUS_M
    theta = math.radians(bearing_deg)
    phi1 = math.radians(lat)
    lambda1 = math.radians(lon)

    phi2 = math.asin(math.sin(phi1) * math.cos(delta) + math.cos(phi1) * math.sin(delta) * math.cos(theta))
    lambda2 = lambda1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * math.sin(phi2),
    )
    return math.degrees(phi2), ((math.degrees(lambda2) + 540.0) % 360.0) - 180.0


class TrajectoryInterpolator:
    """Arc-length path interpolator along GeoJSON LineString coordinates."""

    def __init__(self, geometry: GeoJsonLineString) -> None:
        self.coords: list[tuple[float, float]] = [
            (c[1], c[0])
            for c in geometry.coordinates  # convert [lon, lat] -> (lat, lon)
        ]
        if len(self.coords) < 2:
            raise ValueError("Route geometry must have at least 2 coordinate points")

        self.segment_distances: list[float] = []
        self.cumulative_distances: list[float] = [0.0]

        total = 0.0
        for i in range(len(self.coords) - 1):
            p1 = self.coords[i]
            p2 = self.coords[i + 1]
            dist = haversine_distance(p1[0], p1[1], p2[0], p2[1])
            self.segment_distances.append(dist)
            total += dist
            self.cumulative_distances.append(total)

        self.total_distance_m = total

    def interpolate_at_distance(self, target_distance_m: float) -> tuple[float, float, float]:
        """Returns (latitude, longitude, heading_degrees) at target distance along the path."""
        dist = max(0.0, min(target_distance_m, self.total_distance_m))

        if dist >= self.total_distance_m:
            p_penultimate = self.coords[-2]
            p_last = self.coords[-1]
            bearing = calculate_bearing(p_penultimate[0], p_penultimate[1], p_last[0], p_last[1])
            return p_last[0], p_last[1], bearing

        # Find segment
        idx = 0
        while idx < len(self.cumulative_distances) - 1 and self.cumulative_distances[idx + 1] < dist:
            idx += 1

        seg_dist = self.segment_distances[idx]
        p1 = self.coords[idx]
        p2 = self.coords[idx + 1]
        bearing = calculate_bearing(p1[0], p1[1], p2[0], p2[1])

        if seg_dist <= 1e-6:
            return p1[0], p1[1], bearing

        offset_m = max(0.0, min(seg_dist, dist - self.cumulative_distances[idx]))
        if offset_m <= 1e-6:
            return p1[0], p1[1], bearing
        if abs(offset_m - seg_dist) <= 1e-6:
            return p2[0], p2[1], bearing

        # Great Circle forward geodesic along segment
        lat, lon = destination_point(p1[0], p1[1], offset_m, bearing)
        return lat, lon, bearing


class SimulationKinematicsEngine:
    """Computes time-stepped fixes and applies configured fault vector transformations."""

    def __init__(
        self,
        geometry: GeoJsonLineString,
        speed_mps: float = 12.0,
        cadence_s: float = 1.0,
        fault_configs: list[FaultConfig] | None = None,
    ) -> None:
        self.interpolator = TrajectoryInterpolator(geometry)
        self.speed_mps = max(0.1, speed_mps)
        self.cadence_s = max(0.1, cadence_s)
        self.fault_configs = fault_configs or []
        self.distance_per_step = self.speed_mps * self.cadence_s
        self.total_steps = max(1, math.ceil(self.interpolator.total_distance_m / self.distance_per_step))
        self.accumulated_distance_m: float = 0.0

    def compute_step(
        self,
        run_id: UUID,
        step_index: int,
        base_time: datetime,
        distance_override_m: float | None = None,
    ) -> TestTelemetrySample | None:
        """Computes the telemetry sample for a given step index, or returns None if DROPOUT is active."""
        elapsed_s = step_index * self.cadence_s
        if distance_override_m is not None:
            step_dist = distance_override_m
        elif step_index == 0:
            self.accumulated_distance_m = 0.0
            step_dist = 0.0
        elif self.accumulated_distance_m == 0.0 and step_index > 1:
            step_dist = step_index * self.distance_per_step
            self.accumulated_distance_m = step_dist
        else:
            self.accumulated_distance_m = min(
                self.interpolator.total_distance_m,
                self.accumulated_distance_m + self.speed_mps * self.cadence_s,
            )
            step_dist = self.accumulated_distance_m
        emitted_at = base_time + timedelta(seconds=elapsed_s)

        # 1. Base kinematics
        lat, lon, heading = self.interpolator.interpolate_at_distance(step_dist)
        current_speed = self.speed_mps if step_dist < self.interpolator.total_distance_m else 0.0

        is_fault = False
        fault_type: str | None = None

        # 2. Evaluate active faults
        for fault in self.fault_configs:
            if isinstance(fault, DropoutFault):
                if fault.at_offset_s <= elapsed_s < (fault.at_offset_s + fault.duration_s):
                    # Signal loss - fix is suppressed
                    return None

            elif isinstance(fault, JumpFault):
                # Instantaneous teleportation anomaly at offset window
                if fault.at_offset_s <= elapsed_s < (fault.at_offset_s + self.cadence_s):
                    lat, lon = destination_point(lat, lon, fault.displacement_m, fault.bearing_deg)
                    is_fault = True
                    fault_type = "JUMP"

            elif isinstance(fault, OffsetNoiseFault):
                if fault.at_offset_s <= elapsed_s < (fault.at_offset_s + fault.duration_s):
                    # Lateral displacement + Gaussian drift
                    rng = random.Random(fault.seed + step_index if fault.seed is not None else None)
                    noise_dist = fault.offset_m + rng.gauss(0.0, fault.noise_std_dev_m)
                    noise_bearing = (heading + 90.0) % 360.0
                    lat, lon = destination_point(lat, lon, noise_dist, noise_bearing)
                    is_fault = True
                    fault_type = "OFFSET_NOISE"

        return TestTelemetrySample(
            run_id=run_id,
            step_index=step_index,
            latitude=round(lat, 6),
            longitude=round(lon, 6),
            speed_mps=round(current_speed, 2),
            heading_deg=round(heading, 1),
            is_fault_injected=is_fault,
            fault_type=fault_type,
            emitted_at=emitted_at,
        )

    def to_telemetry_envelope(
        self,
        sample: TestTelemetrySample,
        trip_id: UUID,
        driver_id: UUID,
        assignment_id: UUID,
    ) -> TelemetryEventEnvelope:
        """Adapts simulated sample to production TelemetryEventEnvelope for queue ingestion."""
        # DAVI is detector output; the simulator must not invent a confidence score.
        davi = None
        gps_state: Literal["valid", "jitter", "unavailable", "mock_reported", "unknown"] = (
            "jitter" if sample.is_fault_injected else "valid"
        )

        return TelemetryEventEnvelope(
            schema_version=1,
            event_id=uuid4(),
            event_type="telemetry.observed",
            source="tester.simulation_runner",
            occurred_at=sample.emitted_at,
            correlation_id=sample.run_id,
            simulation_run_id=sample.run_id,
            trip_id=trip_id,
            assignment_id=assignment_id,
            driver_id=driver_id,
            sequence=sample.step_index,
            payload=TelemetryPayload(
                position=TelemetryPosition(
                    latitude=sample.latitude,
                    longitude=sample.longitude,
                    accuracy_m=12.0 if sample.is_fault_injected else 4.0,
                ),
                speed_mps=sample.speed_mps,
                bearing_deg=sample.heading_deg,
                app_state="foreground",
                network_state="online",
                gps_state=gps_state,
                mock_location_reported=sample.is_fault_injected,
                distance_to_pickup_m=max(
                    0.0, self.interpolator.total_distance_m - (sample.step_index * self.distance_per_step)
                ),
                davi_score=davi,
                data_gap_s=0.0,
            ),
        )
