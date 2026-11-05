"""Deterministically enrich synthetic drivers, passengers, vehicles, trips, telemetry, and fraud cases.

Enriches the database with realistic Vietnamese distributions:
- Surnames and given names from Vietnamese naming distributions
- Birth dates between 20-65 with truncated normal distribution peak around 35
- 30 Hanoi landmarks dispersed across 12 districts
- Realistic vehicle models (VinFast VF e34, VF 8, VF 9, Feliz S, Klara S)
- Multi-category fraud distribution (ERR-01, ERR-02, ERR-03, ERR-04, ERR-05, no_violation)
- Continuous kinematic telemetry (speeds, bearings, log-normal GPS CEP accuracy)
- Legally grounded forensic briefs citing GreenSM 2026 regulations
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import uuid
from datetime import UTC, date, datetime, timedelta
from urllib.request import urlopen

NAMESPACE_SEED = uuid.UUID("018f2f4e-9999-7000-8000-000000000366")
ISSUE_191_CASE_ID = "018f2f4e-a000-7000-8000-000000000001"
ISSUE_191_ASSIGNMENT_ID = "018f2f4e-9000-7000-8000-000000000001"
ISSUE_191_PEER_TRIP_IDS = tuple(f"01910000-8000-7000-8000-{index:012d}" for index in range(1, 4))
ISSUE_191_PEER_ASSIGNMENT_IDS = tuple(f"01910000-9000-7000-8000-{index:012d}" for index in range(1, 4))
ISSUE_191_PEER_SPEEDS_MPS = (4.0, 6.0, 8.0)
ISSUE_191_EVENT_NAMESPACE = uuid.UUID("01910000-0000-7000-8000-000000000191")

SURNAME_WEIGHTS = {
    "Nguyễn": 0.31,
    "Trần": 0.11,
    "Lê": 0.09,
    "Phạm": 0.07,
    "Hoàng": 0.05,
    "Vũ": 0.04,
    "Đặng": 0.04,
    "Bùi": 0.04,
    "Đỗ": 0.03,
    "Hồ": 0.02,
    "Ngô": 0.02,
    "Dương": 0.02,
}
GIVEN_NAMES = (
    "Minh",
    "Hùng",
    "Long",
    "Tuấn",
    "Nam",
    "Quang",
    "Linh",
    "Trang",
    "Hương",
    "Mai",
    "Thảo",
    "Phương",
    "Hải",
    "Đức",
    "Thành",
)
MIDDLE_NAMES = ("Văn", "Thị", "Minh", "Hoàng", "Thu", "Ngọc", "Đức", "Thanh", "Quang", "Hải", "Phương", "Anh")
PUBLIC_NAMES_URL = "https://raw.githubusercontent.com/duyet/vietnamese-namedb/master/first_name.json"

HANOI_LANDMARKS = [
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
        "name": "Đại học Quốc gia Hà Nội",
        "lat": 21.0378,
        "lon": 105.7828,
        "district": "Cầu Giấy",
        "address": "144 Xuân Thủy, Cầu Giấy, Hà Nội",
    },
    {
        "name": "Keangnam Landmark 72",
        "lat": 21.0167,
        "lon": 105.7839,
        "district": "Cầu Giấy",
        "address": "Phạm Hùng, Cầu Giấy, Hà Nội",
    },
    {
        "name": "Trung tâm Hội nghị Quốc gia",
        "lat": 21.0062,
        "lon": 105.7885,
        "district": "Nam Từ Liêm",
        "address": "Đại lộ Thăng Long, Nam Từ Liêm, Hà Nội",
    },
    {
        "name": "Sân vận động Quốc gia Mỹ Đình",
        "lat": 21.0205,
        "lon": 105.7640,
        "district": "Nam Từ Liêm",
        "address": "Lê Đức Thọ, Nam Từ Liêm, Hà Nội",
    },
    {
        "name": "Bảo tàng Hà Nội",
        "lat": 21.0084,
        "lon": 105.7877,
        "district": "Nam Từ Liêm",
        "address": "Phạm Hùng, Nam Từ Liêm, Hà Nội",
    },
    {
        "name": "Vincom Mega Mall Smart City",
        "lat": 20.9998,
        "lon": 105.7428,
        "district": "Nam Từ Liêm",
        "address": "Tây Mỗ, Nam Từ Liêm, Hà Nội",
    },
    {
        "name": "Vincom Center Metropolis Liễu Giai",
        "lat": 21.0318,
        "lon": 105.8142,
        "district": "Ba Đình",
        "address": "29 Liễu Giai, Ba Đình, Hà Nội",
    },
    {
        "name": "Lotte Center Hà Nội",
        "lat": 21.0326,
        "lon": 105.8124,
        "district": "Ba Đình",
        "address": "54 Liễu Giai, Ba Đình, Hà Nội",
    },
    {
        "name": "Lăng Chủ tịch Hồ Chí Minh",
        "lat": 21.0368,
        "lon": 105.8346,
        "district": "Ba Đình",
        "address": "2 Hùng Vương, Ba Đình, Hà Nội",
    },
    {
        "name": "Hồ Tây (Chùa Trấn Quốc)",
        "lat": 21.0483,
        "lon": 105.8364,
        "district": "Tây Hồ",
        "address": "Đường Thanh Niên, Tây Hồ, Hà Nội",
    },
    {
        "name": "Cầu Nhật Tân",
        "lat": 21.0850,
        "lon": 105.8185,
        "district": "Tây Hồ",
        "address": "Cầu Nhật Tân, Tây Hồ, Hà Nội",
    },
    {
        "name": "Royal City Megamall",
        "lat": 21.0029,
        "lon": 105.8159,
        "district": "Thanh Xuân",
        "address": "72A Nguyễn Trãi, Thanh Xuân, Hà Nội",
    },
    {
        "name": "Aeon Mall Long Biên",
        "lat": 21.0261,
        "lon": 105.9004,
        "district": "Long Biên",
        "address": "27 Cổ Linh, Long Biên, Hà Nội",
    },
    {
        "name": "Aeon Mall Hà Đông",
        "lat": 20.9818,
        "lon": 105.7538,
        "district": "Hà Đông",
        "address": "Dương Nội, Hà Đông, Hà Nội",
    },
    {
        "name": "Sân bay Quốc tế Nội Bài (T1)",
        "lat": 21.2212,
        "lon": 105.8072,
        "district": "Sóc Sơn",
        "address": "Xã Phú Minh, Sóc Sơn, Hà Nội",
    },
    {
        "name": "Sân bay Quốc tế Nội Bài (T2)",
        "lat": 21.2185,
        "lon": 105.7944,
        "district": "Sóc Sơn",
        "address": "Xã Phú Cường, Sóc Sơn, Hà Nội",
    },
    {
        "name": "Vincom Mega Mall Ocean Park",
        "lat": 20.9898,
        "lon": 105.9528,
        "district": "Gia Lâm",
        "address": "Đa Tốn, Gia Lâm, Hà Nội",
    },
]

VEHICLE_CATALOG = [
    {"model": "VinFast VF e34", "type": "car", "service_class": "GreenCar Standard"},
    {"model": "VinFast VF e34", "type": "car", "service_class": "GreenCar Standard"},
    {"model": "VinFast VF e34", "type": "car", "service_class": "GreenCar Standard"},
    {"model": "VinFast VF e34", "type": "car", "service_class": "GreenCar Standard"},
    {"model": "VinFast VF e34", "type": "car", "service_class": "GreenCar Standard"},
    {"model": "VinFast VF e34", "type": "car", "service_class": "GreenCar Standard"},
    {"model": "VinFast VF e34", "type": "car", "service_class": "GreenCar Standard"},
    {"model": "VinFast VF e34", "type": "car", "service_class": "GreenCar Standard"},
    {"model": "VinFast VF 8", "type": "car", "service_class": "GreenCar Luxury"},
    {"model": "VinFast VF 8", "type": "car", "service_class": "GreenCar Luxury"},
    {"model": "VinFast VF 8", "type": "car", "service_class": "GreenCar Luxury"},
    {"model": "VinFast VF 8", "type": "car", "service_class": "GreenCar Luxury"},
    {"model": "VinFast VF 8", "type": "car", "service_class": "GreenCar Luxury"},
    {"model": "VinFast VF 9", "type": "car", "service_class": "GreenCar Luxury"},
    {"model": "VinFast VF 9", "type": "car", "service_class": "GreenCar Luxury"},
    {"model": "VinFast Feliz S", "type": "motorbike", "service_class": "GreenBike Fast"},
    {"model": "VinFast Feliz S", "type": "motorbike", "service_class": "GreenBike Fast"},
    {"model": "VinFast Feliz S", "type": "motorbike", "service_class": "GreenBike Fast"},
    {"model": "VinFast Klara S", "type": "motorbike", "service_class": "GreenBike Fast"},
    {"model": "VinFast Klara S", "type": "motorbike", "service_class": "GreenBike Fast"},
]


def load_public_given_names(timeout: float = 10.0) -> tuple[str, ...]:
    """Load the MIT licensed given-name distribution, with offline fallback."""
    try:
        with urlopen(PUBLIC_NAMES_URL, timeout=timeout) as response:
            payload = json.load(response)
        names = payload if isinstance(payload, list) else payload.get("names", [])
        cleaned = tuple(str(item).strip() for item in names if str(item).strip())
        return cleaned or GIVEN_NAMES
    except Exception:
        return GIVEN_NAMES


def sample_birth_date(seed: int, reference: date = date.today()) -> date:
    rng = random.Random(seed)
    age = max(20, min(65, int(round(rng.gauss(35.0, 9.0)))))
    latest = date(reference.year - age, reference.month, reference.day)
    earliest = date(reference.year - age - 1, reference.month, reference.day) + timedelta(days=1)
    return earliest + timedelta(days=rng.randrange((latest - earliest).days + 1))


def age_from_birth_date(value: date, reference: date = date.today()) -> int:
    return reference.year - value.year - ((reference.month, reference.day) < (value.month, value.day))


def synthetic_name(seed: int, given_names: tuple[str, ...] = GIVEN_NAMES) -> str:
    rng = random.Random(seed)
    surnames, weights = zip(*SURNAME_WEIGHTS.items())
    m = rng.choice(MIDDLE_NAMES)
    g = rng.choice(given_names)
    return f"{rng.choices(surnames, weights)[0]} {m} {g}"


def sample_driver_metrics(seed: int) -> dict[str, float | int]:
    rng = random.Random(seed + 999)
    rating = round(max(4.10, min(5.00, rng.gauss(4.85, 0.12))), 2)
    acceptance_rate = round(max(82.0, min(99.5, rng.gauss(94.5, 3.0))), 1)
    cancellation_rate = round(max(0.5, min(18.0, rng.gauss(3.5, 2.0))), 1)
    past_warnings = rng.choices([0, 1, 2, 3], weights=[0.60, 0.25, 0.10, 0.05])[0]
    return {
        "rating": rating,
        "acceptance_rate": acceptance_rate,
        "cancellation_rate": cancellation_rate,
        "past_warnings": past_warnings,
    }


def enrich_drivers(cur, reference: date = date.today()) -> int:
    given_names = load_public_given_names()
    cur.execute("SELECT id FROM app.drivers ORDER BY id")
    drivers = cur.fetchall()
    for seed, (driver_id,) in enumerate(drivers):
        birth_date = sample_birth_date(seed, reference)
        name = synthetic_name(seed, given_names)
        metrics = sample_driver_metrics(seed)
        provenance = {
            "source": "synthetic_vietnamese_distribution",
            "seed": seed,
            "reference_date": reference.isoformat(),
            "name_source": "duyet/vietnamese-namedb MIT",
            **metrics,
        }
        cur.execute(
            """
            UPDATE app.drivers
            SET display_name = %s, birth_date = %s,
                profile_provenance = %s::jsonb
            WHERE id = %s
            """,
            (name, birth_date, json.dumps(provenance), driver_id),
        )
    return len(drivers)


def enrich_passengers(cur) -> int:
    given_names = load_public_given_names()
    cur.execute("SELECT id FROM app.passengers ORDER BY id")
    passengers = cur.fetchall()
    rng = random.Random(2026)
    for idx, (p_id,) in enumerate(passengers):
        p_name = synthetic_name(idx + 500, given_names)
        prefix = rng.choice(["090", "091", "098", "097", "093", "094", "086"])
        phone = f"+84 {prefix} {rng.randint(100, 999)} {rng.randint(100, 999)}"
        cur.execute(
            """
            UPDATE app.passengers
            SET display_name = %s, phone_number = %s
            WHERE id = %s
            """,
            (p_name, phone, p_id),
        )
    return len(passengers)


def enrich_vehicles(cur) -> int:
    cur.execute("SELECT id FROM app.vehicles ORDER BY id")
    vehicles = cur.fetchall()
    for idx, (v_id,) in enumerate(vehicles):
        spec = VEHICLE_CATALOG[idx % len(VEHICLE_CATALOG)]
        prefix = "29E" if idx < 10 else ("30E" if idx < 15 else "29MD")
        plate = f"{prefix}-{10000 + (idx * 379) % 89999}"
        cur.execute(
            """
            UPDATE app.vehicles
            SET model = %s, vehicle_type = %s, service_class = %s, registration_ref = %s
            WHERE id = %s
            """,
            (spec["model"], spec["type"], spec["service_class"], plate, v_id),
        )
    return len(vehicles)


def enrich_trips_and_assignments(cur) -> int:
    """Disperse trips across 30 Hanoi landmarks in 12 districts, assign drivers and passengers."""
    cur.execute("SELECT id FROM app.passengers ORDER BY id")
    passenger_ids = [row[0] for row in cur.fetchall()]

    cur.execute("SELECT id FROM app.drivers ORDER BY id")
    driver_ids = [row[0] for row in cur.fetchall()]

    cur.execute("SELECT id, service_class FROM app.vehicles ORDER BY id")
    vehicle_rows = cur.fetchall()
    vehicle_ids = [row[0] for row in vehicle_rows]
    vehicle_services = {row[0]: row[1] for row in vehicle_rows}

    cur.execute(
        "SELECT t.id, a.id as assignment_id FROM app.trips t LEFT JOIN app.trip_assignments a ON a.trip_id = t.id ORDER BY t.created_at, t.id"
    )
    trip_rows = cur.fetchall()

    rng = random.Random(1337)
    for idx, (trip_id, asgn_id) in enumerate(trip_rows):
        lm_p = HANOI_LANDMARKS[idx % len(HANOI_LANDMARKS)]
        lm_d = HANOI_LANDMARKS[(idx * 7 + 5) % len(HANOI_LANDMARKS)]
        if lm_p["name"] == lm_d["name"]:
            lm_d = HANOI_LANDMARKS[(idx * 7 + 6) % len(HANOI_LANDMARKS)]

        # Small coordinate jitter within ~150 meters
        p_lat = round(lm_p["lat"] + rng.uniform(-0.0012, 0.0012), 6)
        p_lon = round(lm_p["lon"] + rng.uniform(-0.0012, 0.0012), 6)
        d_lat = round(lm_d["lat"] + rng.uniform(-0.0012, 0.0012), 6)
        d_lon = round(lm_d["lon"] + rng.uniform(-0.0012, 0.0012), 6)

        p_addr = lm_p["address"]
        d_addr = lm_d["address"]
        dist_name = lm_p["district"]

        pax_id = passenger_ids[idx % len(passenger_ids)] if passenger_ids else None
        drv_id = driver_ids[idx % len(driver_ids)] if driver_ids else None
        veh_id = vehicle_ids[idx % len(vehicle_ids)] if vehicle_ids else None
        svc_class = vehicle_services.get(veh_id, "GreenCar Standard")

        cur.execute(
            """
            UPDATE app.trips
            SET pickup = ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                dropoff = ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                pickup_address = %s,
                dropoff_address = %s,
                district = %s,
                passenger_id = COALESCE(%s, passenger_id),
                requested_service_class = %s
            WHERE id = %s;
            """,
            (p_lon, p_lat, d_lon, d_lat, p_addr, d_addr, dist_name, pax_id, svc_class, trip_id),
        )

        if asgn_id and drv_id and veh_id:
            cur.execute(
                """
                UPDATE app.trip_assignments
                SET driver_id = %s,
                    vehicle_id = %s
                WHERE id = %s;
                """,
                (drv_id, veh_id, asgn_id),
            )

    return len(trip_rows)


def enrich_fraud_cases(cur) -> int:
    """Distribute fraud cases across ERR-01 to ERR-05 and no_violation with valid SLAs and analysts."""
    cur.execute(
        "SELECT id FROM app.principals WHERE organization_id = '018f2f4e-0000-7000-8000-000000000001' ORDER BY id"
    )
    analyst_ids = [row[0] for row in cur.fetchall()]

    cur.execute("SELECT id, assignment_id, created_at, status FROM app.fraud_cases ORDER BY created_at, id")
    cases = cur.fetchall()

    category_buckets = [
        ("ERR-02", 1, 92, "analyst", 25),  # DIC stall: 35%
        ("ERR-03", 1, 88, "analyst", 30),  # Route deviation: 20%
        ("ERR-05", 0, 98, "senior_analyst", 15),  # Fake GPS: 15%
        ("ERR-01", 2, 70, "analyst", 45),  # Driver cancel: 10%
        ("ERR-04", 0, 94, "senior_analyst", 20),  # Collusion: 8%
        ("no_violation", 2, 15, "analyst", 60),  # Nominal: 12%
    ]
    weights = [35, 20, 15, 10, 8, 12]

    rng = random.Random(42)
    for idx, (case_id, asgn_id, created_at, status) in enumerate(cases):
        cat_spec = rng.choices(category_buckets, weights=weights)[0]
        cat, tier, base_score, role, sla_min = cat_spec
        score = min(99, max(5, base_score + rng.randint(-3, 3)))
        analyst_id = analyst_ids[idx % len(analyst_ids)] if analyst_ids else None

        base_time = created_at or datetime.now(UTC)
        sla_due = base_time + timedelta(minutes=sla_min)

        cur.execute(
            """
            UPDATE app.fraud_cases
            SET suspected_category = %s,
                priority_tier = %s,
                priority_score = %s,
                required_role = %s,
                assigned_analyst_id = COALESCE(%s, assigned_analyst_id),
                sla_due_at = %s
            WHERE id = %s;
            """,
            (cat, tier, score, role, analyst_id, sla_due, case_id),
        )

        # Update assignment cancellation reasons to match category
        if asgn_id:
            reason = "Chuyến đi hoàn thành bình thường"
            actor = None
            if cat == "ERR-02":
                reason = "Tài xế dừng đỗ quá 3 phút không di chuyển đón khách"
                actor = "passenger"
            elif cat == "ERR-03":
                reason = "Tài xế đi ngược hướng điểm đón khách"
                actor = "passenger"
            elif cat == "ERR-05":
                reason = "Tọa độ GPS bất thường từ thiết bị tài xế"
                actor = "platform"
            elif cat == "ERR-01":
                reason = "Tài xế tự ý hủy chuyến sau khi nhận cuốc"
                actor = "driver"
            elif cat == "ERR-04":
                reason = "Chuyến xe có lộ trình bất thường nghi vấn ảo"
                actor = "platform"

            cur.execute(
                """
                UPDATE app.trip_assignments
                SET cancellation_reason = %s,
                    cancellation_actor = %s
                WHERE id = %s;
                """,
                (reason, actor, asgn_id),
            )

    return len(cases)


def enrich_telemetry(cur) -> int:
    """Generate realistic kinematic trajectories for all assignments."""
    if has_preserved_road_dataset(cur):
        return 0
    cur.execute(
        """
        SELECT a.id as asgn_id, a.trip_id, a.driver_id, t.organization_id,
               fc.suspected_category,
               ST_X(t.pickup::geometry) as p_lon, ST_Y(t.pickup::geometry) as p_lat,
               ST_X(t.dropoff::geometry) as d_lon, ST_Y(t.dropoff::geometry) as d_lat,
               t.created_at
        FROM app.trip_assignments a
        JOIN app.trips t ON a.trip_id = t.id
        LEFT JOIN app.fraud_cases fc ON fc.assignment_id = a.id
        WHERE (
            EXISTS (
                SELECT 1 FROM app.simulation_labels sl
                WHERE sl.assignment_id = a.id
            ) OR EXISTS (
                SELECT 1 FROM app.route_snapshots rs
                WHERE rs.assignment_id = a.id
                  AND rs.provider = 'synthetic-straight-line'
            )
        )
        AND NOT EXISTS (
            SELECT 1 FROM app.telemetry_points tp
            WHERE tp.assignment_id = a.id
        )
        ORDER BY a.id;
        """
    )
    assignments = cur.fetchall()
    total_points = 0

    # This function is for explicit legacy synthetic assignments only.  Never
    # clear shared telemetry or ingest history during a repeatable seed run.
    rng = random.Random(888)
    for asgn_id, trip_id, drv_id, org_id, cat, p_lon, p_lat, d_lon, d_lat, trip_created in assignments:
        p_lon = p_lon or 105.8542
        p_lat = p_lat or 21.0285
        d_lon = d_lon or 105.8600
        d_lat = d_lat or 21.0350
        drv_id = drv_id or uuid.UUID("018f2f4e-3000-7000-8000-000000000001")
        org_id = org_id or uuid.UUID("018f2f4e-0000-7000-8000-000000000001")
        base_time = trip_created or datetime.now(UTC)

        # Initial driver position ~400m - 1200m away from pickup
        init_lon = round(p_lon + rng.uniform(-0.007, 0.007), 6)
        init_lat = round(p_lat + rng.uniform(-0.007, 0.007), 6)

        num_points = 14
        points = []
        for step in range(num_points):
            pt_id = uuid.uuid5(uuid.NAMESPACE_URL, f"greensentinel:legacy-telemetry:{asgn_id}:{step}")
            pt_time = base_time + timedelta(seconds=step * 20)
            alpha = step / float(num_points - 1)

            anomaly_type = None
            anomaly_score = None
            mock_rep = False

            if cat == "ERR-02":
                # Stalled after 2 steps
                if step < 2:
                    cur_lon = init_lon + (p_lon - init_lon) * 0.15 * step
                    cur_lat = init_lat + (p_lat - init_lat) * 0.15 * step
                    speed = round(3.5 + rng.uniform(-0.5, 0.5), 2)
                else:
                    cur_lon = init_lon + (p_lon - init_lon) * 0.25
                    cur_lat = init_lat + (p_lat - init_lat) * 0.25
                    speed = 0.0
                    anomaly_type = "prolonged_stop"
                    anomaly_score = 0.95
            elif cat == "ERR-03":
                # Diverging / Wrong direction
                delta_lon = p_lon - init_lon
                delta_lat = p_lat - init_lat
                cur_lon = init_lon - delta_lon * 0.5 * alpha + rng.uniform(-0.0002, 0.0002)
                cur_lat = init_lat - delta_lat * 0.5 * alpha + rng.uniform(-0.0002, 0.0002)
                speed = round(9.0 + rng.uniform(-1.5, 2.0), 2)
                if step >= 3:
                    anomaly_type = "route_deviation"
                    anomaly_score = 0.88
            elif cat == "ERR-05":
                # Mock location jumps
                if step in (4, 5, 9):
                    cur_lon = init_lon + rng.uniform(-0.03, 0.03)
                    cur_lat = init_lat + rng.uniform(-0.03, 0.03)
                    speed = round(38.0 + rng.uniform(5.0, 20.0), 2)
                    anomaly_type = "mock_location"
                    anomaly_score = 0.98
                    mock_rep = True
                else:
                    cur_lon = init_lon + (p_lon - init_lon) * alpha
                    cur_lat = init_lat + (p_lat - init_lat) * alpha
                    speed = round(8.0 + rng.uniform(-1.0, 1.5), 2)
            else:
                # Nominal trip moving towards pickup
                cur_lon = init_lon + (p_lon - init_lon) * alpha + rng.uniform(-0.0001, 0.0001)
                cur_lat = init_lat + (p_lat - init_lat) * alpha + rng.uniform(-0.0001, 0.0001)
                # S-curve speed acceleration, cruising, deceleration
                if step < 3:
                    speed = round(2.0 + step * 2.5, 2)
                elif step > num_points - 4:
                    speed = round(max(1.0, 8.5 - (step - (num_points - 4)) * 2.2), 2)
                else:
                    speed = round(8.5 + rng.uniform(-1.5, 1.5), 2)

            cur_lon = round(cur_lon, 6)
            cur_lat = round(cur_lat, 6)

            # Continuous bearing calculation
            if step > 0:
                prev_lon, prev_lat = points[-1][0], points[-1][1]
                dx = (cur_lon - prev_lon) * 111320 * math.cos(math.radians(cur_lat))
                dy = (cur_lat - prev_lat) * 110574
                bearing = (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0
                bearing = round(min(359.9, max(0.0, bearing)), 1)
            else:
                bearing = round(rng.uniform(0.0, 359.9), 1)

            # Continuous log-normal GPS CEP accuracy (2.2m to 6.8m)
            accuracy = round(max(2.1, min(7.5, rng.lognormvariate(1.25, 0.25))), 1)

            points.append((cur_lon, cur_lat))

            payload = {
                "position": {"latitude": cur_lat, "longitude": cur_lon, "accuracy_m": accuracy},
                "speed_mps": speed,
                "bearing_deg": bearing,
                "app_state": "foreground",
                "network_state": "online",
                "gps_state": "mock_reported" if mock_rep else "valid",
                "mock_location_reported": mock_rep,
            }
            raw_payload = json.dumps(payload, sort_keys=True).encode("utf-8")
            payload_hash = bytes(hashlib.sha256(raw_payload).digest())

            cur.execute(
                """
                INSERT INTO app.ingest_events
                    (event_id, organization_id, schema_version, event_type, source,
                     occurred_at, received_at, correlation_id, trip_id, assignment_id,
                     driver_id, producer_sequence, payload, payload_hash)
                VALUES
                    (%s, %s, 1, 'telemetry.observed', 'smartphone-app',
                     %s, %s, %s, %s, %s,
                     %s, %s, %s::jsonb, %s);
                """,
                (
                    pt_id,
                    org_id,
                    pt_time,
                    pt_time + timedelta(milliseconds=200),
                    uuid.uuid5(uuid.NAMESPACE_URL, f"greensentinel:legacy-correlation:{asgn_id}:{step}"),
                    trip_id,
                    asgn_id,
                    drv_id,
                    step + 1,
                    json.dumps(payload),
                    payload_hash,
                ),
            )

            cur.execute(
                """
                INSERT INTO app.telemetry_points
                    (event_id, assignment_id, occurred_at, position, speed_mps, bearing_deg,
                     accuracy_m, app_state, network_state, gps_state, mock_location_reported,
                     anomaly_type, anomaly_score)
                VALUES
                    (%s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s, %s,
                     %s, 'foreground', 'online', %s, %s, %s, %s);
                """,
                (
                    pt_id,
                    asgn_id,
                    pt_time,
                    cur_lon,
                    cur_lat,
                    speed,
                    bearing,
                    accuracy,
                    "mock_reported" if mock_rep else "valid",
                    mock_rep,
                    anomaly_type,
                    anomaly_score,
                ),
            )
            total_points += 1

    return total_points


def has_preserved_road_dataset(cur) -> bool:
    """Return whether source-owned road evidence is already present."""
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM app.route_snapshots
            WHERE provenance->>'dataset_version' IS NOT NULL
        ) OR EXISTS (
            SELECT 1 FROM app.ingest_events
            WHERE source = 'road-simulator'
        );
        """
    )
    return bool(cur.fetchone()[0])


def enrich_features_and_assessments(cur) -> int:
    """Generate continuous DAVI scores, stationary durations and authentic legal forensics."""
    cur.execute(
        """
        SELECT c.id as case_id, c.suspected_category, es.id as snapshot_id,
               fs.id as feature_set_id, ma.id as assessment_id
        FROM app.fraud_cases c
        JOIN app.evidence_snapshots es ON es.case_id = c.id
        LEFT JOIN app.feature_sets fs ON fs.evidence_snapshot_id = es.id
        LEFT JOIN app.model_assessments ma ON ma.evidence_snapshot_id = es.id;
        """
    )
    rows = cur.fetchall()
    rng = random.Random(9999)

    for case_id, cat, snap_id, feat_id, assess_id in rows:
        if cat == "ERR-02":
            davi = round(rng.uniform(-0.94, -0.72), 3)
            stat_dur = rng.randint(210, 340)
            conf = round(rng.uniform(0.89, 0.96), 2)
            brief = (
                f"Tài xế dừng đỗ cố tình kéo dài {stat_dur}s tại khu vực đón nhằm ép hành khách hủy chuyến "
                "(ERR-02 theo Điều 14.2 Quy chế GreenSM 2026). Chỉ số DAVI âm nghiêm trọng."
            )
            reasons = ["STATIONARY_IN_CLEAR_TRAFFIC", "NEGATIVE_DAVI", "ERR-02_CONFIRMED"]
        elif cat == "ERR-03":
            davi = round(rng.uniform(-0.85, -0.45), 3)
            stat_dur = rng.randint(0, 15)
            conf = round(rng.uniform(0.85, 0.91), 2)
            brief = (
                "Lộ trình xe di chuyển ngược hướng điểm đón / lệch tuyến nghiêm trọng "
                "(ERR-03 theo Điều 16.1 Quy chế GreenSM 2026). Phương tiện duy trì vận tốc nhưng khoảng cách tới khách tăng liên tục."
            )
            reasons = ["WRONG_DIRECTION_DIVERGENCE", "OFF_ROUTE_EXCEEDED"]
        elif cat == "ERR-05":
            davi = round(rng.uniform(0.02, 0.25), 3)
            stat_dur = rng.randint(0, 20)
            conf = round(rng.uniform(0.96, 0.99), 2)
            brief = (
                "Phát hiện ứng dụng Mock Location can thiệp tọa độ GPS thiết bị tài xế "
                "(ERR-05 theo Điều 15.3 Quy chế GreenSM 2026). Vận tốc nhảy đột biến."
            )
            reasons = ["MOCK_LOCATION_API_ACTIVE", "SPEED_JUMP_ANOMALY"]
        elif cat == "ERR-01":
            davi = round(rng.uniform(-0.15, 0.10), 3)
            stat_dur = rng.randint(10, 35)
            conf = round(rng.uniform(0.78, 0.86), 2)
            brief = (
                "Tài xế tự ý hủy chuyến sau khi nhận cuốc không có lý do chính đáng "
                "(ERR-01 theo Điều 14.1 Quy chế GreenSM 2026)."
            )
            reasons = ["UNJUSTIFIED_DRIVER_CANCELLATION"]
        elif cat == "ERR-04":
            davi = round(rng.uniform(0.82, 0.94), 3)
            stat_dur = rng.randint(0, 10)
            conf = round(rng.uniform(0.91, 0.96), 2)
            brief = "Dấu hiệu cuốc xe ảo thông đồng tạo doanh số giả lập (ERR-04 theo Điều 17.2 Quy chế GreenSM 2026)."
            reasons = ["CIRCULAR_ROUTE_COLLUSION", "DEVICE_FINGERPRINT_MATCH"]
        else:
            davi = round(rng.uniform(0.75, 0.96), 3)
            stat_dur = rng.randint(5, 25)
            conf = round(rng.uniform(0.92, 0.98), 2)
            brief = "Chuyến đi hoàn thành bình thường, telemetry chuẩn tắc không có dấu hiệu bất thường."
            reasons = ["NOMINAL_TRIP_PROGRESS", "CLEAN_TELEMETRY"]

        features_payload = {
            "davi": davi,
            "stationary_duration_s": stat_dur,
            "category": cat,
        }

        if feat_id:
            cur.execute(
                """
                UPDATE app.feature_sets
                SET davi = %s,
                    stationary_duration_s = %s,
                    features = %s::jsonb
                WHERE id = %s;
                """,
                (davi, stat_dur, json.dumps(features_payload), feat_id),
            )

        if assess_id:
            cur.execute(
                """
                UPDATE app.model_assessments
                SET category = %s,
                    confidence = %s,
                    forensic_brief = %s,
                    reason_codes = %s::jsonb
                WHERE id = %s;
                """,
                (cat, conf, brief, json.dumps(reasons), assess_id),
            )

    return len(rows)


def enrich_route_snapshots(cur) -> int:
    """Generate shortest route snapshots for pickup and destination legs for all assignments."""
    cur.execute(
        """
        SELECT a.id, t.id as trip_id,
               ST_X(t.pickup::geometry) as p_lon, ST_Y(t.pickup::geometry) as p_lat,
               ST_X(t.dropoff::geometry) as d_lon, ST_Y(t.dropoff::geometry) as d_lat,
               (
                   SELECT jsonb_build_array(ST_X(tp.position::geometry), ST_Y(tp.position::geometry))
                   FROM app.telemetry_points tp
                   WHERE tp.assignment_id = a.id
                   ORDER BY tp.occurred_at ASC
                   LIMIT 1
               ) as initial_driver_pos
        FROM app.trip_assignments a
        JOIN app.trips t ON a.trip_id = t.id
        WHERE NOT EXISTS (
            SELECT 1 FROM app.route_snapshots rs WHERE rs.assignment_id = a.id
        );
        """
    )
    missing = cur.fetchall()
    created = 0
    for asgn_id, trip_id, p_lon, p_lat, d_lon, d_lat, init_pos in missing:
        init_lon = init_pos[0] if init_pos else (p_lon - 0.003)
        init_lat = init_pos[1] if init_pos else (p_lat - 0.003)

        # 1. Pickup leg: driver initial point -> pickup
        pickup_line = {
            "type": "LineString",
            "coordinates": [
                [init_lon, init_lat],
                [(init_lon + p_lon) / 2, (init_lat + p_lat) / 2],
                [p_lon, p_lat],
            ],
        }
        dx1 = (p_lon - init_lon) * 111320 * math.cos(math.radians(p_lat))
        dy1 = (p_lat - init_lat) * 110574
        dist1 = int(math.sqrt(dx1 * dx1 + dy1 * dy1) * 1.15) or 500
        dur1 = int(dist1 / 7.0) or 90

        cur.execute(
            """
            INSERT INTO app.route_snapshots
                (assignment_id, calculated_at, provider, routing_profile, map_version, route, distance_m, duration_s, leg)
            VALUES
                (%s, now(), 'osrm', 'car', 'v2026.09',
                 ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)::geography,
                 %s, %s, 'pickup')
            ON CONFLICT (assignment_id, leg) DO NOTHING;
            """,
            (asgn_id, json.dumps(pickup_line), dist1, dur1),
        )

        # 2. Destination leg: pickup -> dropoff
        dest_line = {
            "type": "LineString",
            "coordinates": [
                [p_lon, p_lat],
                [(p_lon + d_lon) / 2, (p_lat + d_lat) / 2],
                [d_lon, d_lat],
            ],
        }
        dx2 = (d_lon - p_lon) * 111320 * math.cos(math.radians(d_lat))
        dy2 = (d_lat - p_lat) * 110574
        dist2 = int(math.sqrt(dx2 * dx2 + dy2 * dy2) * 1.18) or 1200
        dur2 = int(dist2 / 8.5) or 180

        cur.execute(
            """
            INSERT INTO app.route_snapshots
                (assignment_id, calculated_at, provider, routing_profile, map_version, route, distance_m, duration_s, leg)
            VALUES
                (%s, now(), 'osrm', 'car', 'v2026.09',
                 ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)::geography,
                 %s, %s, 'destination')
            ON CONFLICT (assignment_id, leg) DO NOTHING;
            """,
            (asgn_id, json.dumps(dest_line), dist2, dur2),
        )
        created += 1

    return created


def enrich_analyst_cockpit_evidence(cur) -> dict[str, int]:
    """Populate deterministic, provenance-labelled evidence for every demo case.

    Existing normalized tables remain authoritative for traffic, workflow and chat.
    The optional cockpit_evidence JSONB column carries weather/probe/reliability and
    motivation observations until those domains have dedicated tables.
    """
    cur.execute(
        """
        SELECT c.id, c.assignment_id, c.organization_id, c.created_at,
               c.suspected_category, c.assigned_analyst_id,
               cas.id AS session_id
        FROM app.fraud_cases c
        LEFT JOIN app.case_agent_sessions cas ON cas.case_id = c.id
        WHERE c.id::text LIKE '018f2f4e-%'
        ORDER BY c.created_at NULLS LAST, c.id
        """
    )
    cases = cur.fetchall()
    if not cases:
        return {"cases": 0, "traffic": 0, "workflow": 0, "messages": 0}

    cur.execute(
        """SELECT 1 FROM information_schema.columns
           WHERE table_schema = 'app' AND table_name = 'fraud_cases'
             AND column_name = 'cockpit_evidence'"""
    )
    has_cockpit_evidence = cur.fetchone() is not None
    traffic_count = workflow_count = message_count = 0

    for idx, row in enumerate(cases):
        case_id, assignment_id, org_id, created_at, category, analyst_id, session_id = row
        base = created_at or datetime(2026, 1, 1, tzinfo=UTC)
        seed = int(hashlib.sha256(str(case_id).encode()).hexdigest()[:8], 16)
        speed = round(2.8 + (seed % 11) * 0.37, 2)
        congestion = "heavy" if category in ("ERR-02", "ERR-03") and seed % 3 == 0 else "moderate"
        traffic_id = uuid.uuid5(NAMESPACE_SEED, f"cockpit-traffic:{case_id}")
        cur.execute(
            """INSERT INTO app.traffic_observations
                (id, assignment_id, observed_at, valid_until, average_speed_mps,
                 congestion_level, source, is_simulated, provenance)
             VALUES (%s,%s,%s,%s,%s,%s,'demo-telemetry',true,%s::jsonb)
             ON CONFLICT (id) DO UPDATE SET average_speed_mps=EXCLUDED.average_speed_mps,
                 congestion_level=EXCLUDED.congestion_level,
                 provenance=EXCLUDED.provenance""",
            (
                traffic_id,
                assignment_id,
                base,
                base + timedelta(minutes=10),
                speed,
                congestion,
                json.dumps({"source": "synthetic_seed", "seed": seed, "case_id": str(case_id)}),
            ),
        )
        traffic_count += 1

        evidence = {
            "provenance": {"source": "synthetic_seed", "seed": seed, "case_id": str(case_id)},
            "traffic": {"average_speed_mps": speed, "congestion_level": congestion, "source": "demo-telemetry"},
            "ambient": {
                "is_simulated": True,
                "temperature_c": round(24.0 + (seed % 9) * 0.6, 1),
                "relative_humidity_pct": 62 + seed % 24,
                "precipitation_mm": round((seed % 4) * 0.4, 1),
                "condition": "light rain" if seed % 4 == 0 else "partly cloudy",
            },
            "probe": {
                "is_simulated": True,
                "status": "pass" if seed % 7 else "degraded",
                "latency_ms": 80 + (seed % 13) * 7,
                "source": "synthetic_probe",
            },
            "sensor_reliability": {
                "is_simulated": True,
                "gps": round(0.91 + (seed % 8) * 0.01, 2),
                "gps_accuracy_m": round(4.0 + (seed % 7) * 0.4, 1),
                "ping_latency_ms": 80 + (seed % 13) * 7,
                "network": round(0.88 + (seed % 10) * 0.01, 2),
                "battery_pct": 54 + (seed * 3) % 42,
            },
            "stall_davi_points": [
                {
                    "is_simulated": True,
                    "offset_s": n * 30,
                    "davi": round(-0.42 + n * 0.04 + (seed % 5) * 0.01, 3),
                    "speed_mps": 0.6 + n * 0.2,
                }
                for n in range(4)
            ],
            "motivation_assessment": {
                "is_simulated": True,
                "status": "assessed",
                "signal": "limited",
                "narrative": "Demo economic/trip evidence only; no intentionality claim.",
                "evidence_refs": ["driver_profile", "trip_fare"],
            },
            "willingness_assessment": {
                "is_simulated": True,
                "status": "assessed",
                "signal": "responsive",
                "narrative": "Based on the seeded driver reply.",
                "evidence_refs": ["driver_submission"],
            },
        }
        if has_cockpit_evidence:
            cur.execute(
                """UPDATE app.fraud_cases SET cockpit_evidence=%s::jsonb, updated_at=updated_at
                   WHERE id=%s AND (cockpit_evidence IS NULL OR cockpit_evidence = '{}'::jsonb
                          OR cockpit_evidence->'provenance'->>'source'='synthetic_seed')""",
                (json.dumps(evidence, ensure_ascii=False), case_id),
            )

        workflow_trace = {
            "timeline": [
                {"event_type": "case_opened", "occurred_at": base.isoformat(), "label": "Case opened"},
                {
                    "event_type": "evidence_reviewed",
                    "occurred_at": (base + timedelta(minutes=2)).isoformat(),
                    "label": "Evidence reviewed",
                },
            ],
            "provenance": {"source": "synthetic_seed", "seed": seed},
        }
        cur.execute(
            """UPDATE app.fraud_cases
               SET workflow_trace = CASE WHEN workflow_trace IS NULL OR workflow_trace = '{}'::jsonb THEN %s::jsonb ELSE workflow_trace END,
                   workflow_draft = CASE WHEN workflow_draft IS NULL OR workflow_draft = '{}'::jsonb THEN %s::jsonb ELSE workflow_draft END
             WHERE id=%s""",
            (
                json.dumps(workflow_trace),
                json.dumps(
                    {
                        "text": "Synthetic evidence review draft",
                        "version": 1,
                        "updated_at": (base + timedelta(minutes=2)).isoformat(),
                        "updated_by": "synthetic_seed",
                    }
                ),
                case_id,
            ),
        )
        workflow_count += 1

        if session_id is None:
            session_id = uuid.uuid5(NAMESPACE_SEED, f"cockpit-session:{case_id}")
            cur.execute(
                """INSERT INTO app.case_agent_sessions (id,organization_id,case_id,created_by,created_at)
                   VALUES (%s,%s,%s,%s,%s) ON CONFLICT (case_id) DO NOTHING""",
                (session_id, org_id, case_id, analyst_id, base),
            )
            cur.execute("SELECT id FROM app.case_agent_sessions WHERE case_id=%s", (case_id,))
            session_id = cur.fetchone()[0]
        for seq, (role, text) in enumerate(
            (
                ("driver", "Tôi đã đến gần điểm đón và chờ khách theo ứng dụng."),
                ("driver_agent", "Đã ghi nhận trao đổi và yêu cầu bổ sung bằng chứng."),
            ),
            1,
        ):
            turn_id = uuid.uuid5(NAMESPACE_SEED, f"cockpit-turn:{case_id}:{seq}")
            cur.execute(
                """INSERT INTO app.case_agent_messages (id,session_id,turn_id,role,content,created_at)
                   VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (session_id,turn_id,role) DO NOTHING""",
                (
                    uuid.uuid5(NAMESPACE_SEED, f"cockpit-message:{case_id}:{seq}"),
                    session_id,
                    turn_id,
                    role,
                    text,
                    base + timedelta(minutes=seq),
                ),
            )
            message_count += 1
    return {"cases": len(cases), "traffic": traffic_count, "workflow": workflow_count, "messages": message_count}


def seed_issue_191_traffic_acceptance(cur) -> int:
    """Create one available ERR-01 case with three corridor/time peer trips."""
    cur.execute(
        """
        SELECT t.organization_id, t.passenger_id, t.requested_at, t.pickup, t.dropoff,
               t.requested_service_class, a.driver_id, a.vehicle_id,
               min(tp.occurred_at), max(tp.occurred_at)
        FROM app.fraud_cases c
        JOIN app.trip_assignments a ON a.id = c.assignment_id
        JOIN app.trips t ON t.id = a.trip_id
        JOIN app.telemetry_points tp ON tp.assignment_id = a.id
        WHERE c.id = %s::uuid AND a.id = %s::uuid
        GROUP BY t.organization_id, t.passenger_id, t.requested_at, t.pickup, t.dropoff,
                 t.requested_service_class, a.driver_id, a.vehicle_id
        """,
        (ISSUE_191_CASE_ID, ISSUE_191_ASSIGNMENT_ID),
    )
    target = cur.fetchone()
    if target is None:
        raise RuntimeError("Issue #191 acceptance target case or telemetry is missing")

    (
        organization_id,
        passenger_id,
        requested_at,
        pickup,
        dropoff,
        service_class,
        driver_id,
        vehicle_id,
        window_start,
        window_end,
    ) = target

    cur.execute("DELETE FROM app.review_leases WHERE case_id = %s::uuid", (ISSUE_191_CASE_ID,))
    cur.execute(
        """
        UPDATE app.fraud_cases
        SET status = 'ready', suspected_category = 'ERR-01', assigned_analyst_id = NULL,
            updated_at = now(), resolved_at = NULL
        WHERE id = %s::uuid
        """,
        (ISSUE_191_CASE_ID,),
    )

    cur.execute(
        "SELECT event_id FROM app.ingest_events WHERE assignment_id::text = ANY(%s)",
        (list(ISSUE_191_PEER_ASSIGNMENT_IDS),),
    )
    old_event_ids = [row[0] for row in cur.fetchall()]
    if old_event_ids:
        cur.execute("DELETE FROM app.telemetry_points WHERE event_id = ANY(%s)", (old_event_ids,))
    cur.execute(
        "DELETE FROM app.ingest_events WHERE assignment_id::text = ANY(%s)",
        (list(ISSUE_191_PEER_ASSIGNMENT_IDS),),
    )
    cur.execute(
        "DELETE FROM app.trip_assignments WHERE id::text = ANY(%s)",
        (list(ISSUE_191_PEER_ASSIGNMENT_IDS),),
    )
    cur.execute("DELETE FROM app.trips WHERE id::text = ANY(%s)", (list(ISSUE_191_PEER_TRIP_IDS),))

    cur.execute(
        """
        SELECT occurred_at, ST_X(position::geometry), ST_Y(position::geometry), bearing_deg,
               accuracy_m, app_state, network_state, gps_state
        FROM app.telemetry_points
        WHERE assignment_id = %s::uuid AND position IS NOT NULL
        ORDER BY occurred_at
        """,
        (ISSUE_191_ASSIGNMENT_ID,),
    )
    target_points = cur.fetchall()
    if not target_points:
        raise RuntimeError("Issue #191 acceptance target has no positioned telemetry")

    for peer_number, (trip_id, assignment_id, speed_mps) in enumerate(
        zip(ISSUE_191_PEER_TRIP_IDS, ISSUE_191_PEER_ASSIGNMENT_IDS, ISSUE_191_PEER_SPEEDS_MPS, strict=True),
        start=1,
    ):
        cur.execute(
            """
            INSERT INTO app.trips (
                id, organization_id, passenger_id, requested_at, pickup, dropoff,
                requested_service_class, status, completed_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'completed', %s)
            """,
            (
                trip_id,
                organization_id,
                passenger_id,
                requested_at,
                pickup,
                dropoff,
                service_class,
                window_end,
            ),
        )
        cur.execute(
            """
            INSERT INTO app.trip_assignments (
                id, trip_id, driver_id, vehicle_id, state, offered_at, accepted_at,
                arrived_at, started_at, ended_at
            ) VALUES (%s, %s, %s, %s, 'completed', %s, %s, %s, %s, %s)
            """,
            (
                assignment_id,
                trip_id,
                driver_id,
                vehicle_id,
                window_start - timedelta(minutes=5),
                window_start - timedelta(minutes=4),
                window_start - timedelta(minutes=2),
                window_start,
                window_end,
            ),
        )

        for sequence, point in enumerate(target_points, start=1):
            occurred_at, longitude, latitude, bearing, accuracy, app_state, network_state, _gps_state = point
            event_id = uuid.uuid5(ISSUE_191_EVENT_NAMESPACE, f"{assignment_id}:{sequence}")
            payload = {
                "source": "issue_191_acceptance_seed",
                "peer_number": peer_number,
                "sequence": sequence,
            }
            payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            cur.execute(
                """
                INSERT INTO app.ingest_events (
                    event_id, organization_id, schema_version, event_type, source,
                    occurred_at, correlation_id, trip_id, assignment_id, driver_id,
                    producer_sequence, payload, payload_hash
                ) VALUES (%s, %s, 1, 'telemetry.location', 'issue_191_acceptance_seed',
                          %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                """,
                (
                    event_id,
                    organization_id,
                    occurred_at,
                    assignment_id,
                    trip_id,
                    assignment_id,
                    driver_id,
                    sequence,
                    payload_json,
                    hashlib.sha256(payload_json.encode()).digest(),
                ),
            )
            cur.execute(
                """
                INSERT INTO app.telemetry_points (
                    event_id, assignment_id, occurred_at, position, speed_mps, bearing_deg,
                    accuracy_m, app_state, network_state, gps_state, mock_location_reported
                ) VALUES (
                    %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                    %s, %s, %s, %s, %s, %s, false
                )
                """,
                (
                    event_id,
                    assignment_id,
                    occurred_at,
                    longitude,
                    latitude,
                    speed_mps,
                    bearing,
                    min(accuracy or 10.0, 100.0),
                    app_state or "foreground",
                    network_state or "online",
                    "valid",
                ),
            )

    return len(ISSUE_191_PEER_ASSIGNMENT_IDS)


def enrich_cockpit_evidence_only(database_url: str) -> dict[str, int]:
    """Idempotently (re)apply analyst cockpit evidence to an already-enriched database."""
    import psycopg

    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute("SET search_path = app, extensions, public;")
        cur.execute("SET session_replication_role = 'replica';")
        stats = enrich_analyst_cockpit_evidence(cur)
        cur.execute("SET session_replication_role = 'origin';")
        conn.commit()
    return stats


def enrich(database_url: str, reference: date = date.today()) -> dict[str, int]:
    import psycopg

    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute("SET search_path = app, extensions, public;")
        cur.execute("SET session_replication_role = 'replica';")
        n_drivers = enrich_drivers(cur, reference)
        n_passengers = enrich_passengers(cur)
        n_vehicles = enrich_vehicles(cur)
        if has_preserved_road_dataset(cur):
            cockpit = enrich_analyst_cockpit_evidence(cur)
            cur.execute("SET session_replication_role = 'origin';")
            conn.commit()
            return {
                "drivers_enriched": n_drivers,
                "passengers_enriched": n_passengers,
                "vehicles_enriched": n_vehicles,
                "trips_enriched": 0,
                "cases_enriched": 0,
                "telemetry_points_generated": 0,
                "features_assessments_enriched": 0,
                "route_legs_generated": 0,
                "issue_191_peer_trips": 0,
                "cockpit_cases": cockpit["cases"],
                "cockpit_traffic": cockpit["traffic"],
                "cockpit_workflow": cockpit["workflow"],
                "cockpit_messages": cockpit["messages"],
            }
        n_trips = enrich_trips_and_assignments(cur)
        n_cases = enrich_fraud_cases(cur)
        n_points = enrich_telemetry(cur)
        n_features = enrich_features_and_assessments(cur)
        n_routes = enrich_route_snapshots(cur)
        cockpit = enrich_analyst_cockpit_evidence(cur)
        n_issue_191_peers = seed_issue_191_traffic_acceptance(cur)
        cur.execute("SET session_replication_role = 'origin';")
        conn.commit()

    return {
        "drivers_enriched": n_drivers,
        "passengers_enriched": n_passengers,
        "vehicles_enriched": n_vehicles,
        "trips_enriched": n_trips,
        "cases_enriched": n_cases,
        "telemetry_points_generated": n_points,
        "features_assessments_enriched": n_features,
        "route_legs_generated": n_routes,
        "issue_191_peer_trips": n_issue_191_peers,
        "cockpit_cases": cockpit["cases"],
        "cockpit_traffic": cockpit["traffic"],
        "cockpit_workflow": cockpit["workflow"],
        "cockpit_messages": cockpit["messages"],
    }


enrich_all = enrich


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich synthetic drivers, trips, vehicles, telemetry and cases")
    parser.add_argument("--reference-date", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL") or os.environ.get("MIGRATION_DATABASE_URL")
    if not database_url:
        from dotenv import load_dotenv

        load_dotenv(".env")
        database_url = os.environ.get("DATABASE_URL") or os.environ.get("MIGRATION_DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL or MIGRATION_DATABASE_URL is required")

    stats = enrich(database_url, args.reference_date)
    print("Enrichment completed successfully:")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
