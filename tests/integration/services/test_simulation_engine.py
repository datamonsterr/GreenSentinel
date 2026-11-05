"""Unit tests for SimulationKinematicsEngine and fault vector transformations."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from src.models.test_simulation import (
    DropoutFault,
    GeoJsonLineString,
    JumpFault,
    OffsetNoiseFault,
)
from src.services.test_simulation_service import (
    SimulationKinematicsEngine,
    TrajectoryInterpolator,
)


def test_haversine_and_interpolation():
    # Hanoi route points: Hoan Kiem lake to West Lake
    p1 = [105.8524, 21.0285]  # [lon, lat]
    p2 = [105.8342, 21.0450]

    geom = GeoJsonLineString(coordinates=[p1, p2])
    interpolator = TrajectoryInterpolator(geom)

    assert interpolator.total_distance_m > 1000.0  # ~2.6km

    lat_start, lon_start, _ = interpolator.interpolate_at_distance(0.0)
    assert pytest.approx(lat_start, rel=1e-4) == p1[1]
    assert pytest.approx(lon_start, rel=1e-4) == p1[0]

    lat_end, lon_end, _ = interpolator.interpolate_at_distance(interpolator.total_distance_m)
    assert pytest.approx(lat_end, rel=1e-4) == p2[1]
    assert pytest.approx(lon_end, rel=1e-4) == p2[0]


def test_jump_fault_injection():
    p1 = [105.8524, 21.0285]
    p2 = [105.8342, 21.0450]
    geom = GeoJsonLineString(coordinates=[p1, p2])

    jump = JumpFault(at_offset_s=2, displacement_m=500.0, bearing_deg=90.0)
    engine = SimulationKinematicsEngine(geom, speed_mps=10.0, cadence_s=1.0, fault_configs=[jump])

    run_id = uuid4()
    now = datetime.now(UTC)

    # Step 0: Normal
    s0 = engine.compute_step(run_id, 0, now)
    assert s0 is not None
    assert not s0.is_fault_injected

    # Step 2: Jump injected
    s2 = engine.compute_step(run_id, 2, now)
    assert s2 is not None
    assert s2.is_fault_injected
    assert s2.fault_type == "JUMP"


def test_dropout_fault_suppression():
    p1 = [105.8524, 21.0285]
    p2 = [105.8342, 21.0450]
    geom = GeoJsonLineString(coordinates=[p1, p2])

    dropout = DropoutFault(at_offset_s=3, duration_s=2)
    engine = SimulationKinematicsEngine(geom, speed_mps=10.0, cadence_s=1.0, fault_configs=[dropout])

    run_id = uuid4()
    now = datetime.now(UTC)

    # Step 2: Available
    assert engine.compute_step(run_id, 2, now) is not None
    # Step 3 & 4: Suppressed (None)
    assert engine.compute_step(run_id, 3, now) is None
    assert engine.compute_step(run_id, 4, now) is None
    # Step 5: Resumed
    assert engine.compute_step(run_id, 5, now) is not None


def test_offset_noise_fault():
    p1 = [105.8524, 21.0285]
    p2 = [105.8342, 21.0450]
    geom = GeoJsonLineString(coordinates=[p1, p2])

    noise = OffsetNoiseFault(at_offset_s=1, duration_s=3, offset_m=50.0, noise_std_dev_m=5.0, seed=42)
    engine = SimulationKinematicsEngine(geom, speed_mps=10.0, cadence_s=1.0, fault_configs=[noise])

    run_id = uuid4()
    now = datetime.now(UTC)

    s1 = engine.compute_step(run_id, 1, now)
    assert s1 is not None
    assert s1.is_fault_injected
    assert s1.fault_type == "OFFSET_NOISE"


def test_envelope_translation():
    p1 = [105.8524, 21.0285]
    p2 = [105.8342, 21.0450]
    geom = GeoJsonLineString(coordinates=[p1, p2])
    engine = SimulationKinematicsEngine(geom)

    run_id = uuid4()
    trip_id = uuid4()
    driver_id = uuid4()
    assignment_id = uuid4()

    s = engine.compute_step(run_id, 1, datetime.now(UTC))
    assert s is not None
    env = engine.to_telemetry_envelope(s, trip_id=trip_id, driver_id=driver_id, assignment_id=assignment_id)

    assert env.event_type == "telemetry.observed"
    assert env.simulation_run_id == run_id
    assert env.trip_id == trip_id
    assert env.payload.position is not None
    assert env.payload.position.latitude == s.latitude


def test_envelope_leaves_detector_scores_unavailable():
    geom = GeoJsonLineString(coordinates=[[105.8524, 21.0285], [105.8342, 21.0450]])
    engine = SimulationKinematicsEngine(geom)
    sample = engine.compute_step(uuid4(), 1, datetime.now(UTC))
    assert sample is not None
    envelope = engine.to_telemetry_envelope(sample, uuid4(), uuid4(), uuid4())
    assert envelope.payload.davi_score is None
