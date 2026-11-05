"""Case tools consume the case detail GeoJSON trip contract."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.agents.tools.analyst_tools import check_traffic_situation, check_weather_condition


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", [check_weather_condition, check_traffic_situation])
async def test_case_geojson_coordinates_reach_provider(tool):
    detail = SimpleNamespace(
        trip={
            "pickup": {"type": "Point", "coordinates": [105.8542, 21.0285]},
            "dropoff": {"type": "Point", "coordinates": [105.8048, 21.0031]},
        }
    )
    service = SimpleNamespace(get_case_detail=AsyncMock(return_value=detail))
    response = httpx.Response(503)
    with (
        patch("src.agents.tools.analyst_tools.get_case_service", return_value=service),
        patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=response) as get,
    ):
        result = await tool.ainvoke({"case_id": "recorded-case"})
    get.assert_awaited_once()
    if tool is check_weather_condition:
        assert result["latitude"] == 21.0285
        assert result["longitude"] == 105.8542
        assert "latitude=21.0285&longitude=105.8542" in get.call_args.args[0]
    else:
        assert result["origin"] == [21.0285, 105.8542]
        assert result["destination"] == [21.0031, 105.8048]
        assert "105.8542,21.0285;105.8048,21.0031" in get.call_args.args[0]
