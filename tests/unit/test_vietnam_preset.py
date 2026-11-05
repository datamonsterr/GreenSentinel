"""Unit tests for Vietnam preset integration, tenant isolation, and simulation input round-trip."""

from uuid import uuid4

import pytest

from src.services.test_presets import (
    list_presets,
    materialize_preset_simulation_input,
)


def test_list_presets_includes_synthesized_vietnam():
    resp = list_presets(sample_limit=5)
    presets_by_id = {p.id: p for p in resp.presets}

    assert "synthesized-vietnam" in presets_by_id
    vn = presets_by_id["synthesized-vietnam"]
    assert vn.title == "Vietnam trips (synthesized)"
    assert vn.kind == "vietnam"
    assert vn.available is True
    assert vn.selection_size == 1000
    assert vn.available_trips == 1000
    assert vn.metadata["profile"] == "synthesized_vietnam_trip"
    assert vn.metadata["status"] == "published"
    assert vn.metadata["revision"] == "a914d500b1c536f1dbfb59f8ea4c961bd38b5c7e"
    assert vn.metadata["published_trips"] == 1000
    assert vn.metadata["trips_sha256"] == "c4c80903a998420b3a5d68ced5ffb5bb06709fc9ef12817651ab8b89baa628a2"
    assert len(vn.sample_trips) > 0

    for trip in vn.sample_trips:
        assert trip.distance_m is not None and trip.distance_m > 0
        assert trip.telemetry_points > 0


def test_materialize_preset_simulation_input_tenant_binding():
    """Verify organization ownership MUST be assigned from active authorized context,
    never using corpus source fixture org_id to cross tenants.
    """
    resp = list_presets(sample_limit=1)
    vn_preset = next(p for p in resp.presets if p.id == "synthesized-vietnam")
    assert len(vn_preset.sample_trips) > 0
    sample_ref = vn_preset.sample_trips[0].trip_ref

    active_org_id = uuid4()
    payload = materialize_preset_simulation_input(sample_ref, organization_id=active_org_id)

    # Organization binding verified
    assert payload["organization_id"] == str(active_org_id)
    assert payload["driver_profile"]["organization_id"] == str(active_org_id)

    # Geometry & distance validity
    geom = payload["route_geometry"]
    assert geom["type"] == "LineString"
    assert len(geom["coordinates"]) >= 2
    for lon, lat in geom["coordinates"]:
        assert isinstance(lon, float) and isinstance(lat, float)
        assert 102.0 <= lon <= 110.0
        assert 8.0 <= lat <= 24.0

    assert payload["distance_m"] > 0
    assert len(payload["telemetry"]) > 0


def test_materialize_preset_simulation_input_rejects_invalid_org():
    resp = list_presets(sample_limit=1)
    vn_preset = next(p for p in resp.presets if p.id == "synthesized-vietnam")
    sample_ref = vn_preset.sample_trips[0].trip_ref

    with pytest.raises(ValueError):
        materialize_preset_simulation_input(sample_ref, organization_id="not-a-valid-uuid")


def test_materialize_preset_simulation_input_rejects_missing_trip():
    with pytest.raises(ValueError, match="Preset trip not found"):
        materialize_preset_simulation_input("nonexistent_trip_ref_9999", organization_id=uuid4())
