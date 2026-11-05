"""Issue #260 DoD-1 RED: current mapper must use derived FeatureWindow speed.

map_telemetry_event_to_jev_input (src/services/jev_state_builder.py) currently
falls back to producer-reported p["speed_mps"] when the derived speed is 0.
Producer speed is untrusted (TELEMETRY_DISTRIBUTION.md section 3: "Features
derive speed from positions and ignore this field"); the mapper must use
fw.speed.max_mps from compute_feature_window only.
"""

from src.services.feature_engineering import compute_feature_window
from src.services.jev_state_builder import map_telemetry_event_to_jev_input


def _stationary_spoofed_points() -> list[dict]:
    # Same coordinate, 10 s apart: derived speed ~0, reported speed lies (57.5 m/s).
    return [
        {
            "latitude": 21.0285,
            "longitude": 105.8542,
            "accuracy_m": 8,
            "occurred_at": "2026-10-09T18:47:21+00:00",
            "sequence": 0,
            "speed_mps": 57.5,
            "gps_state": "valid",
        },
        {
            "latitude": 21.0285,
            "longitude": 105.8542,
            "accuracy_m": 8,
            "occurred_at": "2026-10-09T18:47:31+00:00",
            "sequence": 1,
            "speed_mps": 57.5,
            "gps_state": "valid",
        },
    ]


def test_mapper_uses_derived_speed_not_reported():
    bundle = {"telemetry": _stationary_spoofed_points(), "trip": {"status": "completed"}}
    jev_inp = map_telemetry_event_to_jev_input(bundle)
    fw = compute_feature_window(bundle["telemetry"], None)
    expected = float(fw.speed.max_mps or 0.0) * 3.6
    assert expected < 120.0  # fixture sanity: derived speed is calm
    assert jev_inp.telemetry["max_speed_kmh"] == round(expected, 1)


def test_mapper_ignores_reported_spike_magnitude():
    bundle = {"telemetry": _stationary_spoofed_points(), "trip": {"status": "completed"}}
    jev_inp = map_telemetry_event_to_jev_input(bundle)
    reported = max(p["speed_mps"] for p in bundle["telemetry"]) * 3.6
    assert reported > 120.0  # fixture sanity: reported speed screams spoof
    assert jev_inp.telemetry["max_speed_kmh"] != reported
