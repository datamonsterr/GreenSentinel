"""Issue #281: dataset-reliability gates for the hardened evidence-v4 profile.

Covers the enum-latch removal, locale/fare coherence, dialogue paraphrase
uniqueness, and held-out dialogue splits. Structural (deterministic) assertions
avoid building the full 10k corpus in CI.
"""

from __future__ import annotations

import collections
import random

import pytest

from scripts.benchmark import build_10k, build_10k_v2
from scripts.benchmark.dialogue_synth import CONTEXTS, _vary, pool_for_split, synthesize_dialogue

_NO_VIOLATION = "no_violation"
_CANCELLED_LABELS = {"ERR-01", "ERR-02", "ERR-03", "insufficient_evidence"}


def _expected_enum_latch_recall(sizes: dict[str, int]) -> dict[str, float]:
    """Deterministic expected recall of a group-argmax classifier on the reason enum."""
    counts: dict[str, collections.Counter] = {}
    for label, weights in build_10k_v2.OPERATIONAL_REASON_WEIGHTS.items():
        for reason, w in weights:
            counts.setdefault(reason, collections.Counter())[label] += sizes[label] * w
    pred = {reason: c.most_common(1)[0][0] for reason, c in counts.items()}
    recall: dict[str, float] = {}
    for label, weights in build_10k_v2.OPERATIONAL_REASON_WEIGHTS.items():
        n = sum(sizes[label] * w for _, w in weights)
        tp = sum(sizes[label] * w for reason, w in weights if pred[reason] == label)
        recall[label] = tp / n
    return recall


# --- Enum latch -------------------------------------------------------------


def test_enum_latch_structural_recall_below_half() -> None:
    """(status, actor, reason) must not reconstruct the label on the 10k mix."""
    sizes: dict[str, int] = dict(build_10k.class_counts_for_n(10000))
    recall = _expected_enum_latch_recall(sizes)
    for label in _CANCELLED_LABELS:
        assert recall[label] < 0.5, f"{label} reproducible from enums at {recall[label]:.3f}"


def test_enum_reason_vocabulary_shared_and_balanced() -> None:
    """Every reason is reachable by every cancelled class; no 1.0 latch reason."""
    weights = build_10k_v2.OPERATIONAL_REASON_WEIGHTS
    for label in _CANCELLED_LABELS:
        assert weights[label], label
        reported = {reason for reason, _ in weights[label]}
        for reason, w in weights[label]:
            assert w > 0.0, (label, reason)
            assert w < 0.5, (label, reason)
        for other in _CANCELLED_LABELS:
            assert reported == {r for r, _ in weights[other]}, f"{label} vs {other} vocab differs"
    assert build_10k_v2.OPERATIONAL_REASON_WEIGHTS[_NO_VIOLATION]


def test_enum_latch_group_purity_gone_on_tiny_build() -> None:
    """No cancelled (actor, reason) cohort in a real build is a single class."""
    bundles, _, _ = build_10k_v2.build_dataset(700, 20261011, progress_every=0, harden=True)
    groups: dict[tuple, collections.Counter] = {}
    for b in bundles:
        if b["trip"]["status"] != "cancelled":
            continue
        key = (b["assignment"].get("cancellation_actor"), b["assignment"].get("cancellation_reason"))
        groups.setdefault(key, collections.Counter())[b["label"]] += 1
    pure = [g for g in groups.values() if len(g) == 1]
    assert not pure, f"label-pure enum cohorts remain: {[dict(g) for g in pure]}"


def test_ground_truth_only_in_label_and_provenance() -> None:
    """Generator no longer writes label-equal literals into detector-visible enums."""
    bundles, _, _ = build_10k_v2.build_dataset(700, 20261011, progress_every=0, harden=True)
    latch_literals = {"driver_stalled_no_show", "driver_cancelled_unjustified", "route_deviation", "traffic_gridlock"}
    for b in bundles:
        actor = (b["assignment"].get("cancellation_actor") or "").lower()
        reason = (b["assignment"].get("cancellation_reason") or "").lower()
        assert actor not in latch_literals, b["trip_ref"]
        assert reason not in latch_literals, b["trip_ref"]
        assert "route_deviation" not in reason
        assert "driver_stalled_no_show" not in reason


# --- Locale -----------------------------------------------------------------


def test_locale_bbox_matches_city() -> None:
    bundles, _, _ = build_10k_v2.build_dataset(700, 20261011, progress_every=0, harden=True)
    for b in bundles:
        is_porto = b.get("city") == "Porto"
        for p in b["telemetry"]:
            if p.get("longitude") is None or p.get("latitude") is None:
                continue
            assert (p["longitude"] < 0) == is_porto, b["trip_ref"]
        assert (b["pickup"]["lon"] < 0) == is_porto, b["trip_ref"]
        assert (b["dropoff"]["lon"] < 0) == is_porto, b["trip_ref"]
        prov = b["geography_provenance"]
        assert prov["country"] == ("PT" if is_porto else "VN"), b["trip_ref"]
        assert b["trip"]["city"] == b.get("city")


# --- Fare -------------------------------------------------------------------


def test_cancelled_trips_carry_no_completed_fare() -> None:
    bundles, _, _ = build_10k_v2.build_dataset(700, 20261011, progress_every=0, harden=True)
    for b in bundles:
        fare = b["trip"].get("fare_amount_vnd")
        if b["trip"]["status"] == "cancelled":
            assert fare is None or fare == 0, b["trip_ref"]
            assert b["trip"].get("fare_state") == "cancelled_no_charge"
        else:
            assert isinstance(fare, int) and fare >= 0, b["trip_ref"]
            km = float(b["route"]["distance_m"]) / 1000.0
            if km > 0:
                assert fare / km <= build_10k_v2.FARE_MAX_PER_KM_VND, b["trip_ref"]


# --- Dialogue ---------------------------------------------------------------


@pytest.mark.parametrize("context", CONTEXTS)
def test_heldout_dialogue_templates_not_in_train(context: str) -> None:
    for role in ("driver", "customer"):
        train = pool_for_split(context, role, "train")
        test = pool_for_split(context, role, "test")
        validation = pool_for_split(context, role, "validation")
        train_texts = {str(e["text"]) for e in train}
        test_texts = {str(e["text"]) for e in test}
        val_texts = {str(e["text"]) for e in validation}
        assert not (train_texts & test_texts), (context, role)
        assert not (train_texts & val_texts), (context, role)
        assert not (test_texts & val_texts), (context, role)


def test_dialogue_paraphrase_raises_unique_fraction() -> None:
    texts = []
    rng = random.Random(7)
    for i in range(120):
        context = CONTEXTS[i % len(CONTEXTS)]
        turns = synthesize_dialogue(rng, context, {"wait_s": 300, "distance_m": 3500}, paraphrase=True, split="train")
        texts.extend(t["text"] for t in turns)
    unique = len(set(texts))
    assert unique / len(texts) > 0.05, f"unique fraction {unique / len(texts):.4f}"


def test_dialogue_paraphrase_preserves_trap_keywords() -> None:
    trigger = "vô cớ"
    out = _vary(random.Random(1), f"Anh từ chối {trigger} cuốc này", "vi")
    assert trigger in out


def test_dialogue_paraphrase_deterministic() -> None:
    a = synthesize_dialogue(random.Random(3), "err02_stall", {}, paraphrase=True, split="train")
    b = synthesize_dialogue(random.Random(3), "err02_stall", {}, paraphrase=True, split="train")
    assert a == b


def test_pool_for_split_unknown_split_raises() -> None:
    with pytest.raises(ValueError):
        pool_for_split("normal_trip", "driver", "nope")


# --- Reproducibility --------------------------------------------------------


def test_v4_profile_reproducible(tmp_path) -> None:
    b, c, g = build_10k_v2.build_dataset(20, 20261011, progress_every=0, harden=True)
    m1 = build_10k_v2.write_output(b, c, g, 20261011, tmp_path / "a", profile="evidence-v4", version="v4", harden=True)
    b2, c2, g2 = build_10k_v2.build_dataset(20, 20261011, progress_every=0, harden=True)
    m2 = build_10k_v2.write_output(
        b2, c2, g2, 20261011, tmp_path / "b", profile="evidence-v4", version="v4", harden=True
    )
    assert m1["trips_sha256"] == m2["trips_sha256"]
    assert (tmp_path / "a" / "trips.jsonl").read_bytes() == (tmp_path / "b" / "trips.jsonl").read_bytes()


def test_frozen_profile_output_batch_names(tmp_path) -> None:
    """Default main() keeps evidence-v2; --profile evidence-v4 writes a separate batch."""
    assert build_10k_v2.main(["--n", "20", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "profiles" / "evidence-v2" / "manifest.json").exists()
    assert build_10k_v2.main(["--n", "20", "--out", str(tmp_path), "--profile", "evidence-v4"]) == 0
    m = __import__("json").loads((tmp_path / "profiles" / "evidence-v4" / "manifest.json").read_text())
    assert m["profile"] == "evidence-v4" and m["hardened"] is True
