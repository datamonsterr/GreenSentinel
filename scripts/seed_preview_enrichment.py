#!/usr/bin/env python3
"""Deterministic enrichment script for analyst workspace preview cases (issue #366).

Populates all persisted database fields that currently show 'Unavailable' on preview demo cases:
1. Vehicle models (VinFast VF e34, VF 8, VF 9, Feliz S, Klara S)
2. Driver metrics & tenure (rating, acceptance_rate, cancellation_rate, total_trips, tenure)
3. Driver statements tailored to case categories
4. Passenger feedback statements and star ratings (1-5)
5. Direct trip fares (fare_amount_vnd) and matching VND fare quotes
6. Telemetry sensor payloads (ping_latency_ms, battery_level_pct)
7. Nominal historical trips to ground realistic 90-day violation ratios (~2.5%–6.5%)
8. Past adjudicated incidents with authentic Vietnamese rationales and outcomes on terminal cases

Supports:
- python3 scripts/seed_preview_enrichment.py --database-url <url> [--dry-run]
- Default mode is --dry-run (prints counts only, mutation requires --apply).
- 100% idempotent; re-running produces identical state without duplication.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_preview_enrichment")

NAMESPACE_SEED = uuid.UUID("018f2f4e-9999-7000-8000-000000000366")

# 30 Authentic Hanoi landmarks across 12 urban and suburban districts
HANOI_LANDMARKS: list[dict[str, Any]] = [
    {
        "name": "Hồ Gươm (Tháp Rùa)",
        "lat": 21.0285,
        "lon": 105.8542,
        "district": "Hoàn Kiếm",
        "address": "Phố Đinh Tiên Hoàng, Hoàn Kiếm, Hà Nội",
    },
    {
        "name": "Nhà hát Lớn Hà Nội",
        "lat": 21.0245,
        "lon": 105.8576,
        "district": "Hoàn Kiếm",
        "address": "Số 1 Tràng Tiền, Hoàn Kiếm, Hà Nội",
    },
    {
        "name": "Nhà thờ Lớn Hà Nội",
        "lat": 21.0307,
        "lon": 105.8495,
        "district": "Hoàn Kiếm",
        "address": "40 Nhà Chung, Hoàn Kiếm, Hà Nội",
    },
    {
        "name": "Chợ Đồng Xuân",
        "lat": 21.0381,
        "lon": 105.8497,
        "district": "Hoàn Kiếm",
        "address": "Đồng Xuân, Hoàn Kiếm, Hà Nội",
    },
    {
        "name": "Cầu Chương Dương",
        "lat": 21.0372,
        "lon": 105.8596,
        "district": "Hoàn Kiếm",
        "address": "Cầu Chương Dương, Hoàn Kiếm, Hà Nội",
    },
    {
        "name": "Văn Miếu - Quốc Tử Giám",
        "lat": 21.0293,
        "lon": 105.8361,
        "district": "Đống Đa",
        "address": "58 Quốc Tử Giám, Đống Đa, Hà Nội",
    },
    {
        "name": "Ga Hà Nội",
        "lat": 21.0244,
        "lon": 105.8412,
        "district": "Đống Đa",
        "address": "120 Lê Duẩn, Đống Đa, Hà Nội",
    },
    {
        "name": "Bệnh viện Bạch Mai",
        "lat": 21.0028,
        "lon": 105.8415,
        "district": "Đống Đa",
        "address": "78 Giải Phóng, Đống Đa, Hà Nội",
    },
    {
        "name": "Đại học Y Hà Nội",
        "lat": 21.0034,
        "lon": 105.8317,
        "district": "Đống Đa",
        "address": "1 Tôn Thất Tùng, Đống Đa, Hà Nội",
    },
    {
        "name": "Vincom Center Bà Triệu",
        "lat": 21.0116,
        "lon": 105.8498,
        "district": "Hai Bà Trưng",
        "address": "191 Bà Triệu, Hai Bà Trưng, Hà Nội",
    },
    {
        "name": "Times City Mega Mall",
        "lat": 20.9953,
        "lon": 105.8687,
        "district": "Hai Bà Trưng",
        "address": "458 Minh Khai, Hai Bà Trưng, Hà Nội",
    },
    {
        "name": "Công viên Thống Nhất",
        "lat": 21.0152,
        "lon": 105.8445,
        "district": "Hai Bà Trưng",
        "address": "Trần Nhân Tông, Hai Bà Trưng, Hà Nội",
    },
    {
        "name": "Cầu Vĩnh Tuy",
        "lat": 21.0055,
        "lon": 105.8752,
        "district": "Hai Bà Trưng",
        "address": "Cầu Vĩnh Tuy, Hai Bà Trưng, Hà Nội",
    },
    {
        "name": "Lăng Chủ tịch Hồ Chí Minh",
        "lat": 21.0368,
        "lon": 105.8346,
        "district": "Ba Đình",
        "address": "2 Hùng Vương, Điện Biên, Ba Đình, Hà Nội",
    },
    {
        "name": "Chùa Một Cột",
        "lat": 21.0358,
        "lon": 105.8335,
        "district": "Ba Đình",
        "address": "Chùa Một Cột, Đội Cấn, Ba Đình, Hà Nội",
    },
    {
        "name": "Hồ Trúc Bạch",
        "lat": 21.0483,
        "lon": 105.8398,
        "district": "Ba Đình",
        "address": "Trúc Bạch, Ba Đình, Hà Nội",
    },
    {
        "name": "Vincom Metropolis Liễu Giai",
        "lat": 21.0318,
        "lon": 105.8142,
        "district": "Ba Đình",
        "address": "29 Liễu Giai, Ba Đình, Hà Nội",
    },
    {
        "name": "Hồ Tây (Chùa Trấn Quốc)",
        "lat": 21.0478,
        "lon": 105.8368,
        "district": "Tây Hồ",
        "address": "Đường Thanh Niên, Tây Hồ, Hà Nội",
    },
    {
        "name": "Phủ Tây Hồ",
        "lat": 21.0602,
        "lon": 105.8295,
        "district": "Tây Hồ",
        "address": "Quảng An, Tây Hồ, Hà Nội",
    },
    {
        "name": "Công viên nước Hồ Tây",
        "lat": 21.0722,
        "lon": 105.8185,
        "district": "Tây Hồ",
        "address": "614 Lạc Long Quân, Tây Hồ, Hà Nội",
    },
    {
        "name": "Trung tâm Hội nghị Quốc gia",
        "lat": 21.0062,
        "lon": 105.7878,
        "district": "Nam Từ Liêm",
        "address": "Đại lộ Thăng Long, Mễ Trì, Nam Từ Liêm, Hà Nội",
    },
    {
        "name": "Sân vận động Mỹ Đình",
        "lat": 21.0205,
        "lon": 105.7639,
        "district": "Nam Từ Liêm",
        "address": "Lê Đức Thọ, Mỹ Đình, Nam Từ Liêm, Hà Nội",
    },
    {
        "name": "Keangnam Landmark 72",
        "lat": 21.0168,
        "lon": 105.7838,
        "district": "Nam Từ Liêm",
        "address": "Phạm Hùng, Mễ Trì, Nam Từ Liêm, Hà Nội",
    },
    {
        "name": "Vincom Center Trần Duy Hưng",
        "lat": 21.0076,
        "lon": 105.7958,
        "district": "Cầu Giấy",
        "address": "119 Trần Duy Hưng, Cầu Giấy, Hà Nội",
    },
    {
        "name": "Công viên Cầu Giấy",
        "lat": 21.0248,
        "lon": 105.7905,
        "district": "Cầu Giấy",
        "address": "Duy Tân, Dịch Vọng Hậu, Cầu Giấy, Hà Nội",
    },
    {
        "name": "Bảo tàng Dân tộc học",
        "lat": 21.0406,
        "lon": 105.7985,
        "district": "Cầu Giấy",
        "address": "Nguyễn Văn Huyên, Cầu Giấy, Hà Nội",
    },
    {
        "name": "Royal City Mega Mall",
        "lat": 21.0028,
        "lon": 105.8162,
        "district": "Thanh Xuân",
        "address": "72A Nguyễn Trãi, Thanh Xuân, Hà Nội",
    },
    {
        "name": "Aeon Mall Long Biên",
        "lat": 21.0267,
        "lon": 105.8985,
        "district": "Long Biên",
        "address": "27 Cổ Linh, Long Biên, Hà Nội",
    },
    {
        "name": "Sân bay Quốc tế Nội Bài (T1)",
        "lat": 21.2212,
        "lon": 105.8072,
        "district": "Sóc Sơn",
        "address": "Xã Phú Minh, Sóc Sơn, Hà Nội",
    },
    {
        "name": "Vincom Mega Mall Ocean Park",
        "lat": 20.9898,
        "lon": 105.9528,
        "district": "Gia Lâm",
        "address": "Đa Tốn, Gia Lâm, Hà Nội",
    },
]


# ---------------------------------------------------------------------------
# Pure Deterministic Generators
# ---------------------------------------------------------------------------


def get_vehicle_model(vehicle_type: str, service_class: str, seed: int) -> str:
    """Return authentic VinFast electric model matching vehicle type and service class."""
    norm_type = str(vehicle_type or "").strip().lower()
    norm_class = str(service_class or "").strip().lower()
    if norm_type == "motorbike" or "bike" in norm_class:
        if "fast" in norm_class:
            models = ("VinFast Feliz S", "VinFast Klara S")
            return models[seed % len(models)]
        return "VinFast Evo 200"

    # Car models
    if "luxury" in norm_class or (seed % 4 == 0):
        lux_models = ("VinFast VF 8", "VinFast VF 9")
        return lux_models[seed % len(lux_models)]
    std_models = ("VinFast VF e34", "VinFast VF 5 Plus")
    return std_models[seed % len(std_models)]


def get_driver_metrics(seed: int) -> dict[str, Any]:
    """Deterministic Vietnamese operational metrics within strict GreenSM bounds."""
    rating = round(4.65 + ((seed * 7 + 3) % 31) * 0.01, 2)
    acceptance_rate = round(89.0 + ((seed * 11 + 5) % 95) * 0.1, 1)
    cancellation_rate = round(0.8 + ((seed * 13 + 2) % 28) * 0.1, 1)
    total_trips = 650 + ((seed * 17 + 10) % 35) * 45
    tenure_months = 8 + ((seed * 19 + 7) % 21)
    return {
        "rating": rating,
        "acceptance_rate": acceptance_rate,
        "cancellation_rate": cancellation_rate,
        "total_trips": total_trips,
        "tenure_months": tenure_months,
    }


def get_driver_statement(category: str | None, seed: int) -> str:
    """Realistic Vietnamese driver dispute statement grounded in operational scenarios."""
    cat = str(category or "").strip()
    statements: dict[str, list[str]] = {
        "ERR-01": [
            "Tôi gặp sự cố kỹ thuật xe đột xuất nên không thể tiếp tục nhận cuốc đón khách.",
            "Phương tiện gặp trục trặc hệ thống điều hòa và phanh, tôi buộc phải hủy chuyến để đảm bảo an toàn.",
        ],
        "ERR-02": [
            "Đường vào điểm đón ùn tắc kéo dài tại nút giao, tôi đã gọi điện nhưng hành khách không chờ được nên tự hủy chuyến.",
            "Khu vực đón xe bị kẹt do công trình đang sửa đường, tôi dừng chờ và liên lạc nhưng khách báo bận tự hủy.",
        ],
        "ERR-03": [
            "Đoạn đường đang thi công rào chắn nên tôi phải đi vòng theo chỉ dẫn giao thông, không cố ý kéo dài lộ trình.",
            "Đường đê cấm ô tô giờ cao điểm nên tôi buộc phải đi hướng cầu Vĩnh Tuy, lộ trình dài hơn dự kiến ban đầu.",
        ],
        "ERR-04": [
            "Khách đặt xe đi liên tỉnh, chuyến đi hoàn thành đầy đủ các điểm dừng theo yêu cầu của người đi.",
            "Chuyến xe chở khách quen đặt qua ứng dụng, có đón trả đúng lộ trình thỏa thuận và thanh toán đầy đủ.",
        ],
        "ERR-05": [
            "Khu vực tầng hầm và nhiều toà nhà cao tầng làm tín hiệu GPS trên điện thoại bị trôi lệch, tôi không can thiệp phần mềm.",
            "Điện thoại bị nóng quá nhiệt khi chạy ngoài trời trưa nắng khiến chip GPS ghi nhận tọa độ nhảy liên tục.",
        ],
        "no_violation": [
            "Tôi đã đón và trả khách đúng quy trình của GreenSM, hành trình thuận lợi không có sự cố.",
            "Chuyến đi diễn ra chuẩn tắc, khách hàng thanh toán đầy đủ qua thẻ và hài lòng với chất lượng phục vụ.",
        ],
    }
    candidates = statements.get(
        cat,
        [
            "Tôi đã di chuyển theo lộ trình gợi ý trên ứng dụng, sẵn sàng hợp tác đối soát dữ liệu viễn thông.",
            "Lộ trình thực tế tuân thủ hướng dẫn giao thông trên đường, không có hành vi vi phạm quy chế.",
        ],
    )
    return candidates[seed % len(candidates)]


def get_passenger_feedback(category: str | None, seed: int) -> dict[str, Any]:
    """Realistic Vietnamese passenger statement and star rating grounded in case category."""
    cat = str(category or "").strip()
    feedback_catalog: dict[str, list[dict[str, Any]]] = {
        "ERR-01": [
            {
                "reason_code": "driver_cancelled",
                "statement": "Tài xế nhận cuốc rồi tự ý hủy chuyến sau 5 phút chờ đợi mà không báo trước.",
                "rating_smallint": 1,
            },
            {
                "reason_code": "unresponsive_driver",
                "statement": "Tôi đợi xe hơn 10 phút thì tài xế tự bấm hủy chuyến, gọi điện không bắt máy.",
                "rating_smallint": 1,
            },
        ],
        "ERR-02": [
            {
                "reason_code": "driver_no_show",
                "statement": "Tài xế đỗ yên một chỗ cách tôi 300m hơn 4 phút không chịu di chuyển đón, gọi không nghe máy.",
                "rating_smallint": 1,
            },
            {
                "reason_code": "driver_stall",
                "statement": "Xe đứng yên tại ngã tư không đi đón, tôi có việc gấp nên buộc phải hủy chuyến.",
                "rating_smallint": 2,
            },
        ],
        "ERR-03": [
            {
                "reason_code": "wrong_direction",
                "statement": "Tài xế lái xe đi ngược hướng điểm đón ngày càng xa, tôi phải hủy chuyến vì muộn giờ làm.",
                "rating_smallint": 1,
            },
            {
                "reason_code": "off_route",
                "statement": "Tài xế không theo định vị mà chạy lòng vòng qua quận khác, tôi cảm thấy không yên tâm.",
                "rating_smallint": 1,
            },
        ],
        "ERR-04": [
            {
                "reason_code": "unauthorized_trip",
                "statement": "Tôi không thực hiện chuyến đi này nhưng thẻ tín dụng vẫn bị trừ tiền tự động.",
                "rating_smallint": 1,
            },
            {
                "reason_code": "fare_dispute",
                "statement": "Cước phí thực tế cao bất thường so với giá ước tính hiển thị lúc đặt xe.",
                "rating_smallint": 2,
            },
        ],
        "ERR-05": [
            {
                "reason_code": "gps_jumping",
                "statement": "Vị trí xe trên ứng dụng nhảy liên tục từ quận này sang quận khác rất bất thường.",
                "rating_smallint": 2,
            },
            {
                "reason_code": "telemetry_error",
                "statement": "Ứng dụng báo xe đã đến nhưng thực tế không thấy xe đâu, vị trí hiển thị sai lệch lớn.",
                "rating_smallint": 2,
            },
        ],
        "no_violation": [
            {
                "reason_code": "trip_completed",
                "statement": "Chuyến đi êm ái, tài xế lịch sự, xe sạch sẽ và đón đúng giờ.",
                "rating_smallint": 5,
            },
            {
                "reason_code": "good_service",
                "statement": "Bác tài vui vẻ nhiệt tình, lái xe an toàn, phục vụ chu đáo.",
                "rating_smallint": 5,
            },
        ],
    }
    candidates = feedback_catalog.get(
        cat,
        [
            {
                "reason_code": "complaint",
                "statement": "Chuyến đi có sự chậm trễ so với dự kiến ban đầu, đề nghị tổng đài kiểm tra lại.",
                "rating_smallint": 3,
            },
            {
                "reason_code": "service_inquiry",
                "statement": "Cần đối chiếu lại lộ trình và thời gian thực tế của cuốc xe.",
                "rating_smallint": 3,
            },
        ],
    )
    return candidates[seed % len(candidates)]


def get_sensor_reliability(seed: int, sequence: int = 0) -> dict[str, float]:
    """Realistic ping latency (ms) and battery percentage (%) within physical limits."""
    latency = round(25.0 + ((seed * 7) % 45) + ((sequence * 3) % 7) * 0.8, 1)
    battery = round(max(25.0, min(99.0, 92.0 - ((seed * 5) % 35) - (sequence % 50) * 0.05)), 1)
    return {"ping_latency_ms": latency, "battery_level_pct": battery}


def get_trip_fare(distance_m: int | None, seed: int, category: str | None = None) -> dict[str, Any]:
    """Calculate realistic Hanoi taxi trip fare and matching quote with positive incentive delta for fraud."""
    if distance_m and distance_m > 500:
        base = 14000
        rate_per_km = 12500
        raw_fare = int(base + (distance_m / 1000.0) * rate_per_km)
        fare_vnd = int(round(raw_fare / 1000.0) * 1000)
    else:
        fare_vnd = 45000 + ((seed * 11) % 28) * 8000

    cat = str(category or "").strip()
    if cat in ("ERR-02", "ERR-03", "ERR-04", "ERR-05"):
        # Driver gained positive economic incentive reward (fare delta > 0)
        delta_vnd = 15000 + ((seed * 7) % 15) * 2000
        quoted_vnd = max(25000, fare_vnd - delta_vnd)
    else:
        delta_vnd = 0
        quoted_vnd = fare_vnd

    return {
        "fare_amount_vnd": fare_vnd,
        "quoted_minor": quoted_vnd * 100,
        "delta_vnd": delta_vnd,
    }


# ---------------------------------------------------------------------------
# Database Enrichment Operations
# ---------------------------------------------------------------------------


def enrich_vehicles_model(cur: Any, dry_run: bool = False) -> int:
    """Populate model on app.vehicles with VinFast EV catalog."""
    cur.execute("SELECT id, vehicle_type, service_class, model FROM app.vehicles ORDER BY id;")
    vehicles = cur.fetchall()
    count = 0
    for idx, v in enumerate(vehicles):
        v_id = v[0] if isinstance(v, tuple) else v["id"]
        v_type = v[1] if isinstance(v, tuple) else v["vehicle_type"]
        s_class = v[2] if isinstance(v, tuple) else v["service_class"]
        cur_model = v[3] if isinstance(v, tuple) else v["model"]

        target_model = get_vehicle_model(v_type, s_class, idx)
        if cur_model != target_model:
            count += 1
            if not dry_run:
                cur.execute(
                    "UPDATE app.vehicles SET model = %s WHERE id = %s;",
                    (target_model, v_id),
                )
    return count


def enrich_drivers_profile_and_metrics(cur: Any, dry_run: bool = False) -> int:
    """Populate driver operational metrics, tenure, and profile provenance."""
    cur.execute("SELECT id, external_ref, display_name, created_at, rating FROM app.drivers ORDER BY id;")
    drivers = cur.fetchall()
    count = 0
    now = datetime.now(UTC)
    for idx, d in enumerate(drivers):
        d_id = d[0] if isinstance(d, tuple) else d["id"]
        d_ref = d[1] if isinstance(d, tuple) else d["external_ref"]
        d_name = d[2] if isinstance(d, tuple) else d["display_name"]

        metrics = get_driver_metrics(idx)
        tenure_months = metrics["tenure_months"]
        backdated_created_at = now - timedelta(days=tenure_months * 30 + (idx % 25))
        avatar_url = f"https://api.dicebear.com/7.x/bottts/svg?seed={d_ref or d_name or str(d_id)}"

        provenance = {
            "source": "synthetic_seed",
            "seed": idx,
            "tenure_months": tenure_months,
            "rating": metrics["rating"],
            "acceptance_rate": metrics["acceptance_rate"],
            "cancellation_rate": metrics["cancellation_rate"],
            "total_trips": metrics["total_trips"],
            "updated_at": now.isoformat(),
        }

        count += 1
        if not dry_run:
            cur.execute(
                """
                UPDATE app.drivers
                SET rating = %s,
                    acceptance_rate = %s,
                    cancellation_rate = %s,
                    total_trips = %s,
                    avatar_url = %s,
                    created_at = %s,
                    account_status = 'active',
                    profile_provenance = %s::jsonb
                WHERE id = %s;
                """,
                (
                    metrics["rating"],
                    metrics["acceptance_rate"],
                    metrics["cancellation_rate"],
                    metrics["total_trips"],
                    avatar_url,
                    backdated_created_at,
                    json.dumps(provenance),
                    d_id,
                ),
            )
    return count


def enrich_trips_fare_and_addresses(cur: Any, dry_run: bool = False) -> tuple[int, int]:
    """Populate fare_amount_vnd, addresses, district, and matching fare quotes."""
    cur.execute(
        """
        SELECT t.id, t.created_at, fc.suspected_category,
               fq.id as fare_quote_id, fq.estimated_distance_m
        FROM app.trips t
        LEFT JOIN app.trip_assignments ta ON ta.trip_id = t.id
        LEFT JOIN app.fraud_cases fc ON fc.assignment_id = ta.id
        LEFT JOIN LATERAL (
            SELECT id, estimated_distance_m FROM app.fare_quotes
            WHERE trip_id = t.id ORDER BY version DESC LIMIT 1
        ) fq ON true
        ORDER BY t.created_at, t.id;
        """
    )
    trips = cur.fetchall()
    trip_count = 0
    quote_count = 0
    for idx, t in enumerate(trips):
        t_id = t[0] if isinstance(t, tuple) else t["id"]
        t_created = t[1] if isinstance(t, tuple) else t["created_at"]
        t_cat = t[2] if isinstance(t, tuple) else t["suspected_category"]
        fq_id = t[3] if isinstance(t, tuple) else t["fare_quote_id"]
        fq_dist = t[4] if isinstance(t, tuple) else t["estimated_distance_m"]

        lm_p = HANOI_LANDMARKS[idx % len(HANOI_LANDMARKS)]
        lm_d = HANOI_LANDMARKS[(idx * 7 + 5) % len(HANOI_LANDMARKS)]
        if lm_p["name"] == lm_d["name"]:
            lm_d = HANOI_LANDMARKS[(idx * 7 + 6) % len(HANOI_LANDMARKS)]

        fare_info = get_trip_fare(fq_dist, idx, t_cat)
        match_type = "now" if (idx % 2 == 0) else "auto"

        trip_count += 1
        if not dry_run:
            cur.execute(
                """
                UPDATE app.trips
                SET fare_amount_vnd = %s,
                    match_type = %s,
                    pickup_address = %s,
                    dropoff_address = %s,
                    district = %s
                WHERE id = %s;
                """,
                (
                    fare_info["fare_amount_vnd"],
                    match_type,
                    lm_p["address"],
                    lm_d["address"],
                    lm_p["district"],
                    t_id,
                ),
            )

        quote_id = fq_id or uuid.uuid5(NAMESPACE_SEED, f"fq_{t_id}")
        dist_m = fq_dist or (5500 + (idx % 15) * 800)
        dur_s = int(dist_m / 8.0)
        quoted_at = t_created or datetime.now(UTC)

        quote_count += 1
        if not dry_run:
            cur.execute(
                """
                INSERT INTO app.fare_quotes (
                    id, trip_id, version, currency, estimated_amount_minor,
                    estimated_distance_m, estimated_duration_s, quoted_at
                )
                VALUES (%s, %s, 1, 'VND', %s, %s, %s, %s)
                ON CONFLICT (trip_id, version) DO UPDATE SET
                    estimated_amount_minor = EXCLUDED.estimated_amount_minor,
                    currency = 'VND';
                """,
                (
                    quote_id,
                    t_id,
                    fare_info["quoted_minor"],
                    dist_m,
                    dur_s,
                    quoted_at,
                ),
            )

    return trip_count, quote_count


def enrich_driver_submissions(cur: Any, dry_run: bool = False) -> int:
    """Ensure all fraud cases have a realistic Vietnamese driver statement."""
    cur.execute(
        """
        SELECT c.id as case_id, c.suspected_category, c.created_at, ds.id as submission_id
        FROM app.fraud_cases c
        LEFT JOIN app.driver_submissions ds ON ds.case_id = c.id
        ORDER BY c.created_at, c.id;
        """
    )
    cases = cur.fetchall()
    count = 0
    for idx, c in enumerate(cases):
        c_id = c[0] if isinstance(c, tuple) else c["case_id"]
        c_cat = c[1] if isinstance(c, tuple) else c["suspected_category"]
        c_created = c[2] if isinstance(c, tuple) else c["created_at"]
        sub_id = c[3] if isinstance(c, tuple) else c["submission_id"]

        statement = get_driver_statement(c_cat, idx)
        base_time = c_created or datetime.now(UTC)
        received_at = base_time + timedelta(minutes=15)
        deadline_at = base_time + timedelta(hours=24)
        provenance = {"source": "synthetic_seed", "category": c_cat, "case_id": str(c_id)}

        count += 1
        if not dry_run:
            if sub_id:
                cur.execute(
                    """
                    UPDATE app.driver_submissions
                    SET statement = %s,
                        status = 'present',
                        received_at = %s,
                        provenance = %s::jsonb
                    WHERE id = %s;
                    """,
                    (statement, received_at, json.dumps(provenance), sub_id),
                )
            else:
                new_sub_id = uuid.uuid5(NAMESPACE_SEED, f"ds_{c_id}")
                cur.execute(
                    """
                    INSERT INTO app.driver_submissions (
                        id, case_id, status, statement, deadline_at, received_at, provenance
                    )
                    VALUES (%s, %s, 'present', %s, %s, %s, %s::jsonb);
                    """,
                    (new_sub_id, c_id, statement, deadline_at, received_at, json.dumps(provenance)),
                )
    return count


def enrich_passenger_feedback(cur: Any, dry_run: bool = False) -> int:
    """Ensure all fraud case assignments have a customer feedback statement and star rating."""
    cur.execute(
        """
        SELECT c.id as case_id, c.assignment_id, c.suspected_category, c.created_at, pf.id as feedback_id
        FROM app.fraud_cases c
        JOIN app.trip_assignments a ON c.assignment_id = a.id
        LEFT JOIN app.passenger_feedback pf ON pf.assignment_id = a.id
        ORDER BY c.created_at, c.id;
        """
    )
    cases = cur.fetchall()
    count = 0
    for idx, c in enumerate(cases):
        asgn_id = c[1] if isinstance(c, tuple) else c["assignment_id"]
        c_cat = c[2] if isinstance(c, tuple) else c["suspected_category"]
        c_created = c[3] if isinstance(c, tuple) else c["created_at"]
        fb_id = c[4] if isinstance(c, tuple) else c["feedback_id"]

        fb_data = get_passenger_feedback(c_cat, idx)
        submitted_at = (c_created or datetime.now(UTC)) + timedelta(minutes=5)

        count += 1
        if not dry_run:
            if fb_id:
                cur.execute(
                    """
                    UPDATE app.passenger_feedback
                    SET reason_code = %s,
                        statement = %s,
                        rating_smallint = %s,
                        is_synthetic = true,
                        submitted_at = %s
                    WHERE id = %s;
                    """,
                    (fb_data["reason_code"], fb_data["statement"], fb_data["rating_smallint"], submitted_at, fb_id),
                )
            else:
                new_fb_id = uuid.uuid5(NAMESPACE_SEED, f"pf_{asgn_id}")
                cur.execute(
                    """
                    INSERT INTO app.passenger_feedback (
                        id, assignment_id, submitted_at, reason_code, statement, is_synthetic, rating_smallint
                    )
                    VALUES (%s, %s, %s, %s, %s, true, %s);
                    """,
                    (
                        new_fb_id,
                        asgn_id,
                        submitted_at,
                        fb_data["reason_code"],
                        fb_data["statement"],
                        fb_data["rating_smallint"],
                    ),
                )
    return count


def enrich_telemetry_sensor_payloads(cur: Any, dry_run: bool = False) -> int:
    """Populate ping_latency_ms and battery_level_pct in app.ingest_events payload."""
    cur.execute(
        """
        SELECT e.event_id, e.producer_sequence, e.payload
        FROM app.ingest_events e
        WHERE (e.payload->>'ping_latency_ms' IS NULL OR e.payload->>'battery_level_pct' IS NULL)
        ORDER BY e.occurred_at ASC;
        """
    )
    events = cur.fetchall()
    count = len(events)
    if dry_run or count == 0:
        return count

    # Fast bulk update using jsonb concatenation
    cur.execute(
        """
        UPDATE app.ingest_events
        SET payload = payload || jsonb_build_object(
            'ping_latency_ms', round((28.0 + (abs(('x' || substring(md5(event_id::text), 1, 4))::bit(16)::int) % 45)::numeric), 1),
            'battery_level_pct', round((55.0 + (abs(('x' || substring(md5(event_id::text || 'bat'), 1, 4))::bit(16)::int) % 40)::numeric), 1),
            'sensor_provenance', 'synthetic_seed'
        )
        WHERE payload->>'ping_latency_ms' IS NULL OR payload->>'battery_level_pct' IS NULL;
        """
    )
    return count


def enrich_historical_trips_for_scorecard(cur: Any, dry_run: bool = False) -> int:
    """Seed nominal non-fraud historical trips so 90-day violation ratios reflect fleet reality (~2.5%–6.5%)."""
    cur.execute(
        """
        SELECT d.id, d.organization_id, dva.vehicle_id
        FROM app.drivers d
        LEFT JOIN LATERAL (
            SELECT vehicle_id FROM app.driver_vehicle_assignments
            WHERE driver_id = d.id ORDER BY effective_from DESC LIMIT 1
        ) dva ON true
        ORDER BY d.id;
        """
    )
    drivers = cur.fetchall()

    cur.execute("SELECT id FROM app.passengers ORDER BY id LIMIT 30;")
    passenger_rows = cur.fetchall()
    passenger_ids = [p[0] if isinstance(p, tuple) else p["id"] for p in passenger_rows]
    if not passenger_ids:
        return 0

    now = datetime.now(UTC)
    trips_to_seed = 0

    for d_idx, d_row in enumerate(drivers):
        drv_id = d_row[0] if isinstance(d_row, tuple) else d_row["id"]
        org_id = d_row[1] if isinstance(d_row, tuple) else d_row["organization_id"]
        veh_id = d_row[2] if isinstance(d_row, tuple) else d_row["vehicle_id"]
        if not veh_id:
            continue

        # Check existing historical non-fraud trip count for this driver in last 90 days
        cur.execute(
            """
            SELECT count(*)
            FROM app.trips t
            JOIN app.trip_assignments ta ON ta.trip_id = t.id
            WHERE ta.driver_id = %s AND t.created_at >= NOW() - INTERVAL '90 days'
              AND NOT EXISTS (SELECT 1 FROM app.fraud_cases fc WHERE fc.assignment_id = ta.id);
            """,
            (drv_id,),
        )
        existing_nominal = (cur.fetchone() or (0,))[0]
        needed_nominal = max(0, 60 - existing_nominal)
        trips_to_seed += needed_nominal

        if dry_run or needed_nominal == 0:
            continue

        trip_inserts: list[tuple] = []
        assignment_inserts: list[tuple] = []

        for t_idx in range(needed_nominal):
            t_uuid = uuid.uuid5(NAMESPACE_SEED, f"hist_trip_{drv_id}_{t_idx}")
            a_uuid = uuid.uuid5(NAMESPACE_SEED, f"hist_asgn_{drv_id}_{t_idx}")
            pax_id = passenger_ids[(d_idx * 7 + t_idx) % len(passenger_ids)]

            days_ago = 1 + ((d_idx * 11 + t_idx * 3) % 85)
            created_at = now - timedelta(days=days_ago, hours=(t_idx % 12), minutes=(t_idx * 7 % 60))

            lm_p = HANOI_LANDMARKS[(d_idx * 5 + t_idx) % len(HANOI_LANDMARKS)]
            lm_d = HANOI_LANDMARKS[(d_idx * 5 + t_idx + 3) % len(HANOI_LANDMARKS)]
            fare_vnd = 55000 + ((d_idx * 3 + t_idx * 7) % 20) * 5000

            trip_inserts.append(
                (
                    t_uuid,
                    org_id,
                    pax_id,
                    created_at,
                    lm_p["lon"],
                    lm_p["lat"],
                    lm_d["lon"],
                    lm_d["lat"],
                    "completed",
                    created_at,
                    created_at,
                    lm_p["address"],
                    lm_d["address"],
                    lm_p["district"],
                    "auto",
                    fare_vnd,
                )
            )

            assignment_inserts.append(
                (
                    a_uuid,
                    t_uuid,
                    drv_id,
                    veh_id,
                    "completed",
                    created_at,
                    created_at,
                    created_at + timedelta(minutes=5),
                    created_at + timedelta(minutes=6),
                    created_at + timedelta(minutes=25),
                    created_at,
                )
            )

        cur.executemany(
            """
            INSERT INTO app.trips (
                id, organization_id, passenger_id, requested_at,
                pickup, dropoff, status, completed_at, created_at,
                pickup_address, dropoff_address, district, match_type, fare_amount_vnd,
                requested_service_class
            )
            VALUES (
                %s, %s, %s, %s,
                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                %s, %s, %s,
                %s, %s, %s, %s, %s,
                'GreenCar Standard'
            )
            ON CONFLICT (id) DO NOTHING;
            """,
            trip_inserts,
        )

        cur.executemany(
            """
            INSERT INTO app.trip_assignments (
                id, trip_id, driver_id, vehicle_id, state,
                offered_at, accepted_at, arrived_at, started_at, ended_at, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING;
            """,
            assignment_inserts,
        )

    return trips_to_seed


def enrich_past_adjudications(cur: Any, dry_run: bool = False) -> int:
    """Ensure historical terminal cases have realistic findings and outcomes without modifying active cases."""
    cur.execute(
        """
        SELECT c.id as case_id, c.suspected_category, c.created_at,
               COALESCE(c.assigned_analyst_id, (SELECT id FROM app.principals WHERE organization_id = c.organization_id LIMIT 1)) as analyst_id,
               es.id as snapshot_id, es.policy_version_id,
               a.id as adjudication_id
        FROM app.fraud_cases c
        JOIN app.evidence_snapshots es ON es.case_id = c.id
        LEFT JOIN app.adjudications a ON a.case_id = c.id
        WHERE c.status IN ('resolved', 'auto_dismissed', 'dismissed', 'closed')
        ORDER BY c.created_at, c.id;
        """
    )
    cases = cur.fetchall()
    count = 0
    for idx, c in enumerate(cases):
        c_id = c[0] if isinstance(c, tuple) else c["case_id"]
        c_cat = c[1] if isinstance(c, tuple) else c["suspected_category"]
        c_created = c[2] if isinstance(c, tuple) else c["created_at"]
        an_id = c[3] if isinstance(c, tuple) else c["analyst_id"]
        snap_id = c[4] if isinstance(c, tuple) else c["snapshot_id"]
        pol_id = c[5] if isinstance(c, tuple) else c["policy_version_id"]
        adj_id = c[6] if isinstance(c, tuple) else c["adjudication_id"]

        if adj_id is not None or not an_id or not snap_id or not pol_id:
            continue

        cat = str(c_cat or "").strip()
        if cat == "ERR-01":
            outcome = "warn"
            rationale = "Tài xế tự ý hủy chuyến sau khi nhận cuốc. Cảnh cáo kỹ thuật hệ thống lần đầu."
        elif cat == "ERR-02":
            outcome = "fine"
            rationale = (
                "Tài xế cố ý dừng đỗ kéo dài ép khách hủy chuyến (ERR-02). Xử phạt khấu trừ vi phạm theo Điều 14.2."
            )
        elif cat == "ERR-03":
            outcome = "fine"
            rationale = (
                "Di chuyển sai lộ trình đón khách nghiêm trọng (ERR-03). Áp dụng khấu trừ cước và cảnh cáo vi phạm."
            )
        elif cat in ("ERR-04", "ERR-05"):
            outcome = "suspend"
            rationale = "Phát hiện dấu hiệu can thiệp GPS/tạo cuốc ảo nghiêm trọng. Tạm khóa tài khoản tài xế 7 ngày để điều tra."
        else:
            outcome = "dismiss"
            rationale = "Hội đồng thẩm định kết luận: DISMISS căn cứ chứng cứ GPS và đối chiếu chính sách."

        idem_key = uuid.uuid5(NAMESPACE_SEED, f"adj_idem_{c_id}")
        req_hash = hashlib.sha256(f"adj_{c_id}_{outcome}".encode()).digest()
        app_time = (c_created or datetime.now(UTC)) + timedelta(hours=2)
        new_adj_id = uuid.uuid5(NAMESPACE_SEED, f"adj_{c_id}")

        count += 1
        if not dry_run:
            cur.execute(
                """
                INSERT INTO app.adjudications (
                    id, case_id, evidence_snapshot_id, policy_version_id,
                    analyst_id, outcome, rationale, explicit_human_approval,
                    idempotency_key, request_hash, approved_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, true, %s, %s, %s)
                ON CONFLICT (case_id) DO NOTHING;
                """,
                (
                    new_adj_id,
                    c_id,
                    snap_id,
                    pol_id,
                    an_id,
                    outcome,
                    rationale,
                    idem_key,
                    req_hash,
                    app_time,
                ),
            )

    return count


# ---------------------------------------------------------------------------
# Main Orchestration
# ---------------------------------------------------------------------------


def enrich_preview_cases(
    database_url: str | None = None,
    conn: psycopg.Connection | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Execute all enrichment tasks in an isolated transaction."""
    load_dotenv()
    url = (
        database_url
        or os.environ.get("TARGET_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("MIGRATION_DATABASE_URL")
        or "postgresql://postgres:postgrespassword@localhost:5432/postgres"
    )

    close_conn = False
    if conn is None:
        conn = psycopg.connect(url, autocommit=False)
        close_conn = True

    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")

            n_veh = enrich_vehicles_model(cur, dry_run=dry_run)
            n_drv = enrich_drivers_profile_and_metrics(cur, dry_run=dry_run)
            n_trips, n_quotes = enrich_trips_fare_and_addresses(cur, dry_run=dry_run)
            n_subs = enrich_driver_submissions(cur, dry_run=dry_run)
            n_feed = enrich_passenger_feedback(cur, dry_run=dry_run)
            n_tlm = enrich_telemetry_sensor_payloads(cur, dry_run=dry_run)
            n_hist = enrich_historical_trips_for_scorecard(cur, dry_run=dry_run)
            n_adjs = enrich_past_adjudications(cur, dry_run=dry_run)

        if not dry_run:
            conn.commit()
            logger.info("Enrichment transaction committed successfully.")
        else:
            conn.rollback()
            logger.info("Dry-run mode: transaction rolled back, 0 mutations applied.")

        stats = {
            "vehicles_enriched": n_veh,
            "drivers_enriched": n_drv,
            "trips_enriched": n_trips,
            "fare_quotes_enriched": n_quotes,
            "driver_submissions_enriched": n_subs,
            "passenger_feedback_enriched": n_feed,
            "telemetry_events_enriched": n_tlm,
            "historical_trips_seeded": n_hist,
            "past_adjudications_enriched": n_adjs,
        }
        return stats
    finally:
        if close_conn:
            conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich seeded preview demo cases with realistic Vietnamese values for analyst workspace."
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="Target PostgreSQL connection URL",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Dry run: print counts only without modifying the database (default: true)",
    )
    parser.add_argument(
        "--apply",
        dest="apply",
        action="store_true",
        default=False,
        help="Apply mutations to the target database (shortcut for --no-dry-run)",
    )
    args = parser.parse_args()

    # If --apply was specified, dry_run becomes False
    dry_run = False if args.apply else bool(args.dry_run)

    mode_str = "DRY-RUN (counts only)" if dry_run else "APPLY (committing changes)"
    print(f"=== Preview Seed Enrichment [{mode_str}] ===")
    stats = enrich_preview_cases(database_url=args.database_url, dry_run=dry_run)
    print("\nResults:")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
