import asyncio
import time
from types import SimpleNamespace

import httpx
import pytest

from src.services.traffic_evidence_service import TrafficEvidenceService


def settings(**values):
    defaults = {
        "traffic_incidents_url": "https://traffic.test/incidents",
        "traffic_api_key": "secret",
        "traffic_timeout_seconds": 1.0,
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


UNAVAILABLE_PROVIDER = {
    "status": "unavailable",
    "reason": "provider_unreachable",
    "historical_absence_proven": False,
    "retention": "memory_only",
}


def transport_for(response: httpx.Response):
    def handler(request: httpx.Request) -> httpx.Response:
        return response

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_history_normalizes_speed_and_congestion_ratio():
    result = await TrafficEvidenceService(settings()).fetch_corridor_historical_traffic(
        [105.7, 21.0, 105.8, 21.1],
        "2026-10-11T10:00:00Z",
        "2026-10-11T10:30:00Z",
        peer_trip_speeds_kmh=[15, 30, 60],
    )
    assert result["status"] == "available"
    assert result["observed_speed_kmh"] == 30
    assert result["free_flow_speed_kmh"] == 51
    assert result["congestion_ratio"] == pytest.approx(0.411765)
    assert result["congested"] is True
    assert result["source_type"] == "first_party_peer_telemetry"
    assert result["peer_count"] == 3


@pytest.mark.asyncio
async def test_history_zero_observed_speed_is_full_congestion_without_division_error():
    result = await TrafficEvidenceService(settings()).fetch_corridor_historical_traffic(
        *QUERY, peer_trip_speeds_kmh=[0, 0, 50]
    )
    assert result["congestion_ratio"] == 1.0
    assert result["congested"] is True


@pytest.mark.asyncio
async def test_invalid_bbox_and_time_return_structured_validation_error():
    service = TrafficEvidenceService(settings())
    result = await service.fetch_corridor_historical_traffic(
        [0, 0, 0, 0], "2026-10-11T10:00:00Z", "2026-10-11T10:30:00Z"
    )
    assert result["status"] == "validation_error"
    assert result["reason"] == "invalid_request"


QUERY = ([105.7, 21.0, 105.8, 21.1], "2026-10-11T10:00:00Z", "2026-10-11T10:30:00Z")


@pytest.mark.parametrize(
    "bbox,start,end",
    [
        ([105, 21], QUERY[1], QUERY[2]),
        ([105, 21, float("nan"), 22], QUERY[1], QUERY[2]),
        ([False, 21, 106, 22], QUERY[1], QUERY[2]),
        (["105", 21, 106, 22], QUERY[1], QUERY[2]),
        ([106, 21, 105, 22], QUERY[1], QUERY[2]),
        (QUERY[0], "2026-10-11T10:00:00", QUERY[2]),
        (QUERY[0], QUERY[2], QUERY[1]),
        (QUERY[0], QUERY[1], QUERY[1]),
    ],
)
async def test_invalid_queries_never_call_provider(bbox, start, end):
    def forbidden(_request):
        pytest.fail("Invalid query reached provider")

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
        result = await TrafficEvidenceService(settings(), client=client).query_traffic_incident_feed(bbox, start, end)
    assert result == {"status": "validation_error", "reason": "invalid_request"}


@pytest.mark.parametrize("speeds", [[], [10, 20], [-1, 10, 20], [0, 0, 0]])
async def test_history_insufficient_peer_evidence_is_unavailable(speeds):
    result = await TrafficEvidenceService(settings()).fetch_corridor_historical_traffic(
        *QUERY, peer_trip_speeds_kmh=speeds
    )
    assert result == {"status": "unavailable", "reason": "insufficient_peer_evidence"}


@pytest.mark.parametrize(
    "payload", [{}, {"incidents": None}, {"incidents": [None]}, {"incidents": [{}]}, {"incidents": [{"id": "1"}]}]
)
async def test_malformed_incident_feed_cannot_become_clear_roads(payload):
    async with httpx.AsyncClient(transport=transport_for(httpx.Response(200, json=payload))) as client:
        result = await TrafficEvidenceService(settings(), client=client).query_traffic_incident_feed(*QUERY)
    assert result == UNAVAILABLE_PROVIDER


async def test_incident_does_not_automatically_mean_congestion():
    payload = {"incidents": [{"id": "1", "type": "roadworks", "private": "discard"}], "congested": False}
    async with httpx.AsyncClient(transport=transport_for(httpx.Response(200, json=payload))) as client:
        result = await TrafficEvidenceService(settings(), client=client).query_traffic_incident_feed(*QUERY)
    assert result["status"] == "available"
    assert result["incidents"] == [{"id": "1", "type": "roadworks"}]
    assert result["congested"] is False
    assert result["historical_absence_proven"] is False
    assert result["retention"] == "memory_only"


async def test_real_deadline_bounds_slow_provider_and_cancels_request():
    cancelled = asyncio.Event()

    async def slow(_request):
        try:
            await asyncio.sleep(1)
        finally:
            cancelled.set()
        return httpx.Response(200, json={"incidents": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:
        start = time.monotonic()
        result = await TrafficEvidenceService(
            settings(traffic_timeout_seconds=0.02), client=client
        ).query_traffic_incident_feed(*QUERY)
    assert time.monotonic() - start < 0.5
    assert cancelled.is_set()
    assert result == UNAVAILABLE_PROVIDER


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, json={"incidents": []}),
        httpx.Response(200, content="not json"),
        httpx.Response(200, json={"status": "unavailable", "incidents": []}),
    ],
)
async def test_redirects_invalid_json_and_provider_failure_fail_closed(response):
    async with httpx.AsyncClient(transport=transport_for(response)) as client:
        result = await TrafficEvidenceService(settings(), client=client).query_traffic_incident_feed(*QUERY)
    assert result == UNAVAILABLE_PROVIDER


@pytest.mark.parametrize(
    "url",
    [
        "https://[invalid",
        "https:///missing",
        "http://traffic.test",
        "https://user:password@traffic.test",
        "https://traffic.test/?key=hidden",
    ],
)
async def test_unsafe_configured_endpoint_is_not_requested(url):
    result = await TrafficEvidenceService(settings(traffic_incidents_url=url)).query_traffic_incident_feed(*QUERY)
    assert result == {
        "status": "unavailable",
        "reason": "provider_not_configured",
        "historical_absence_proven": False,
        "retention": "memory_only",
    }


async def test_response_body_read_is_bounded():
    class Endless(httpx.AsyncByteStream):
        def __init__(self):
            self.reads = 0

        async def __aiter__(self):
            for _ in range(100):
                self.reads += 1
                yield b"x" * 65536

    stream = Endless()
    async with httpx.AsyncClient(transport=transport_for(httpx.Response(200, stream=stream))) as client:
        result = await TrafficEvidenceService(settings(), client=client).query_traffic_incident_feed(*QUERY)
    assert stream.reads <= 9
    assert result == UNAVAILABLE_PROVIDER


async def test_query_passes_exact_corridor_window_to_configured_gateway():
    def handler(request):
        assert request.url.host == "traffic.test"
        assert request.url.params["bbox"] == "105.7,21.0,105.8,21.1"
        assert request.url.params["start_time"] == QUERY[1]
        assert request.url.params["end_time"] == QUERY[2]
        assert request.headers["Authorization"] == "Bearer secret"
        return httpx.Response(200, json={"incidents": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await TrafficEvidenceService(settings(), client=client).query_traffic_incident_feed(*QUERY)
    assert result["status"] == "available"


async def test_invalid_endpoint_port_returns_unavailable_instead_of_throwing():
    result = await TrafficEvidenceService(
        settings(traffic_incidents_url="https://traffic.test:bad")
    ).query_traffic_incident_feed(*QUERY)
    assert result["status"] == "unavailable"


@pytest.mark.asyncio
async def test_missing_peer_telemetry_is_explicitly_unavailable():
    service = TrafficEvidenceService(settings())
    result = await service.fetch_corridor_historical_traffic(
        [105.7, 21.0, 105.8, 21.1], "2026-10-11T10:00:00Z", "2026-10-11T10:30:00Z"
    )
    assert result == {"status": "unavailable", "reason": "insufficient_peer_evidence"}


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_incident_feed_empty_result_is_not_null():
    response = httpx.Response(200, json={"incidents": []})
    async with httpx.AsyncClient(transport=transport_for(response)) as client:
        result = await TrafficEvidenceService(settings(), client=client).query_traffic_incident_feed(
            [105.7, 21.0, 105.8, 21.1], "2026-10-11T10:00:00Z", "2026-10-11T10:30:00Z"
        )
    assert result["status"] == "available"
    assert result["incidents"] == []
    assert result["congested"] is False
    assert result["historical_absence_proven"] is False
    assert result["retention"] == "memory_only"


@pytest.mark.asyncio
async def test_timeout_is_translated_to_provider_unreachable():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow provider", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await TrafficEvidenceService(settings(), client=client).query_traffic_incident_feed(
            [105.7, 21.0, 105.8, 21.1], "2026-10-11T10:00:00Z", "2026-10-11T10:30:00Z"
        )
    assert result == UNAVAILABLE_PROVIDER
