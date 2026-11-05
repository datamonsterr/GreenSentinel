import json

from src.services import routing_service


class Response:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps(self.payload).encode()


def test_fetch_osrm_route_success(monkeypatch):
    monkeypatch.setattr(
        routing_service,
        "urlopen",
        lambda *_args, **_kwargs: Response(
            {
                "routes": [
                    {
                        "geometry": {"type": "LineString", "coordinates": [[1, 2], [3, 4]]},
                        "distance": 12.4,
                        "duration": 8.6,
                    }
                ]
            }
        ),
    )
    result = routing_service.fetch_osrm_route([1, 2], [3, 4])
    assert result["geometry"]["coordinates"] == [[1, 2], [3, 4]]
    assert result["distance_m"] == 12
    assert result["duration_s"] == 9
    assert result["provenance"]["status"] == "ok"


def test_fetch_osrm_route_rejects_timeout_and_empty_routes(monkeypatch):
    def timeout(*_args, **_kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(routing_service, "urlopen", timeout)
    assert routing_service.fetch_osrm_route([1, 2], [3, 4]) is None

    monkeypatch.setattr(routing_service, "urlopen", lambda *_args, **_kwargs: Response({"routes": []}))
    assert routing_service.fetch_osrm_route([1, 2], [3, 4]) is None


def test_fetch_osrm_route_rejects_invalid_response(monkeypatch):
    response = Response({"code": "NoRoute", "routes": [{"geometry": {"coordinates": []}}]})
    monkeypatch.setattr(routing_service, "urlopen", lambda *_args, **_kwargs: response)
    assert routing_service.fetch_osrm_route([1, 2], [3, 4]) is None


def test_fetch_osrm_route_rejects_invalid_coordinates(monkeypatch):
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("provider must not receive invalid coordinates")

    monkeypatch.setattr(routing_service, "urlopen", fail_if_called)
    assert routing_service.fetch_osrm_route([float("nan"), 2], [3, 4]) is None
    assert routing_service.fetch_osrm_route([181, 2], [3, 4]) is None
    assert routing_service.fetch_osrm_route(None, [3, 4]) is None
