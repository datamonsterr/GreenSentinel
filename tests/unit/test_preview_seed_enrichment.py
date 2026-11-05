"""Unit tests for deterministic preview seed generators (issue #366).

Covers pure deterministic functions:
- Vehicle model selection (VinFast VF e34, VF 8, VF 9, Feliz S, Klara S)
- Driver metrics and tenure (rating, acceptance, cancellation, trips, tenure_months)
- Driver statements (ERR-01 .. ERR-05, nominal)
- Passenger feedback and star ratings (1-5)
- Telemetry sensor reliability (ping_latency_ms, battery_level_pct)
- Trip fare calculation and fare quote delta
"""

from scripts.seed_preview_enrichment import (
    get_driver_metrics,
    get_driver_statement,
    get_passenger_feedback,
    get_sensor_reliability,
    get_trip_fare,
    get_vehicle_model,
)


def test_vehicle_model_deterministic_and_valid():
    """Vehicle models match VinFast EV catalog and remain deterministic per seed."""
    # Cars
    car_std = get_vehicle_model("car", "GreenCar Standard", seed=1)
    assert car_std in ("VinFast VF e34", "VinFast VF 5 Plus")
    car_lux = get_vehicle_model("car", "GreenCar Luxury", seed=2)
    assert car_lux in ("VinFast VF 8", "VinFast VF 9")

    # Motorbikes
    bike_fast = get_vehicle_model("motorbike", "GreenBike Fast", seed=3)
    assert bike_fast in ("VinFast Feliz S", "VinFast Klara S")
    bike_std = get_vehicle_model("motorbike", "GreenBike Standard", seed=4)
    assert bike_std == "VinFast Evo 200"

    # Determinism
    assert get_vehicle_model("car", "GreenCar Standard", seed=42) == get_vehicle_model(
        "car", "GreenCar Standard", seed=42
    )


def test_driver_metrics_within_realistic_bounds():
    """Driver metrics follow GreenSM platform distributions and Vietnamese norms."""
    for seed in range(20):
        metrics = get_driver_metrics(seed)
        assert 4.60 <= metrics["rating"] <= 5.00
        assert 88.0 <= metrics["acceptance_rate"] <= 100.0
        assert 0.5 <= metrics["cancellation_rate"] <= 5.0
        assert 450 <= metrics["total_trips"] <= 3000
        assert 6 <= metrics["tenure_months"] <= 36

    # Idempotence / determinism
    assert get_driver_metrics(10) == get_driver_metrics(10)


def test_driver_statement_per_category():
    """Driver statements provide authentic Vietnamese explanations tailored to categories."""
    categories = ["ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05", "no_violation", "insufficient_evidence", None]
    for cat in categories:
        statement = get_driver_statement(cat, seed=1)
        assert isinstance(statement, str)
        assert len(statement) >= 20
        # Must contain Vietnamese characters
        assert any(c in statement for c in "áàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵđ")

    # Category specifics
    assert "hủy" in get_driver_statement("ERR-01", 1).lower()
    assert "tắc" in get_driver_statement("ERR-02", 1).lower() or "dừng" in get_driver_statement("ERR-02", 1).lower()
    assert "vòng" in get_driver_statement("ERR-03", 1).lower() or "hướng" in get_driver_statement("ERR-03", 1).lower()
    assert "gps" in get_driver_statement("ERR-05", 1).lower() or "tín hiệu" in get_driver_statement("ERR-05", 1).lower()


def test_passenger_feedback_and_rating():
    """Passenger feedback produces reason codes, statements, and valid star ratings."""
    for cat in ["ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05", "no_violation"]:
        fb = get_passenger_feedback(cat, seed=7)
        assert "statement" in fb and len(fb["statement"]) >= 15
        assert "reason_code" in fb and isinstance(fb["reason_code"], str)
        assert 1 <= fb["rating_smallint"] <= 5

    # Violations have low ratings, no_violation has 5 stars
    assert get_passenger_feedback("ERR-02", 1)["rating_smallint"] <= 2
    assert get_passenger_feedback("no_violation", 1)["rating_smallint"] == 5


def test_sensor_reliability_ranges():
    """Ping latency and battery level generate valid floats in measurable physical ranges."""
    for seed in range(10):
        sensor = get_sensor_reliability(seed=seed, sequence=5)
        assert 20.0 <= sensor["ping_latency_ms"] <= 150.0
        assert 15.0 <= sensor["battery_level_pct"] <= 100.0


def test_trip_fare_and_quote_delta():
    """Trip fares are positive integer VND; fraud cases have positive incentive deltas."""
    nominal = get_trip_fare(distance_m=8000, seed=1, category="no_violation")
    assert nominal["fare_amount_vnd"] >= 40000
    assert nominal["delta_vnd"] == 0
    assert nominal["quoted_minor"] == nominal["fare_amount_vnd"] * 100

    fraud = get_trip_fare(distance_m=8000, seed=1, category="ERR-02")
    assert fraud["fare_amount_vnd"] >= 40000
    assert fraud["delta_vnd"] > 0
    assert fraud["quoted_minor"] < fraud["fare_amount_vnd"] * 100
