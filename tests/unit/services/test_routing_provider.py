"""Provider port and legacy service contract, using an offline HTTP boundary."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pytest

from src.services import routing_service


class Response:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, *_args):
        return json.dumps(self.payload).encode()


def test_unavailable_trip_has_no_fabricated_geometry(monkeypatch):
    def timeout(*_args, **_kwargs):
        raise TimeoutError("provider unavailable")

    monkeypatch.setattr(routing_service, "urlopen", timeout)
    assert routing_service.resolve_trip_route([105.8342, 21.0278], [105.8352, 21.0280], [105.8443, 21.0285]) is None


def test_osrm_port_returns_typed_success_with_legacy_units():
    from src.services.osrm_adapter import OSRMAdapter
    from src.services.route_provider import RouteRequest, RouteSuccess

    payload = {
        "routes": [
            {
                "geometry": {"type": "LineString", "coordinates": [[105.83, 21.02], [105.84, 21.03]]},
                "distance": 12.4,
                "duration": 8.6,
            }
        ]
    }
    provider = OSRMAdapter(opener=lambda *_args, **_kwargs: Response(payload))
    result = provider.route(RouteRequest([105.83, 21.02], [105.84, 21.03], mode="drive"))
    assert isinstance(result, RouteSuccess)
    assert result.data["distance_m"] == 12
    assert result.data["duration_s"] == 9
    assert result.data["provider"] == "osrm"
    assert result.data["provenance"] == {"source": "osrm", "status": "ok"}


def geo_payload(geometry=None):
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": geometry
                or {
                    "type": "MultiLineString",
                    "coordinates": [
                        [[105.83, 21.02], [105.84, 21.03]],
                        [[105.85, 21.04], [105.86, 21.05]],
                    ],
                },
                "properties": {"distance": 1317, "time": 87.581, "mode": "motorcycle", "legs": []},
            }
        ],
    }


def test_geoapify_preserves_disjoint_legs_and_fractional_duration():
    from src.services.geoapify_adapter import GeoapifyAdapter
    from src.services.route_provider import RouteRequest, RouteSuccess

    provider = GeoapifyAdapter(api_key="fixture-only", opener=lambda *_a, **_kw: Response(geo_payload()))
    result = provider.route(RouteRequest([105.83, 21.02], [105.86, 21.05], traffic="approximated"))
    assert isinstance(result, RouteSuccess)
    assert result.data["geometry"] == geo_payload()["features"][0]["geometry"]
    assert result.data["duration_s"] == 87.581
    assert result.data["traffic_model"] == "approximated"
    assert result.data["provenance"]["traffic_observation"] == "modeled"


@pytest.mark.parametrize("name", ["osrm", "geoapify"])
def test_malformed_vertex_splits_geometry_without_a_connector(name):
    from src.services.geoapify_adapter import GeoapifyAdapter
    from src.services.osrm_adapter import OSRMAdapter
    from src.services.route_provider import RouteRequest, RouteSuccess

    geometry = {
        "type": "LineString",
        "coordinates": [
            [105.83, 21.02],
            [105.84, 21.03],
            [float("nan"), 21.04],
            [105.85, 21.04],
            [105.86, 21.05],
        ],
    }
    if name == "osrm":
        payload = {"routes": [{"geometry": geometry, "distance": 1317, "duration": 88}]}
        provider = OSRMAdapter(opener=lambda *_a, **_kw: Response(payload))
    else:
        provider = GeoapifyAdapter(api_key="fixture-only", opener=lambda *_a, **_kw: Response(geo_payload(geometry)))
    result = provider.route(RouteRequest([105.83, 21.02], [105.86, 21.05], mode="drive"))
    assert isinstance(result, RouteSuccess)
    assert result.data["geometry"] == {
        "type": "MultiLineString",
        "coordinates": [
            [[105.83, 21.02], [105.84, 21.03]],
            [[105.85, 21.04], [105.86, 21.05]],
        ],
    }


@pytest.mark.parametrize(
    "start",
    [
        None,
        [],
        [181, 21],
        [105, 91],
        [float("inf"), 21],
        [105, float("nan")],
        [21.0278, 105.8342],
        [True, 21],
        [10**400, 21],
    ],
)
@pytest.mark.parametrize("name", ["osrm", "geoapify"])
def test_invalid_coordinate_never_reaches_transport(name, start):
    from src.services.geoapify_adapter import GeoapifyAdapter
    from src.services.osrm_adapter import OSRMAdapter
    from src.services.route_provider import RouteFailure, RouteRequest

    calls = []

    def transport(*args, **kwargs):
        calls.append(1)
        return Response(geo_payload())

    provider = (
        OSRMAdapter(opener=transport) if name == "osrm" else GeoapifyAdapter(api_key="fixture-only", opener=transport)
    )
    result = provider.route(RouteRequest(start, [105.84, 21.03], mode="drive"))
    assert result == RouteFailure("invalid_input")
    assert calls == []


@pytest.mark.parametrize("mode", ["drive", "scooter", "motorcycle"])
@pytest.mark.parametrize("route_type", ["balanced", "short"])
@pytest.mark.parametrize("traffic", ["free_flow", "approximated"])
def test_geoapify_request_uses_lat_lon_and_supported_options(mode, route_type, traffic):
    from src.services.geoapify_adapter import GeoapifyAdapter
    from src.services.route_provider import RouteRequest, RouteSuccess

    requests = []

    def transport(url, *, timeout):
        requests.append((parse_qs(urlsplit(url).query), timeout))
        return Response(geo_payload())

    result = GeoapifyAdapter(api_key="fixture-only", opener=transport).route(
        RouteRequest(
            [105.8342, 21.0278], [105.8443, 21.0285], mode=mode, route_type=route_type, traffic=traffic, timeout=200
        )
    )
    assert isinstance(result, RouteSuccess)
    query, timeout = requests[0]
    assert query["waypoints"] == ["21.0278,105.8342|21.0285,105.8443"]
    assert query["mode"] == [mode]
    assert query["type"] == [route_type]
    assert query["traffic"] == [traffic]
    assert query["details"] == ["instruction_details"]
    assert timeout == 10


@pytest.mark.parametrize(
    "options",
    [
        {"mode": "walk"},
        {"route_type": "fast"},
        {"traffic": "live"},
        {"timeout": float("nan")},
        {"timeout": "invalid"},
        {"instruction_details": "private"},
    ],
)
def test_unsupported_options_are_typed_failures_before_http(options):
    from src.services.geoapify_adapter import GeoapifyAdapter
    from src.services.route_provider import RouteFailure, RouteRequest

    calls = []
    provider = GeoapifyAdapter(api_key="fixture-only", opener=lambda *_a, **_kw: calls.append(1))
    result = provider.route(RouteRequest([105.83, 21.02], [105.84, 21.03], **options))
    assert isinstance(result, RouteFailure)
    assert result.code in {"invalid_input", "unsupported_option"}
    assert calls == []


@pytest.mark.parametrize("name", ["osrm", "geoapify"])
@pytest.mark.parametrize(
    "status,code", [(401, "unauthorized"), (403, "forbidden"), (429, "rate_limited"), (503, "unavailable")]
)
def test_http_failures_have_only_safe_union_fields(name, status, code, caplog):
    from src.services.geoapify_adapter import GeoapifyAdapter
    from src.services.osrm_adapter import OSRMAdapter
    from src.services.route_provider import RouteFailure, RouteRequest

    calls = []

    def transport(*_a, **_kw):
        calls.append(1)
        raise HTTPError(
            "https://private.invalid/?apiKey=fixture-canary",
            status,
            "fixture-canary",
            {"x-api-key": "fixture-canary"},
            None,
        )

    provider = (
        OSRMAdapter(opener=transport) if name == "osrm" else GeoapifyAdapter(api_key="fixture-only", opener=transport)
    )
    result = provider.route(RouteRequest([105.83, 21.02], [105.84, 21.03], mode="drive"))
    assert result == RouteFailure(code, status)
    assert calls == [1]
    assert "fixture-canary" not in repr(result) + caplog.text


def test_urlerror_wrapped_timeout_is_typed_and_sanitized():
    from src.services.geoapify_adapter import GeoapifyAdapter
    from src.services.route_provider import RouteFailure, RouteRequest

    def transport(*_a, **_kw):
        raise URLError(TimeoutError("fixture-canary"))

    result = GeoapifyAdapter(api_key="fixture-only", opener=transport).route(
        RouteRequest([105.83, 21.02], [105.84, 21.03])
    )
    assert result == RouteFailure("timeout")


def test_legacy_osrm_seam_never_logs_provider_exception(monkeypatch, caplog):
    def transport(*_a, **_kw):
        raise RuntimeError("https://private.invalid/?apiKey=fixture-canary")

    monkeypatch.setattr(routing_service, "urlopen", transport)
    with caplog.at_level("INFO"):
        assert routing_service.fetch_osrm_route([105.83, 21.02], [105.84, 21.03]) is None
    assert "fixture-canary" not in caplog.text


def test_trip_combination_keeps_disconnected_osrm_legs(monkeypatch):
    responses = iter(
        [
            {
                "routes": [
                    {
                        "geometry": {"type": "LineString", "coordinates": [[105.83, 21.02], [105.84, 21.03]]},
                        "distance": 10,
                        "duration": 2,
                    }
                ]
            },
            {
                "routes": [
                    {
                        "geometry": {"type": "LineString", "coordinates": [[105.85, 21.04], [105.86, 21.05]]},
                        "distance": 20,
                        "duration": 3,
                    }
                ]
            },
        ]
    )
    monkeypatch.setattr(routing_service, "urlopen", lambda *_a, **_kw: Response(next(responses)))
    result = routing_service.resolve_trip_route([105.83, 21.02], [105.84, 21.03], [105.86, 21.05])
    assert result["route_geometry"] == {
        "type": "MultiLineString",
        "coordinates": [
            [[105.83, 21.02], [105.84, 21.03]],
            [[105.85, 21.04], [105.86, 21.05]],
        ],
    }


def test_resolve_trip_route_with_waypoints_stitches_continuous_route(monkeypatch):
    # 3 legs: origin -> wp, wp -> pickup, pickup -> dest
    responses = iter(
        [
            {
                "routes": [
                    {
                        "geometry": {"type": "LineString", "coordinates": [[105.83, 21.02], [105.835, 21.025]]},
                        "distance": 500,
                        "duration": 60,
                    }
                ]
            },
            {
                "routes": [
                    {
                        "geometry": {"type": "LineString", "coordinates": [[105.835, 21.025], [105.84, 21.03]]},
                        "distance": 600,
                        "duration": 70,
                    }
                ]
            },
            {
                "routes": [
                    {
                        "geometry": {"type": "LineString", "coordinates": [[105.84, 21.03], [105.86, 21.05]]},
                        "distance": 2000,
                        "duration": 200,
                    }
                ]
            },
        ]
    )
    monkeypatch.setattr(routing_service, "urlopen", lambda *_a, **_kw: Response(next(responses)))
    result = routing_service.resolve_trip_route(
        origin=[105.83, 21.02],
        pickup=[105.84, 21.03],
        destination=[105.86, 21.05],
        waypoints=[[105.835, 21.025]],
    )
    assert result is not None
    assert result["pickup_route"]["distance_m"] == 1100
    assert result["pickup_route"]["duration_s"] == 130
    assert result["pickup_route"]["coordinates"] == [
        [105.83, 21.02],
        [105.835, 21.025],
        [105.84, 21.03],
    ]
    assert result["route_geometry"] == {
        "type": "LineString",
        "coordinates": [
            [105.83, 21.02],
            [105.835, 21.025],
            [105.84, 21.03],
            [105.86, 21.05],
        ],
    }


def test_resolve_trip_route_with_waypoint_failure_returns_none(monkeypatch):
    responses = iter(
        [
            {"routes": []},  # first leg fails
        ]
    )
    monkeypatch.setattr(routing_service, "urlopen", lambda *_a, **_kw: Response(next(responses)))
    result = routing_service.resolve_trip_route(
        origin=[105.83, 21.02],
        pickup=[105.84, 21.03],
        destination=[105.86, 21.05],
        waypoints=[[105.835, 21.025]],
    )
    assert result is None


def test_resolve_trip_route_stitches_floating_point_epsilon(monkeypatch):
    # End of leg 1 and start of leg 2 differ by floating-point epsilon (1e-6)
    responses = iter(
        [
            {
                "routes": [
                    {
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[105.83, 21.02], [105.840000001, 21.030000001]],
                        },
                        "distance": 1000,
                        "duration": 100,
                    }
                ]
            },
            {
                "routes": [
                    {
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[105.84, 21.03], [105.86, 21.05]],
                        },
                        "distance": 2000,
                        "duration": 200,
                    }
                ]
            },
        ]
    )
    monkeypatch.setattr(routing_service, "urlopen", lambda *_a, **_kw: Response(next(responses)))
    result = routing_service.resolve_trip_route([105.83, 21.02], [105.84, 21.03], [105.86, 21.05])
    assert result is not None
    assert result["route_geometry"]["type"] == "LineString"
    assert len(result["route_geometry"]["coordinates"]) == 3


@pytest.mark.parametrize("name", ["osrm", "geoapify"])
@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"routes": "bad", "features": "bad"},
        {"routes": [None], "features": [None]},
        {"routes": [{}], "features": [{}]},
    ],
)
def test_malformed_payload_is_a_typed_failure(name, payload):
    from src.services.geoapify_adapter import GeoapifyAdapter
    from src.services.osrm_adapter import OSRMAdapter
    from src.services.route_provider import RouteFailure, RouteRequest

    provider = (
        OSRMAdapter(opener=lambda *_a, **_kw: Response(payload))
        if name == "osrm"
        else GeoapifyAdapter(api_key="fixture-only", opener=lambda *_a, **_kw: Response(payload))
    )
    result = provider.route(RouteRequest([105.83, 21.02], [105.84, 21.03], mode="drive"))
    assert result == RouteFailure("malformed_payload")


def test_bad_json_has_no_raw_error_text():
    from src.services.geoapify_adapter import GeoapifyAdapter
    from src.services.route_provider import RouteFailure, RouteRequest

    class BadJSON(Response):
        def read(self, *_a):
            return b"fixture-canary invalid JSON"

    result = GeoapifyAdapter(api_key="fixture-only", opener=lambda *_a, **_kw: BadJSON(None)).route(
        RouteRequest([105.83, 21.02], [105.84, 21.03])
    )
    assert result == RouteFailure("malformed_payload")


def test_geoapify_missing_key_fails_without_http(monkeypatch):
    from src.services.geoapify_adapter import GeoapifyAdapter
    from src.services.route_provider import RouteFailure, RouteRequest

    monkeypatch.delenv("GEOAPIFY_API_KEY", raising=False)
    calls = []
    result = GeoapifyAdapter(opener=lambda *_a, **_kw: calls.append(1)).route(
        RouteRequest([105.83, 21.02], [105.84, 21.03])
    )
    assert result == RouteFailure("missing_key")
    assert calls == []


def test_secure_transport_blocks_redirect_and_bounds_body(monkeypatch):
    from src.services import routing_http

    handlers = []
    reads = []

    class LargeResponse(Response):
        def read(self, limit):
            reads.append(limit)
            return b"x" * limit

    class Opener:
        def open(self, *_a, **_kw):
            return LargeResponse(None)

    def build(*args):
        handlers.extend(args)
        return Opener()

    monkeypatch.setattr(routing_http, "build_opener", build)
    with pytest.raises(ValueError, match="Provider response exceeds limit"):
        with routing_http.safe_urlopen("https://fixture.invalid", timeout=2) as response:
            response.read()
    assert reads == [2 * 1024 * 1024 + 1]
    with pytest.raises(HTTPError) as error:
        handlers[0].redirect_request(None, None, 302, "private", {}, "https://other.invalid")
    assert error.value.code == 302


@pytest.mark.parametrize("name", ["osrm", "geoapify"])
@pytest.mark.parametrize("metric", [True, -1, 0, float("inf"), float("nan"), "invalid"])
def test_invalid_metrics_are_unavailable_not_fabricated(name, metric):
    from src.services.geoapify_adapter import GeoapifyAdapter
    from src.services.osrm_adapter import OSRMAdapter
    from src.services.route_provider import RouteFailure, RouteRequest

    geometry = {"type": "LineString", "coordinates": [[105.83, 21.02], [105.84, 21.03]]}
    if name == "osrm":
        payload = {"routes": [{"geometry": geometry, "distance": metric, "duration": 10}]}
        provider = OSRMAdapter(opener=lambda *_a, **_kw: Response(payload))
    else:
        payload = geo_payload(geometry)
        payload["features"][0]["properties"]["time"] = metric
        provider = GeoapifyAdapter(api_key="fixture-only", opener=lambda *_a, **_kw: Response(payload))
    assert provider.route(RouteRequest([105.83, 21.02], [105.84, 21.03], mode="drive")) == RouteFailure(
        "malformed_payload"
    )


@pytest.mark.parametrize("name", ["osrm", "geoapify"])
def test_geometry_with_only_isolated_vertices_is_unavailable(name):
    from src.services.geoapify_adapter import GeoapifyAdapter
    from src.services.osrm_adapter import OSRMAdapter
    from src.services.route_provider import RouteFailure, RouteRequest

    geometry = {
        "type": "MultiLineString",
        "coordinates": [
            [[105.83, 21.02]],
            [[105.84, 21.03], None, [105.85, 21.04]],
        ],
    }
    payload = (
        {"routes": [{"geometry": geometry, "distance": 10, "duration": 2}]} if name == "osrm" else geo_payload(geometry)
    )
    provider = (
        OSRMAdapter(opener=lambda *_a, **_kw: Response(payload))
        if name == "osrm"
        else GeoapifyAdapter(api_key="fixture-only", opener=lambda *_a, **_kw: Response(payload))
    )
    assert provider.route(RouteRequest([105.83, 21.02], [105.84, 21.03], mode="drive")) == RouteFailure(
        "malformed_payload"
    )


def test_application_geoapify_selection_defaults_bike_to_motorcycle(monkeypatch):
    monkeypatch.setenv("ROUTING_PROVIDER", "geoapify")
    monkeypatch.setenv("GEOAPIFY_API_KEY", "fixture-only")
    modes = []

    def transport(url, **_kw):
        modes.append(parse_qs(urlsplit(url).query)["mode"])
        return Response(geo_payload())

    monkeypatch.setattr(routing_service, "urlopen", transport)
    result = routing_service.fetch_route([105.83, 21.02], [105.84, 21.03])
    assert result["provider"] == "geoapify"
    assert modes == [["motorcycle"]]


def test_osrm_does_not_claim_motorcycle_or_modeled_traffic():
    from src.services.osrm_adapter import OSRMAdapter
    from src.services.route_provider import RouteFailure, RouteRequest

    calls = []
    provider = OSRMAdapter(opener=lambda *_a, **_kw: calls.append(1))
    assert provider.route(RouteRequest([105.83, 21.02], [105.84, 21.03])) == RouteFailure("unsupported_option")
    assert calls == []


def test_legacy_single_line_consumers_degrade_on_split_osrm_geometry(monkeypatch):
    geometry = {
        "type": "MultiLineString",
        "coordinates": [
            [[105.83, 21.02], [105.84, 21.03]],
            [[105.85, 21.04], [105.86, 21.05]],
        ],
    }
    payload = {"routes": [{"geometry": geometry, "distance": 1317, "duration": 88}]}
    monkeypatch.setattr(routing_service, "urlopen", lambda *_a, **_kw: Response(payload))
    assert routing_service.fetch_osrm_route([105.83, 21.02], [105.86, 21.05]) is None
