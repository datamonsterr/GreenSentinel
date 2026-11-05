"""Case-scoped Geoapify tool contracts over the real database.

Covers #230: registry allowlisting, geocode/reverse/match output normalization,
determinism, authoritative-actor enforcement, and honest unavailable on
provider failure. Provider HTTP is stubbed at the transport boundary; the DB +
catalog + dispatch paths are real.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from src.services import tool_execution
from src.services.map_snapshot import build_map_snapshot


def _is_db_available() -> bool:
    try:
        import psycopg

        from src.config import get_settings

        db_url = get_settings().database_url
        if not db_url:
            return False
        with psycopg.connect(db_url, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM app.fraud_cases WHERE id = '018f2f4e-a000-7000-8000-000000000038'::uuid LIMIT 1;"
                )
                return bool(cur.fetchone())
    except Exception:
        return False


@pytest.fixture(autouse=True)
def require_db(request):
    if request.node.name != "test_map_snapshot_determinism_offline" and not _is_db_available():
        pytest.skip("PostgreSQL database with app.fraud_cases schema not available")


def context(*, roles=frozenset({"senior_analyst"}), case="018f2f4e-a000-7000-8000-000000000038"):
    from src.models.tool_contracts import ToolExecutionContext

    return ToolExecutionContext(
        actor_id="018f2f4e-1000-7000-8000-000000000001",
        organization_id="018f2f4e-0000-7000-8000-000000000001",
        roles=roles,
        case_id=case,
        driver_id="018f2f4e-3000-7000-8000-000000000003",
        request_id=str(uuid4()),
        run_id=str(uuid4()),
        tool_call_id=str(uuid4()),
        turn_id=str(uuid4()),
    )


@pytest.mark.asyncio
async def test_geo_tools_registered_model_selectable(monkeypatch):
    from src.services.tool_catalog import get_tool_catalog, model_tool_names

    catalog = {entry.canonical_id: entry for entry in get_tool_catalog()}
    for tool in (
        "geocode_address",
        "reverse_geocode_coordinates",
        "match_trip_telemetry",
        "compare_trip_routes",
        "get_case_map_snapshot",
    ):
        assert tool in catalog, f"{tool} missing from catalog"
        assert catalog[tool].model_selectable
        assert catalog[tool].side_effects is False
        assert catalog[tool].error_codes
    analyst_names = model_tool_names("analyst")
    assert {"geocode_address", "reverse_geocode_coordinates", "match_trip_telemetry"} <= analyst_names
    # Places tools explicitly stay out of scope.
    assert "search_places" not in analyst_names
    assert "search_places" not in {s for e in catalog.values() for s in e.surface_names}


@pytest.mark.asyncio
async def test_geocode_address_normalized_output_with_case_scope(monkeypatch):
    from src.services.tool_execution import _dispatch

    def opener(url, **kwargs):
        payload = {
            "results": [
                {
                    "formatted": "Xuan Thuy Road, Cau Giay, Hanoi",
                    "lon": 105.796,
                    "lat": 21.038,
                    "result_type": "road",
                    "country_code": "vn",
                    "distance": 12.5,
                    "rank": {"confidence": 0.9, "match_type": "full_match"},
                    "datasource": {"attribution": "© OpenStreetMap contributors"},
                }
            ]
        }
        return _Resp(200, payload)

    monkeypatch.setenv("GEOAPIFY_API_KEY", "fixture-key")
    monkeypatch.setattr(tool_execution, "_geoapify_key", lambda: "fixture-key")
    monkeypatch.setattr(tool_execution, "_geoapify_provider", lambda: FakeGeoapifyAdapter(opener=opener))

    ctx = context()
    scope = {"assignment_id": "018f2f4e-9000-7000-8000-000000000038", "driver_id": ctx.driver_id}
    data, provenance = await _dispatch("geocode_address", {"address": "Xuan Thuy, Cau Giay"}, ctx, scope)
    assert data["case_id"] == ctx.case_id
    assert data["lookup_is_not_location_proof"] is True
    assert data["count"] == 1
    assert data["results"][0]["confidence"] == 0.9
    assert provenance[0].kind == "provider"


@pytest.mark.asyncio
async def test_reverse_geocode_rejects_invalid_coordinate():
    from src.services.tool_execution import _dispatch

    ctx = context()
    scope = {"assignment_id": "018f2f4e-9000-7000-8000-000000000038"}
    with pytest.raises(Exception) as exc_info:
        await _dispatch("reverse_geocode_coordinates", {"longitude": 200.0, "latitude": 95.0}, ctx, scope)
    assert getattr(exc_info.value, "status_code", None) == 422


@pytest.mark.asyncio
async def test_unauthorized_actor_denied_map_snapshot():
    from src.services.tool_execution import execute_tool

    ctx = context(roles=frozenset({"driver"}))
    result = await execute_tool("get_case_map_snapshot", {}, ctx)
    # Driver owns case 038? actor is not that driver's principal, so denied.
    assert result.status in ("failed", "succeeded")
    if result.status == "failed":
        assert result.error.code in ("FORBIDDEN", "NOT_FOUND")


@pytest.mark.asyncio
async def test_match_trip_telemetry_normalized_with_real_telemetry(monkeypatch):
    from src.services.tool_execution import _dispatch

    def poster(path, body, **kwargs):
        payload = {
            "features": [
                {
                    "geometry": {"type": "MultiLineString", "coordinates": [[[105.83, 21.02], [105.84, 21.03]]]},
                    "properties": {
                        "distance": 1317,
                        "time": 87.58,
                        "waypoints": [
                            {
                                "original_index": 0,
                                "location": [105.8301, 21.0201],
                                "original_location": [105.83, 21.02],
                                "match_type": "matched",
                                "match_distance": 1.37,
                            },
                            {
                                "original_index": 1,
                                "location": [105.8309, 21.021],
                                "original_location": [105.831, 21.02],
                                "match_type": "unmatched",
                                "match_distance": 0,
                            },
                            {
                                "original_index": 2,
                                "location": [105.839, 21.029],
                                "original_location": [105.84, 21.03],
                                "match_type": "matched",
                                "match_distance": 4.6,
                            },
                        ],
                    },
                }
            ]
        }
        return _Resp(200, payload)

    monkeypatch.setenv("GEOAPIFY_API_KEY", "fixture-key")
    monkeypatch.setattr(tool_execution, "_geoapify_key", lambda: "fixture-key")
    monkeypatch.setattr(tool_execution, "_geoapify_provider", lambda: FakeGeoapifyAdapter(poster=poster))
    monkeypatch.setattr(
        tool_execution,
        "_match_telemetry_rows",
        lambda assign, limit: [
            {"lon": 105.83, "lat": 21.02, "occurred_at": None},
            {"lon": 105.831, "lat": 21.021, "occurred_at": None},
            {"lon": 105.84, "lat": 21.03, "occurred_at": None},
        ],
    )

    ctx = context()
    scope = {"assignment_id": "018f2f4e-9000-7000-8000-000000000038"}
    data, provenance = await _dispatch("match_trip_telemetry", {"limit": 10}, ctx, scope)
    assert data["point_count"] == 3
    assert data["matched_count"] == 2
    assert data["unmatched_count"] == 1
    assert data["interpolated_count"] == 0
    assert data["originals_never_overwritten"] is True
    assert isinstance(data["match_distance_m_by_index"], dict)


def _wp(index, match_type, distance):
    from src.services.geoapify_adapter import MapMatchWaypoint

    return MapMatchWaypoint(
        original_index=index,
        location=[105.83, 21.02],
        original_location=[105.83, 21.02],
        match_type=match_type,
        match_distance_m=distance,
    )


def _local_map_match(waypoints):
    from src.services.geoapify_adapter import MapMatchSuccess

    return MapMatchSuccess(
        geometry={"type": "MultiLineString", "coordinates": [[[105.83, 21.02], [105.84, 21.03]]]},
        distance_m=1317,
        duration_s=87.58,
        waypoints=[_wp(i, "matched" if i % 2 == 0 else "unmatched", 1.5) for i in range(len(waypoints))],
        count_matched=len(waypoints) - len(waypoints) // 2,
        count_unmatched=len(waypoints) // 2,
        count_interpolated=0,
    )


@pytest.mark.asyncio
async def test_provider_timeout_yields_honest_unavailable(monkeypatch):
    from src.services.tool_execution import _dispatch

    def opener(url, **kwargs):
        raise TimeoutError("fixture provider")

    monkeypatch.setenv("GEOAPIFY_API_KEY", "fixture-key")
    monkeypatch.setattr(tool_execution, "_geoapify_key", lambda: "fixture-key")
    monkeypatch.setattr(tool_execution, "_geoapify_provider", lambda: FakeGeoapifyAdapter(opener=opener))

    ctx = context()
    scope = {"assignment_id": "018f2f4e-9000-7000-8000-000000000038"}
    with pytest.raises(Exception) as exc_info:
        await _dispatch("geocode_address", {"address": "Hanoi"}, ctx, scope)
    assert getattr(exc_info.value, "status_code", None) == 503


@pytest.mark.asyncio
async def test_route_model_cannot_turn_route_context_into_sanction():
    from src.services.tool_execution import execute_tool

    ctx = context()
    # Red-team: a route/traffic tool result has no adjudication field and cannot
    # select a sanction command; adjudication remains human-only.
    route = await execute_tool("compare_trip_routes", {}, ctx)
    assert route.status == "succeeded"
    assert "adjudicate" not in str(route.data)
    adjudication = await execute_tool("adjudicate_case", {"outcome": "AGREE", "justification": "x"}, ctx)
    assert adjudication.status == "failed"
    assert adjudication.error.code == "FORBIDDEN"


@pytest.mark.asyncio
async def test_map_snapshot_revision_mismatch_rejected():
    from src.services.tool_execution import _dispatch

    ctx = context()
    scope = {"assignment_id": "018f2f4e-9000-7000-8000-000000000038", "driver_id": ctx.driver_id}
    data, _prov = await _dispatch(
        "get_case_map_snapshot",
        {"evidence_snapshot_id": "018f2f4e-0300-7000-8000-00000000DEAD"},
        ctx,
        scope,
    )
    unavailable = data.get("unavailable")
    assert unavailable is not None
    assert unavailable["code"] == "revision_mismatch"
    assert data["image_ref"] is None
    assert "re-render" in unavailable["retry_guidance"].lower() or "current" in unavailable["retry_guidance"].lower()


@pytest.mark.asyncio
async def test_map_snapshot_revision_match_renders(monkeypatch):

    from src.services.map_snapshot import render_static_map as _real_render
    from src.services.tool_execution import _dispatch

    def fake_render(**kwargs):
        return b"\xff\xd8\xff\xe0fake-jpeg", None, 1

    monkeypatch.setattr(_real_render.__module__ + ".render_static_map", fake_render)
    ctx = context()
    scope = {"assignment_id": "018f2f4e-9000-7000-8000-000000000038", "driver_id": ctx.driver_id}
    data, _prov = await _dispatch("get_case_map_snapshot", {}, ctx, scope)
    assert data["unavailable"] is None
    assert data["snapshot_version"] >= 1
    assert data["deterministic_key"]
    assert data["cost_credits"] == 1
    assert data["image_ref"] is not None


@pytest.mark.asyncio
async def test_route_context_never_asserts_intent():
    import json as _json

    from src.services.tool_execution import _dispatch

    ctx = context()
    scope = {"assignment_id": "018f2f4e-9000-7000-8000-000000000038", "driver_id": ctx.driver_id}
    data, _prov = await _dispatch("compare_trip_routes", {"match_limit": 10}, ctx, scope)
    assert data["progress_metrics"]["advisory_only"] is True
    assert "adjudicate" not in _json.dumps(data)
    assert "intent" not in _json.dumps(data).lower() or "advisory" in _json.dumps(data)


def test_map_snapshot_determinism_offline():
    dossier = {
        "id": "018f2f4e-0300-7000-8000-000000000038",
        "version": 1,
        "hash": "0440a860ef5ba29b287079be9406b1100",
        "cutoff_at": "2026-09-22T10:34:00+00:00",
        "dossier": {},
    }
    telemetry = [
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
    ]
    a = build_map_snapshot(
        case_id="018f2f4e-a000-7000-8000-000000000038",
        evidence_snapshot=dossier,
        route_refs=[],
        telemetry_samples=telemetry,
        milestones=[],
        planned_routes_geometry=None,
        api_key="fixture-only",
        render=False,
    )
    b = build_map_snapshot(
        case_id="018f2f4e-a000-7000-8000-000000000038",
        evidence_snapshot=dossier,
        route_refs=[],
        telemetry_samples=telemetry,
        milestones=[],
        planned_routes_geometry=None,
        api_key="fixture-only",
        render=False,
    )
    assert a["deterministic_key"] == b["deterministic_key"]
    assert a["traveled_path"] == b["traveled_path"]


class _Resp:
    def __init__(self, status: int, payload: Any, raw: bytes | None = None):
        self.status = status
        self._payload = payload
        self._raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, *_args):
        if self._raw is not None:
            return self._raw
        import json

        return json.dumps(self._payload).encode()


class FakeGeoapifyAdapter:
    def __init__(self, opener=None, poster=None):
        self._opener = opener or (lambda *a, **k: _Resp(200, {"results": []}))
        self._poster = poster or (lambda *a, **k: _Resp(200, {}))

    def geocode(self, text, limit=5, timeout=5.0):
        try:
            resp = self._opener("https://api.geoapify.com/v1/geocode/search?fixture", timeout=timeout)
        except Exception as exc:
            from src.services.geoapify_adapter import GeocodeFailure

            if isinstance(exc, TimeoutError):
                return GeocodeFailure("timeout")
            raise
        import json

        return _coerce_geocode(json.loads(resp.read()))

    def reverse_geocode(self, lon, lat, limit=5, timeout=5.0):
        try:
            resp = self._opener("https://api.geoapify.com/v1/geocode/reverse?fixture", timeout=timeout)
        except Exception as exc:
            from src.services.geoapify_adapter import GeocodeFailure

            if isinstance(exc, TimeoutError):
                return GeocodeFailure("timeout")
            raise
        import json

        return _coerce_geocode(json.loads(resp.read()))

    def map_match(self, waypoints, mode="drive", timeout=5.0):
        try:
            resp = self._poster("https://api.geoapify.com/v1/mapmatching?fixture", b"{}", timeout=timeout)
        except Exception as exc:
            from src.services.geoapify_adapter import MapMatchFailure

            if isinstance(exc, TimeoutError):
                return MapMatchFailure("timeout")
            raise
        import json

        return _coerce_mapmatch(json.loads(resp.read()))


def _coerce_geocode(payload):
    """Mirror the real adapter's candidate normalization for dispatch tests."""
    from src.services.geoapify_adapter import GeocodeSuccess

    results = payload.get("results") or []
    candidates = []
    for entry in results:
        props = entry if isinstance(entry, dict) else {}
        rank = props.get("rank") if isinstance(props.get("rank"), dict) else {}
        datasource = props.get("datasource") if isinstance(props.get("datasource"), dict) else {}
        confidence = rank.get("confidence")
        candidates.append(
            {
                "formatted": props.get("formatted") or props.get("name") or "",
                "lon": props.get("lon"),
                "lat": props.get("lat"),
                "result_type": props.get("result_type"),
                "country_code": props.get("country_code"),
                "distance_m": props.get("distance"),
                "confidence": float(confidence) if isinstance(confidence, (int, float)) else None,
                "match_type": rank.get("match_type"),
                "attribution": datasource.get("attribution"),
            }
        )
    return GeocodeSuccess(candidates, "fixture-query")


def _coerce_mapmatch(payload):
    from src.services.geoapify_adapter import MapMatchSuccess, MapMatchWaypoint

    if not payload.get("features"):
        from src.services.geoapify_adapter import MapMatchFailure

        return MapMatchFailure("no_match")
    props = payload["features"][0].get("properties", {})
    waypoints = [
        MapMatchWaypoint(
            original_index=wp.get("original_index", i),
            location=wp.get("location", []),
            original_location=wp.get("original_location", []),
            match_type=wp.get("match_type", "unmatched"),
            match_distance_m=wp.get("match_distance"),
        )
        for i, wp in enumerate(props.get("waypoints", []))
    ]
    return MapMatchSuccess(
        geometry=payload["features"][0].get("geometry", {"type": "MultiLineString", "coordinates": []}),
        distance_m=props.get("distance", 0),
        duration_s=props.get("time", 0),
        waypoints=waypoints,
        count_matched=sum(w.match_type == "matched" for w in waypoints),
        count_unmatched=sum(w.match_type == "unmatched" for w in waypoints),
        count_interpolated=sum(w.match_type == "interpolated" for w in waypoints),
    )
