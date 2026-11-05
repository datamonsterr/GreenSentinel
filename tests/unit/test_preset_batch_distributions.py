"""Unit tests for preset detail and computed distributions (Issue #458)."""

from __future__ import annotations

from src.services.test_presets import (
    compute_preset_distributions,
    get_preset_detail,
)


def test_compute_preset_distributions_vietnam():
    """Distributions for synthesized-vietnam are computed from records, not hard-coded."""
    distributions = compute_preset_distributions("synthesized-vietnam")

    # Sample file has 100 records
    assert distributions.total_records == 100

    # Grouped label counts: fraud (ERR-*) vs no_violation vs insufficient_evidence
    assert distributions.by_label.no_violation == 76
    assert distributions.by_label.fraud == 24
    assert distributions.by_label.insufficient_evidence == 0
    assert distributions.by_label.grouped == {
        "fraud": 24,
        "no_violation": 76,
        "insufficient_evidence": 0,
    }

    # Per-code breakdown
    assert distributions.per_code == {
        "no_violation": 76,
        "ERR-01": 8,
        "ERR-02": 7,
        "ERR-05": 4,
        "ERR-03": 3,
        "ERR-04": 2,
    }

    # Severity distribution
    assert distributions.by_severity["P0"] == 4
    assert distributions.by_severity["P1"] == 10
    assert distributions.by_severity["P2"] == 10
    assert distributions.by_severity["no_violation"] == 76

    # City distribution
    assert distributions.by_city["Hanoi"] == 80
    assert distributions.by_city["Ho Chi Minh City"] == 20

    # Scenario distribution
    assert distributions.by_scenario["normal_trip"] == 78
    assert distributions.by_scenario["driver_stall_cancel"] == 15
    assert distributions.by_scenario["gps_spoofing"] == 4
    assert distributions.by_scenario["route_deviation"] == 3

    # Cancellation actor distribution
    assert distributions.by_cancellation_actor["none"] == 82
    assert distributions.by_cancellation_actor["passenger"] == 10
    assert distributions.by_cancellation_actor["driver"] == 8


def test_compute_preset_distributions_all_normal():
    """Distributions for all-normal contain exclusively no_violation trips."""
    distributions = compute_preset_distributions("all-normal")
    assert distributions.total_records > 0
    assert distributions.by_label.fraud == 0
    assert distributions.by_label.insufficient_evidence == 0
    assert distributions.by_label.no_violation == distributions.total_records
    assert set(distributions.per_code.keys()) == {"no_violation"}


def test_preset_detail_published_release_counts_labelled():
    """Published release identity counts stay, labelled as published_release_counts."""
    detail = get_preset_detail("synthesized-vietnam")
    assert detail.id == "synthesized-vietnam"
    assert detail.title == "Vietnam trips (synthesized)"
    assert detail.source_release == "synthesized_vietnam_trip"
    assert detail.revision == "a914d500b1c536f1dbfb59f8ea4c961bd38b5c7e"
    assert detail.trips_sha256 == "c4c80903a998420b3a5d68ced5ffb5bb06709fc9ef12817651ab8b89baa628a2"
    assert detail.license is not None
    assert detail.trip_count == 100

    # Published release counts labelled
    pub_counts = detail.published_release_counts
    assert pub_counts["published_trips"] == 1000
    assert "class_counts" in pub_counts or "published_class_counts" in pub_counts


def test_preset_detail_sample_trips_rich_fields():
    """Sample trips include rich fields from docs/data/SYNTHESIZED_VIETNAM_TRIP_394.md."""
    detail = get_preset_detail("synthesized-vietnam", sample_limit=5)
    assert len(detail.sample_trips) == 5

    first = detail.sample_trips[0]
    assert first.trip_ref.startswith("vn_trip_")
    assert first.label in {"no_violation", "ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05"}
    assert first.city in {"Hanoi", "Ho Chi Minh City"}
    assert first.driver_name is not None
    assert first.license_plate is not None
    assert first.pickup_name is not None
    assert first.dropoff_name is not None
    assert first.distance_m is not None and first.distance_m > 0
    assert first.duration_s is not None and first.duration_s > 0
