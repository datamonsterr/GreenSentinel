"""Mock repository and tool handlers for driver data, telemetry, and trip history."""

from __future__ import annotations

import unicodedata
from typing import Any

from src.models.schemas import DriverCardData, DriverHistoryItem

MOCK_DRIVERS: dict[str, dict[str, Any]] = {
    "drv-8492-nguyen-van-a": {
        "driver_id": "drv-8492-nguyen-van-a",
        "full_name": "Nguyễn Văn A",
        "phone_number": "+84 912 345 678",
        "vehicle_plate": "29E-123.45",
        "vehicle_type": "Green SM Car (VF e34)",
        "rating": 4.82,
        "total_trips": 1420,
        "acceptance_rate_pct": 89.5,
        "completion_rate_pct": 91.0,
        "joined_date": "2023-04-15",
        "operating_status": "active",
    },
    "drv-3819-tran-dinh-trong": {
        "driver_id": "drv-3819-tran-dinh-trong",
        "full_name": "Trần Đình Trọng",
        "phone_number": "+84 983 221 990",
        "vehicle_plate": "30F-982.11",
        "vehicle_type": "Green SM Car (VF 8)",
        "rating": 4.65,
        "total_trips": 890,
        "acceptance_rate_pct": 78.0,
        "completion_rate_pct": 82.5,
        "joined_date": "2023-08-20",
        "operating_status": "under_investigation",
    },
    "drv-4418-pham-hoang-long": {
        "driver_id": "drv-4418-pham-hoang-long",
        "full_name": "Phạm Hoàng Long",
        "phone_number": "+84 904 882 113",
        "vehicle_plate": "29D-441.82",
        "vehicle_type": "Green SM Bike (Feliz S)",
        "rating": 4.95,
        "total_trips": 3100,
        "acceptance_rate_pct": 98.0,
        "completion_rate_pct": 99.1,
        "joined_date": "2023-05-10",
        "operating_status": "active",
    },
    "drv-5521-le-quang-minh": {
        "driver_id": "drv-5521-le-quang-minh",
        "full_name": "Lê Quang Minh",
        "phone_number": "+84 918 765 432",
        "vehicle_plate": "51K-882.91",
        "vehicle_type": "Green SM Car (VF 5 Plus)",
        "rating": 4.71,
        "total_trips": 640,
        "acceptance_rate_pct": 84.0,
        "completion_rate_pct": 88.0,
        "joined_date": "2024-02-15",
        "operating_status": "active",
    },
    "drv-9102-hoang-thuy-linh": {
        "driver_id": "drv-9102-hoang-thuy-linh",
        "full_name": "Hoàng Thùy Linh",
        "phone_number": "+84 936 112 344",
        "vehicle_plate": "29E-991.02",
        "vehicle_type": "Green SM Car (VF 9)",
        "rating": 4.98,
        "total_trips": 2200,
        "acceptance_rate_pct": 99.0,
        "completion_rate_pct": 99.5,
        "joined_date": "2023-03-01",
        "operating_status": "active",
    },
    "drv-6643-vu-duc-thanh": {
        "driver_id": "drv-6643-vu-duc-thanh",
        "full_name": "Vũ Đức Thành",
        "phone_number": "+84 977 445 667",
        "vehicle_plate": "30H-664.31",
        "vehicle_type": "Green SM Car (VF e34)",
        "rating": 4.20,
        "total_trips": 310,
        "acceptance_rate_pct": 65.0,
        "completion_rate_pct": 71.0,
        "joined_date": "2024-05-10",
        "operating_status": "suspended",
    },
}

MOCK_DRIVER_HISTORIES: dict[str, list[dict[str, Any]]] = {
    "drv-8492-nguyen-van-a": [
        {
            "trip_id": "trip-9021-hanoi",
            "timestamp": "2026-09-22T08:12:00Z",
            "service_type": "Green SM Car",
            "pickup_address": "12 Bà Triệu, Hoàn Kiếm, Hà Nội",
            "dropoff_address": "Sân bay Nội Bài, T1",
            "status": "passenger_cancelled",
            "stall_duration_sec": 210,
            "anomaly_flag": "ERR-02",
            "fare_vnd": 280000,
        },
        {
            "trip_id": "trip-8891-hanoi",
            "timestamp": "2026-09-20T17:45:00Z",
            "service_type": "Green SM Car",
            "pickup_address": "Vincom Bà Triệu",
            "dropoff_address": "Keangnam Landmark 72",
            "status": "completed",
            "stall_duration_sec": 30,
            "anomaly_flag": None,
            "fare_vnd": 145000,
        },
        {
            "trip_id": "trip-8744-hanoi",
            "timestamp": "2026-09-15T09:30:00Z",
            "service_type": "Green SM Car",
            "pickup_address": "Bệnh viện Bạch Mai",
            "dropoff_address": "Times City T10",
            "status": "passenger_cancelled",
            "stall_duration_sec": 195,
            "anomaly_flag": "ERR-02",
            "fare_vnd": 85000,
        },
    ],
    "drv-3819-tran-dinh-trong": [
        {
            "trip_id": "trip-7721-hanoi",
            "timestamp": "2026-09-21T14:10:00Z",
            "service_type": "Green SM Car",
            "pickup_address": "Royal City, Thanh Xuân",
            "dropoff_address": "Bến xe Mỹ Đình",
            "status": "disputed",
            "stall_duration_sec": 320,
            "anomaly_flag": "ERR-01",
            "fare_vnd": 110000,
        }
    ],
    "drv-6643-vu-duc-thanh": [
        {
            "trip_id": "trip-6601-hanoi",
            "timestamp": "2026-09-19T20:15:00Z",
            "service_type": "Green SM Car",
            "pickup_address": "Cầu Giấy, Hà Nội",
            "dropoff_address": "Hồ Gươm",
            "status": "passenger_cancelled",
            "stall_duration_sec": 260,
            "anomaly_flag": "ERR-02",
            "fare_vnd": 120000,
        },
        {
            "trip_id": "trip-6589-hanoi",
            "timestamp": "2026-09-18T11:00:00Z",
            "service_type": "Green SM Car",
            "pickup_address": "Mỹ Đình",
            "dropoff_address": "Sân bay Nội Bài",
            "status": "passenger_cancelled",
            "stall_duration_sec": 240,
            "anomaly_flag": "ERR-02",
            "fare_vnd": 290000,
        },
    ],
    "drv-5521-le-quang-minh": [
        {
            "trip_id": "trip-5510-hcm",
            "timestamp": "2026-09-21T09:00:00Z",
            "service_type": "Green SM Car",
            "pickup_address": "Quận 1, TP.HCM",
            "dropoff_address": "Sân bay Tân Sơn Nhất",
            "status": "completed",
            "stall_duration_sec": 10,
            "anomaly_flag": None,
            "fare_vnd": 130000,
        }
    ],
}


def strip_accents(text: str) -> str:
    """Normalize and strip Vietnamese diacritics for flexible fuzzy matching."""
    s = unicodedata.normalize("NFD", text)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D").lower()


def get_driver_profile(driver_id_or_name: str) -> DriverCardData | None:
    """Retrieve driver profile by ID, plate number, or approximate name (accent-insensitive)."""
    raw_query = driver_id_or_name.strip()
    norm_query = strip_accents(raw_query)

    for key, data in MOCK_DRIVERS.items():
        key_norm = strip_accents(key)
        name_norm = strip_accents(data["full_name"])
        plate_norm = strip_accents(data["vehicle_plate"])
        if (
            norm_query in key_norm
            or norm_query in name_norm
            or norm_query in plate_norm
            or key_norm in norm_query
            or name_norm in norm_query
        ):
            return DriverCardData(**data)

    # Default fallback driver if not found
    return DriverCardData(
        driver_id=f"drv-{norm_query.replace(' ', '-')[:12]}",
        full_name=raw_query.title(),
        phone_number="+84 9xx xxx xxx",
        vehicle_plate="29E-xxx.xx",
        vehicle_type="Green SM Car",
        rating=4.8,
        total_trips=500,
        acceptance_rate_pct=92.0,
        completion_rate_pct=94.0,
        joined_date="2023-06-01",
        operating_status="active",
    )


def get_driver_history(driver_id: str) -> list[DriverHistoryItem]:
    """Retrieve trip and anomaly history for driver (accent-insensitive)."""
    norm_query = strip_accents(driver_id.strip())

    for key, history_list in MOCK_DRIVER_HISTORIES.items():
        key_norm = strip_accents(key)
        driver_name_norm = strip_accents(MOCK_DRIVERS.get(key, {}).get("full_name", ""))
        if (
            norm_query in key_norm
            or norm_query in driver_name_norm
            or key_norm in norm_query
            or (driver_name_norm and driver_name_norm in norm_query)
        ):
            return [DriverHistoryItem(**item) for item in history_list]

    # Return nominal baseline trip if not in mock database
    return [
        DriverHistoryItem(
            trip_id=f"trip-{norm_query[:6]}-01",
            timestamp="2026-09-21T10:00:00Z",
            service_type="Green SM Car",
            pickup_address="Hoàn Kiếm, Hà Nội",
            dropoff_address="Cầu Giấy, Hà Nội",
            status="completed",
            stall_duration_sec=15,
            anomaly_flag=None,
            fare_vnd=95000,
        )
    ]
