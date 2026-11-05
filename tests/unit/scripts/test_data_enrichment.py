from datetime import date

from scripts.enrich_demo_data import age_from_birth_date, sample_birth_date


def test_birth_dates_are_between_20_and_65_on_reference_date():
    reference = date(2026, 9, 24)
    dates = [sample_birth_date(seed, reference) for seed in range(500)]
    ages = [age_from_birth_date(value, reference) for value in dates]

    assert min(ages) >= 20
    assert max(ages) <= 65
    assert 32 <= sum(ages) / len(ages) <= 38


def test_mipo_rows_are_normalized_without_claiming_wgs84():
    from scripts.import_mipo import normalize_trajectory

    result = normalize_trajectory({"trajectory": [[1, 2], [3, 4]], "label": 1}, 7)

    assert result["source_row"] == 7
    assert result["variant"] == "outlier"
    assert result["points_xy"] == [[1.0, 2.0], [3.0, 4.0]]
    assert result["coordinate_reference"] == "unknown_planar"
