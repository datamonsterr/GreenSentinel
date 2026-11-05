"""Unit tests for the 10k benchmark builder (Issue #254)."""

import hashlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


build_10k = _load("build_10k", "scripts/benchmark/build_10k.py")


def _sha(bundles):
    lines = [json.dumps(b, sort_keys=True, separators=(",", ":"), ensure_ascii=False) for b in bundles]
    return hashlib.sha256(("\n".join(lines) + "\n").encode()).hexdigest()


def test_determinism_tiny_build():
    b1, _, _ = build_10k.build_dataset(20, 20261011, "happy", progress_every=0)
    b2, _, _ = build_10k.build_dataset(20, 20261011, "happy", progress_every=0)
    assert _sha(b1) == _sha(b2)
    assert b1 == b2


def test_determinism_manifest_sha(tmp_path):
    b1, c1, g1 = build_10k.build_dataset(20, 20261011, "happy", progress_every=0)
    m1 = build_10k.write_output(b1, c1, g1, 20261011, "happy", tmp_path / "a")
    b2, c2, g2 = build_10k.build_dataset(20, 20261011, "happy", progress_every=0)
    m2 = build_10k.write_output(b2, c2, g2, 20261011, "happy", tmp_path / "b")
    assert m1["trips_sha256"] == m2["trips_sha256"]
    assert (tmp_path / "a" / "trips.jsonl").read_bytes() == (tmp_path / "b" / "trips.jsonl").read_bytes()


def test_class_mix_exact_10k():
    assert build_10k.class_counts_for_n(10000) == {
        "no_violation": 7000,
        "ERR-02": 800,
        "insufficient_evidence": 600,
        "ERR-01": 500,
        "ERR-03": 500,
        "ERR-04": 300,
        "ERR-05": 300,
    }


def test_class_mix_scaled_1000():
    counts = build_10k.class_counts_for_n(1000)
    assert sum(counts.values()) == 1000
    assert counts == {
        "no_violation": 700,
        "ERR-02": 80,
        "insufficient_evidence": 60,
        "ERR-01": 50,
        "ERR-03": 50,
        "ERR-04": 30,
        "ERR-05": 30,
    }
    bundles, _, _ = build_10k.build_dataset(1000, 20261011, "happy", progress_every=0)
    assert dict(Counter(b["label"] for b in bundles)) == counts


def test_bundle_key_completeness():
    bundles, _, _ = build_10k.build_dataset(20, 20261011, "happy", progress_every=0)
    assert bundles
    for b in bundles:
        assert build_10k.REQUIRED_BUNDLE_KEYS <= set(b), b["trip_ref"]
        assert {"approach_ssd_s", "davi", "coverage", "max_gap_s", "mock_ratio", "arrived_at_pickup"} <= set(
            b["measured_features"]
        )
        assert b["label_provenance"]["synthetic"] is True
        assert b["telemetry"]
        if b.get("dialogue_mode") == "empty":
            assert b["conversation"] == []
        else:
            assert b["conversation"]
        assert {"dialogue_mode", "legit_cancel_subset", "customer_actions", "passenger_feedback"} <= set(b)
        assert b["dialogue_mode"] in ("full", "empty", "customer_only")
        assert set(b["driver_objection"]) == {"status", "text"}


def _fake(label, gridlock=False, **measured):
    base = {"approach_ssd_s": 10.0, "davi": 0.9, "coverage": 1.0, "max_gap_s": 15.0, "mock_ratio": 0.0}
    base.update(measured)
    return {"label": label, "gridlock_subset": gridlock, "measured_features": base}


def _gates():
    return {
        "err02_ssd_cover": 0.95,
        "gridlock_davi_min": 0.5,
        "gridlock_davi_cover": 0.90,
        "dropout_gap_min_s": 30,
        "spoof_mock_min": 0.8,
        "normal_ssd_cover": 0.95,
        "normal_ssd_max_s": 60,
        "slowcrawl_davi_min": 0.3,
        "slowcrawl_davi_cover": 0.90,
        "slowcrawl_ssd_max_s": 180,
        "slowcrawl_ssd_cover": 0.95,
        "loop_tort_min": 2.0,
        "loop_tort_cover": 0.95,
        "loop_davi_max": 0.0,
        "loop_davi_cover": 0.90,
    }


def _fake_subset(label, route_tort=1.3, **measured):
    row = _fake(label, **measured)
    row["route"] = {"tortuosity": route_tort}
    return row


def test_gates_pass_fixtures():
    bundles = (
        [_fake("ERR-02", approach_ssd_s=200.0)] * 20
        + [_fake("no_violation", gridlock=True, davi=0.8)] * 10
        + [_fake("no_violation", approach_ssd_s=5.0)] * 10
        + [_fake("insufficient_evidence", max_gap_s=60.0)]
        + [_fake("ERR-05", mock_ratio=1.0)]
    )
    slow = _fake_subset("ERR-02", approach_ssd_s=45.0, davi=0.8)
    slow["slowcrawl_subset"] = True
    loop = _fake_subset("ERR-03", route_tort=2.8, davi=-0.4)
    loop["loop_subset"] = True
    bundles += [slow] * 5 + [loop] * 5
    assert all(g["pass"] for g in build_10k.check_gates(bundles, _gates()))


def test_gates_fail_fixtures():
    # ERR-02 stalls too short -> SSD gate fails; clean spoof mock -> mock gate fails.
    bundles = (
        [_fake("ERR-02", approach_ssd_s=10.0)] * 20
        + [_fake("no_violation", approach_ssd_s=5.0)] * 10
        + [_fake("insufficient_evidence", max_gap_s=60.0)]
        + [_fake("ERR-05", mock_ratio=0.0)]
    )
    results = {g["gate"]: g for g in build_10k.check_gates(bundles, _gates())}
    assert results["ERR-02 SSD>=180"]["pass"] is False
    assert results["spoof mock>=0.8"]["pass"] is False
    assert results["dropout max_gap>30"]["pass"] is True
    # Empty slowcrawl/loop subsets pass vacuously (no rows to violate).
    assert results["slowcrawl DAVI>0.3"]["pass"] is True
    assert results["loop tort>=2.0"]["pass"] is True


def test_gates_fail_subset_fixtures():
    # Slow-crawl that never moves toward pickup + loop with normal tortuosity fail.
    slow = _fake_subset("ERR-02", approach_ssd_s=45.0, davi=-0.2)
    slow["slowcrawl_subset"] = True
    loop = _fake_subset("ERR-03", route_tort=1.5, davi=-0.4)
    loop["loop_subset"] = True
    bundles = (
        [_fake("ERR-02", approach_ssd_s=200.0)] * 20
        + [_fake("no_violation", approach_ssd_s=5.0)] * 10
        + [_fake("insufficient_evidence", max_gap_s=60.0)]
        + [_fake("ERR-05", mock_ratio=1.0)]
        + [slow] * 5
        + [loop] * 5
    )
    results = {g["gate"]: g for g in build_10k.check_gates(bundles, _gates())}
    assert results["slowcrawl DAVI>0.3"]["pass"] is False
    assert results["loop tort>=2.0"]["pass"] is False
    assert results["ERR-02 SSD>=180"]["pass"] is True  # slowcrawl excluded from the stall gate


def test_dialogue_modes_present_and_shaped():
    bundles, _, _ = build_10k.build_dataset(500, 20261011, "happy", progress_every=0)
    modes = {b["dialogue_mode"] for b in bundles}
    assert modes <= {"full", "empty", "customer_only"}
    assert "empty" in modes
    assert "customer_only" in modes
    for b in bundles:
        if b["dialogue_mode"] == "empty":
            assert b["conversation"] == []
        elif b["dialogue_mode"] == "customer_only":
            assert 2 <= len(b["conversation"]) <= 6
            assert {t["role"] for t in b["conversation"]} == {"customer"}


def test_legit_cancel_subset():
    bundles, _, _ = build_10k.build_dataset(500, 20261011, "happy", progress_every=0)
    legit = [b for b in bundles if b.get("legit_cancel_subset") is True]
    assert legit
    allowed = {e["reason"] for e in build_10k.LEGIT_CANCEL_REASONS}
    assert len(build_10k.LEGIT_CANCEL_REASONS) >= 10
    for b in legit:
        assert b["label"] == "no_violation"
        assert b["trip"]["status"] == "cancelled"
        assert b["assignment"]["cancellation_actor"] == "passenger"
        assert b["assignment"]["cancellation_reason"] in allowed


def test_passenger_feedback_shape_and_consistency():
    bundles, _, _ = build_10k.build_dataset(500, 20261011, "happy", progress_every=0)
    complaint = set(build_10k.COMPLAINT_CATEGORIES)
    praise = set(build_10k.PRAISE_CATEGORIES)
    for b in bundles:
        fb = b["passenger_feedback"]
        assert set(fb) == {"rating", "category", "text"}
        assert fb["rating"] is None or fb["rating"] in (1, 2, 3, 4, 5)
        assert fb["text"]
        if b["label"] in ("ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05"):
            assert fb["category"] in complaint, (b["label"], fb["category"])
        elif b["label"] == "no_violation":
            assert fb["category"] in praise | {"neutral"}, fb["category"]
        else:
            assert fb["category"] == "neutral"


def test_customer_actions_derived():
    bundles, _, _ = build_10k.build_dataset(200, 20261011, "happy", progress_every=0)
    for b in bundles:
        actions = {a["action"]: a["at_offset_s"] for a in b["customer_actions"]}
        if b["conversation"]:
            assert "chat_opened" in actions and "message_sent" in actions
        else:
            assert "chat_opened" not in actions and "message_sent" not in actions
        cancelled_pre = b["trip"]["status"] == "cancelled" and b["assignment"]["arrived_at"] is None
        assert ("cancelled_before_pickup" in actions) == cancelled_pre
        rated = b["passenger_feedback"]["rating"] is not None
        assert ("rated" in actions) == rated


def test_manifest_config_version_from_cfg(tmp_path):
    bundles, counts, gates = build_10k.build_dataset(20, 20261011, "happy", progress_every=0)
    manifest = build_10k.write_output(bundles, counts, gates, 20261011, "happy", tmp_path / "m")
    assert manifest["config_version"] == "0.4.0-benchmark"


def test_g1g2_subsets_present_and_shaped():
    bundles, _, _ = build_10k.build_dataset(2000, 20261011, "happy", progress_every=0)
    slow = [b for b in bundles if b.get("slowcrawl_subset") is True]
    loop = [b for b in bundles if b.get("loop_subset") is True]
    assert slow and loop
    # Shares within tolerance of the configured 0.30 (binomial slack at n=2000).
    err02 = [b for b in bundles if b["label"] == "ERR-02"]
    err03 = [b for b in bundles if b["label"] == "ERR-03"]
    assert abs(len(slow) / len(err02) - 0.30) < 0.10
    assert abs(len(loop) / len(err03) - 0.30) < 0.10
    for b in slow:
        assert b["label"] == "ERR-02" and b["scenario"] == "slow_crawl_fraud"
        assert b["traffic_observation"]["congestion_level"] == "clear"
        assert b["measured_features"]["approach_ssd_s"] < 180
        assert b["measured_features"]["davi"] > 0.3
        assert b["trip"]["status"] == "cancelled"
    for b in loop:
        assert b["label"] == "ERR-03" and b["scenario"] == "loop_deviation"
        assert b["route"]["tortuosity"] >= 2.0
        assert b["measured_features"]["davi"] < 0.0
        assert b["trip"]["status"] == "cancelled"


def test_g1g2_subset_gates_pass_on_real_build():
    bundles, _, gates = build_10k.build_dataset(2000, 20261011, "happy", progress_every=0)
    by_gate = {g["gate"]: g for g in gates}
    assert by_gate["slowcrawl DAVI>0.3"]["pass"] is True
    assert by_gate["slowcrawl SSD<180"]["pass"] is True
    assert by_gate["loop tort>=2.0"]["pass"] is True
    assert by_gate["loop DAVI<0"]["pass"] is True
    assert by_gate["ERR-02 SSD>=180"]["pass"] is True
