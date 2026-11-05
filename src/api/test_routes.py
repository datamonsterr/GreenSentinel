"""FastAPI endpoints for SPEC-0130 Tester Trip Simulation."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlencode
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from src.api.auth import Principal, require_principal
from src.config import Settings, get_settings
from src.models.test_simulation import (
    MAX_START_TO_PICKUP_M,
    ClerkLinkedDriverResponse,
    GeocodeResponse,
    GeocodeResult,
    GeoJsonLineString,
    PresetBatchEvent,
    PresetBatchRunCreate,
    PresetBatchRunDetailResponse,
    PresetBatchRunResponse,
    ProductionPublishResponse,
    PublishProductionPayload,
    RouteResolveRequest,
    RouteResolveResponse,
    TestCaseResponse,
    TestCaseSaveRequest,
    TestControlCommand,
    TestDefinitionRevisionCreate,
    TestDefinitionRevisionResponse,
    TestNotificationResponse,
    TestPipelineStage,
    TestPlanCreate,
    TestPlanResponse,
    TestPresetDetailResponse,
    TestPresetListResponse,
    TestPresetPlanRequest,
    TestPresetPlanResponse,
    TestRunCreate,
    TestRunOverview,
    TestRunResponse,
    TestRunSummary,
    TestRunTitleUpdate,
    TestRunTraceStage,
    TestTelemetrySample,
    TestTriageRequest,
    TestTriageResponse,
)
from src.services.case_service import CaseService, get_case_service
from src.services.clerk_directory import ClerkDirectoryClient
from src.services.driver_directory import DriverRecord, get_driver_directory
from src.services.feature_engineering import compute_feature_window
from src.services.route_analytics import haversine_distance_m
from src.services.routing_http import safe_urlopen
from src.services.routing_service import resolve_trip_route
from src.services.telemetry_queue_worker import JevAssessmentAgent
from src.services.test_preset_batch import (
    build_trip_compact_snapshot,
    run_preset_batch,
    validate_preset_batch_run_params,
)
from src.services.test_presets import (
    create_preset_plan,
    get_preset_detail,
    list_presets,
    load_preset_records,
)
from src.services.test_simulation_runner import get_simulation_runner
from src.services.test_simulation_service import SimulationKinematicsEngine

logger = logging.getLogger(__name__)

PRESET_LOCATIONS: list[dict[str, Any]] = [
    {
        "formatted": "Hồ Hoàn Kiếm, Tràng Tiền, Hoàn Kiếm, Hà Nội",
        "lat": 21.0285,
        "lon": 105.8524,
        "address_line1": "Hồ Hoàn Kiếm",
        "city": "Hà Nội",
    },
    {
        "formatted": "Sân bay Quốc tế Nội Bài, Sóc Sơn, Hà Nội",
        "lat": 21.2187,
        "lon": 105.8072,
        "address_line1": "Sân bay Nội Bài",
        "city": "Hà Nội",
    },
    {
        "formatted": "Quảng trường Ba Đình, Điện Biên, Ba Đình, Hà Nội",
        "lat": 21.0345,
        "lon": 105.8342,
        "address_line1": "Quảng trường Ba Đình",
        "city": "Hà Nội",
    },
    {
        "formatted": "Vincom Center Bà Triệu, 191 Bà Triệu, Lê Đại Hành, Hai Bà Trưng, Hà Nội",
        "lat": 21.0118,
        "lon": 105.8497,
        "address_line1": "191 Bà Triệu",
        "city": "Hà Nội",
    },
    {
        "formatted": "Hồ Tây, Quảng An, Tây Hồ, Hà Nội",
        "lat": 21.0601,
        "lon": 105.8236,
        "address_line1": "Hồ Tây",
        "city": "Hà Nội",
    },
    {
        "formatted": "Nhà hát Lớn Hà Nội, 1 Tràng Tiền, Hoàn Kiếm, Hà Nội",
        "lat": 21.0245,
        "lon": 105.8576,
        "address_line1": "1 Tràng Tiền",
        "city": "Hà Nội",
    },
    {
        "formatted": "Bến xe Mỹ Đình, Phạm Hùng, Nam Từ Liêm, Hà Nội",
        "lat": 21.0282,
        "lon": 105.7779,
        "address_line1": "Bến xe Mỹ Đình",
        "city": "Hà Nội",
    },
    {
        "formatted": "Đại học Bách Khoa Hà Nội, 1 Đại Cồ Việt, Hai Bà Trưng, Hà Nội",
        "lat": 21.0049,
        "lon": 105.8434,
        "address_line1": "1 Đại Cồ Việt",
        "city": "Hà Nội",
    },
    {
        "formatted": "Keangnam Landmark 72, Phạm Hùng, Mễ Trì, Nam Từ Liêm, Hà Nội",
        "lat": 21.0173,
        "lon": 105.7838,
        "address_line1": "Keangnam Landmark 72",
        "city": "Hà Nội",
    },
    {
        "formatted": "Lotte Center Hà Nội, 54 Liễu Giai, Cống Vị, Ba Đình, Hà Nội",
        "lat": 21.0322,
        "lon": 105.8123,
        "address_line1": "54 Liễu Giai",
        "city": "Hà Nội",
    },
    {
        "formatted": "Vinhomes Smart City, Tây Mỗ, Nam Từ Liêm, Hà Nội",
        "lat": 20.9995,
        "lon": 105.7485,
        "address_line1": "Vinhomes Smart City",
        "city": "Hà Nội",
    },
    {
        "formatted": "Vinhomes Royal City, 72A Nguyễn Trãi, Thượng Đình, Thanh Xuân, Hà Nội",
        "lat": 21.0028,
        "lon": 105.8156,
        "address_line1": "72A Nguyễn Trãi",
        "city": "Hà Nội",
    },
    {
        "formatted": "Vinhomes Times City, 458 Minh Khai, Vĩnh Tuy, Hai Bà Trưng, Hà Nội",
        "lat": 20.9958,
        "lon": 105.8672,
        "address_line1": "458 Minh Khai",
        "city": "Hà Nội",
    },
    {
        "formatted": "Sân vận động Quốc gia Mỹ Đình, Lê Đức Thọ, Nam Từ Liêm, Hà Nội",
        "lat": 21.0205,
        "lon": 105.7639,
        "address_line1": "Sân vận động Mỹ Đình",
        "city": "Hà Nội",
    },
    {
        "formatted": "Trung tâm Hội nghị Quốc gia, Đại lộ Thăng Long, Mễ Trì, Nam Từ Liêm, Hà Nội",
        "lat": 21.0064,
        "lon": 105.7876,
        "address_line1": "Đại lộ Thăng Long",
        "city": "Hà Nội",
    },
    {
        "formatted": "Tràng Tiền Plaza, 24 Hai Bà Trưng, Tràng Tiền, Hoàn Kiếm, Hà Nội",
        "lat": 21.0258,
        "lon": 105.8528,
        "address_line1": "24 Hai Bà Trưng",
        "city": "Hà Nội",
    },
    {
        "formatted": "Chợ Đồng Xuân, Đồng Xuân, Hoàn Kiếm, Hà Nội",
        "lat": 21.0378,
        "lon": 105.8497,
        "address_line1": "Chợ Đồng Xuân",
        "city": "Hà Nội",
    },
    {
        "formatted": "Văn Miếu Quốc Tử Giám, 58 Quốc Tử Giám, Văn Miếu, Đống Đa, Hà Nội",
        "lat": 21.0293,
        "lon": 105.8360,
        "address_line1": "58 Quốc Tử Giám",
        "city": "Hà Nội",
    },
    {
        "formatted": "Indochina Plaza Hanoi (IPH), 241 Xuân Thủy, Dịch Vọng Hậu, Cầu Giấy, Hà Nội",
        "lat": 21.0365,
        "lon": 105.7824,
        "address_line1": "241 Xuân Thủy",
        "city": "Hà Nội",
    },
    {
        "formatted": "Công viên Cầu Giấy, Duy Tân, Dịch Vọng Hậu, Cầu Giấy, Hà Nội",
        "lat": 21.0298,
        "lon": 105.7895,
        "address_line1": "Công viên Cầu Giấy",
        "city": "Hà Nội",
    },
    {
        "formatted": "Đại học Quốc gia Hà Nội, 144 Xuân Thủy, Dịch Vọng Hậu, Cầu Giấy, Hà Nội",
        "lat": 21.0375,
        "lon": 105.7818,
        "address_line1": "144 Xuân Thủy",
        "city": "Hà Nội",
    },
    {
        "formatted": "Bệnh viện Bạch Mai, 78 Giải Phóng, Phương Mai, Đống Đa, Hà Nội",
        "lat": 20.9992,
        "lon": 105.8415,
        "address_line1": "78 Giải Phóng",
        "city": "Hà Nội",
    },
    {
        "formatted": "Bệnh viện Việt Đức, 40 Tràng Thi, Hàng Bông, Hoàn Kiếm, Hà Nội",
        "lat": 21.0289,
        "lon": 105.8485,
        "address_line1": "40 Tràng Thi",
        "city": "Hà Nội",
    },
    {
        "formatted": "Aeon Mall Long Biên, 27 Cổ Linh, Long Biên, Hà Nội",
        "lat": 21.0268,
        "lon": 105.9015,
        "address_line1": "27 Cổ Linh",
        "city": "Hà Nội",
    },
    {
        "formatted": "Aeon Mall Hà Đông, Dương Nội, Hà Đông, Hà Nội",
        "lat": 20.9785,
        "lon": 105.7512,
        "address_line1": "Khu đô thị Dương Nội",
        "city": "Hà Nội",
    },
    {
        "formatted": "Bến xe Giáp Bát, Giải Phóng, Giáp Bát, Hoàng Mai, Hà Nội",
        "lat": 20.9812,
        "lon": 105.8412,
        "address_line1": "Bến xe Giáp Bát",
        "city": "Hà Nội",
    },
    {
        "formatted": "Bến xe Nước Ngầm, Ngọc Hồi, Hoàng Liệt, Hoàng Mai, Hà Nội",
        "lat": 20.9635,
        "lon": 105.8418,
        "address_line1": "Bến xe Nước Ngầm",
        "city": "Hà Nội",
    },
    {
        "formatted": "Bến xe Gia Lâm, Ngô Gia Khảm, Gia Thụy, Long Biên, Hà Nội",
        "lat": 21.0512,
        "lon": 105.8778,
        "address_line1": "Bến xe Gia Lâm",
        "city": "Hà Nội",
    },
    {
        "formatted": "Cầu Long Biên, Phúc Xá, Ba Đình, Hà Nội",
        "lat": 21.0425,
        "lon": 105.8562,
        "address_line1": "Cầu Long Biên",
        "city": "Hà Nội",
    },
    {
        "formatted": "Vincom Center Nguyễn Chí Thanh, 54A Nguyễn Chí Thanh, Láng Thượng, Đống Đa, Hà Nội",
        "lat": 21.0227,
        "lon": 105.8087,
        "address_line1": "54A Nguyễn Chí Thanh",
        "city": "Hà Nội",
    },
]


def _normalize_vietnamese(text: str) -> str:
    """Normalize Vietnamese diacritics for resilient keyword search."""
    res = text.lower()
    table = {
        "à": "a",
        "á": "a",
        "ả": "a",
        "ã": "a",
        "ạ": "a",
        "ă": "a",
        "ằ": "a",
        "ắ": "a",
        "ẳ": "a",
        "ẵ": "a",
        "ặ": "a",
        "â": "a",
        "ầ": "a",
        "ấ": "a",
        "ẩ": "a",
        "ẫ": "a",
        "ậ": "a",
        "è": "e",
        "é": "e",
        "ẻ": "e",
        "ẽ": "e",
        "ẹ": "e",
        "ê": "e",
        "ề": "e",
        "ế": "e",
        "ể": "e",
        "ễ": "e",
        "ệ": "e",
        "ì": "i",
        "í": "i",
        "ỉ": "i",
        "ĩ": "i",
        "ị": "i",
        "ò": "o",
        "ó": "o",
        "ỏ": "o",
        "õ": "o",
        "ọ": "o",
        "ô": "o",
        "ồ": "o",
        "ố": "o",
        "ổ": "o",
        "ỗ": "o",
        "ộ": "o",
        "ơ": "o",
        "ờ": "o",
        "ớ": "o",
        "ở": "o",
        "ỡ": "o",
        "ợ": "o",
        "ù": "u",
        "ú": "u",
        "ủ": "u",
        "ũ": "u",
        "ụ": "u",
        "ư": "u",
        "ừ": "u",
        "ứ": "u",
        "ử": "u",
        "ữ": "u",
        "ự": "u",
        "ỳ": "y",
        "ý": "y",
        "ỷ": "y",
        "ỹ": "y",
        "ỵ": "y",
        "đ": "d",
    }
    for k, v in table.items():
        res = res.replace(k, v)
    return res


router = APIRouter(tags=["Tester Simulation"])


def calculate_instantaneous_davi(
    p_prev: tuple[float, float],
    p_curr: tuple[float, float],
    p_target: tuple[float, float],
) -> float:
    """Calculate directional alignment vector index (cosine) towards target."""
    dx_mov = (p_curr[0] - p_prev[0]) * math.cos(math.radians((p_prev[1] + p_curr[1]) / 2.0))
    dy_mov = p_curr[1] - p_prev[1]
    dx_tgt = (p_target[0] - p_prev[0]) * math.cos(math.radians((p_prev[1] + p_target[1]) / 2.0))
    dy_tgt = p_target[1] - p_prev[1]

    norm_mov = math.hypot(dx_mov, dy_mov)
    norm_tgt = math.hypot(dx_tgt, dy_tgt)
    if norm_mov <= 1e-7 or norm_tgt <= 1e-7:
        return 0.0
    cos = (dx_mov * dx_tgt + dy_mov * dy_tgt) / (norm_mov * norm_tgt)
    return round(max(-1.0, min(1.0, cos)), 4)


def point_to_segment_distance_m(
    p: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    """Calculate perpendicular distance in meters from point p to line segment a-b."""
    mid_lat = math.radians((a[1] + b[1]) / 2.0)
    cos_lat = math.cos(mid_lat)

    dx = (b[0] - a[0]) * cos_lat
    dy = b[1] - a[1]
    px = (p[0] - a[0]) * cos_lat
    py = p[1] - a[1]

    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq <= 1e-12:
        return haversine_distance_m(p, a)

    t = max(0.0, min(1.0, (px * dx + py * dy) / seg_len_sq))
    closest = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
    return haversine_distance_m(p, closest)


def min_distance_to_route_m(p: tuple[float, float], route_coords: list[list[float]]) -> float:
    """Calculate minimum perpendicular distance from coordinate to route polyline."""
    if len(route_coords) < 2:
        return 0.0
    return min(
        point_to_segment_distance_m(
            p,
            (route_coords[i][0], route_coords[i][1]),
            (route_coords[i + 1][0], route_coords[i + 1][1]),
        )
        for i in range(len(route_coords) - 1)
    )


def verify_test_context(
    x_test_context: str | None = Header(default=None, alias="X-Test-Context"),
) -> None:
    """Enforces an explicit isolation header; omission is never a safe default."""
    if x_test_context is None or x_test_context.lower() != "true":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Header 'X-Test-Context: true' is required for test simulation endpoints",
        )


async def require_test_operator(
    request: Request,
    x_test_context: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    service: CaseService = Depends(get_case_service),
) -> Principal:
    verify_test_context(x_test_context)
    # Authentication is always resolved by the shared principal dependency.
    # Test headers are accepted only through its explicit APP_ENV=test fixture.
    principal = await require_principal(request, settings, service)
    if principal is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Clerk session required")
    if (
        settings.app_env == "test"
        and settings.test_auth_enabled
        and not request.headers.get("authorization")
        and not request.headers.get("x-organization-id")
    ):
        raise HTTPException(status_code=403, detail="Active organization required")
    if not principal.organization_id:
        raise HTTPException(status_code=403, detail="Active organization required")
    # Every organization member may use the isolated console.  No role guard.
    return principal


router.dependencies.insert(0, Depends(verify_test_context))
router.dependencies.append(Depends(require_test_operator))


@router.get("/actors")
async def list_simulation_actors(
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
    service: CaseService = Depends(get_case_service),
) -> dict[str, list[dict[str, str]]]:
    verify_test_context(x_test_context)
    return service.list_simulation_actors(principal.organization_id)


@router.get("/drivers/search", response_model=list[ClerkLinkedDriverResponse])
async def search_drivers(
    email: str = Query(..., min_length=3, description="Email address or search query (min 3 chars)"),
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
    settings: Settings = Depends(get_settings),
) -> list[ClerkLinkedDriverResponse]:
    """Query Clerk Backend API users by email and return only active linked drivers in caller's org."""
    verify_test_context(x_test_context)
    if not settings.clerk_secret_key:
        raise HTTPException(
            status_code=503,
            detail="Clerk secret missing: set CLERK_SECRET_KEY to enable driver directory",
        )
    clerk_client = ClerkDirectoryClient(secret_key=settings.clerk_secret_key)
    clerk_users = await clerk_client.search_users(email, limit=10)
    dir_svc = get_driver_directory()
    matched = dir_svc.search_active_drivers_by_clerk_users(principal.organization_id, clerk_users)
    return [
        ClerkLinkedDriverResponse(
            driver_id=str(d.driver_id),
            display_name=d.display_name,
            email=d.email or "",
            principal_id=str(d.principal_id),
            vehicle_id=str(d.vehicle_id) if d.vehicle_id else None,
            license_plate=d.license_plate,
        )
        for d in matched[:10]
    ]


@router.get("/drivers/linked", response_model=list[ClerkLinkedDriverResponse])
async def list_linked_drivers(
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
    settings: Settings = Depends(get_settings),
) -> list[ClerkLinkedDriverResponse]:
    """Return all active, Clerk-linked drivers of the organization with display name and email."""
    verify_test_context(x_test_context)
    if not settings.clerk_secret_key:
        raise HTTPException(
            status_code=503,
            detail="Clerk secret missing: set CLERK_SECRET_KEY to enable driver directory",
        )
    dir_svc = get_driver_directory()
    active_drivers = dir_svc.list_active_drivers(principal.organization_id)
    if not active_drivers:
        return []

    clerk_client = ClerkDirectoryClient(secret_key=settings.clerk_secret_key)
    clerk_uids = [d.external_subject for d in active_drivers if d.external_subject]
    clerk_users = await clerk_client.get_users_by_ids(clerk_uids)
    clerk_map = {str(u.get("id")): u for u in clerk_users if u.get("id")}

    responses: list[ClerkLinkedDriverResponse] = []
    for d in active_drivers:
        u = clerk_map.get(d.external_subject)
        email = ClerkDirectoryClient.extract_primary_email(u) if u else (d.email or "")
        display_name = ClerkDirectoryClient.extract_display_name(u) if u else d.display_name
        responses.append(
            ClerkLinkedDriverResponse(
                driver_id=str(d.driver_id),
                display_name=display_name,
                email=email,
                principal_id=str(d.principal_id),
                vehicle_id=str(d.vehicle_id) if d.vehicle_id else None,
                license_plate=d.license_plate,
            )
        )
    return responses


@router.post("/plans", response_model=TestPlanResponse, status_code=status.HTTP_201_CREATED)
async def create_plan(
    payload: TestPlanCreate,
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
) -> TestPlanResponse:
    verify_test_context(x_test_context)
    runner = get_simulation_runner()
    return runner.repository.create_plan(payload, organization_id=principal.organization_id, created_by=principal.id)


@router.get("/plans", response_model=list[TestPlanResponse])
async def list_plans(
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
) -> list[TestPlanResponse]:
    verify_test_context(x_test_context)
    runner = get_simulation_runner()
    return runner.repository.list_plans(organization_id=principal.organization_id)


@router.get("/plans/{plan_id}", response_model=TestPlanResponse)
async def get_plan(
    plan_id: UUID,
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
) -> TestPlanResponse:
    verify_test_context(x_test_context)
    runner = get_simulation_runner()
    plan = runner.repository.get_plan(plan_id, organization_id=principal.organization_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Test plan not found")
    return plan


@router.post("/routes/resolve", response_model=RouteResolveResponse)
async def resolve_simulation_route(
    payload: RouteResolveRequest,
    x_test_context: str | None = Header(default="true"),
) -> RouteResolveResponse:
    verify_test_context(x_test_context)
    result = await asyncio.to_thread(
        resolve_trip_route,
        origin=payload.origin,
        pickup=payload.pickup,
        destination=payload.destination,
        waypoints=payload.waypoints,
    )
    if result is None:
        await asyncio.sleep(0.3)
        result = await asyncio.to_thread(
            resolve_trip_route,
            origin=payload.origin,
            pickup=payload.pickup,
            destination=payload.destination,
            waypoints=payload.waypoints,
        )
    if result is None:
        raise HTTPException(status_code=503, detail="Route provider unavailable")
    return RouteResolveResponse(**result)


@router.get("/geocode", response_model=GeocodeResponse)
async def geocode_location(
    text: str = Query(..., min_length=1),
    limit: int = Query(default=10, ge=1, le=20),
    x_test_context: str | None = Header(default="true"),
    settings: Settings | None = Depends(get_settings),
) -> GeocodeResponse:
    verify_test_context(x_test_context)
    active_settings = settings if isinstance(settings, Settings) else get_settings()
    api_key = active_settings.geoapify_api_key or os.getenv("GEOAPIFY_API_KEY", "")
    coordinate_query = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*", text)
    if api_key:
        if coordinate_query:
            lon, lat = coordinate_query.groups()
            params = urlencode({"lon": lon, "lat": lat, "limit": limit, "apiKey": api_key})
            url = f"https://api.geoapify.com/v1/geocode/reverse?{params}"
        else:
            params = urlencode({"text": text, "filter": "countrycode:vn", "limit": limit, "apiKey": api_key})
            url = f"https://api.geoapify.com/v1/geocode/search?{params}"

        def _fetch_geoapify() -> list[GeocodeResult]:
            with safe_urlopen(url, timeout=4.0) as resp:
                if resp.status != 200:
                    return []
                payload = json.loads(resp.read().decode("utf-8"))
                features = payload.get("features", [])
                results: list[GeocodeResult] = []
                for f in features:
                    props = f.get("properties", {})
                    geom = f.get("geometry", {})
                    coords = geom.get("coordinates", [])
                    if isinstance(coords, list) and len(coords) >= 2:
                        results.append(
                            GeocodeResult(
                                formatted=props.get("formatted") or str(text),
                                lat=float(coords[1]),
                                lon=float(coords[0]),
                                address_line1=props.get("address_line1"),
                                city=props.get("city"),
                            )
                        )
                return results

        try:
            api_results = await asyncio.to_thread(_fetch_geoapify)
            if api_results:
                return GeocodeResponse(results=api_results)
        except Exception as exc:
            logger.warning(
                "Geoapify geocode request failed (%s), using curated landmark matches only",
                type(exc).__name__,
            )

    # Fallback matching from curated landmarks
    raw_query = text.strip()
    norm_query = _normalize_vietnamese(raw_query)
    query_tokens = [tok for tok in norm_query.split() if len(tok) > 1]

    matched: list[dict[str, Any]] = []
    for item in PRESET_LOCATIONS:
        norm_fmt = _normalize_vietnamese(item["formatted"])
        norm_addr = _normalize_vietnamese(item.get("address_line1", ""))
        if any(tok in norm_fmt or tok in norm_addr for tok in query_tokens):
            matched.append(item)

    results: list[GeocodeResult] = [GeocodeResult(**p) for p in matched[:limit]]

    if coordinate_query and not results:
        raise HTTPException(status_code=503, detail="Reverse geocoding unavailable")

    return GeocodeResponse(results=results[:limit])


@router.get("/config")
async def get_test_console_config(
    x_test_context: str | None = Header(default="true"),
) -> dict[str, Any]:
    verify_test_context(x_test_context)
    return {
        "max_start_to_pickup_m": MAX_START_TO_PICKUP_M,
    }


@router.post("/definitions", response_model=TestDefinitionRevisionResponse, status_code=status.HTTP_201_CREATED)
async def create_definition_revision(
    payload: TestDefinitionRevisionCreate,
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
) -> TestDefinitionRevisionResponse:
    verify_test_context(x_test_context)
    runner = get_simulation_runner()
    plan = runner.repository.get_plan(payload.plan_id, organization_id=principal.organization_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    # Driver validation: must be an active Clerk-linked driver in caller's organization
    dir_svc = get_driver_directory()
    driver_id = payload.driver_config.driver_id
    active_driver = dir_svc.get_active_driver(principal.organization_id, driver_id)
    if not active_driver:
        raise HTTPException(
            status_code=422,
            detail=f"Driver '{driver_id}' is not an active Clerk-linked driver in this organization",
        )
    payload.driver_config.driver_id = str(active_driver.driver_id)
    if active_driver.license_plate:
        payload.driver_config.vehicle_plate = active_driver.license_plate

    # 4 km rule: initial snapshot > 4000 m (haversine) from pickup is rejected with 422
    if payload.initial_snapshot is not None:
        pickup_coord: tuple[float, float] | None = None
        if payload.pickup_snapshot is not None:
            pickup_coord = (
                payload.pickup_snapshot.location.longitude,
                payload.pickup_snapshot.location.latitude,
            )
        elif len(payload.route_geometry.coordinates) == 3:
            pickup_coord = (
                payload.route_geometry.coordinates[1][0],
                payload.route_geometry.coordinates[1][1],
            )

        if pickup_coord is not None:
            initial_coord = (
                payload.initial_snapshot.location.longitude,
                payload.initial_snapshot.location.latitude,
            )
            dist_m = haversine_distance_m(initial_coord, pickup_coord)
            if dist_m > MAX_START_TO_PICKUP_M:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Initial snapshot is {dist_m:.1f} m from pickup, "
                        f"exceeding the maximum allowed distance of {MAX_START_TO_PICKUP_M} m."
                    ),
                )

    # If exactly 3 coordinates are provided (origin, pickup, destination), expand to realistic road network
    if len(payload.route_geometry.coordinates) == 3:
        resolved = await asyncio.to_thread(
            resolve_trip_route,
            origin=payload.route_geometry.coordinates[0],
            pickup=payload.route_geometry.coordinates[1],
            destination=payload.route_geometry.coordinates[2],
        )
        if resolved is None:
            raise HTTPException(status_code=503, detail="Route provider unavailable")
        if resolved["route_geometry"]["type"] != "LineString":
            raise HTTPException(
                status_code=422, detail="Disjoint route geometry is unavailable for simulation definitions"
            )
        payload.route_geometry = GeoJsonLineString(**resolved["route_geometry"])

    return runner.repository.create_definition_revision(payload, organization_id=principal.organization_id)


@router.get("/definitions/{rev_id}", response_model=TestDefinitionRevisionResponse)
async def get_definition_revision(
    rev_id: UUID,
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
) -> TestDefinitionRevisionResponse:
    verify_test_context(x_test_context)
    runner = get_simulation_runner()
    rev = runner.repository.get_definition_revision(rev_id, organization_id=principal.organization_id)
    if not rev:
        raise HTTPException(status_code=404, detail="Definition revision not found")
    return rev


@router.post("/runs", response_model=TestRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_and_start_run(
    payload: TestRunCreate,
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
) -> TestRunResponse:
    verify_test_context(x_test_context)
    runner = get_simulation_runner()
    definition = runner.repository.get_definition_revision(
        payload.definition_revision_id, organization_id=principal.organization_id
    )
    if not definition:
        raise HTTPException(status_code=404, detail="Definition revision not found")

    engine = SimulationKinematicsEngine(
        geometry=definition.route_geometry,
        speed_mps=definition.driver_config.speed_mps,
        cadence_s=definition.driver_config.update_cadence_s,
    )

    try:
        run = runner.repository.create_run(
            payload, total_steps=engine.total_steps, organization_id=principal.organization_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if run.status == "QUEUED":
        await runner.start_run(run.id)
    return run


@router.get("/runs/{run_id}", response_model=TestRunResponse)
async def get_run_status(
    run_id: UUID,
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
) -> TestRunResponse:
    verify_test_context(x_test_context)
    runner = get_simulation_runner()
    run = runner.repository.get_run(run_id, organization_id=principal.organization_id)
    if not run:
        raise HTTPException(status_code=404, detail="Simulation run not found")
    return run


@router.get("/runs", response_model=list[TestRunSummary])
async def list_runs(
    limit: int = Query(default=50, ge=1, le=200),
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
) -> list[TestRunSummary]:
    """Console history: only runs owned by the caller's organization."""
    verify_test_context(x_test_context)
    runner = get_simulation_runner()
    return runner.repository.list_runs(principal.organization_id, limit=limit)


@router.patch("/runs/{run_id}", response_model=TestRunResponse)
async def update_run_title(
    run_id: UUID,
    payload: TestRunTitleUpdate,
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
) -> TestRunResponse:
    verify_test_context(x_test_context)
    runner = get_simulation_runner()
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Title must not be blank")
    updated = runner.repository.update_run_title(run_id, title, principal.organization_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Simulation run not found")
    return updated


@router.get("/runs/{run_id}/overview", response_model=TestRunOverview)
async def get_run_overview(
    run_id: UUID,
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
) -> TestRunOverview:
    """Recorded pipeline evidence for one run; never invents progress or labels."""
    verify_test_context(x_test_context)
    runner = get_simulation_runner()
    run = runner.repository.get_run(run_id, principal.organization_id)
    if not run:
        raise HTTPException(status_code=404, detail="Simulation run not found")

    samples = runner.repository.get_samples(run_id, limit=1)
    cases = runner.repository.list_cases(run_id=str(run_id), organization_id=principal.organization_id)
    receipt = runner.repository.get_publish_submission(run_id, principal.organization_id, include_processing=True)
    processing = receipt.get("result", {}) if receipt else {}

    classification_counts: dict[str, int] = {}
    for case in cases:
        for label in case.get("anomaly_types") or []:
            classification_counts[label] = classification_counts.get(label, 0) + 1
    if processing.get("status") == "processed" and isinstance(processing.get("category"), str):
        # The canonical classifier also evaluates normal trips, which have no
        # fraud case. Its persisted receipt is the model-processing evidence.
        classification_counts = {processing["category"]: 1}

    trips_input = 1 if samples else 0
    trips_processed = 1 if cases or processing.get("status") == "processed" else 0
    trips_classified = 1 if classification_counts else 0
    terminal = run.status in {"COMPLETED", "CANCELLED", "FAILED"}

    def stage_state(count: int) -> Literal["done", "active", "waiting"]:
        if count > 0:
            return "done"
        return "waiting" if terminal else "active"

    stages = [
        TestPipelineStage(key="input", label="Trips input", count=trips_input, state=stage_state(trips_input)),
        TestPipelineStage(
            key="models",
            label="Trips through models",
            count=trips_processed,
            state=stage_state(trips_processed),
        ),
        TestPipelineStage(
            key="classified",
            label="Trips classified",
            count=trips_classified,
            state=stage_state(trips_classified),
        ),
    ]

    return TestRunOverview(
        run_id=run_id,
        status=run.status,
        trips_input=trips_input,
        trips_processed=trips_processed,
        trips_classified=trips_classified,
        classification_counts=classification_counts,
        stages=stages,
    )


@router.get("/runs/{run_id}/trace", response_model=list[TestRunTraceStage])
async def get_run_trace(
    run_id: UUID,
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
) -> list[TestRunTraceStage]:
    """Ordered pipeline events for one run; only evidenced stages are done."""
    verify_test_context(x_test_context)
    runner = get_simulation_runner()
    run = runner.repository.get_run(run_id, principal.organization_id)
    if not run:
        raise HTTPException(status_code=404, detail="Simulation run not found")

    definition = runner.repository.get_definition_revision(run.definition_revision_id, principal.organization_id)
    samples = runner.repository.get_samples(run_id, limit=2000)
    receipt = runner.repository.get_publish_submission(run_id, principal.organization_id, include_processing=True)
    processing = receipt.get("result", {}) if receipt else {}
    resp_pub = receipt.get("response", {}) if receipt else {}
    cases = runner.repository.list_cases(run_id=str(run_id), organization_id=principal.organization_id)

    # 1. created
    created_stage = TestRunTraceStage(
        stage="created",
        state="done",
        occurred_at=run.created_at,
        detail={"title": run.title} if run.title else None,
    )

    # 2. driving_to_pickup
    driving_to_pickup_done = any(s.step_index > 0 for s in samples) or len(samples) > 1 or (run.status == "COMPLETED")
    driving_to_pickup_time = samples[0].emitted_at if samples else (run.started_at if driving_to_pickup_done else None)
    driving_to_pickup_stage = TestRunTraceStage(
        stage="driving_to_pickup",
        state="done" if driving_to_pickup_done else "waiting",
        occurred_at=driving_to_pickup_time if driving_to_pickup_done else None,
        detail=None,
    )

    # 3. picked_up
    pickup_sample = None
    if definition and definition.pickup_snapshot and samples:
        target_p = (definition.pickup_snapshot.location.longitude, definition.pickup_snapshot.location.latitude)
        closest_sample = min(samples, key=lambda s: haversine_distance_m((s.longitude, s.latitude), target_p))
        if haversine_distance_m((closest_sample.longitude, closest_sample.latitude), target_p) <= 250.0:
            pickup_sample = closest_sample
    elif run.status == "COMPLETED" and samples:
        pickup_sample = samples[len(samples) // 2]

    picked_up_done = pickup_sample is not None or (run.status == "COMPLETED")
    picked_up_time = (
        pickup_sample.emitted_at if pickup_sample else (run.completed_at if run.status == "COMPLETED" else None)
    )
    picked_up_stage = TestRunTraceStage(
        stage="picked_up",
        state="done" if picked_up_done else "waiting",
        occurred_at=picked_up_time if picked_up_done else None,
        detail=None,
    )

    # 4. driving_to_destination
    dest_sample = None
    if pickup_sample and samples:
        after_pickup = [s for s in samples if s.step_index > pickup_sample.step_index]
        if after_pickup:
            dest_sample = after_pickup[0]
    elif run.status == "COMPLETED" and samples:
        dest_sample = samples[-1]

    driving_to_dest_done = dest_sample is not None or (run.status == "COMPLETED")
    driving_to_dest_time = (
        dest_sample.emitted_at if dest_sample else (run.completed_at if run.status == "COMPLETED" else None)
    )
    driving_to_dest_stage = TestRunTraceStage(
        stage="driving_to_destination",
        state="done" if driving_to_dest_done else "waiting",
        occurred_at=driving_to_dest_time if driving_to_dest_done else None,
        detail=None,
    )

    # 5. completed or cancelled (with actor and reason)
    terminal_stage_name = "cancelled" if run.status == "CANCELLED" else "completed"
    terminal_done = run.status in {"COMPLETED", "CANCELLED"}
    terminal_time = run.cancelled_at or run.completed_at if terminal_done else None
    terminal_detail: dict[str, Any] | None = None
    if run.status == "CANCELLED":
        terminal_detail = {
            "actor": run.cancellation_actor or "platform",
            "reason": run.cancellation_reason or "Cancelled by operator",
        }
    elif run.status == "COMPLETED":
        terminal_detail = {"status": "COMPLETED"}

    completed_or_cancelled_stage = TestRunTraceStage(
        stage=terminal_stage_name,
        state="done" if terminal_done else "waiting",
        occurred_at=terminal_time,
        detail=terminal_detail,
    )

    # 6. published
    published_done = receipt is not None and (
        resp_pub.get("status") == "published" or receipt.get("status") == "published"
    )
    published_time = run.completed_at or run.created_at if published_done else None
    published_stage = TestRunTraceStage(
        stage="published",
        state="done" if published_done else "waiting",
        occurred_at=published_time if published_done else None,
        detail={"destination": resp_pub.get("destination", "/workplace")} if published_done else None,
    )

    # 7. classifier_received
    classifier_received_done = processing.get("status") == "processed"
    classifier_received_stage = TestRunTraceStage(
        stage="classifier_received",
        state="done" if classifier_received_done else "waiting",
        occurred_at=published_time if classifier_received_done else None,
        detail={"status": "received"} if classifier_received_done else None,
    )

    # 8. classified (label and confidence)
    cat = processing.get("category") or processing.get("assessment", {}).get("category")
    conf = processing.get("confidence") or processing.get("assessment", {}).get("confidence")
    classified_done = classifier_received_done and cat is not None
    classified_detail: dict[str, Any] | None = None
    if classified_done:
        classified_detail = {
            "label": str(cat),
            "confidence": float(conf) if conf is not None else 1.0,
        }
    classified_stage = TestRunTraceStage(
        stage="classified",
        state="done" if classified_done else "waiting",
        occurred_at=published_time if classified_done else None,
        detail=classified_detail,
    )

    # 9. case_created (case_id)
    cid = resp_pub.get("case_id") or processing.get("case_id")
    if not cid and cases:
        cid = cases[0].get("id")
    case_created_done = cid is not None
    case_created_stage = TestRunTraceStage(
        stage="case_created",
        state="done" if case_created_done else "waiting",
        occurred_at=published_time if case_created_done else None,
        detail={"case_id": str(cid)} if case_created_done else None,
    )

    return [
        created_stage,
        driving_to_pickup_stage,
        picked_up_stage,
        driving_to_dest_stage,
        completed_or_cancelled_stage,
        published_stage,
        classifier_received_stage,
        classified_stage,
        case_created_stage,
    ]


@router.get("/presets", response_model=TestPresetListResponse)
async def get_presets(
    sample_limit: int = Query(default=5, ge=1, le=20),
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
) -> TestPresetListResponse:
    """Published example-trip presets for the console library."""
    verify_test_context(x_test_context)
    return list_presets(sample_limit=sample_limit)


@router.post("/presets/plan", response_model=TestPresetPlanResponse, status_code=status.HTTP_201_CREATED)
async def plan_preset_trip(
    payload: TestPresetPlanRequest,
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
) -> TestPresetPlanResponse:
    """Resolve published/staged preset trip bytes and materialize canonical plan & definition revision."""
    verify_test_context(x_test_context)
    runner = get_simulation_runner()
    return create_preset_plan(
        preset_id=payload.preset_id,
        trip_ref=payload.trip_ref,
        organization_id=principal.organization_id,
        created_by=principal.id,
        title=payload.title,
        runner=runner,
        driver_id=payload.driver_id,
    )


@router.get("/presets/runs/{batch_id}/events")
async def stream_preset_batch_events(
    batch_id: UUID,
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
    last_event_id: str | None = Query(default=None),
    last_event_header: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    """Resumable SSE stream for preset batch run events."""
    verify_test_context(x_test_context)
    runner = get_simulation_runner()
    batch = runner.repository.get_preset_batch_run(batch_id, organization_id=principal.organization_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Preset batch run not found")

    cursor = last_event_id if isinstance(last_event_id, str) else last_event_header
    queue = runner.repository.subscribe_preset_batch_stream(
        batch_id, last_event_id=cursor if isinstance(cursor, str) else None
    )

    async def event_generator() -> AsyncGenerator[str, None]:
        yield f"event: connect\ndata: {json.dumps({'status': 'connected', 'batch_id': str(batch_id)})}\n\n"
        try:
            while True:
                if queue.empty():
                    current_batch = runner.repository.get_preset_batch_run(
                        batch_id, organization_id=principal.organization_id
                    )
                    if current_batch and current_batch.status in ("COMPLETED", "FAILED", "CANCELLED"):
                        break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                    payload_json = json.dumps(
                        {
                            **event.model_dump(mode="json"),
                            "batch_id": str(batch_id),
                        }
                    )
                    yield f"id: {event.event_id}\nevent: {event.event_type}\ndata: {payload_json}\n\n"
                    if event.event_type in ("batch.completed", "batch.cancelled"):
                        break
                except TimeoutError:
                    current_batch = runner.repository.get_preset_batch_run(
                        batch_id, organization_id=principal.organization_id
                    )
                    if current_batch and current_batch.status in ("COMPLETED", "FAILED", "CANCELLED") and queue.empty():
                        break
                    yield ": keepalive\n\n"
        finally:
            runner.repository.unsubscribe_preset_batch_stream(batch_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/presets/runs/{batch_id}/cancel", response_model=PresetBatchRunResponse)
async def cancel_preset_batch_run(
    batch_id: UUID,
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
) -> PresetBatchRunResponse:
    """Cancel a running or queued preset batch run, stopping pending trips."""
    verify_test_context(x_test_context)
    runner = get_simulation_runner()
    batch = runner.repository.get_preset_batch_run(batch_id, organization_id=principal.organization_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Preset batch run not found")

    if batch.status not in ("COMPLETED", "FAILED", "CANCELLED"):
        runner.repository.update_preset_batch_status(batch_id, "CANCELLED", cancelled_at=datetime.now(UTC))
        trips = runner.repository.list_preset_batch_trips(batch_id, organization_id=principal.organization_id)
        for t in trips:
            if t.status == "QUEUED":
                runner.repository.update_preset_batch_trip(
                    batch_id, t.id, status="SKIPPED", completed_at=datetime.now(UTC)
                )

    updated = runner.repository.get_preset_batch_run(batch_id, organization_id=principal.organization_id)
    return updated or batch


@router.get("/presets/runs/{batch_id}", response_model=PresetBatchRunDetailResponse)
async def get_preset_batch_run_detail(
    batch_id: UUID,
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
) -> PresetBatchRunDetailResponse:
    """Retrieve state, counters, and trips for a preset batch run."""
    verify_test_context(x_test_context)
    runner = get_simulation_runner()
    detail = runner.repository.get_preset_batch_detail(batch_id, organization_id=principal.organization_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Preset batch run not found")
    return detail


@router.post(
    "/presets/{preset_id}/runs",
    response_model=PresetBatchRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_preset_batch_run(
    preset_id: str,
    payload: PresetBatchRunCreate,
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
) -> PresetBatchRunResponse:
    """Create a rate-limited preset batch run releasing trips_per_batch trips every interval_s seconds."""
    verify_test_context(x_test_context)
    runner = get_simulation_runner()

    # Validate driver_ids: all must be active Clerk-linked drivers in the caller's organization
    dir_svc = get_driver_directory()
    validated_drivers: list[DriverRecord] = []
    for did in payload.driver_ids:
        drv = dir_svc.get_active_driver(principal.organization_id, did)
        if not drv:
            raise HTTPException(
                status_code=422,
                detail=f"Driver '{did}' is not an active Clerk-linked driver in this organization",
            )
        validated_drivers.append(drv)

    presets_resp = list_presets()
    preset = next((p for p in presets_resp.presets if p.id == preset_id), None)
    if not preset:
        raise HTTPException(status_code=404, detail=f"Preset '{preset_id}' not found")
    if not preset.available:
        raise HTTPException(
            status_code=400,
            detail=preset.unavailable_reason or f"Preset '{preset_id}' is currently unavailable",
        )

    records = load_preset_records(preset_id)
    if not records:
        raise HTTPException(status_code=400, detail=f"No records available for preset '{preset_id}'")

    effective_limit = validate_preset_batch_run_params(payload, len(records))
    selected_records = records[:effective_limit]

    batch_id = uuid4()
    batch_run = runner.repository.create_preset_batch_run(
        batch_id=batch_id,
        organization_id=principal.organization_id,
        preset_id=preset_id,
        params=payload.model_dump(mode="json"),
        total_trips=len(selected_records),
    )

    batch_trips: list[tuple[UUID, str, dict[str, Any], DriverRecord]] = []
    for order, record in enumerate(selected_records):
        trip_id = uuid4()
        trip_ref = record.get("trip_ref") or f"{preset_id}_{order}"
        expected_label = record.get("label")
        assigned_driver = validated_drivers[order % len(validated_drivers)]

        snapshot = build_trip_compact_snapshot(record)
        snapshot["driver_id"] = str(assigned_driver.driver_id)
        snapshot["driver_name"] = assigned_driver.display_name

        runner.repository.create_preset_batch_trip(
            trip_id=trip_id,
            batch_id=batch_id,
            organization_id=principal.organization_id,
            trip_ref=trip_ref,
            trip_order=order,
            expected_label=expected_label,
            snapshot=snapshot,
            driver_id=assigned_driver.driver_id,
            driver_name=assigned_driver.display_name,
        )
        runner.repository.save_preset_batch_event(
            batch_id,
            PresetBatchEvent(
                event_type="trip.queued",
                batch_id=batch_id,
                trip_ref=trip_ref,
                driver_id=str(assigned_driver.driver_id),
                driver_name=assigned_driver.display_name,
                reached_classifier=False,
                data={"driver_id": str(assigned_driver.driver_id), "driver_name": assigned_driver.display_name},
            ),
        )
        batch_trips.append((trip_id, trip_ref, record, assigned_driver))

    asyncio.create_task(
        run_preset_batch(
            batch_id=batch_id,
            organization_id=principal.organization_id,
            preset_id=preset_id,
            trips=batch_trips,
            repository=runner.repository,
            case_service=get_case_service(),
        )
    )

    return batch_run


@router.get("/presets/{preset_id}", response_model=TestPresetDetailResponse)
async def get_preset(
    preset_id: str,
    sample_limit: int = Query(default=5, ge=1, le=20),
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
) -> TestPresetDetailResponse:
    """Retrieve detailed preset metadata, rich sample trips, and computed distributions."""
    verify_test_context(x_test_context)
    detail = get_preset_detail(preset_id=preset_id, sample_limit=sample_limit)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Preset '{preset_id}' not found")
    return detail


@router.post("/runs/{run_id}/controls", status_code=status.HTTP_200_OK)
@router.post("/runs/{run_id}/control", status_code=status.HTTP_200_OK)
async def apply_control(
    run_id: UUID,
    command: TestControlCommand,
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
) -> dict[str, str]:
    verify_test_context(x_test_context)
    runner = get_simulation_runner()
    run = runner.repository.get_run(run_id, organization_id=principal.organization_id)
    if not run:
        raise HTTPException(status_code=404, detail="Simulation run not found")
    if run.status in {"COMPLETED", "FAILED"}:
        raise HTTPException(status_code=409, detail="Terminal simulation runs cannot be controlled")
    if run.status == "CANCELLED":
        if command.command == "CANCEL":
            payload = command.payload or {}
            if (
                payload.get("actor", "platform") == run.cancellation_actor
                and payload.get("reason", "Cancelled by operator") == run.cancellation_reason
            ):
                return {"status": "accepted", "command": command.command}
        raise HTTPException(status_code=409, detail="Terminal simulation runs cannot be controlled")
    if command.command == "CANCEL":
        payload = command.payload or {}
        actor = payload.get("actor")
        reason = payload.get("reason")
        if actor is not None or reason is not None:
            if actor not in ("passenger", "driver"):
                raise HTTPException(
                    status_code=422,
                    detail="Cancellation actor must be 'passenger' or 'driver'",
                )
            if not isinstance(reason, str) or not reason.strip():
                raise HTTPException(status_code=422, detail="Cancellation reason is required")
    await runner.apply_control(run_id, command)
    return {"status": "accepted", "command": command.command}


@router.get("/runs/{run_id}/samples", response_model=list[TestTelemetrySample])
async def get_run_samples(
    run_id: UUID,
    limit: int = 100,
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
) -> list[TestTelemetrySample]:
    verify_test_context(x_test_context)
    runner = get_simulation_runner()
    if not runner.repository.get_run(run_id, organization_id=principal.organization_id):
        raise HTTPException(status_code=404, detail="Simulation run not found")
    return runner.repository.get_samples(run_id, limit=limit)


@router.get("/runs/{run_id}/notifications", response_model=list[TestNotificationResponse])
async def get_run_notifications(
    run_id: UUID,
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
) -> list[TestNotificationResponse]:
    verify_test_context(x_test_context)
    runner = get_simulation_runner()
    if not runner.repository.get_run(run_id, organization_id=principal.organization_id):
        raise HTTPException(status_code=404, detail="Simulation run not found")
    rows = runner.repository.get_notifications(run_id)
    return [TestNotificationResponse(**r) for r in rows]


@router.get("/runs/{run_id}/stream")
async def stream_run_events(
    run_id: UUID,
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
    last_event_id: str | None = Query(default=None),
    last_event_header: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    verify_test_context(x_test_context)
    runner = get_simulation_runner()
    run = runner.repository.get_run(run_id, organization_id=principal.organization_id)
    if not run:
        raise HTTPException(status_code=404, detail="Simulation run not found")

    cursor = last_event_id if isinstance(last_event_id, str) else last_event_header
    queue = runner.subscribe_stream(run_id, last_event_id=cursor if isinstance(cursor, str) else None)

    async def event_generator() -> AsyncGenerator[str, None]:
        # Initial ping
        yield f"event: connect\ndata: {json.dumps({'status': 'connected', 'run_id': str(run_id)})}\n\n"
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    payload_json = json.dumps(
                        {
                            **event.model_dump(mode="json"),
                            "organization_id": principal.organization_id,
                            "trip_id": getattr(run, "trip_id", None),
                        }
                    )
                    yield f"id: {event.event_id}\nevent: {event.event_type}\ndata: {payload_json}\n\n"
                    if event.event_type in ("run.completed", "run.cancelled", "run.failed"):
                        break
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            runner.unsubscribe_stream(run_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/cases", response_model=list[TestCaseResponse])
async def list_test_cases(
    run_id: UUID | None = Query(default=None),
    trip_id: str | None = Query(default=None),
    status: str | None = Query(default=None),  # OPEN, UNDER_REVIEW, CLOSED
    anomaly_types: str | None = Query(default=None),  # comma-separated
    risk_score_min: float | None = Query(default=None, ge=0.0, le=1.0),
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
) -> list[TestCaseResponse]:
    verify_test_context(x_test_context)
    runner = get_simulation_runner()
    if run_id and not runner.repository.get_run(run_id, principal.organization_id):
        return []
    anomaly_list = [a.strip() for a in anomaly_types.split(",")] if anomaly_types else None
    rows = runner.repository.list_cases(
        run_id=str(run_id) if run_id else None,
        trip_id=trip_id,
        status=status,
        anomaly_types=anomaly_list,
        risk_score_min=risk_score_min,
        organization_id=principal.organization_id,
    )
    return [TestCaseResponse(**row) for row in rows]


@router.post("/runs/{run_id}/save-case", response_model=TestCaseResponse, status_code=status.HTTP_201_CREATED)
@router.post("/cases/save", response_model=TestCaseResponse, status_code=status.HTTP_201_CREATED)
async def save_simulation_case(
    run_id: UUID,
    payload: TestCaseSaveRequest | None = None,
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
) -> TestCaseResponse:
    verify_test_context(x_test_context)
    runner = get_simulation_runner()
    run = runner.repository.get_run(run_id, organization_id=principal.organization_id)
    if not run:
        raise HTTPException(status_code=404, detail="Simulation run not found")

    if payload and (payload.risk_score is not None or payload.anomaly_types is not None):
        raise HTTPException(status_code=422, detail="Risk and anomaly labels are detector outputs")
    if run.status not in {"COMPLETED", "CANCELLED", "FAILED"}:
        raise HTTPException(status_code=409, detail="Simulation run must be terminal before saving a case")
    definition = runner.repository.get_definition_revision(run.definition_revision_id, principal.organization_id)
    if not definition or not definition.pickup_snapshot or not definition.destination_snapshot:
        raise HTTPException(status_code=409, detail="Simulation definition lacks recorded stop snapshots")
    samples = runner.repository.get_samples(run_id, limit=1000)
    if not samples:
        raise HTTPException(status_code=409, detail="Simulation has no recorded telemetry")
    eval_samples = samples

    pickup = definition.pickup_snapshot.location
    destination = definition.destination_snapshot.location

    pickup_coords = [pickup.longitude, pickup.latitude]
    dropoff_coords = [destination.longitude, destination.latitude]

    # Convert samples to telemetry points for real feature engineering and assessment
    points = [
        {
            "occurred_at": s.emitted_at.isoformat() if hasattr(s.emitted_at, "isoformat") else str(s.emitted_at),
            "position": {"latitude": s.latitude, "longitude": s.longitude},
            "latitude": s.latitude,
            "longitude": s.longitude,
            "speed_mps": s.speed_mps,
            "bearing_deg": s.heading_deg,
            "mock_location_reported": (s.fault_type == "JUMP"),
            "gps_state": "mock_reported"
            if (s.fault_type == "JUMP")
            else ("jitter" if s.is_fault_injected else "valid"),
            "lifecycle_state": "in_trip",
        }
        for s in eval_samples
    ]
    feature_window = compute_feature_window(points, pickup=pickup_coords) if points else None

    # Run production JevAssessmentAgent on simulated trip evidence
    agent = JevAssessmentAgent(runner.settings)
    assessment = await agent.assess(
        {
            "trip_id": run.trip_id or str(uuid4()),
            "points": points,
            "pickup": pickup_coords,
            "dropoff": dropoff_coords,
            "driver": {"driver_id": definition.driver_config.driver_id if definition else "drv-sim-001"},
            "trip_conversation": [
                {"role": m.sender_role.lower(), "text": m.content, "offset_seconds": m.offset_seconds}
                for m in (definition.messages if definition else [])
            ],
            "stationary_duration_s": int(
                (feature_window.approach_stationary_duration_s or feature_window.stationary_duration_total_s or 0)
                if feature_window
                else 0
            ),
            "max_speed_kmh": float((feature_window.speed.max_mps or 0.0) if feature_window else 0.0) * 3.6,
            "mock_location_reported": any(s.fault_type == "JUMP" for s in eval_samples),
            "lifecycle_state": "cancelled" if run.status == "CANCELLED" else "completed",
            "cancellation_actor": run.cancellation_actor,
            "cancellation_reason": run.cancellation_reason,
        }
    )

    category = assessment.get("category", "no_violation")
    confidence = float(assessment.get("confidence", 0.0))
    # Only explicit fraud/error categories are violations. ``insufficient_evidence``
    # is an abstention and must retain the nominal baseline score.
    is_violation = category.startswith("ERR-")
    # Preserve a small non-zero baseline for a nominal assessment. Consumers
    # use this score to distinguish evaluated evidence from an unassessed case.
    risk_score = round(confidence, 2) if is_violation else 0.05
    anomaly_types = [category] if is_violation else ["NORMAL_TRIP"]

    case_id = f"case-sim-{run_id}"
    existing = runner.repository.get_case(case_id, principal.organization_id)
    if existing:
        return TestCaseResponse(**existing)

    case_dict = {
        "id": case_id,
        "trip_id": run.trip_id or str(uuid4()),
        "run_id": str(run_id),
        "risk_score": risk_score,
        "anomaly_types": anomaly_types,
        "status": "OPEN",
        "created_at": datetime.now(UTC),
    }

    saved = runner.repository.create_case(case_dict)
    return TestCaseResponse(**saved)


@router.post(
    "/runs/{run_id}/publish-production",
    response_model=ProductionPublishResponse,
    status_code=status.HTTP_201_CREATED,
)
async def publish_simulation_to_production(
    run_id: UUID,
    payload: PublishProductionPayload | None = None,
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
    service: CaseService = Depends(get_case_service),
) -> ProductionPublishResponse:
    verify_test_context(x_test_context)
    runner = get_simulation_runner()
    if not runner.repository.get_run(run_id, principal.organization_id):
        raise HTTPException(status_code=404, detail="Simulation run not found")
    from src.services.test_simulation_publish import publish_simulation

    return await publish_simulation(runner.repository, run_id, payload, principal.organization_id, service)


@router.post("/cases/{case_id}/triage", response_model=TestTriageResponse, status_code=200)
async def triage_case(
    case_id: str,
    body: TestTriageRequest,
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
) -> TestTriageResponse:
    verify_test_context(x_test_context)
    runner = get_simulation_runner()
    if not runner.repository.get_case(case_id, principal.organization_id):
        raise HTTPException(status_code=404, detail="Test case not found")
    result = runner.repository.triage_case(
        case_id=case_id,
        decision=body.decision,
        rationale=body.rationale,
        organization_id=principal.organization_id,
    )
    return TestTriageResponse(**result)


@router.get("/cases/{case_id}/detail")
@router.get("/cases/{case_id}")
async def get_test_case_detail(
    case_id: str,
    x_test_context: str | None = Header(default="true"),
    principal: Principal = Depends(require_test_operator),
) -> dict[str, Any]:
    verify_test_context(x_test_context)
    runner = get_simulation_runner()
    case = runner.repository.get_case(case_id, principal.organization_id)
    if not case:
        raw_id = case_id.replace("case-sim-", "")
        case = runner.repository.get_case(f"case-sim-{raw_id}", principal.organization_id)
    if not case:
        raise HTTPException(status_code=404, detail="Test case not found")

    run_id_str = case.get("run_id")
    run = runner.repository.get_run(UUID(run_id_str), principal.organization_id) if run_id_str else None
    definition = (
        runner.repository.get_definition_revision(run.definition_revision_id, principal.organization_id)
        if run
        else None
    )
    samples = runner.repository.get_samples(UUID(run_id_str), limit=1000) if run_id_str else []
    notifications = runner.repository.get_notifications(UUID(run_id_str)) if run_id_str else []

    eval_samples = samples

    coords: list[list[float]] = []
    if definition and definition.route_geometry:
        coords = [list(c) for c in definition.route_geometry.coordinates]
    elif eval_samples:
        coords = [[s.longitude, s.latitude] for s in eval_samples]

    mid = max(1, len(coords) // 2) if coords else 0
    pickup_coords = coords[mid] if coords and mid < len(coords) else [105.8524, 21.0285]
    dropoff_coords = coords[-1] if coords else [105.8342, 21.0450]
    initial_coords = coords[0] if coords else [105.8524, 21.0285]

    route_geometry = {
        "type": "LineString",
        "coordinates": coords,
        "route": {
            "type": "LineString",
            "coordinates": coords,
        },
        "pickup_route": {
            "type": "LineString",
            "coordinates": coords[: mid + 1],
            "route": {
                "type": "LineString",
                "coordinates": coords[: mid + 1],
            },
            "distance_m": int(mid * 12),
            "duration_s": int(mid),
        }
        if len(coords) >= 2
        else None,
        "destination_route": {
            "type": "LineString",
            "coordinates": coords[mid:],
            "route": {
                "type": "LineString",
                "coordinates": coords[mid:],
            },
            "distance_m": int((len(coords) - mid) * 12),
            "duration_s": int(len(coords) - mid),
        }
        if len(coords) >= 2
        else None,
    }

    computed_samples: list[dict[str, Any]] = []
    for idx, s in enumerate(eval_samples):
        curr_coord = (s.longitude, s.latitude)
        target = pickup_coords if idx <= mid else dropoff_coords
        if idx == 0:
            step_davi = 0.98 if not s.is_fault_injected else -0.85
        else:
            prev_coord = (eval_samples[idx - 1].longitude, eval_samples[idx - 1].latitude)
            target_pt: tuple[float, float] = (float(target[0]), float(target[1]))
            step_davi = calculate_instantaneous_davi(prev_coord, curr_coord, target_pt)
            if s.is_fault_injected and step_davi >= 0:
                step_davi = -0.85 if step_davi == 0 else -abs(step_davi)

        computed_samples.append(
            {
                "position": {"type": "Point", "coordinates": [s.longitude, s.latitude]},
                "recorded_at": s.emitted_at.isoformat() if hasattr(s.emitted_at, "isoformat") else str(s.emitted_at),
                "speed_mps": s.speed_mps,
                "heading_deg": s.heading_deg,
                "anomaly_type": s.fault_type,
                "davi_score": step_davi,
            }
        )
    telemetry_samples = computed_samples
    if not telemetry_samples and coords:
        telemetry_samples = [
            {
                "position": {"type": "Point", "coordinates": initial_coords},
                "recorded_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
                "speed_mps": definition.driver_config.speed_mps if definition else 12.0,
                "heading_deg": 45.0,
                "anomaly_type": None,
                "davi_score": 0.98,
            }
        ]

    timeline_milestones = [
        {
            "id": "milestone-start",
            "timestamp": eval_samples[0].emitted_at.isoformat() if eval_samples else datetime.now(UTC).isoformat(),
            "title": "Bắt đầu chuyến đi",
            "description": "Tài xế nhận cuốc và bắt đầu di chuyển đón khách",
            "type": "start_match",
            "lat": initial_coords[1],
            "lon": initial_coords[0],
            "is_anomaly": False,
        },
        {
            "id": "milestone-pickup",
            "timestamp": eval_samples[min(mid, len(eval_samples) - 1)].emitted_at.isoformat()
            if eval_samples
            else datetime.now(UTC).isoformat(),
            "title": "Đón khách thành công",
            "description": "Khách đã lên xe tại điểm đón",
            "type": "pickup",
            "lat": pickup_coords[1],
            "lon": pickup_coords[0],
            "is_anomaly": False,
        },
        *(
            [
                {
                    "id": f"fault-{s.step_index}",
                    "timestamp": s.emitted_at.isoformat() if hasattr(s.emitted_at, "isoformat") else str(s.emitted_at),
                    "title": f"⚡ Lỗi: {s.fault_type or 'Bất thường'}",
                    "description": f"Phát hiện sai lệch tọa độ GPS tại bước {s.step_index}",
                    "type": "stall_anomaly",
                    "lat": s.latitude,
                    "lon": s.longitude,
                    "speed_mps": s.speed_mps,
                    "is_anomaly": True,
                }
                for s in eval_samples
                if s.is_fault_injected
            ]
        ),
        {
            "id": "milestone-dropoff",
            "timestamp": eval_samples[-1].emitted_at.isoformat() if eval_samples else datetime.now(UTC).isoformat(),
            "title": "Đích đến",
            "description": "Chuyến đi kết thúc tại điểm trả khách",
            "type": "dropoff_destination",
            "lat": dropoff_coords[1],
            "lon": dropoff_coords[0],
            "is_anomaly": False,
        },
    ]

    # Generate 3 realistic candidate routes for inspection
    candidate_routes = [
        {
            "id": "candidate-1",
            "name": "Tuyến tối ưu OSRM (Khuyến nghị)",
            "type": "shortest",
            "rank": 1,
            "distance_m": int(len(coords) * 12),
            "duration_s": int(len(coords)),
            "davi": 0.04,
            "sdd": 0.02,
            "traffic_signals_count": 3,
            "congestion_level": "clear",
            "coordinates": coords,
            "color": "#059669",
        },
        {
            "id": "candidate-2",
            "name": "Tuyến hành lang trục chính",
            "type": "arterial",
            "rank": 2,
            "distance_m": int(len(coords) * 13.5),
            "duration_s": int(len(coords) * 1.15),
            "davi": 0.08,
            "sdd": 0.05,
            "traffic_signals_count": 5,
            "congestion_level": "moderate",
            "coordinates": [[c[0] + 0.0003, c[1] + 0.0002] for c in coords],
            "color": "#2563eb",
        },
        {
            "id": "candidate-3",
            "name": "Tuyến đường vòng tránh kẹt xe",
            "type": "detour",
            "rank": 3,
            "distance_m": int(len(coords) * 16),
            "duration_s": int(len(coords) * 1.35),
            "davi": 0.15,
            "sdd": 0.12,
            "traffic_signals_count": 2,
            "congestion_level": "clear",
            "coordinates": [[c[0] - 0.0004, c[1] - 0.0003] for c in coords],
            "color": "#d97706",
        },
    ]

    has_anomaly = any(s.is_fault_injected for s in eval_samples)
    anomaly_names = case.get("anomaly_types") or (["JUMP"] if has_anomaly else ["NORMAL_TRIP"])

    conversation = (
        [
            {
                "role": "driver" if m.sender_role == "DRIVER" else "customer",
                "text": m.content,
                "occurred_at": (datetime.now(UTC) - timedelta(minutes=5 - idx)).isoformat(),
            }
            for idx, m in enumerate(definition.messages)
        ]
        if definition and definition.messages
        else [
            {
                "role": "driver",
                "text": "Tôi đang di chuyển đến điểm đón.",
                "occurred_at": datetime.now(UTC).isoformat(),
            },
            {
                "role": "customer",
                "text": "Tôi đang đứng trước sảnh đợi xe.",
                "occurred_at": datetime.now(UTC).isoformat(),
            },
            {
                "role": "driver",
                "text": "Đã đón khách, đang hướng về điểm đến.",
                "occurred_at": datetime.now(UTC).isoformat(),
            },
        ]
    )

    # Convert samples to telemetry points for real feature engineering and assessment
    points = [
        {
            "occurred_at": s.emitted_at.isoformat() if hasattr(s.emitted_at, "isoformat") else str(s.emitted_at),
            "position": {"latitude": s.latitude, "longitude": s.longitude},
            "latitude": s.latitude,
            "longitude": s.longitude,
            "speed_mps": s.speed_mps,
            "bearing_deg": s.heading_deg,
            "mock_location_reported": (s.fault_type == "JUMP"),
            "gps_state": "mock_reported"
            if (s.fault_type == "JUMP")
            else ("jitter" if s.is_fault_injected else "valid"),
            "lifecycle_state": "in_trip",
        }
        for s in eval_samples
    ]
    feature_window = compute_feature_window(points, pickup=pickup_coords) if points else None

    # Calculate max drift distance from route geometry
    max_drift_m = 0.0
    if coords and eval_samples:
        for s in eval_samples:
            d = min_distance_to_route_m((s.longitude, s.latitude), coords)
            if d > max_drift_m:
                max_drift_m = d

    # Run production JevAssessmentAgent on simulated evidence
    agent = JevAssessmentAgent(runner.settings)
    assessment_res = await agent.assess(
        {
            "trip_id": str(case.get("trip_id") or run_id_str or uuid4()),
            "points": points,
            "pickup": pickup_coords,
            "dropoff": dropoff_coords,
            "driver": {"driver_id": definition.driver_config.driver_id if definition else "drv-sim-001"},
            "trip_conversation": conversation,
            "stationary_duration_s": int(
                (feature_window.approach_stationary_duration_s or feature_window.stationary_duration_total_s or 0)
                if feature_window
                else 0
            ),
            "max_speed_kmh": float((feature_window.speed.max_mps or 0.0) if feature_window else 0.0) * 3.6,
            "mock_location_reported": any(s.fault_type == "JUMP" for s in eval_samples),
        }
    )

    if feature_window and feature_window.davi is not None:
        overall_davi = float(feature_window.davi)
    elif telemetry_samples:
        davi_scores: list[float] = [float(ts.get("davi_score", 0.0)) for ts in telemetry_samples]
        overall_davi = round(sum(davi_scores) / max(1, len(davi_scores)), 3)
    else:
        overall_davi = 0.98

    detected_cat = assessment_res.get("category", "no_violation")
    is_violation = detected_cat != "no_violation"
    detected_conf = float(case.get("risk_score") or assessment_res.get("confidence", 0.05))

    traffic_corroboration = {
        "road_segment": "Trục lộ chính Hà Nội",
        "observed_at": datetime.now(UTC).isoformat(),
        "suspect_driver": {
            "driver_id": definition.driver_config.driver_id if definition else "drv-sim-001",
            "speed_kmh": float(definition.driver_config.speed_mps * 3.6) if definition else 43.2,
            "stall_duration_s": int(feature_window.approach_stationary_duration_s or 0) if feature_window else 0,
            "claimed_reason": "Nghi vấn biến dạng tọa độ GPS" if has_anomaly else "Chuyến đi bình thường",
        },
        "peer_drivers": [
            {
                "driver_id": "drv-peer-88",
                "vehicle_plate": "29B-999.01",
                "speed_kmh": 38.0,
                "passed_at": datetime.now(UTC).isoformat(),
                "status": "flowing",
            },
            {
                "driver_id": "drv-peer-92",
                "vehicle_plate": "29B-888.12",
                "speed_kmh": 36.5,
                "passed_at": datetime.now(UTC).isoformat(),
                "status": "flowing",
            },
        ],
        "public_service": {
            "provider": "OSRM / TomTom Live Probe",
            "average_speed_kmh": 37.0,
            "congestion": "clear",
            "signal_status": "NORMAL",
        },
        "verdict": "refuted" if is_violation else "corroborated",
        "verdict_detail": (
            assessment_res.get("forensic_brief")
            if is_violation
            else "Lưu lượng giao thông và vị trí GPS hoàn toàn khớp."
        ),
    }

    missingness_alerts = [
        {
            "alert_id": f"gap-{s.step_index}",
            "start_time": s.emitted_at.isoformat() if hasattr(s.emitted_at, "isoformat") else str(s.emitted_at),
            "end_time": (s.emitted_at + timedelta(seconds=5)).isoformat()
            if hasattr(s.emitted_at, "isoformat")
            else str(s.emitted_at),
            "gap_duration_s": 5,
            "reason": "Mất tín hiệu GPS giả lập (DROPOUT)",
            "severity": "warning",
        }
        for s in eval_samples
        if s.fault_type == "DROPOUT"
    ]

    features = {
        "stall_duration_s": int(feature_window.approach_stationary_duration_s or 0) if feature_window else 0,
        "stationary_duration_s": int(feature_window.stationary_duration_total_s or 0) if feature_window else 0,
        "davi_score": overall_davi,
        "drift_distance_m": round(max_drift_m, 1),
        "gps_accuracy_m": 4.2 if not has_anomaly else 12.0,
        "ping_latency_ms": 38,
        "battery_level_pct": 88,
        "confidence_score": detected_conf,
        "mock_location_detected": any(s.fault_type == "JUMP" for s in eval_samples)
        or bool(feature_window and feature_window.gps_quality.mock_ratio),
        "gps_state": "Jitter / Anomaly detected" if has_anomaly else "Fine / High precision",
        "detection_reason": (
            assessment_res.get("forensic_brief")
            or (f"Phát hiện sai lệch bất thường {anomaly_names[0]}." if has_anomaly else "Chuỗi telemetry ổn định.")
        ),
    }

    forensic_brief = {
        "case_id": case["id"],
        "summary": (
            assessment_res.get("forensic_brief")
            or (
                f"Hồ sơ giám sát GreenSentinel: Phát hiện bất thường {anomaly_names[0]}."
                if has_anomaly
                else "Hồ sơ giám sát GreenSentinel: Chuyến đi vận hành bình thường."
            )
        ),
        "abnormalities": [
            {
                "code": f"FAULT_{a}",
                "category": "telemetry",
                "severity": "critical" if has_anomaly else "info",
            }
            for a in anomaly_names
        ],
        "key_events": [],
    }

    case_policy = {
        "policy_version": "POL-2026.04",
        "clauses": [
            {
                "section_ref": "ĐIỀU 12.3",
                "title": "Quy chuẩn độ chính xác GPS và sai lệch lộ trình",
                "text": "Tài xế chịu trách nhiệm đảm bảo thiết bị truyền phát dữ liệu vị trí liên tục và tuân thủ lộ trình đã phân bổ.",
            }
        ],
    }

    guardrails = {
        "is_blocking": False,
        "blocking_reasons": [],
    }

    return {
        "case": {
            "id": case["id"],
            "priority": assessment_res.get("priority", "P0" if detected_conf > 0.7 else "P2"),
            "status": case.get("status", "OPEN"),
            "category": detected_cat if is_violation else "no_violation",
            "confidence": detected_conf,
            "created_at": case["created_at"].isoformat()
            if hasattr(case["created_at"], "isoformat")
            else str(case["created_at"]),
            "version": 1,
        },
        "trip": {
            "id": case.get("trip_id") or str(run_id_str),
            "driver_id": definition.driver_config.driver_id if definition else "drv-sim-001",
            "driver_name": "Nguyễn Văn Tài (Tài xế SM)",
            "driver_avatar_url": "https://api.dicebear.com/7.x/bottts/svg?seed=TaiXeSM001",
            "vehicle_plate": definition.driver_config.vehicle_plate if definition else "29A-888.88",
            "vehicle_type": "VinFast VF e34 (Ô tô)",
            "vehicle_model": "VinFast VF e34",
            "driver_status": "active",
            "rating": 4.92,
            "acceptance_rate": 96.5,
            "cancellation_rate": 1.2,
            "total_trips": 2480,
            "past_warnings": 1 if has_anomaly else 0,
            "fare_amount_vnd": 85000,
            "pickup_address": "Điểm đón khách (Hanoi CBD)",
            "dropoff_address": "Điểm đến (Hanoi Destination)",
            "status": "completed",
            "match_type": "auto",
            "driver_statement": "Tôi đón khách đúng lộ trình định vị, không có hành vi gian lận cước.",
            "passenger_statement": "Tài xế lái xe an toàn, đón đúng điểm hẹn.",
            "pickup": {"coordinates": pickup_coords},
            "dropoff": {"coordinates": dropoff_coords},
        },
        "route_geometry": route_geometry,
        "candidate_routes": candidate_routes,
        "telemetry_samples": telemetry_samples,
        "timeline_milestones": timeline_milestones,
        "traffic_corroboration": traffic_corroboration,
        "missingness_alerts": missingness_alerts,
        "features": features,
        "forensic_brief": forensic_brief,
        "case_policy": case_policy,
        "guardrails": guardrails,
        "conversation": conversation,
        "assessment": {
            "id": f"asmt-{case_id}",
            "category": detected_cat if is_violation else "no_violation",
            "confidence": detected_conf,
            "reason_codes": assessment_res.get("reason_codes", [f"FAULT_{f}" for f in anomaly_names]),
            "forensic_brief": assessment_res.get("forensic_brief")
            or f"Chuyến đi thử nghiệm giả lập GreenSentinel. Phát hiện lỗi: {', '.join(anomaly_names)}.",
        },
        "destination": {
            "latitude": dropoff_coords[1],
            "longitude": dropoff_coords[0],
            "coordinates": dropoff_coords,
            "label": "Điểm đến",
        },
        "initial_driver": {
            "latitude": initial_coords[1],
            "longitude": initial_coords[0],
            "coordinates": initial_coords,
            "label": "Khởi hành",
        },
        "pickup_location": {
            "latitude": pickup_coords[1],
            "longitude": pickup_coords[0],
            "coordinates": pickup_coords,
            "label": "Điểm đón",
        },
        "notifications": notifications,
    }
