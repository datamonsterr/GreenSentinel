"""Tests for scripts/benchmark/population_synth.py (issue #253)."""

from __future__ import annotations

import random

from scripts.benchmark.population_synth import (
    DRIVER_COLUMNS,
    FRAUD_SHARE_DEFAULT,
    PASSENGER_COLUMNS,
    PROVENANCE,
    RATING_CAP,
    RATING_FLOOR,
    sample_fraud_driver_ids,
    synthesize_driver_analytics,
    synthesize_drivers,
    synthesize_passengers,
)


def _drivers(seed: int, n: int, **kw):
    return synthesize_drivers(random.Random(seed), n, **kw)


def test_determinism_same_seed_identical():
    assert _drivers(7, 50) == _drivers(7, 50)
    assert synthesize_passengers(random.Random(7), 50) == synthesize_passengers(random.Random(7), 50)
    d = _drivers(7, 5)[0]
    assert synthesize_driver_analytics(random.Random(3), d) == synthesize_driver_analytics(random.Random(3), d)


def test_different_seeds_differ():
    assert _drivers(7, 50) != _drivers(8, 50)


def test_fraud_share_within_tolerance():
    drivers = _drivers(42, 2000)
    flagged = sum(1 for d in drivers if d["profile_provenance"]["fraud_propensity"])
    assert abs(flagged / len(drivers) - FRAUD_SHARE_DEFAULT) <= 0.03


def test_fraud_priors_elevated():
    drivers = _drivers(11, 2000)
    fraud = [d for d in drivers if d["profile_provenance"]["fraud_propensity"]]
    honest = [d for d in drivers if not d["profile_provenance"]["fraud_propensity"]]

    def mean(ds: list, k: str) -> float:
        return sum(d["profile_provenance"][k] for d in ds) / len(ds)

    assert mean(fraud, "prior_sanctions_count") > mean(honest, "prior_sanctions_count")
    assert mean(fraud, "prior_cancellation_rate") > mean(honest, "prior_cancellation_rate")
    assert mean(fraud, "complaint_rate") > mean(honest, "complaint_rate")
    # Spec: fraud prior cancellation 2-4x honest base per driver
    assert all(d["profile_provenance"]["prior_cancellation_rate"] >= 0.004 for d in fraud)


def test_rating_range_and_partner_types():
    drivers = _drivers(5, 500)
    assert all(RATING_FLOOR <= d["rating"] <= RATING_CAP for d in drivers)
    assert {d["partner_type"] for d in drivers} == {"fleet", "owner_driver", "rent_to_own"}
    assert all(d["account_status"] == "active" and d["is_synthetic"] is True for d in drivers)
    assert all(d["birth_date"] is None for d in drivers)


def test_db_shape_exact_keys():
    drivers = _drivers(9, 10)
    assert all(set(d.keys()) == set(DRIVER_COLUMNS) for d in drivers)
    passengers = synthesize_passengers(random.Random(9), 10)
    assert all(set(p.keys()) == set(PASSENGER_COLUMNS) for p in passengers)
    assert [p["external_ref"] for p in passengers] == [f"pax_bm_{i + 1:04d}" for i in range(10)]
    assert all(p["is_synthetic"] is True for p in passengers)


def test_provenance_marker():
    drivers = _drivers(9, 5)
    for d in drivers:
        prov = d["profile_provenance"]
        assert prov["synthetic"] is True
        assert prov["generator"] == PROVENANCE["generator"]
        assert prov["version"] == PROVENANCE["version"]
        assert isinstance(prov["tenure_days"], int) and isinstance(prov["fraud_propensity"], bool)


def test_sample_fraud_driver_ids():
    drivers = _drivers(21, 500)
    ids = sample_fraud_driver_ids(random.Random(21), drivers)
    assert len(ids) == int(500 * FRAUD_SHARE_DEFAULT)
    assert set(ids) <= {d["id"] for d in drivers}
    assert sample_fraud_driver_ids(random.Random(21), drivers) == ids
    assert sample_fraud_driver_ids(random.Random(1), [], 0.12) == []


def test_analytics_windows_and_no_labels():
    d = _drivers(13, 5)[0]
    a = synthesize_driver_analytics(random.Random(13), d, {"recent_trips_7d": 20, "recent_trips_30d": 80})
    assert set(a.keys()) == {
        "driver_id",
        "window_7d",
        "window_30d",
        "dispute_history_count",
        "prior_sanctions_count",
        "historical_cancellation_ratio",
    }
    assert a["driver_id"] == d["id"]
    assert a["window_7d"]["trips"] == 20 and a["window_30d"]["trips"] == 80
    assert a["prior_sanctions_count"] == d["profile_provenance"]["prior_sanctions_count"]
    forbidden = {"label", "expected_category", "fraud", "violation", "is_fraud"}
    assert forbidden.isdisjoint(set(a.keys()))
