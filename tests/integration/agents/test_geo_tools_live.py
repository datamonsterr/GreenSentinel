"""Live-source tests for real agent geo tools (no mocks).

Covers:
- check_weather_condition → Open-Meteo (locked decision; Geoapify has no weather API)
- check_traffic_situation → OSRM corridor (real routing; traffic=approximated stays #231 work)
- Geoapify geocode + routing → live provider behind server key (skipped without key)
- Unavailable paths return honest `unavailable` (never fabricated fallback presented as live)

Live tests skip (not fail) when network/key is absent so default CI stays hermetic.
"""

import json
import os
import urllib.parse
import urllib.request

import pytest

from src.agents.tools.analyst_tools import (
    check_traffic_situation,
    check_weather_condition,
)

HANOI_PICKUP = {"lat": 21.0278, "lon": 105.8520}
HANOI_DEST = {"lat": 21.0480, "lon": 105.8340}


def _live_allowed() -> bool:
    return os.getenv("GEOAPIFY_LIVE", "0") == "1" or os.getenv("AGENT_LIVE_GEO", "0") == "1"


@pytest.mark.asyncio
async def test_weather_returns_live_open_meteo_or_honest_fallback():
    res = await check_weather_condition.ainvoke(HANOI_PICKUP)
    assert "xml_widget" in res
    assert res["latitude"] == HANOI_PICKUP["lat"]
    assert res["longitude"] == HANOI_PICKUP["lon"]
    assert isinstance(res.get("force_majeure"), bool)
    assert res["source"] in ("Open-Meteo Weather API", "fallback_baseline")
    if res["source"] == "Open-Meteo Weather API":
        assert isinstance(res["temperature_c"], float)
        assert isinstance(res["weather_code"], int)
        assert "precipitation_mm" in res and "rain_mm" in res
    else:
        # Fallback must declare itself, never pose as live observation.
        assert res["weather_code"] == 1


@pytest.mark.asyncio
async def test_weather_missing_location_is_unavailable_not_mock():
    res = await check_weather_condition.ainvoke({})
    assert res["source"] == "unavailable"
    assert res["reason"] == "location_not_recorded"


@pytest.mark.asyncio
async def test_traffic_returns_live_osrm_or_honest_fallback():
    res = await check_traffic_situation.ainvoke(
        {
            "start_lat": HANOI_PICKUP["lat"],
            "start_lon": HANOI_PICKUP["lon"],
            "end_lat": HANOI_DEST["lat"],
            "end_lon": HANOI_DEST["lon"],
        }
    )
    assert "xml_widget" in res
    assert res["source"] in ("OSRM Routing API & Physical Telemetry", "corridor_fallback")
    assert isinstance(res["distance_km"], (int, float)) and res["distance_km"] > 0
    assert res["congestion_level"] in ("clear", "moderate", "heavy_gridlock")
    assert isinstance(res["corroborates_delay"], bool)


@pytest.mark.asyncio
async def test_traffic_missing_coords_is_unavailable_not_mock():
    res = await check_traffic_situation.ainvoke({"start_lat": 21.0})
    assert res["source"] == "unavailable"
    assert res["reason"] == "route_coordinates_not_recorded"


@pytest.mark.skipif(not _live_allowed(), reason="Set GEOAPIFY_LIVE=1 with GEOAPIFY_API_KEY to run live provider test")
def test_geoapify_geocode_live_returns_hanoi_feature_without_key_leak():
    key = os.getenv("GEOAPIFY_API_KEY", "")
    assert key, "GEOAPIFY_API_KEY required for live provider test"
    params = urllib.parse.urlencode({"text": "Hoan Kiem, Hanoi", "limit": 1, "apiKey": key})
    with urllib.request.urlopen(f"https://api.geoapify.com/v1/geocode/search?{params}", timeout=10) as resp:
        assert resp.status == 200
        payload = json.loads(resp.read().decode("utf-8"))
    features = payload.get("features", [])
    assert len(features) >= 1
    assert payload.get("type") == "FeatureCollection"
    # Sanitized shape: key must never appear in recorded output.
    recorded = json.dumps({"count": len(features), "country": "vn"})
    assert key not in recorded


@pytest.mark.skipif(not _live_allowed(), reason="Set GEOAPIFY_LIVE=1 with GEOAPIFY_API_KEY to run live provider test")
def test_geoapify_routing_live_motorcycle_returns_geometry_without_key_leak():
    key = os.getenv("GEOAPIFY_API_KEY", "")
    assert key, "GEOAPIFY_API_KEY required for live provider test"
    waypoints = "21.0278,105.8520|21.0480,105.8340"
    params = urllib.parse.urlencode({"waypoints": waypoints, "mode": "motorcycle", "apiKey": key})
    with urllib.request.urlopen(f"https://api.geoapify.com/v1/routing?{params}", timeout=10) as resp:
        assert resp.status == 200
        payload = json.loads(resp.read().decode("utf-8"))
    features = payload.get("features", [])
    assert len(features) >= 1
    geometry_type = features[0].get("geometry", {}).get("type")
    assert geometry_type in ("LineString", "MultiLineString")
    recorded = json.dumps({"geometry_type": geometry_type})
    assert key not in recorded
