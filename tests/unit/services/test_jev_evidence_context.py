"""Tests for evidence-only model context, threshold removal, and verdict vocabulary guards (Issue #547 / #494)."""

from __future__ import annotations

import json
import re

import pytest

from src.services.jev_assessment_service import DEFAULT_SYSTEM_PROMPT
from src.services.jev_criteria import (
    CRITERIA_BASELINE,
    CRITERIA_RISK_BANDS,
    CRITERIA_SEMANTIC,
    get_jev_criteria,
)
from src.services.jev_state_builder import build_jev_state

# Forbidden threshold pattern: comparisons with digits, e.g. ">= 180", "< 90", "> 35%", "<= 1.15"
THRESHOLD_REGEX = re.compile(r"[<>]=?\s*\d+")

# Forbidden verdict vocabulary for evidence state (English & Vietnamese)
FORBIDDEN_VERDICT_EN = [
    "high risk",
    "high_risk",
    "elevated",
    "abnormal",
    "suspicious",
    "normal",
    "violation",
    "fraud",
    "verdict",
    "penalty",
    "guilty",
    "infraction",
    "anomaly",
]

FORBIDDEN_VERDICT_VN = [
    "rủi ro cao",
    "rủi ro tăng",
    "bất thường",
    "nghi vấn",
    "bình thường",
    "vi phạm",
    "gian lận",
    "kết luận",
    "xử phạt",
    "cảnh báo",
]


SAMPLE_FIXTURE_BUNDLE = {
    "trip_id": "tr_evidence_test_001",
    "assignment_id": "asg_evidence_test_001",
    "trip": {"status": "completed", "cancellation_actor": None, "cancellation_reason": None},
    "assignment": {"arrived_at": "2026-10-17T10:05:00Z", "started_at": "2026-10-17T10:06:00Z"},
    "driver_profile": {"rating": 4.85, "acceptance_rate": 0.95},
    "driver_analytics": {"total_trips": 120, "cancellation_rate": 0.02},
    "conversation": [{"sender": "passenger", "text": "Toi dang o sanh toa nha"}],
    "customer_report": "Khach bao xe don dung gio",
    "pickup": [105.8500, 21.0200],
    "dropoff": [105.8600, 21.0300],
    "planned_route": {"distance_m": 2500.0, "is_estimated": False},
    "telemetry": [
        {"occurred_at": "2026-10-17T10:00:00Z", "longitude": 105.8500, "latitude": 21.0150, "speed_mps": 0.0},
        {"occurred_at": "2026-10-17T10:01:00Z", "longitude": 105.8505, "latitude": 21.0160, "speed_mps": 5.0},
        {"occurred_at": "2026-10-17T10:02:00Z", "longitude": 105.8510, "latitude": 21.0175, "speed_mps": 8.0},
        {"occurred_at": "2026-10-17T10:03:00Z", "longitude": 105.8510, "latitude": 21.0175, "speed_mps": 0.0},
        {"occurred_at": "2026-10-17T10:04:00Z", "longitude": 105.8510, "latitude": 21.0175, "speed_mps": 0.0},
        {"occurred_at": "2026-10-17T10:05:00Z", "longitude": 105.8500, "latitude": 21.0200, "speed_mps": 4.0},
    ],
}


class TestPromptAndCriteriaNoThresholds:
    """Verify that system prompt and semantic criteria contain NO numeric thresholds."""

    def test_default_system_prompt_no_numeric_thresholds(self) -> None:
        """DEFAULT_SYSTEM_PROMPT must not contain comparison operators with numbers."""
        matches = THRESHOLD_REGEX.findall(DEFAULT_SYSTEM_PROMPT)
        assert not matches, f"Found numeric thresholds in DEFAULT_SYSTEM_PROMPT: {matches}"

    def test_default_system_prompt_preserves_policy_and_codes(self) -> None:
        """DEFAULT_SYSTEM_PROMPT must preserve Vietnamese prose, class codes, and policy references."""
        assert "GreenSM" in DEFAULT_SYSTEM_PROMPT
        for code in ("ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05", "no_violation"):
            assert code in DEFAULT_SYSTEM_PROMPT, f"Missing class code {code} in DEFAULT_SYSTEM_PROMPT"

        for policy_ref in ("Điều 14.1", "Điều 14.2", "Điều 15.1", "Điều 15.3", "Điều 16.1"):
            assert policy_ref in DEFAULT_SYSTEM_PROMPT, f"Missing policy ref {policy_ref} in DEFAULT_SYSTEM_PROMPT"

    def test_semantic_criteria_no_numeric_thresholds(self) -> None:
        """CRITERIA_SEMANTIC definitions must not contain comparison operators with numbers."""
        criteria = get_jev_criteria("semantic")
        assert criteria == CRITERIA_SEMANTIC
        for code, text in criteria.items():
            matches = THRESHOLD_REGEX.findall(text)
            assert not matches, f"Found numeric threshold in CRITERIA_SEMANTIC[{code}]: {matches} in '{text}'"

    def test_semantic_criteria_covers_all_classes_as_behaviours(self) -> None:
        """CRITERIA_SEMANTIC must cover all classes as qualitative behaviours."""
        criteria = get_jev_criteria("semantic")
        assert set(criteria.keys()) == {
            "ERR-01",
            "ERR-02",
            "ERR-03",
            "ERR-04",
            "ERR-05",
            "no_violation",
        }
        for code, text in criteria.items():
            assert len(text) > 10, f"Criterion for {code} is too short"

    def test_get_jev_criteria_default_is_semantic(self) -> None:
        """Default call to get_jev_criteria() must return semantic criteria."""
        default_crit = get_jev_criteria()
        assert default_crit == CRITERIA_SEMANTIC

    def test_legacy_criteria_selectable(self) -> None:
        """Legacy variants 'baseline' and 'risk_bands' remain selectable for benchmarks."""
        assert get_jev_criteria("baseline") == CRITERIA_BASELINE
        assert get_jev_criteria("risk_bands") == CRITERIA_RISK_BANDS


class TestEvidenceStateBuilder:
    """Verify the new 'evidence' state variant in jev_state_builder."""

    def test_build_jev_state_default_is_evidence_classref(self) -> None:
        """build_jev_state default variant must be 'evidence_classref'."""
        default_state = build_jev_state(SAMPLE_FIXTURE_BUNDLE)
        classref_state = build_jev_state(SAMPLE_FIXTURE_BUNDLE, variant="evidence_classref")
        assert default_state == classref_state
        meas = default_state["telemetry"]["measurements"]
        assert "class_medians" in meas["speed_p50"]

    def test_evidence_state_no_raw_points(self) -> None:
        """Evidence state must not dump raw telemetry points."""
        state = build_jev_state(SAMPLE_FIXTURE_BUNDLE, variant="evidence")
        telem = state.get("telemetry", {})
        assert "points" not in telem
        assert "raw_points" not in telem
        assert "telemetry_points" not in telem
        assert "samples" not in telem

    def test_evidence_state_no_verdict_words_in_generated_telemetry(self) -> None:
        """Telemetry measurements and narratives generated by state builder must have no verdict vocabulary."""
        state = build_jev_state(SAMPLE_FIXTURE_BUNDLE, variant="evidence")
        telem = state.get("telemetry", {})
        telem_json = json.dumps(telem, ensure_ascii=False).lower()

        # Empirical reference distribution statements (e.g. "chuyến bình thường (tham chiếu tập train)")
        # are empirical reference context, not risk verdicts. Scrub reference phrase before testing forbidden verdict words.
        scrubbed_for_check = re.sub(r"chuyến bình thường\s*\(tham chiếu[^\)]*\)", "", telem_json)

        for forbidden in FORBIDDEN_VERDICT_EN:
            assert forbidden not in scrubbed_for_check, (
                f"Forbidden EN verdict '{forbidden}' found in evidence telemetry: {telem_json}"
            )

        for forbidden in FORBIDDEN_VERDICT_VN:
            assert forbidden not in scrubbed_for_check, (
                f"Forbidden VN verdict '{forbidden}' found in evidence telemetry: {telem_json}"
            )

    def test_evidence_state_no_rule_derived_verdict_flags(self) -> None:
        """Telemetry in evidence state must not contain rule-derived summary flags like wrong_direction or anomaly flags."""
        state = build_jev_state(SAMPLE_FIXTURE_BUNDLE, variant="evidence")
        telem = state.get("telemetry", {})
        assert "wrong_direction" not in telem, "rule-derived 'wrong_direction' flag present in evidence telemetry"
        assert "risk_bands" not in telem, "pre-calculated 'risk_bands' present in evidence telemetry"

    def test_evidence_state_measurements_carry_units(self) -> None:
        """Every measurement structure in evidence state must carry an explicit unit."""
        state = build_jev_state(SAMPLE_FIXTURE_BUNDLE, variant="evidence")
        telem = state.get("telemetry", {})
        measurements = telem.get("measurements", {})
        assert measurements, "Evidence telemetry must contain a 'measurements' dictionary"

        for name, m in measurements.items():
            if isinstance(m, dict):
                assert "unit" in m, f"Measurement '{name}' does not carry a 'unit' field: {m}"
                assert "value" in m, f"Measurement '{name}' does not carry a 'value' field: {m}"
                assert "band" not in m, f"Measurement '{name}' must not carry a verdict 'band': {m}"

    def test_evidence_state_token_budget_under_1500_tokens(self) -> None:
        """Evidence state JSON size must remain safely under 1,500 estimated tokens (chars / 3.0)."""
        state = build_jev_state(SAMPLE_FIXTURE_BUNDLE, variant="evidence")
        state_json = json.dumps(state, ensure_ascii=False)
        estimated_tokens = len(state_json) / 3.0
        assert estimated_tokens < 1500, (
            f"Token budget exceeded: {estimated_tokens:.1f} tokens (length {len(state_json)})"
        )

    def test_evidence_measurements_from_real_shaped_bundle_with_dict_pickup(self) -> None:
        """Reproduce BUG 1: pickup-relative measurements must be computed when pickup is a dict."""
        from scripts.benchmark.run_10k import bundle_to_input

        real_shaped_bundle = {
            "trip_id": "tr_dev300_shape_001",
            "assignment_id": "asg_dev300_shape_001",
            "trip": {"status": "completed", "cancellation_actor": None, "cancellation_reason": None},
            "assignment": {"arrived_at": "2026-10-17T10:05:00Z", "started_at": "2026-10-17T10:06:00Z"},
            "driver_profile": {"rating": 4.85, "acceptance_rate": 0.95},
            "driver_analytics": {"total_trips": 120, "cancellation_rate": 0.02},
            "conversation": [{"sender": "passenger", "text": "Toi dang o sanh toa nha"}],
            "customer_report": "Khach bao xe don dung gio",
            "pickup": {
                "lat": 21.0200,
                "lon": 105.8500,
                "name": "Sảnh Vincom",
                "street": "Bà Triệu",
                "city": "Hanoi",
            },
            "dropoff": {
                "lat": 21.0300,
                "lon": 105.8600,
                "name": "Nhà hát Lớn",
                "street": "Tràng Tiền",
                "city": "Hanoi",
            },
            "planned_route": {"distance_m": 2500.0, "is_estimated": False},
            "telemetry": [
                {"occurred_at": "2026-10-17T10:00:00Z", "longitude": 105.8500, "latitude": 21.0150, "speed_mps": 0.0},
                {"occurred_at": "2026-10-17T10:00:10Z", "longitude": 105.8502, "latitude": 21.0160, "speed_mps": 5.0},
                {"occurred_at": "2026-10-17T10:00:20Z", "longitude": 105.8505, "latitude": 21.0175, "speed_mps": 8.0},
                {"occurred_at": "2026-10-17T10:00:30Z", "longitude": 105.8508, "latitude": 21.0185, "speed_mps": 6.0},
                {"occurred_at": "2026-10-17T10:00:40Z", "longitude": 105.8509, "latitude": 21.0195, "speed_mps": 4.0},
                {"occurred_at": "2026-10-17T10:00:50Z", "longitude": 105.8510, "latitude": 21.0200, "speed_mps": 2.0},
            ],
        }

        jev_inp, _points, _trip_data = bundle_to_input(real_shaped_bundle)
        state = build_jev_state(jev_inp, variant="evidence")
        measurements = state.get("telemetry", {}).get("measurements", {})

        # Assert pickup-relative measurements are non-null numbers
        progress = measurements.get("pickup_progress_ratio", {}).get("value")
        assert isinstance(progress, (int, float)), f"pickup_progress_ratio is null or not a number: {progress}"

        davi = measurements.get("directional_approach_vector_index", {}).get("value")
        assert isinstance(davi, (int, float)), f"directional_approach_vector_index is null or not a number: {davi}"

        min_dist = measurements.get("min_distance_to_pickup", {}).get("value")
        assert isinstance(min_dist, (int, float)), f"min_distance_to_pickup is null or not a number: {min_dist}"

        # Assert distance-to-pickup change in window progression
        window_progression = state.get("telemetry", {}).get("window_progression", [])
        assert window_progression, "window_progression should not be empty"
        assert any("Khoảng cách đến điểm đón" in s for s in window_progression), (
            f"Missing distance-to-pickup narrative in windows: {window_progression}"
        )

    def test_measurement_descriptions_no_numeric_thresholds(self) -> None:
        """BUG 2: Scan every measurement description string for any number adjacent to unit or comparison word."""
        # Forbidden: number adjacent to a unit or comparison word (EN & VN: trên, dưới, vượt, hơn, over, above, below, >, <)
        threshold_scan_regex = re.compile(
            r"(?i)(?:(?:trên|dưới|vượt|hơn|over|above|below|[><]=?)\s*\d+|\d+\s*(?:trên|dưới|vượt|hơn|over|above|below|km/h|kmh|mps|m/s|km|m|s|giây|phút|giờ|%))"
        )

        state = build_jev_state(SAMPLE_FIXTURE_BUNDLE, variant="evidence")
        measurements = state.get("telemetry", {}).get("measurements", {})
        assert measurements, "measurements dictionary must not be empty"

        violations = []
        for name, m in measurements.items():
            if isinstance(m, dict) and "description" in m:
                desc = m["description"]
                matches = threshold_scan_regex.findall(desc)
                if matches:
                    violations.append(f"{name}: '{desc}' matched {matches}")

        assert not violations, f"Found numeric thresholds in measurement descriptions: {violations}"

    def test_dev300_evidence_coverage_zero_nulls(self) -> None:
        """Dev300 coverage check: per-class null rate for each measurement must be 0% where pickup exists."""
        from collections import defaultdict
        from pathlib import Path

        from scripts.benchmark.run_10k import bundle_to_input

        dev300_path = Path("/home/dat/releases_v2_1/dev300.jsonl")
        if not dev300_path.exists():
            import pytest

            pytest.skip("dev300.jsonl not found at /home/dat/releases_v2_1/dev300.jsonl")

        with open(dev300_path, encoding="utf-8") as f:
            trips = [json.loads(line) for line in f]

        assert len(trips) == 300, f"Expected 300 trips in dev300.jsonl, got {len(trips)}"

        class_counts = defaultdict(int)
        null_counts = defaultdict(lambda: defaultdict(int))
        pickup_relative_keys = [
            "pickup_progress_ratio",
            "directional_approach_vector_index",
            "min_distance_to_pickup",
        ]

        for t in trips:
            lbl = t.get("label", "unknown")
            class_counts[lbl] += 1
            jev_inp, _pts, _trip_data = bundle_to_input(t)
            state = build_jev_state(jev_inp, variant="evidence")
            meas = state.get("telemetry", {}).get("measurements", {})

            for k in meas.keys():
                if meas[k].get("value") is None:
                    null_counts[lbl][k] += 1

        # Assert 0% null rate for all measurements across all classes
        null_violations = []
        for lbl, n in class_counts.items():
            for k in pickup_relative_keys:
                cnt = null_counts[lbl][k]
                if cnt > 0:
                    null_violations.append(f"Class {lbl}: {k} has {cnt}/{n} nulls ({cnt / n * 100:.1f}%)")

        assert not null_violations, f"Found null measurements on dev300: {null_violations}"

    def test_percentile_position_rendering_with_in_test_reference(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unit test for percentile anchoring with a tiny in-test reference fixture (no corpus dependency)."""
        from src.services import jev_state_builder

        mock_artifact = {
            "quantiles": {
                "pickup_progress_ratio": {
                    "p01": 0.10,
                    "p05": 0.25,
                    "p10": 0.43,
                    "p25": 0.70,
                    "p50": 0.95,
                    "p75": 0.98,
                    "p90": 0.99,
                    "p95": 1.00,
                    "p99": 1.00,
                },
                "route_detour_ratio": {
                    "p01": 1.00,
                    "p05": 1.01,
                    "p10": 1.02,
                    "p25": 1.05,
                    "p50": 1.10,
                    "p75": 1.20,
                    "p90": 1.35,
                    "p95": 1.45,
                    "p99": 1.80,
                },
            },
            "class_medians": {
                "pickup_progress_ratio": {
                    "no_violation": 0.95,
                    "ERR-01": 0.92,
                    "ERR-02": 0.88,
                    "ERR-03": 0.28,
                    "ERR-04": 0.85,
                    "ERR-05": 0.94,
                    "insufficient_evidence": 0.91,
                },
                "route_detour_ratio": {
                    "no_violation": 1.05,
                    "ERR-01": 1.08,
                    "ERR-02": 1.10,
                    "ERR-03": 1.75,
                    "ERR-04": 1.02,
                    "ERR-05": 1.06,
                    "insufficient_evidence": 1.05,
                },
            },
        }

        monkeypatch.setattr(jev_state_builder, "load_reference_artifact", lambda: mock_artifact)

        test_bundle = {
            "pickup": [105.8500, 21.0200],
            "dropoff": [105.8600, 21.0300],
            "planned_route": {"distance_m": 2500.0, "is_estimated": False},
            "telemetry": [
                {"occurred_at": 1000, "longitude": 105.8500, "latitude": 21.0150, "speed_mps": 5.0},
                {"occurred_at": 1060, "longitude": 105.8520, "latitude": 21.0160, "speed_mps": 5.0},
            ],
        }

        state = build_jev_state(test_bundle, variant="evidence")
        meas = state.get("telemetry", {}).get("measurements", {})
        progress_meas = meas.get("pickup_progress_ratio", {})
        assert "reference_position" in progress_meas
        assert "thấp hơn" in progress_meas["reference_position"]
        assert "chuyến bình thường (tham chiếu tập train)" in progress_meas["reference_position"]

        # Ensure no forbidden verdict words in reference_position
        ref_text = progress_meas["reference_position"].lower()
        scrubbed = re.sub(r"chuyến bình thường\s*\(tham chiếu[^\)]*\)", "", ref_text)
        for forbidden in FORBIDDEN_VERDICT_EN:
            assert forbidden not in scrubbed
        for forbidden in FORBIDDEN_VERDICT_VN:
            assert forbidden not in scrubbed

    def test_percentile_position_missing_artifact_graceful(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When reference quantiles file is absent, builder must omit percentile clause and never crash."""
        from src.services import jev_state_builder

        monkeypatch.setattr(jev_state_builder, "load_reference_artifact", lambda: None)

        state = build_jev_state(SAMPLE_FIXTURE_BUNDLE, variant="evidence")
        meas = state.get("telemetry", {}).get("measurements", {})
        for _name, m in meas.items():
            if isinstance(m, dict):
                assert "reference_position" not in m

    def test_evidence_classref_variant(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """evidence_classref variant shows train-split median for each violation class."""
        from src.services import jev_state_builder

        mock_artifact = {
            "quantiles": {
                "route_detour_ratio": {
                    "p01": 1.0,
                    "p05": 1.01,
                    "p10": 1.02,
                    "p25": 1.05,
                    "p50": 1.10,
                    "p75": 1.20,
                    "p90": 1.35,
                    "p95": 1.45,
                    "p99": 1.80,
                }
            },
            "class_medians": {
                "route_detour_ratio": {
                    "no_violation": 1.05,
                    "ERR-01": 1.08,
                    "ERR-02": 1.10,
                    "ERR-03": 1.75,
                    "ERR-04": 1.02,
                    "ERR-05": 1.06,
                    "insufficient_evidence": 1.05,
                }
            },
        }

        monkeypatch.setattr(jev_state_builder, "load_reference_artifact", lambda: mock_artifact)

        state = build_jev_state(SAMPLE_FIXTURE_BUNDLE, variant="evidence_classref")
        meas = state.get("telemetry", {}).get("measurements", {})
        detour = meas.get("route_detour_ratio", {})
        detour_str = json.dumps(detour, ensure_ascii=False)
        assert "trung vị ERR-03:" in detour_str

    def test_phase_segmentation_normal_trip_starts_at_pickup_drives_to_dropoff(self) -> None:
        """Requirement 5(a): normal trip starting at pickup and driving to dropoff.

        Must have:
        - reached_pickup is True with timestamp
        - non-negative dropoff progress
        - no positive 'Khoảng cách đến điểm đón tăng thêm' lines in trip phase
        - window progression lines identify 'Giai đoạn chở khách' and report progress towards dropoff
        """
        normal_trip_bundle = {
            "pickup": [105.8500, 21.0200],
            "dropoff": [105.8600, 21.0300],
            "planned_route": {"distance_m": 1600.0, "is_estimated": False},
            "telemetry": [
                {
                    "occurred_at": "2026-10-18T10:00:00Z",
                    "longitude": 105.8500,
                    "latitude": 21.0200,
                    "speed_mps": 0.0,
                    "accuracy_m": 5.0,
                },
                {
                    "occurred_at": "2026-10-18T10:01:00Z",
                    "longitude": 105.8525,
                    "latitude": 21.0225,
                    "speed_mps": 6.5,
                    "accuracy_m": 8.0,
                },
                {
                    "occurred_at": "2026-10-18T10:02:00Z",
                    "longitude": 105.8550,
                    "latitude": 21.0250,
                    "speed_mps": 7.0,
                    "accuracy_m": 10.0,
                },
                {
                    "occurred_at": "2026-10-18T10:03:00Z",
                    "longitude": 105.8575,
                    "latitude": 21.0275,
                    "speed_mps": 6.5,
                    "accuracy_m": 7.0,
                },
                {
                    "occurred_at": "2026-10-18T10:04:00Z",
                    "longitude": 105.8600,
                    "latitude": 21.0300,
                    "speed_mps": 0.0,
                    "accuracy_m": 5.0,
                },
            ],
        }

        state = build_jev_state(normal_trip_bundle, variant="evidence")
        meas = state.get("telemetry", {}).get("measurements", {})

        # Reached pickup boolean and time
        reached_m = meas.get("reached_pickup", {})
        assert reached_m.get("value") is True
        assert reached_m.get("time") == "2026-10-18T10:00:00Z"
        assert meas.get("approach_duration", {}).get("value") == 0.0

        # Non-negative dropoff progress
        dropoff_prog = meas.get("dropoff_progress_ratio", {}).get("value")
        assert dropoff_prog is not None
        assert dropoff_prog >= 0.0, f"Expected non-negative dropoff progress, got {dropoff_prog}"

        # Window progression assertions
        window_narratives = state.get("telemetry", {}).get("window_progression", [])
        assert window_narratives, "window_progression must not be empty"

        for line in window_narratives:
            # Must not have positive distance-to-pickup increase in the trip phase
            assert "Khoảng cách đến điểm đón tăng thêm" not in line, f"Forbidden line in trip phase: '{line}'"
            # Lines must identify trip phase
            assert "Giai đoạn chở khách" in line, f"Expected 'Giai đoạn chở khách' in line: '{line}'"

        # At least one window reports moving closer to dropoff
        assert any("Khoảng cách đến điểm trả giảm bớt" in line for line in window_narratives)

    def test_phase_segmentation_err03_synthetic_approach_moves_away_from_pickup(self) -> None:
        """Requirement 5(b): ERR-03-like synthetic approach moving away from pickup before reaching it.

        Must show:
        - reached_pickup is False
        - negative pickup progress (pickup_progress_ratio < 0)
        - window progression lines identify 'Giai đoạn tiếp cận điểm đón' and report increasing distance to pickup
        """
        err03_bundle = {
            "pickup": [105.8500, 21.0200],
            "dropoff": [105.8600, 21.0300],
            "planned_route": {"distance_m": 2500.0, "is_estimated": False},
            "telemetry": [
                {
                    "occurred_at": "2026-10-18T10:00:00Z",
                    "longitude": 105.8500,
                    "latitude": 21.0180,
                    "speed_mps": 0.0,
                    "accuracy_m": 5.0,
                },
                {
                    "occurred_at": "2026-10-18T10:01:00Z",
                    "longitude": 105.8500,
                    "latitude": 21.0150,
                    "speed_mps": 6.0,
                    "accuracy_m": 5.0,
                },
                {
                    "occurred_at": "2026-10-18T10:02:00Z",
                    "longitude": 105.8500,
                    "latitude": 21.0110,
                    "speed_mps": 7.0,
                    "accuracy_m": 5.0,
                },
                {
                    "occurred_at": "2026-10-18T10:03:00Z",
                    "longitude": 105.8500,
                    "latitude": 21.0060,
                    "speed_mps": 8.0,
                    "accuracy_m": 5.0,
                },
            ],
        }

        state = build_jev_state(err03_bundle, variant="evidence")
        meas = state.get("telemetry", {}).get("measurements", {})

        reached_m = meas.get("reached_pickup", {})
        assert reached_m.get("value") is False
        assert reached_m.get("time") is None

        pickup_prog = meas.get("pickup_progress_ratio", {}).get("value")
        assert pickup_prog is not None
        assert pickup_prog < 0.0, f"Expected negative pickup progress for ERR-03 approach, got {pickup_prog}"

        window_narratives = state.get("telemetry", {}).get("window_progression", [])
        assert window_narratives, "window_progression must not be empty"

        for line in window_narratives:
            assert "Giai đoạn tiếp cận điểm đón" in line, f"Expected approach phase label in: '{line}'"

        assert any("Khoảng cách đến điểm đón tăng thêm" in line for line in window_narratives)

    def test_phase_segmentation_never_reaches_pickup_whole_track_is_approach(self) -> None:
        """Requirement 5(c): whole track is approach when driver never reaches pickup."""
        unreached_bundle = {
            "pickup": [105.8500, 21.0200],
            "dropoff": [105.8600, 21.0300],
            "planned_route": {"distance_m": 2500.0, "is_estimated": False},
            "telemetry": [
                {
                    "occurred_at": "2026-10-18T10:00:00Z",
                    "longitude": 105.8400,
                    "latitude": 21.0100,
                    "speed_mps": 5.0,
                    "accuracy_m": 10.0,
                },
                {
                    "occurred_at": "2026-10-18T10:01:00Z",
                    "longitude": 105.8410,
                    "latitude": 21.0110,
                    "speed_mps": 5.0,
                    "accuracy_m": 10.0,
                },
                {
                    "occurred_at": "2026-10-18T10:02:00Z",
                    "longitude": 105.8420,
                    "latitude": 21.0120,
                    "speed_mps": 5.0,
                    "accuracy_m": 10.0,
                },
            ],
        }

        state = build_jev_state(unreached_bundle, variant="evidence")
        meas = state.get("telemetry", {}).get("measurements", {})

        reached_m = meas.get("reached_pickup", {})
        assert reached_m.get("value") is False

        app_dur = meas.get("approach_duration", {}).get("value")
        assert app_dur == 120.0

        dropoff_prog = meas.get("dropoff_progress_ratio", {}).get("value")
        assert dropoff_prog is None

        window_narratives = state.get("telemetry", {}).get("window_progression", [])
        assert all("Giai đoạn tiếp cận điểm đón" in line for line in window_narratives)
