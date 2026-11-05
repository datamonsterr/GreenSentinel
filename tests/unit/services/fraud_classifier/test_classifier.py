from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.models.classifier import ClassifierResult
from src.services.fraud_classifier.model import (
    ClassifierUnavailableError,
    FraudClassifier,
    get_fraud_classifier,
    reset_fraud_classifier,
)

FIXTURE_PATH = Path("tests/fixtures/benchmark/classifier_fixtures.json")


@pytest.fixture
def fixtures() -> dict:
    with FIXTURE_PATH.open() as f:
        return json.load(f)


@pytest.fixture
def classifier() -> FraudClassifier:
    reset_fraud_classifier()
    try:
        return get_fraud_classifier()
    except ClassifierUnavailableError:
        pytest.skip("Models not yet exported / available locally")


def test_guardrail_short_circuit_result(classifier: FraudClassifier, fixtures: dict):
    trip = fixtures["guardrail_trip"]
    res = classifier.predict(trip)

    assert isinstance(res, ClassifierResult)
    assert res.category == "insufficient_evidence"
    assert res.guardrail_blocked is True
    assert res.guardrail_reason == "APP_CRASH"
    assert res.assessment_source == "guardrail_short_circuit"
    assert res.confidence == 1.0
    assert res.probabilities["insufficient_evidence"] == 1.0
    assert sum(res.probabilities.values()) == pytest.approx(1.0, abs=1e-5)
    assert res.inference_ms >= 0.0
    assert res.feature_ms >= 0.0


def test_normal_trip_classification_result(classifier: FraudClassifier, fixtures: dict):
    trip = fixtures["normal_trip"]
    res = classifier.predict(trip)

    assert isinstance(res, ClassifierResult)
    assert res.assessment_source == "r3d_classifier"
    assert res.guardrail_blocked is False
    assert res.category in res.probabilities
    assert res.probabilities["insufficient_evidence"] == 0.0
    assert sum(res.probabilities.values()) == pytest.approx(1.0, abs=1e-5)
    assert res.confidence == pytest.approx(res.probabilities[res.category], abs=1e-5)
    assert res.model_version == "r3d-2026.10.18"
    assert len(res.artifact_sha) > 0
    assert res.feature_ms > 0.0
    assert res.inference_ms > 0.0


def test_batch_prediction_vectorization(classifier: FraudClassifier, fixtures: dict):
    trips = [fixtures["normal_trip"], fixtures["guardrail_trip"]]
    batch_res = classifier.predict_many(trips)

    assert len(batch_res) == 2
    single_0 = classifier.predict(trips[0])
    single_1 = classifier.predict(trips[1])

    assert batch_res[0].category == single_0.category
    for c in single_0.probabilities:
        assert batch_res[0].probabilities[c] == pytest.approx(single_0.probabilities[c], abs=1e-5)

    assert batch_res[1].category == single_1.category
    assert batch_res[1].guardrail_blocked == single_1.guardrail_blocked


def test_singleton_thread_safety(classifier: FraudClassifier):
    c1 = get_fraud_classifier()
    c2 = get_fraud_classifier()
    assert c1 is c2


def test_fraud_classifier_satisfies_protocol(classifier: FraudClassifier):
    from src.api.classifier_routes import FraudClassifierProtocol

    assert isinstance(classifier, FraudClassifierProtocol)
    assert hasattr(classifier, "predict")
    assert hasattr(classifier, "predict_many")
    assert hasattr(classifier, "get_info")
    info = classifier.get_info()
    assert isinstance(info, dict)
    assert "model_version" in info
    assert "artifact_shas" in info
    assert "loaded_at" in info
    assert "load_ms" in info
    assert "metrics" in info


def test_classifier_info_contract_route(classifier: FraudClassifier):
    from fastapi.testclient import TestClient

    from src.api.classifier_routes import get_classifier_service
    from src.config import Settings, get_settings
    from src.main import app

    app.dependency_overrides[get_classifier_service] = lambda: classifier
    app.dependency_overrides[get_settings] = lambda: Settings(
        app_env="test",
        test_auth_enabled=True,
        fraud_classifier_enabled=True,
    )

    try:
        with TestClient(app) as client:
            resp = client.get("/api/v1/classifier/info", headers={"x-role": "analyst"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["model_version"] == classifier.model_version
            assert data["artifact_shas"]
            assert isinstance(data["artifact_shas"], dict)
            assert len(data["artifact_shas"]) > 0
            for filename, sha in data["artifact_shas"].items():
                assert len(sha) == 12
                assert filename in {"r3c.txt", "r3f.onnx", "stacker.txt"}
            assert data["loaded_at"] is not None
            assert isinstance(data["loaded_at"], str)
            assert data["load_ms"] is not None
            assert isinstance(data["load_ms"], (int, float))
            assert data["load_ms"] > 0
            assert data["metrics"]
            assert isinstance(data["metrics"], dict)
            assert "dev300" in data["metrics"] or "test_6000" in data["metrics"]
    finally:
        app.dependency_overrides.clear()
