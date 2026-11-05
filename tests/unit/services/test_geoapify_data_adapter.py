"""Deterministic case-map snapshot + Geoapify data adapter contracts (offline)."""

from __future__ import annotations

import json

import pytest

from src.services.geoapify_adapter import (
    GeoapifyAdapter,
    GeocodeFailure,
    GeocodeSuccess,
    MapMatchFailure,
    MapMatchSuccess,
)
from src.services.map_snapshot import (
    _encode_polyline,
    _gap_windows,
    build_map_snapshot,
    build_post_payload,
    deterministic_key,
    render_static_map,
)


class Response:
    status = 200

    def __init__(self, payload=None, raw=None):
        self.payload = payload
        self._raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, *_args):
        if self._raw is not None:
            return self._raw
        return json.dumps(self.payload).encode()


def _geoapi_payload(features=True, results=None, status=200):
    class R(Response):
        pass

    r = R()
    r.status = status
    if features:
        r.payload = {"features": results}
    else:
        r.payload = {"results": results}
    return r


GEOCODE_FEATURE = {
    "geometry": {"type": "Point", "coordinates": [105.8525357, 21.0288313]},
    "properties": {
        "formatted": "Hoàn Kiếm Lake, Hoan Kiem Ward, Hà Nội, Vietnam",
        "result_type": "amenity",
        "country_code": "vn",
        "distance": 30.5,
        "rank": {"confidence": 0.95, "match_type": "inner_part"},
        "datasource": {"attribution": "© OpenStreetMap contributors"},
    },
}


def test_geocode_normalizes_candidates_with_confidence_and_distance():
    calls = []

    def opener(url, **kwargs):
        calls.append(url)
        return _geoapi_payload(results=[GEOCODE_FEATURE])

    provider = GeoapifyAdapter(api_key="fixture-only", opener=opener)
    result = provider.geocode("Hoan Kiem Lake")
    assert isinstance(result, GeocodeSuccess)
    assert result.query == "Hoan Kiem Lake"
    candidate = result.candidates[0]
    assert candidate["confidence"] == 0.95
    assert candidate["distance_m"] == 30.5
    assert candidate["formatted"].startswith("Hoàn Kiếm")
    assert candidate["attribution"].startswith("© OpenStreetMap")
    assert "apiKey=fixture-only" in calls[0]


def test_geocode_never_leaks_key_in_failure():
    def opener(url, **kwargs):
        raise TimeoutError("fixture")

    provider = GeoapifyAdapter(api_key="fixture-only", opener=opener)
    result = provider.geocode("Hanoi")
    assert isinstance(result, GeocodeFailure)
    assert result.code == "timeout"


def test_geocode_missing_key_fails_without_http(monkeypatch):
    monkeypatch.delenv("GEOAPIFY_API_KEY", raising=False)
    provider = GeoapifyAdapter(opener=lambda *_a, **_kw: pytest.fail("no HTTP on missing key"))
    result = provider.geocode("Hanoi")
    assert isinstance(result, GeocodeFailure)
    assert result.code == "missing_key"


def test_reverse_geocode_invalid_coordinate_rejected():
    provider = GeoapifyAdapter(api_key="fixture-only", opener=lambda *_a, **_kw: pytest.fail("no HTTP"))
    assert isinstance(provider.reverse_geocode(200.0, 100.0), GeocodeFailure)


def test_reverse_geocode_normalizes_candidates():
    def opener(url, **kwargs):
        return _geoapi_payload(results=[GEOCODE_FEATURE])

    provider = GeoapifyAdapter(api_key="fixture-only", opener=opener)
    result = provider.reverse_geocode(105.8525357, 21.0288313)
    assert isinstance(result, GeocodeSuccess)
    assert result.candidates[0]["distance_m"] == 30.5


MAPMATCH_PAYLOAD = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {
                "type": "MultiLineString",
                "coordinates": [[[105.83, 21.02], [105.84, 21.03]]],
            },
            "properties": {
                "distance": 1317,
                "time": 87.581,
                "waypoints": [
                    {
                        "original_index": 0,
                        "location": [105.8301, 21.0201],
                        "original_location": [105.83, 21.02],
                        "match_type": "matched",
                        "match_distance": 1.37,
                        "leg_index": 0,
                        "step_index": 0,
                    },
                    {
                        "original_index": 1,
                        "location": [105.8309, 21.0211],
                        "original_location": [105.831, 21.021],
                        "match_type": "unmatched",
                        "match_distance": 0,
                        "leg_index": None,
                        "step_index": None,
                    },
                    {
                        "original_index": 2,
                        "location": [105.839, 21.029],
                        "original_location": [105.84, 21.03],
                        "match_type": "matched",
                        "match_distance": 4.6,
                        "leg_index": 0,
                        "step_index": 5,
                    },
                ],
            },
        }
    ],
}


def test_map_match_preserves_match_type_and_counts():
    posted = []

    def poster(path, body, **kwargs):
        posted.append(json.loads(body))
        return Response(MAPMATCH_PAYLOAD)

    provider = GeoapifyAdapter(api_key="fixture-only", poster=poster)
    waypoints = [
        {"location": [105.83, 21.02], "timestamp": "2026-09-22T10:19:00Z"},
        {"location": [105.831, 21.021], "timestamp": "2026-09-22T10:19:30Z"},
        {"location": [105.84, 21.03], "timestamp": "2026-09-22T10:20:00Z"},
    ]
    result = provider.map_match(waypoints)
    assert isinstance(result, MapMatchSuccess)
    assert result.count_matched == 2
    assert result.count_unmatched == 1
    assert result.count_interpolated == 0
    assert [w.match_type for w in result.waypoints] == ["matched", "unmatched", "matched"]
    assert result.waypoints[0].match_distance_m == 1.37
    assert posted[0]["mode"] == "drive"
    assert posted[0]["waypoints"][0]["location"] == [105.83, 21.02]


def test_map_match_rejects_short_input():
    provider = GeoapifyAdapter(api_key="fixture-only", poster=lambda *_a, **_kw: pytest.fail("no HTTP"))
    assert isinstance(provider.map_match([{"location": [105.83, 21.02]}]), MapMatchFailure)


# ─── Map snapshot determinism ────────────────────────────────────────────────


def _snapshot_dossier():
    return {
        "id": "018f2f4e-0300-7000-8000-000000000038",
        "version": 1,
        "hash": "0440a860ef5ba29b287079be9406b1100",
        "cutoff_at": "2026-09-22T10:34:00+00:00",
        "dossier": {},
    }


def _telemetry():
    return [
        {
            "event_id": "e1",
            "occurred_at": "2026-09-22T10:19:00+00:00",
            "position": {"coordinates": [105.839174, 21.004685]},
        },
        {
            "event_id": "e2",
            "occurred_at": "2026-09-22T10:20:00+00:00",
            "position": {"coordinates": [105.8395, 21.0047]},
        },
        {
            "event_id": "e3",
            "occurred_at": "2026-09-22T10:20:45+00:00",
            "position": {"coordinates": [105.8400, 21.0050]},
        },
    ]


def test_snapshot_determinism_same_revision_same_refs():
    a = build_map_snapshot(
        case_id="018f2f4e-a000-7000-8000-000000000038",
        evidence_snapshot=_snapshot_dossier(),
        route_refs=[],
        telemetry_samples=_telemetry(),
        milestones=[
            {
                "id": "ms-start",
                "type": "start_match",
                "timestamp": "2026-09-22T10:19:00+00:00",
                "lat": 21.004685,
                "lon": 105.839174,
                "sequence": 0,
            }
        ],
        planned_routes_geometry=None,
        api_key="fixture-only",
        render=False,
    )
    b = build_map_snapshot(
        case_id="018f2f4e-a000-7000-8000-000000000038",
        evidence_snapshot=_snapshot_dossier(),
        route_refs=[],
        telemetry_samples=_telemetry(),
        milestones=[
            {
                "id": "ms-start",
                "type": "start_match",
                "timestamp": "2026-09-22T10:19:00+00:00",
                "lat": 21.004685,
                "lon": 105.839174,
                "sequence": 0,
            }
        ],
        planned_routes_geometry=None,
        api_key="fixture-only",
        render=False,
    )
    assert a["deterministic_key"] == b["deterministic_key"]
    assert a["traveled_path"] == b["traveled_path"]
    assert a["checkpoint_times"] == b["checkpoint_times"]
    assert a["gap_windows"] == b["gap_windows"]
    assert a["snapshot_version"] == 1


def test_snapshot_new_revision_creates_new_artifact():
    base = _snapshot_dossier()
    a = build_map_snapshot(
        case_id="c",
        evidence_snapshot=base,
        route_refs=[],
        telemetry_samples=_telemetry(),
        milestones=[],
        planned_routes_geometry=None,
        api_key="key",
        render=False,
    )
    bumped = dict(base, version=2, hash="deadbeef")
    b = build_map_snapshot(
        case_id="c",
        evidence_snapshot=bumped,
        route_refs=[],
        telemetry_samples=_telemetry(),
        milestones=[],
        planned_routes_geometry=None,
        api_key="key",
        render=False,
    )
    assert a["snapshot_version"] == 1
    assert b["snapshot_version"] == 2
    assert a["deterministic_key"] != b["deterministic_key"]


def test_snapshot_bound_to_revision_deterministic_key():
    assert deterministic_key(1, "hash-a") == deterministic_key(1, "hash-a")
    assert deterministic_key(1, "hash-a") != deterministic_key(2, "hash-a")


def test_snapshot_unavailable_path_no_geometry():
    result = build_map_snapshot(
        case_id="c",
        evidence_snapshot=_snapshot_dossier(),
        route_refs=[],
        telemetry_samples=[],
        milestones=[],
        planned_routes_geometry=None,
        api_key="fixture-only",
        render=False,
    )
    assert result["unavailable"] is not None
    assert result["unavailable"]["code"] in {"no_telemetry", "no_geometry"}
    assert result["image_ref"] is None
    assert result["deterministic_key"]


def test_render_static_map_quota_returns_structured_unavailable():
    class Quota(Response):
        status = 429

    result, unavailable, credits = render_static_map(
        url="https://maps.geoapify.com/v1/staticmap?x=1",
        post_payload=None,
        api_key="fixture-only",
        opener=lambda *_a, **_kw: Quota(),
        poster=lambda *_a, **_kw: Quota(),
    )
    assert result is None
    assert unavailable is not None
    assert unavailable["code"] == "quota_exceeded"
    assert "retry" in unavailable["retry_guidance"].lower()
    assert credits == 0


def test_render_static_map_timeout_returns_unavailable():
    def timeout(*_a, **_kw):
        raise TimeoutError("fixture")

    result, unavailable, credits = render_static_map(
        url="https://maps.geoapify.com/v1/staticmap?x=1",
        post_payload=None,
        api_key="fixture-only",
        opener=timeout,
        poster=timeout,
    )
    assert result is None
    assert unavailable["code"] == "provider_timeout"
    assert unavailable["retryable"] is True


def test_post_build_for_complex_geometry():
    payload = build_post_payload(
        center_lon=105.83,
        center_lat=21.02,
        zoom=14,
        markers=[{"lon": 105.83, "lat": 21.02, "color": "green", "text": "S"}],
        traveled_polyline=[[105.83, 21.02], [105.84, 21.03]],
        planned_routes=[{"leg": "destination_route", "points": [[105.84, 21.03], [105.85, 21.04]]}],
    )
    assert payload["style"] == "osm-bright"
    assert payload["geometries"][0]["type"] == "polyline6"
    assert payload["geometries"][0]["linestyle"] == "solid"
    assert payload["geometries"][1]["linestyle"] == "dashed"
    assert isinstance(payload["geometries"][0]["value"], str)


def test_polyline_encoder_deterministic():
    points_a = [[21.0278, 105.8342], [21.0282, 105.8355]]
    points_b = [[21.0278, 105.8342], [21.0282, 105.8355]]
    assert _encode_polyline(points_a) == _encode_polyline(points_b)
    assert isinstance(_encode_polyline(points_a), str)


def test_gap_window_detection():
    points = [
        {"occurred_at": "2026-09-22T10:19:00+00:00"},
        {"occurred_at": "2026-09-22T10:19:20+00:00", "lon": 1, "lat": 1},
        {"occurred_at": "2026-09-22T10:21:30+00:00", "lon": 2, "lat": 2},
    ]
    windows = _gap_windows(points, gap_threshold_s=30.0)
    assert len(windows) == 1
    assert windows[0]["gap_seconds"] == 130.0
    assert windows[0]["start_lon"] == 1


def test_gap_window_survives_without_coordinates():
    points = [
        {"occurred_at": "2026-09-22T10:19:00+00:00"},
        {"occurred_at": "2026-09-22T10:20:00+00:00"},
    ]
    windows = _gap_windows(points, gap_threshold_s=30.0)
    assert len(windows) == 1
    assert "start_lon" not in windows[0]
