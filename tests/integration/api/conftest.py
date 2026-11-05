"""Prevent auth-environment probes from leaking production service singletons."""

import pytest


@pytest.fixture(autouse=True)
def isolated_api_services(monkeypatch):
    monkeypatch.setattr("src.services.case_service._case_service_instance", None)
    monkeypatch.setattr("src.services.driver_dispute_service._driver_dispute_service_instance", None)
