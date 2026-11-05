"""Integration test running the app with real classifier, skipping cleanly when artifacts are absent."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.config import Settings, get_settings
from src.main import app


def test_real_classifier_integration():
    try:
        from src.services.fraud_classifier import get_fraud_classifier

        classifier = get_fraud_classifier()
        assert classifier is not None
    except Exception as exc:
        pytest.skip(f"Real fraud classifier artifacts not present or loadable: {exc}")

    test_settings = Settings(
        app_env="test",
        test_auth_enabled=True,
        fraud_classifier_enabled=True,
    )
    app.dependency_overrides[get_settings] = lambda: test_settings

    with TestClient(app) as client:
        # Check info endpoint
        headers = {"x-role": "analyst"}
        info_resp = client.get("/api/v1/classifier/info", headers=headers)
        assert info_resp.status_code == 200
        info_data = info_resp.json()
        assert "model_version" in info_data

        # Check assess endpoint with a minimal trip bundle
        sample_trip = {
            "trip_id": "integration_test_trip",
            "pickup": [105.8542, 21.0285],
            "dropoff": [105.8600, 21.0350],
            "points": [
                {
                    "latitude": 21.0285,
                    "longitude": 105.8542,
                    "speed_mps": 5.0,
                    "bearing_deg": 45.0,
                    "accuracy_m": 4.0,
                    "app_state": "foreground",
                    "network_state": "online",
                    "gps_state": "valid",
                    "occurred_at": "2026-10-19T10:00:00Z",
                }
            ],
        }
        assess_resp = client.post(
            "/api/v1/classifier/assess",
            json={"bundle": sample_trip},
            headers=headers,
        )
        assert assess_resp.status_code == 200
        data = assess_resp.json()
        assert "category" in data
        assert "inference_ms" in data
        assert "server-timing" in assess_resp.headers

    app.dependency_overrides.clear()
