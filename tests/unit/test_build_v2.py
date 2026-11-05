"""Unit tests for releases_v2 realistic corpus generator (scripts/benchmark/build_v2)."""

import json
import tempfile
from pathlib import Path

import pytest

from scripts.benchmark.build_v2.builder import generate_v2_dataset
from scripts.benchmark.build_v2.config import GeneratorV2Config
from scripts.benchmark.build_v2.geometry import point_to_polyline_min_distance_m
from scripts.benchmark.run_10k import _scrub, bundle_to_input


@pytest.fixture(scope="module")
def small_v2_dataset():
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir) / "releases_v2_sample"
        cfg = GeneratorV2Config(seed=20261017, n_trips=140, total_drivers=30)
        dest, sha, manifest = generate_v2_dataset(out_dir, config=cfg)
        yield dest, sha, manifest


def test_v2_file_structure(small_v2_dataset):
    dest, sha, manifest = small_v2_dataset
    assert (dest / "trips.jsonl").exists()
    assert (dest / "labels.csv").exists()
    assert (dest / "manifest.json").exists()
    assert (dest / "checksums.json").exists()
    assert (dest / "sample_100.jsonl").exists()
    assert (dest / "sample_100.parquet").exists()


def test_v2_bundle_schema_and_keys(small_v2_dataset):
    dest, sha, manifest = small_v2_dataset
    required_keys = {
        "trip_ref",
        "trip_id",
        "assignment_id",
        "driver_id",
        "passenger_id",
        "vehicle_id",
        "label",
        "scenario",
        "requested_at",
        "pickup",
        "dropoff",
        "route",
        "telemetry",
        "traffic_observation",
        "platform_incident",
        "trip",
        "assignment",
        "conversation",
        "customer_report",
        "driver_objection",
        "driver_profile",
        "driver_analytics",
        "vehicle",
        "planned_route",
        "split",
        "release",
        "prevalence_weight",
        "simulation_audit",
    }
    with (dest / "trips.jsonl").open("r", encoding="utf-8") as f:
        for line in f:
            t = json.loads(line)
            missing = required_keys - set(t.keys())
            assert not missing, f"Trip {t.get('trip_ref')} missing keys: {missing}"
            assert "severity" not in t, "Top-level severity must be absent"
            assert "severity" in t["simulation_audit"]
            assert t["release"] in {"releases_v2", "releases_v2.1"}
            assert t["split"] in {"train", "validation", "test"}
            assert isinstance(t["prevalence_weight"], (int, float))
            assert t["prevalence_weight"] > 0
            # traffic_observation must be populated
            tro = t["traffic_observation"]
            assert "congestion_level" in tro
            assert "traffic_level" in tro
            assert "average_speed_mps" in tro
            assert tro["congestion_level"] in {"clear", "moderate", "heavy"}
            # planned_route must contain real road geometry
            pr = t["planned_route"]
            assert "coordinates" in pr["geometry"]
            assert len(pr["geometry"]["coordinates"]) >= 2
            assert pr["distance_m"] > 0
            assert pr["duration_s"] > 0


def test_v2_driver_split_disjoint(small_v2_dataset):
    dest, sha, manifest = small_v2_dataset
    split_drivers: dict[str, set[str]] = {"train": set(), "validation": set(), "test": set()}
    with (dest / "trips.jsonl").open("r", encoding="utf-8") as f:
        for line in f:
            t = json.loads(line)
            split_drivers[t["split"]].add(t["driver_id"])

    # Disjoint driver check: no intersection between any pairs of splits
    assert len(split_drivers["train"] & split_drivers["validation"]) == 0
    assert len(split_drivers["train"] & split_drivers["test"]) == 0
    assert len(split_drivers["validation"] & split_drivers["test"]) == 0
    assert manifest["drivers"]["leakage"] == 0


def test_v2_road_grounding_and_vietnam_bounds(small_v2_dataset):
    dest, sha, manifest = small_v2_dataset
    with (dest / "trips.jsonl").open("r", encoding="utf-8") as f:
        for line in f:
            t = json.loads(line)
            plat, plon = t["pickup"]["lat"], t["pickup"]["lon"]
            dlat, dlon = t["dropoff"]["lat"], t["dropoff"]["lon"]
            assert 8.0 <= plat <= 24.0 and 102.0 <= plon <= 110.0
            assert 8.0 <= dlat <= 24.0 and 102.0 <= dlon <= 110.0

            # Normal trips cross-track to planned road geometry
            if t["label"] == "no_violation" and not t.get("simulation_audit", {}).get("is_hard_negative"):
                coords = t["planned_route"]["geometry"]["coordinates"]
                residuals = [
                    point_to_polyline_min_distance_m(p["longitude"], p["latitude"], coords)
                    for p in t["telemetry"]
                    if not p.get("is_multipath_outlier")
                ]
                if residuals:
                    median_res = sorted(residuals)[len(residuals) // 2]
                    assert median_res <= 15.0, f"Normal trip road median residual {median_res}m > 15m"


def test_v2_noise_model_kinematics(small_v2_dataset):
    dest, sha, manifest = small_v2_dataset
    intervals = []
    speed_gaps = []
    accuracies = []

    with (dest / "trips.jsonl").open("r", encoding="utf-8") as f:
        for line in f:
            t = json.loads(line)
            pts = t["telemetry"]
            for i in range(1, len(pts)):
                p1, p2 = pts[i - 1], pts[i]
                if p1.get("occurred_at") and p2.get("occurred_at"):
                    from datetime import datetime

                    t1 = datetime.fromisoformat(p1["occurred_at"].replace("Z", "+00:00"))
                    t2 = datetime.fromisoformat(p2["occurred_at"].replace("Z", "+00:00"))
                    dt = (t2 - t1).total_seconds()
                    intervals.append(dt)

                    # Speed consistency check: reported speed vs displacement speed
                    rep_speed = p2.get("speed_mps")
                    if rep_speed is not None and not p2.get("mock_location_reported"):
                        from scripts.benchmark.build_v2.geometry import haversine_m

                        disp = haversine_m(p1["longitude"], p1["latitude"], p2["longitude"], p2["latitude"])
                        impl_speed = disp / max(1e-3, dt)
                        speed_gaps.append(abs(rep_speed - impl_speed))

                acc = p2.get("accuracy_m")
                if acc is not None:
                    accuracies.append(acc)

    # 1. Ping intervals must not all be 15.0s
    distinct_intervals = set(round(i, 1) for i in intervals)
    assert len(distinct_intervals) > 5, "Ping intervals lack jitter/missed pings/profile mixture"

    # 2. Speed gap |v_reported - v_implied| should have median < 3.0 m/s for legitimate points
    if speed_gaps:
        median_gap = sorted(speed_gaps)[len(speed_gaps) // 2]
        assert median_gap < 3.0, f"Speed gap median {median_gap} m/s too high (reported speed inconsistent)"

    # 3. Accuracy median ~8-15m
    if accuracies:
        median_acc = sorted(accuracies)[len(accuracies) // 2]
        assert 6.0 <= median_acc <= 20.0, f"Accuracy median {median_acc}m out of expected range"


def test_v2_all_7_classes_and_err03_subtypes(small_v2_dataset):
    dest, sha, manifest = small_v2_dataset
    classes_present = set()
    err03_subtypes = set()

    with (dest / "trips.jsonl").open("r", encoding="utf-8") as f:
        for line in f:
            t = json.loads(line)
            classes_present.add(t["label"])
            if t["label"] == "ERR-03":
                sub = t.get("simulation_audit", {}).get("err03_subtype")
                if sub:
                    err03_subtypes.add(sub)

    expected_classes = {
        "no_violation",
        "ERR-01",
        "ERR-02",
        "ERR-03",
        "ERR-04",
        "ERR-05",
        "insufficient_evidence",
    }
    assert classes_present == expected_classes
    assert "approach_wrong_direction" in err03_subtypes
    assert "in_trip_detour" in err03_subtypes


def test_v2_dialogue_leak_reduction(small_v2_dataset):
    dest, sha, manifest = small_v2_dataset
    has_empty_conv = False
    leak_phrases = ["cuốc ảo", "sai hướng", "gian lận"]

    with (dest / "trips.jsonl").open("r", encoding="utf-8") as f:
        for line in f:
            t = json.loads(line)
            conv = t.get("conversation") or []
            if not conv:
                has_empty_conv = True
            for turn in conv:
                text = turn.get("text", "").lower()
                for leak in leak_phrases:
                    assert leak not in text, f"Label leaked in dialogue: '{leak}' found in '{text}'"

            report = (t.get("customer_report") or "").lower()
            for leak in leak_phrases:
                assert leak not in report, f"Label leaked in report: '{leak}' found in '{report}'"

    assert has_empty_conv, "Expected at least one trip with empty dialogue"


def test_v2_prevalence_weight_reweighting(small_v2_dataset):
    dest, sha, manifest = small_v2_dataset
    test_fraud_weighted = 0.0
    test_total_weighted = 0.0

    adverse = {"ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05"}
    with (dest / "trips.jsonl").open("r", encoding="utf-8") as f:
        for line in f:
            t = json.loads(line)
            if t["split"] == "test":
                w = t["prevalence_weight"]
                test_total_weighted += w
                if t["label"] in adverse:
                    test_fraud_weighted += w

    if test_total_weighted > 0:
        fraud_share = test_fraud_weighted / test_total_weighted
        # Prevalence weight reweights fraud close to ~1% (0.005 to 0.02)
        assert 0.005 <= fraud_share <= 0.025, f"Reweighted fraud share {fraud_share:.4f} not near 1%"


def test_v2_determinism():
    with tempfile.TemporaryDirectory() as tmpdir:
        out1 = Path(tmpdir) / "run1"
        out2 = Path(tmpdir) / "run2"
        cfg = GeneratorV2Config(seed=12345, n_trips=35, total_drivers=10)
        _, sha1, _ = generate_v2_dataset(out1, config=cfg)
        _, sha2, _ = generate_v2_dataset(out2, config=cfg)
        assert sha1 == sha2, "Determinism failed: same seed yielded different sha256"


def test_v2_leak_audit(small_v2_dataset):
    dest, sha, manifest = small_v2_dataset
    with (dest / "trips.jsonl").open("r", encoding="utf-8") as f:
        for line in f:
            raw_bundle = json.loads(line)
            # Item 1: severity moved inside simulation_audit, absent from top level
            assert "severity" not in raw_bundle, "Top-level severity must not be present (label shortcut)"
            assert "simulation_audit" in raw_bundle
            assert "severity" in raw_bundle["simulation_audit"]

            scrubbed = _scrub(raw_bundle)
            # Generator-only keys should be removed
            assert "simulation_audit" not in scrubbed
            assert "scenario" not in scrubbed
            assert "severity" not in scrubbed
            assert "label" not in scrubbed
            assert "label_provenance" not in scrubbed

            # Detector input projection audit
            inp, pts, trip_data = bundle_to_input(raw_bundle)
            inp_dict = inp.model_dump()
            assert "severity" not in inp_dict
            assert "scenario" not in inp_dict
            assert "severity" not in trip_data
            assert "scenario" not in trip_data


def test_v2_customer_report_honest_and_fraud(small_v2_dataset):
    dest, sha, manifest = small_v2_dataset
    honest_reports = 0
    honest_total = 0
    fraud_reports = 0
    fraud_total = 0
    fraud_classes = {"ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05"}

    with (dest / "trips.jsonl").open("r", encoding="utf-8") as f:
        for line in f:
            t = json.loads(line)
            rep = t.get("customer_report")
            if t["label"] == "no_violation":
                honest_total += 1
                if rep is not None:
                    honest_reports += 1
            elif t["label"] in fraud_classes:
                fraud_total += 1
                if rep is not None:
                    fraud_reports += 1

    assert honest_total > 0
    assert fraud_total > 0
    # Customer report presence != fraud
    assert honest_reports > 0, "Honest trips (no_violation) must have some customer reports"
    assert honest_reports < honest_total, "Not all honest trips should have reports"
    assert fraud_reports < fraud_total, "Some fraud trips must have no reports (silent fraud)"


def test_v2_device_speed_plausible_cap_with_multipath(small_v2_dataset):
    dest, sha, manifest = small_v2_dataset
    max_device_speed_mps = 0.0
    multipath_outliers_found = False

    with (dest / "trips.jsonl").open("r", encoding="utf-8") as f:
        for line in f:
            t = json.loads(line)
            for p in t["telemetry"]:
                sp = p.get("speed_mps")
                if sp is not None:
                    max_device_speed_mps = max(max_device_speed_mps, float(sp))
                if p.get("is_multipath_outlier"):
                    multipath_outliers_found = True

    assert multipath_outliers_found, "Fixture must include multipath outliers"
    # Urban speed cap: device speed_mps should never exceed 25.0 m/s (~90 km/h)
    assert max_device_speed_mps <= 25.0, (
        f"Device speed_mps max {max_device_speed_mps} m/s ({max_device_speed_mps * 3.6:.1f} km/h) exceeds urban cap 25 m/s"
    )


def test_v2_err01_err02_contain_moving_points(small_v2_dataset):
    dest, sha, manifest = small_v2_dataset
    err01_max_speeds = []
    err02_max_speeds = []

    with (dest / "trips.jsonl").open("r", encoding="utf-8") as f:
        for line in f:
            t = json.loads(line)
            if t["label"] == "ERR-01":
                speeds = [float(p["speed_mps"]) for p in t["telemetry"] if p.get("speed_mps") is not None]
                if speeds:
                    err01_max_speeds.append(max(speeds))
            elif t["label"] == "ERR-02":
                speeds = [float(p["speed_mps"]) for p in t["telemetry"] if p.get("speed_mps") is not None]
                if speeds:
                    err02_max_speeds.append(max(speeds))

    assert len(err01_max_speeds) > 0, "No ERR-01 trips found"
    assert len(err02_max_speeds) > 0, "No ERR-02 trips found"
    assert all(s > 2.0 for s in err01_max_speeds), "ERR-01 trips must have moving points (approach leg)"
    assert all(s > 2.0 for s in err02_max_speeds), "ERR-02 trips must have moving points (approach leg)"


def test_v2_err05_urban_median_speed(small_v2_dataset):
    dest, sha, manifest = small_v2_dataset
    err05_medians_mps = []

    with (dest / "trips.jsonl").open("r", encoding="utf-8") as f:
        for line in f:
            t = json.loads(line)
            if t["label"] == "ERR-05":
                speeds = [float(p["speed_mps"]) for p in t["telemetry"] if p.get("speed_mps") is not None]
                if speeds:
                    err05_medians_mps.append(sorted(speeds)[len(speeds) // 2])

    assert len(err05_medians_mps) > 0, "No ERR-05 trips found"
    # Urban speed median: typical average 20-30 km/h (5.5 - 8.5 m/s), should not be 114 km/h (31.7 m/s)
    for med in err05_medians_mps:
        med_kmh = med * 3.6
        assert med_kmh <= 45.0, f"ERR-05 median speed {med_kmh:.1f} km/h is not urban (< 45 km/h)"


def test_v2_text_only_classifier(small_v2_dataset):
    from scripts.benchmark.build_v2.text_classifier import evaluate_text_leakage_classifier

    dest, sha, manifest = small_v2_dataset
    res = evaluate_text_leakage_classifier(dest / "trips.jsonl")
    assert "macro_f1" in res
    assert 0.0 <= res["macro_f1"] <= 1.0
    # Text-only macro-F1 must be well below full evidence (e.g. <= 0.45)
    assert res["macro_f1"] <= 0.45, f"Text classifier macro-F1 {res['macro_f1']:.3f} > 0.45 indicates text leakage"


def test_v2_run_10k_compatibility(small_v2_dataset):
    dest, sha, manifest = small_v2_dataset
    with (dest / "trips.jsonl").open("r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= 10:
                break
            bundle = json.loads(line)
            inp, pts, trip_data = bundle_to_input(bundle)
            assert inp is not None
            assert isinstance(pts, list)
            assert isinstance(trip_data, dict)


def test_v2_mock_location_reported_rates():
    """Verify mock_location_reported is not a perfect shortcut:

    - Configurable versioned rates in GeneratorV2Config (default ~50% ERR-05, ~0.3% honest)
    - ERR-05 trips flag mock in ~50% of trips; remaining 50% rely on teleport jumps only
    - ~0.3% of no_violation trips report mock flag with normal kinematics
    - Other classes have 0% mock flag
    """
    cfg = GeneratorV2Config(seed=20261017, n_trips=2000, total_drivers=100)
    assert hasattr(cfg, "mock_flag_err05_rate"), "Config missing mock_flag_err05_rate"
    assert hasattr(cfg, "mock_flag_honest_rate"), "Config missing mock_flag_honest_rate"
    assert 0.40 <= cfg.mock_flag_err05_rate <= 0.60
    assert 0.001 <= cfg.mock_flag_honest_rate <= 0.010

    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir) / "mock_rate_fixture"
        dest, sha, manifest = generate_v2_dataset(out_dir, config=cfg)

        per_label_trips: dict[str, int] = {}
        per_label_mock_trips: dict[str, int] = {}
        unflagged_err05_jumps: list[float] = []

        with (dest / "trips.jsonl").open("r", encoding="utf-8") as f:
            for line in f:
                t = json.loads(line)
                lbl = t["label"]
                pts = t["telemetry"]
                has_mock = any(bool(p.get("mock_location_reported")) for p in pts)

                per_label_trips[lbl] = per_label_trips.get(lbl, 0) + 1
                if has_mock:
                    per_label_mock_trips[lbl] = per_label_mock_trips.get(lbl, 0) + 1

                if lbl == "ERR-05" and not has_mock:
                    # Must still rely on teleport jump
                    max_disp = 0.0
                    from scripts.benchmark.build_v2.geometry import haversine_m

                    for p1, p2 in zip(pts, pts[1:]):
                        disp = haversine_m(p1["longitude"], p1["latitude"], p2["longitude"], p2["latitude"])
                        if disp > max_disp:
                            max_disp = disp
                    unflagged_err05_jumps.append(max_disp)

        err05_total = per_label_trips.get("ERR-05", 0)
        err05_mock = per_label_mock_trips.get("ERR-05", 0)
        err05_rate = err05_mock / max(1, err05_total)

        nv_total = per_label_trips.get("no_violation", 0)
        nv_mock = per_label_mock_trips.get("no_violation", 0)
        nv_rate = nv_mock / max(1, nv_total)

        # 1. ERR-05 mock rate tolerance [0.35, 0.65] around 50%
        assert 0.35 <= err05_rate <= 0.65, f"ERR-05 mock rate {err05_rate:.2%} not within tolerance [35%, 65%]"

        # 2. no_violation mock rate tolerance [0.001, 0.010] around 0.3%
        assert 0.001 <= nv_rate <= 0.010, f"no_violation mock rate {nv_rate:.3%} not within tolerance [0.1%, 1.0%]"

        # 3. Other classes must be 0% mock flag
        for other_lbl in ["ERR-01", "ERR-02", "ERR-03", "ERR-04", "insufficient_evidence"]:
            other_mock = per_label_mock_trips.get(other_lbl, 0)
            assert other_mock == 0, f"{other_lbl} should have 0 mock trips, found {other_mock}"

        # 4. Unflagged ERR-05 trips must still contain teleport jumps (> 500m displacement jump)
        assert len(unflagged_err05_jumps) > 0, "No unflagged ERR-05 trips generated"
        assert all(j >= 500.0 for j in unflagged_err05_jumps), (
            f"Unflagged ERR-05 jumps {unflagged_err05_jumps} must rely on teleport jumps >= 500m"
        )


def test_v2_1_generator_version_and_release_name():
    cfg = GeneratorV2Config()
    assert cfg.release_name == "releases_v2.1"
    assert "v2.1" in cfg.generator_version
    assert hasattr(cfg, "driver_objection_rates")
    rates = cfg.driver_objection_rates
    assert 0.03 <= rates["no_violation"] <= 0.05
    assert 0.15 <= rates["insufficient_evidence"] <= 0.25
    for fraud_cls in ["ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05"]:
        assert 0.30 <= rates[fraud_cls] <= 0.60


def test_v2_1_driver_objection_rates_and_realism():
    """Verify driver_objection rates across classes:
    - Honest drivers dispute too (flagged gridlock stalls, detours, glitches, ratings)
    - Some fraud drivers never dispute (silent fraud)
    - Realistic per-class rates in expected ranges
    """
    cfg = GeneratorV2Config(seed=20261017, n_trips=2000, total_drivers=100)
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir) / "v2_1_objection_fixture"
        dest, sha, manifest = generate_v2_dataset(out_dir, config=cfg)

        per_label_trips: dict[str, int] = {}
        per_label_objections: dict[str, int] = {}
        all_objection_texts: list[str] = []

        with (dest / "trips.jsonl").open("r", encoding="utf-8") as f:
            for line in f:
                t = json.loads(line)
                lbl = t["label"]
                per_label_trips[lbl] = per_label_trips.get(lbl, 0) + 1
                obj = t.get("driver_objection")
                if obj and isinstance(obj, dict) and obj.get("text"):
                    per_label_objections[lbl] = per_label_objections.get(lbl, 0) + 1
                    all_objection_texts.append(obj["text"])

        # Every class must have some objections (no 0% objection class)
        for lbl in ["no_violation", "insufficient_evidence", "ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05"]:
            total = per_label_trips.get(lbl, 0)
            with_obj = per_label_objections.get(lbl, 0)
            assert with_obj > 0, f"{lbl} must have some objections (honest/fraud drivers dispute)"
            assert with_obj < total, f"{lbl} must have some non-objection trips (silent drivers)"

        # Check empirical rates are close to target
        nv_rate = per_label_objections.get("no_violation", 0) / max(1, per_label_trips.get("no_violation", 0))
        assert 0.02 <= nv_rate <= 0.07, f"no_violation objection rate {nv_rate:.3f} outside [0.02, 0.07]"

        ie_rate = per_label_objections.get("insufficient_evidence", 0) / max(
            1, per_label_trips.get("insufficient_evidence", 0)
        )
        assert 0.10 <= ie_rate <= 0.30, f"insufficient_evidence objection rate {ie_rate:.3f} outside [0.10, 0.30]"

        for f_cls in ["ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05"]:
            f_rate = per_label_objections.get(f_cls, 0) / max(1, per_label_trips.get(f_cls, 0))
            assert 0.25 <= f_rate <= 0.65, f"{f_cls} objection rate {f_rate:.3f} outside [0.25, 0.65]"


def test_v2_1_driver_objection_leakage_and_paraphrase():
    from scripts.benchmark.realism_report import LABEL_KEYWORDS_PATTERN

    cfg = GeneratorV2Config(seed=20261017, n_trips=500, total_drivers=40)
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir) / "v2_1_leak_fixture"
        dest, sha, manifest = generate_v2_dataset(out_dir, config=cfg)

        objection_texts = []
        with (dest / "trips.jsonl").open("r", encoding="utf-8") as f:
            for line in f:
                t = json.loads(line)
                obj = t.get("driver_objection")
                if obj and isinstance(obj, dict) and obj.get("text"):
                    txt = obj["text"]
                    objection_texts.append(txt)
                    assert not bool(LABEL_KEYWORDS_PATTERN.search(txt)), f"Keyword leak in objection: {txt}"
                    for c_name in [
                        "ERR-01",
                        "ERR-02",
                        "ERR-03",
                        "ERR-04",
                        "ERR-05",
                        "insufficient_evidence",
                        "no_violation",
                    ]:
                        assert c_name not in txt, f"Class name {c_name} leaked in objection text: {txt}"

        assert len(objection_texts) > 20
        # Diversity check
        assert len(set(objection_texts)) / len(objection_texts) >= 0.50


def test_v2_1_automated_shortcut_audit():
    from scripts.benchmark.realism_report import run_shortcut_audit

    cfg = GeneratorV2Config(seed=20261017, n_trips=500, total_drivers=40)
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir) / "v2_1_audit_fixture"
        dest, sha, manifest = generate_v2_dataset(out_dir, config=cfg)

        audit = run_shortcut_audit(dest / "trips.jsonl")
        assert audit["passed"] is True, f"Audit failed: {audit.get('failing_features')}"
        assert len(audit["top_15_features"]) == 15
        for feat in audit["top_15_features"]:
            if feat["is_non_kinematic"]:
                assert feat["macro_f1"] <= 0.30, (
                    f"Non-kinematic feature {feat['feature']} exceeded 0.30: {feat['macro_f1']}"
                )


def test_v2_1_shortcut_audit_fails_on_injected_shortcut():
    from scripts.benchmark.realism_report import run_shortcut_audit

    cfg = GeneratorV2Config(seed=20261017, n_trips=300, total_drivers=30)
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir) / "v2_1_corrupt_fixture"
        dest, sha, manifest = generate_v2_dataset(out_dir, config=cfg)

        trips = []
        with (dest / "trips.jsonl").open("r", encoding="utf-8") as f:
            for line in f:
                trips.append(json.loads(line))

        # Inject an artificial shortcut into customer_report length (different lengths per class)
        class_lens = {
            "no_violation": 10,
            "ERR-01": 50,
            "ERR-02": 100,
            "ERR-03": 150,
            "ERR-04": 200,
            "ERR-05": 250,
            "insufficient_evidence": 300,
        }
        for t in trips:
            t["customer_report"] = "x" * class_lens.get(t["label"], 10)

        audit = run_shortcut_audit(trips)
        assert audit["passed"] is False, "Audit should fail on injected non-kinematic shortcut"
        failing_names = [f["feature"] for f in audit["failing_features"]]
        assert "len_customer_report" in failing_names
