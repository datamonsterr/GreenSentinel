"""
Synthetic Dataset Generator for P-063 Driver Incentive Cheating (DIC) Fraud Engine.

Generates:
- 1 Organization (VinFast / GreenSM Mobility)
- 10 Fraud Analysts (Principals + Principal Roles)
- 50 Users / Passengers
- 20 Drivers + 20 Vehicles + 20 Assignments
- 100 Trips (across Hanoi coordinates)
- 100 Trip Assignments
- 100 Fare Quotes & Simulated Payment Transactions
- High-frequency GPS Telemetry points matching schemas/telemetry-event.schema.json
- Route Snapshots (LineString geometry)
- Traffic Observations & Platform Incidents
- Fraud Cases with assigned analysts, priority tiers, and statuses
- Driver Submissions, Passenger Feedback, Evidence Snapshots, Feature Sets, Model Assessments, Review Leases, and Adjudications for test cases
- Simulation Runs and Ground Truth Simulation Labels (DIC, Gridlock, Technical Dropout, Fake GPS, Clean)

Outputs: data/synthetic/seed_data.json
"""

import hashlib
import json
import math
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Fix random seed for full reproducibility
random.seed(42)

BASE_TIME = datetime(2026, 9, 22, 6, 0, 0, tzinfo=UTC)


def hash_payload(data: Any) -> str:
    raw = json.dumps(data, sort_keys=True).encode("utf-8")
    return "\\x" + hashlib.sha256(raw).hexdigest()


def distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_m = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return earth_radius_m * c


def bearing_degrees(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_lambda = math.radians(lon2 - lon1)
    y = math.sin(delta_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)
    deg = math.degrees(math.atan2(y, x))
    return (deg + 360.0) % 360.0


def generate_synthetic_dataset() -> dict[str, Any]:
    random.seed(42)
    # Load landmarks
    landmarks_file = Path("data/real/hanoi_landmarks.json")
    if landmarks_file.exists():
        with open(landmarks_file, encoding="utf-8") as landmark_stream:
            landmarks = json.load(landmark_stream)
    else:
        landmarks = [
            {"name": "Ho Guom", "lat": 21.0285, "lon": 105.8542, "district": "Hoan Kiem"},
            {"name": "Keangnam", "lat": 21.0167, "lon": 105.7839, "district": "Cau Giay"},
            {"name": "Noi Bai", "lat": 21.2212, "lon": 105.8072, "district": "Soc Son"},
        ]

    # 1. Organization
    org_id = "018f2f4e-0000-7000-8000-000000000001"
    organization = {
        "id": org_id,
        "name": "GreenSM Mobility Hanoi Corp",
        "created_at": (BASE_TIME - timedelta(days=30)).isoformat(),
    }

    # 2. 10 Fraud Analysts
    analysts = []
    principal_roles = []
    analyst_names = [
        ("Nguyen Thi Lan", "senior_analyst"),
        ("Tran Van Binh", "senior_analyst"),
        ("Le Hoang Nam", "analyst"),
        ("Pham Minh Duc", "analyst"),
        ("Vu Thi Mai", "analyst"),
        ("Doan Quang Huy", "analyst"),
        ("Hoang Thu Thao", "analyst"),
        ("Bui Anh Tuan", "analyst"),
        ("Dang Ngoc Linh", "analyst"),
        ("Ngo Quoc Bao", "admin"),
    ]
    for i, (name, role) in enumerate(analyst_names):
        p_id = f"018f2f4e-1000-7000-8000-{i + 1:012d}"
        analysts.append(
            {
                "id": p_id,
                "organization_id": org_id,
                "external_subject": f"user_clerk_analyst_{i + 1:03d}",
                "display_name": name,
                "status": "active",
                "created_at": (BASE_TIME - timedelta(days=20)).isoformat(),
            }
        )
        principal_roles.append(
            {"principal_id": p_id, "role": role, "granted_at": (BASE_TIME - timedelta(days=20)).isoformat()}
        )

    # 3. 50 Passengers / Users
    passengers = []
    passenger_first = ["Nguyen", "Tran", "Le", "Pham", "Hoang", "Vu", "Phan", "Bui", "Do", "Dang"]
    passenger_mid = ["Van", "Thi", "Minh", "Thu", "Ngoc", "Duc", "Thanh", "Quang", "Gia", "Hai"]
    passenger_last = ["An", "Binh", "Chau", "Dung", "Hanh", "Khoa", "Linh", "Mai", "Nam", "Phuc"]

    for i in range(50):
        p_id = f"018f2f4e-2000-7000-8000-{i + 1:012d}"
        f = passenger_first[i % len(passenger_first)]
        m = passenger_mid[(i // len(passenger_first)) % len(passenger_mid)]
        last_name = passenger_last[i % len(passenger_last)]
        full_name = f"{f} {m} {last_name}"
        passengers.append(
            {
                "id": p_id,
                "organization_id": org_id,
                "principal_id": None,
                "external_ref": f"pax_sm_{i + 1:04d}",
                "is_synthetic": True,
                "display_name": full_name,
                "created_at": (BASE_TIME - timedelta(days=15)).isoformat(),
            }
        )

    # 4. 20 Drivers & 20 Vehicles & Driver Vehicle Assignments
    drivers = []
    vehicles = []
    driver_vehicle_assignments = []
    partner_types = ["owner_driver", "fleet", "rent_to_own"]
    v_classes = ["GreenCar Standard", "GreenCar Luxury", "GreenBike Fast"]

    driver_last_names = [
        "Hung",
        "Cuong",
        "Thang",
        "Long",
        "Tuan",
        "Dat",
        "Kien",
        "Son",
        "Tung",
        "Thanh",
        "Viet",
        "Hai",
        "Quang",
        "Dung",
        "Huy",
        "Phong",
        "Lam",
        "Bac",
        "Trung",
        "Nam",
    ]
    for i in range(20):
        d_id = f"018f2f4e-3000-7000-8000-{i + 1:012d}"
        v_id = f"018f2f4e-4000-7000-8000-{i + 1:012d}"
        dva_id = f"018f2f4e-5000-7000-8000-{i + 1:012d}"
        driver_name = f"Nguyen {driver_last_names[i]}"
        p_type = partner_types[i % len(partner_types)]
        v_type = "car" if i < 15 else "motorbike"
        s_class = v_classes[i % len(v_classes)]
        plate_prefix = 29 if i < 10 else 30
        plate = f"{plate_prefix}E-{10000 + i * 37}"

        drivers.append(
            {
                "id": d_id,
                "organization_id": org_id,
                "principal_id": None,
                "external_ref": f"drv_gsm_{i + 1:04d}",
                "partner_type": p_type,
                "account_status": "active",
                "is_synthetic": True,
                "display_name": driver_name,
                "avatar_url": f"https://api.dicebear.com/7.x/bottts/svg?seed=drv_gsm_{i + 1:04d}",
                "rating": round(4.65 + (i * 0.015) % 0.32, 2),
                "acceptance_rate": round(90.0 + (i * 0.4) % 9.0, 1),
                "cancellation_rate": round(1.0 + (i * 0.1) % 3.0, 1),
                "total_trips": 500 + i * 115,
                "created_at": (BASE_TIME - timedelta(days=15)).isoformat(),
            }
        )

        vehicles.append(
            {
                "id": v_id,
                "organization_id": org_id,
                "registration_ref": plate,
                "vehicle_type": v_type,
                "service_class": s_class,
                "telemetry_source": "smartphone" if i % 2 == 0 else "tcu",
                "created_at": (BASE_TIME - timedelta(days=15)).isoformat(),
            }
        )

        driver_vehicle_assignments.append(
            {
                "id": dva_id,
                "driver_id": d_id,
                "vehicle_id": v_id,
                "effective_from": (BASE_TIME - timedelta(days=15)).isoformat(),
                "effective_to": None,
            }
        )

    # 5. Policy Versions & Policy Chunks
    policy_id = "018f2f4e-6000-7000-8000-000000000001"
    policy_version = {
        "id": policy_id,
        "version": "v2026.1-q3-anti-cheating",
        "status": "published",
        "effective_from": (BASE_TIME - timedelta(days=60)).isoformat(),
        "effective_to": None,
        "source_hash": "\\x" + hashlib.sha256(b"GreenSM Anti-Cheating Policy v2026.1").hexdigest(),
        "action_matrix": {
            "ERR-01": {"default_sanction": "suspend", "suspension_days": 30},
            "ERR-02": {"default_sanction": "warn", "repeat_sanction": "fine", "fine_amount_vnd": 200000},
            "ERR-05": {"default_sanction": "suspend", "suspension_days": 7},
        },
        "is_demo_policy": True,
        "created_at": (BASE_TIME - timedelta(days=60)).isoformat(),
    }
    policy_chunks = [
        {
            "id": "018f2f4e-6001-7000-8000-000000000001",
            "policy_version_id": policy_id,
            "source_ref": "Quy che Hop tac Kinh doanh GreenSM 2026",
            "section_ref": "Dieu 14.2 - Hanh vi Co tinh Dinh cuoc de Khach huy (DIC)",
            "content": "Tai xe co tinh dung yen hoac di chuyen nguoc huong don khach qua 3 phut khong co ly do chinh dang (ket xe, tai nan) de buoc hanh khach phai huy chuyen se bi coi la hanh vi Driver Incentive Cheating vi pham muc ERR-02.",
            "content_hash": "\\x" + hashlib.sha256(b"Dieu 14.2 GreenSM DIC Policy").hexdigest(),
            "embedding": [0.01] * 1536,
            "embedding_model": "text-embedding-3-small",
        },
        {
            "id": "018f2f4e-6001-7000-8000-000000000002",
            "policy_version_id": policy_id,
            "source_ref": "Quy che Hop tac Kinh doanh GreenSM 2026",
            "section_ref": "Dieu 15.1 - Gian lan GPS va Cong cu Gia lap vi tri (Fake GPS)",
            "content": "Su dung ung dung mock location hoac can thiep phan cung de truyen toa do gia lap len he thong se bi xu ly dinh chi tai khoan lap tuc (ERR-05).",
            "content_hash": "\\x" + hashlib.sha256(b"Dieu 15.1 GreenSM Fake GPS Policy").hexdigest(),
            "embedding": [0.02] * 1536,
            "embedding_model": "text-embedding-3-small",
        },
    ]

    # 6. 100 Trips & Assignments & Cases
    # Distribution of scenarios across 100 trips:
    # 0..24: Intentional DIC (stall / backward heading to induce passenger cancellation) -> ERR-02
    # 25..39: Traffic Gridlock (stalled due to real severe traffic congestion) -> no_violation (guardrail protected)
    # 40..54: Technical Dropout (app crashed / network loss) -> insufficient_evidence / no_violation (incident protected)
    # 55..64: Fake GPS / mock location reported -> ERR-05
    # 65..99: Clean Completed Trips -> no_violation (normal rides)

    trips = []
    trip_assignments = []
    fare_quotes = []
    payment_transactions = []
    fraud_cases = []
    case_assignment_history = []
    review_leases = []
    driver_submissions = []
    evidence_snapshots = []
    feature_sets = []
    model_assessments = []
    adjudications = []
    sanctions = []
    route_snapshots = []
    traffic_observations = []
    platform_incidents = []
    passenger_feedback = []
    telemetry_points = []
    ingest_events = []
    simulation_runs = []
    simulation_labels = []

    # Create 5 simulation runs
    scenarios = ["intentional_dic", "traffic_gridlock", "technical_dropout", "fake_gps", "gps_jitter"]
    sim_run_ids = {}
    for i, scen in enumerate(scenarios):
        s_id = f"018f2f4e-7000-7000-8000-{i + 1:012d}"
        sim_run_ids[scen] = s_id
        simulation_runs.append(
            {
                "id": s_id,
                "organization_id": org_id,
                "scenario": scen,
                "seed": 42 + i,
                "generator_version": "v1.0.0-synthetic-eda",
                "status": "completed",
                "simulated_clock_origin": BASE_TIME.isoformat(),
                "started_at": BASE_TIME.isoformat(),
                "finished_at": (BASE_TIME + timedelta(hours=4)).isoformat(),
                "requested_by": analysts[0]["id"],
                "created_at": BASE_TIME.isoformat(),
            }
        )

    for trip_idx in range(100):
        t_id = f"018f2f4e-8000-7000-8000-{trip_idx + 1:012d}"
        asgn_id = f"018f2f4e-9000-7000-8000-{trip_idx + 1:012d}"
        case_id = f"018f2f4e-a000-7000-8000-{trip_idx + 1:012d}"
        pax = passengers[trip_idx % len(passengers)]
        drv = drivers[trip_idx % len(drivers)]
        veh = vehicles[trip_idx % len(vehicles)]
        assigned_analyst = analysts[trip_idx % len(analysts)]

        # Determine Scenario
        if trip_idx < 25:
            scen = "intentional_dic"
            expected_category = "ERR-02"
            expected_guardrail = "none"
            trip_status = "cancelled"
            asgn_state = "cancelled"
            prio_tier = 0
            prio_score = 90 + (trip_idx % 10)
            case_status = "ready" if trip_idx < 15 else "in_review"
        elif trip_idx < 40:
            scen = "traffic_gridlock"
            # Keep one active route-deviation claim for hosted traffic
            # corroboration. The remaining gridlock cases exercise dismissal.
            expected_category = "ERR-01" if trip_idx == 32 else "no_violation"
            expected_guardrail = "heavy_congestion_detected"
            trip_status = "cancelled"
            asgn_state = "cancelled"
            prio_tier = 2
            prio_score = 30 + (trip_idx % 10)
            case_status = "resolved" if trip_idx < 32 else "ready"
        elif trip_idx < 55:
            scen = "technical_dropout"
            expected_category = "insufficient_evidence"
            expected_guardrail = "app_crash_incident"
            trip_status = "cancelled"
            asgn_state = "cancelled"
            prio_tier = 2
            prio_score = 25 + (trip_idx % 10)
            case_status = "evidence_requested" if trip_idx < 48 else "ready"
        elif trip_idx < 65:
            scen = "fake_gps"
            expected_category = "ERR-05"
            expected_guardrail = "mock_provider_flag"
            trip_status = "cancelled"
            asgn_state = "cancelled"
            prio_tier = 0
            prio_score = 95
            case_status = "escalated" if trip_idx < 60 else "ready"
        else:
            scen = "gps_jitter"  # clean trips with slight GPS jitter
            expected_category = "no_violation"
            expected_guardrail = "normal_trip_flow"
            trip_status = "completed"
            asgn_state = "completed"
            prio_tier = 2
            prio_score = 10
            case_status = "resolved"

        req_time = BASE_TIME + timedelta(minutes=trip_idx * 7)
        matched_time = req_time + timedelta(seconds=25)
        end_time = req_time + timedelta(minutes=15)

        # Geographic landmarks
        lm_pickup = landmarks[trip_idx % len(landmarks)]
        lm_dropoff = landmarks[(trip_idx + 7) % len(landmarks)]

        # Driver starting point near pickup (~500m to 1.5km away)
        drv_start_lat = lm_pickup["lat"] + (random.uniform(-0.01, 0.01))
        drv_start_lon = lm_pickup["lon"] + (random.uniform(-0.01, 0.01))

        # WKT strings for PostGIS: POINT(lon lat)
        pickup_wkt = f"POINT({lm_pickup['lon']:.6f} {lm_pickup['lat']:.6f})"
        dropoff_wkt = f"POINT({lm_dropoff['lon']:.6f} {lm_dropoff['lat']:.6f})"

        trips.append(
            {
                "id": t_id,
                "organization_id": org_id,
                "passenger_id": pax["id"],
                "requested_at": req_time.isoformat(),
                "pickup": pickup_wkt,
                "dropoff": dropoff_wkt,
                "requested_service_class": veh["service_class"],
                "status": trip_status,
                "cancelled_at": end_time.isoformat() if trip_status == "cancelled" else None,
                "completed_at": end_time.isoformat() if trip_status == "completed" else None,
                "created_at": req_time.isoformat(),
                "pickup_name": lm_pickup["name"],
                "dropoff_name": lm_dropoff["name"],
                "pickup_address": lm_pickup["name"],
                "dropoff_address": lm_dropoff["name"],
                "district": lm_pickup.get("district"),
                "match_type": "now" if trip_idx % 2 == 0 else "auto",
            }
        )

        trip_assignments.append(
            {
                "id": asgn_id,
                "trip_id": t_id,
                "driver_id": drv["id"],
                "vehicle_id": veh["id"],
                "state": asgn_state,
                "offered_at": req_time.isoformat(),
                "accepted_at": matched_time.isoformat(),
                "arrived_at": None if trip_status == "cancelled" else (req_time + timedelta(minutes=3)).isoformat(),
                "started_at": None if trip_status == "cancelled" else (req_time + timedelta(minutes=4)).isoformat(),
                "ended_at": end_time.isoformat(),
                "cancellation_actor": "passenger" if trip_status == "cancelled" else None,
                "cancellation_reason": "Driver stalled / did not move toward pickup"
                if scen == "intentional_dic"
                else "Trip completed normally",
                "created_at": matched_time.isoformat(),
            }
        )

        # Fare & Payment
        dist_m = int(distance_meters(lm_pickup["lat"], lm_pickup["lon"], lm_dropoff["lat"], lm_dropoff["lon"]))
        est_fare_vnd = max(25000, int((dist_m / 1000.0) * 14000))
        fare_quotes.append(
            {
                "id": f"018f2f4e-b000-7000-8000-{trip_idx + 1:012d}",
                "trip_id": t_id,
                "version": 1,
                "currency": "VND",
                "estimated_amount_minor": est_fare_vnd * 100,
                "estimated_distance_m": dist_m,
                "estimated_duration_s": int(dist_m / 6.0),
                "quoted_at": req_time.isoformat(),
            }
        )

        payment_transactions.append(
            {
                "id": f"018f2f4e-c000-7000-8000-{trip_idx + 1:012d}",
                "trip_id": t_id,
                "kind": "refund" if trip_status == "cancelled" else "charge",
                "amount_minor": est_fare_vnd * 100,
                "currency": "VND",
                "status": "succeeded",
                "provider_ref": f"pay_txn_{trip_idx + 1:05d}",
                "is_simulated": True,
                "occurred_at": end_time.isoformat(),
            }
        )

        # Synthetic straight segments are visualization evidence, never road shortest paths.
        for leg, suffix, start, end in (
            ("pickup", "d100", (drv_start_lon, drv_start_lat), (lm_pickup["lon"], lm_pickup["lat"])),
            ("destination", "d000", (lm_pickup["lon"], lm_pickup["lat"]), (lm_dropoff["lon"], lm_dropoff["lat"])),
        ):
            leg_distance = int(distance_meters(start[1], start[0], end[1], end[0]))
            route_snapshots.append(
                {
                    "id": f"018f2f4e-{suffix}-7000-8000-{trip_idx + 1:012d}",
                    "assignment_id": asgn_id,
                    "leg": leg,
                    "calculated_at": matched_time.isoformat(),
                    "provider": "synthetic-straight-line",
                    "routing_profile": "driving-car",
                    "map_version": "synthetic-v1",
                    "route": f"LINESTRING({start[0]:.6f} {start[1]:.6f}, {end[0]:.6f} {end[1]:.6f})",
                    "distance_m": leg_distance,
                    "duration_s": int(leg_distance / 6.0),
                    "provenance": {"origin": "synthetic", "is_shortest_path": False},
                }
            )

        # Traffic Observations
        congestion = "heavy" if scen == "traffic_gridlock" else ("clear" if scen == "intentional_dic" else "moderate")
        traffic_speed = 3.0 if scen == "traffic_gridlock" else 9.5
        traffic_observations.append(
            {
                "id": f"018f2f4e-e000-7000-8000-{trip_idx + 1:012d}",
                "assignment_id": asgn_id,
                "observed_at": matched_time.isoformat(),
                "valid_until": (matched_time + timedelta(minutes=30)).isoformat(),
                "average_speed_mps": traffic_speed,
                "congestion_level": congestion,
                "source": "tomtom-realtime",
                "is_simulated": True,
                "provenance": {"sensor_id": f"traffic_cam_hn_{trip_idx % 5 + 1:02d}"},
            }
        )

        # Platform Incidents (app crash / network dropout)
        if scen == "technical_dropout":
            platform_incidents.append(
                {
                    "id": f"018f2f4e-f000-7000-8000-{trip_idx + 1:012d}",
                    "assignment_id": asgn_id,
                    "incident_type": "app_crash",
                    "state": "observed",
                    "started_at": (matched_time + timedelta(minutes=2)).isoformat(),
                    "ended_at": end_time.isoformat(),
                    "source_event_id": None,
                    "details": {"exception": "SIGSEGV in RenderEngine", "os": "Android 15"},
                }
            )

        # Passenger Feedback
        if scen == "intentional_dic":
            passenger_feedback.append(
                {
                    "id": f"018f2f4e-0100-7000-8000-{trip_idx + 1:012d}",
                    "assignment_id": asgn_id,
                    "submitted_at": end_time.isoformat(),
                    "reason_code": "DRIVER_NOT_MOVING",
                    "statement": "Tài xế đứng yên một chỗ hơn 4 phút không chịu đi đón, gọi điện không phản hồi. Buộc phải hủy chuyến.",
                    "is_synthetic": True,
                }
            )

        # Fraud Case
        fraud_cases.append(
            {
                "id": case_id,
                "organization_id": org_id,
                "assignment_id": asgn_id,
                "status": case_status,
                "suspected_category": expected_category
                if case_status in ("ready", "in_review", "resolved", "escalated")
                else None,
                "priority_tier": prio_tier,
                "priority_score": prio_score,
                "priority_rule_version": "v1.2.0-priority-rules",
                "assigned_analyst_id": assigned_analyst["id"],
                "required_role": "analyst" if prio_tier > 0 else "senior_analyst",
                "version": 2 if case_status == "resolved" else 1,
                "sla_due_at": (matched_time + timedelta(minutes=30)).isoformat(),
                "created_at": matched_time.isoformat(),
                "updated_at": end_time.isoformat(),
                "resolved_at": end_time.isoformat() if case_status == "resolved" else None,
            }
        )

        # Simulation Label
        simulation_labels.append(
            {
                "simulation_run_id": sim_run_ids[scen],
                "assignment_id": asgn_id,
                "expected_category": expected_category,
                "expected_guardrail": expected_guardrail,
                "expected_outcome": "fine"
                if expected_category == "ERR-02"
                else ("suspend" if expected_category == "ERR-05" else "dismiss"),
            }
        )

        # Case Assignment History
        case_assignment_history.append(
            {
                "id": f"018f2f4e-0200-7000-8000-{trip_idx + 1:012d}",
                "case_id": case_id,
                "from_analyst_id": None,
                "to_analyst_id": assigned_analyst["id"],
                "to_required_role": "analyst" if prio_tier > 0 else "senior_analyst",
                "assigned_by": analysts[-1]["id"],  # Ngo Quoc Bao (admin)
                "reason": "Automatic queue assignment based on workload and tier",
                "assigned_at": matched_time.isoformat(),
            }
        )

        # Review Lease (for in_review cases)
        if case_status == "in_review":
            review_leases.append(
                {
                    "case_id": case_id,
                    "analyst_id": assigned_analyst["id"],
                    "token_hash": "\\x" + hashlib.sha256(f"lease_token_{trip_idx}".encode()).hexdigest(),
                    "case_version": 1,
                    "evidence_snapshot_id": f"018f2f4e-0300-7000-8000-{trip_idx + 1:012d}",
                    "acquired_at": matched_time.isoformat(),
                    "expires_at": (matched_time + timedelta(minutes=15)).isoformat(),
                }
            )

        # Driver Submission
        if scen == "intentional_dic":
            driver_submissions.append(
                {
                    "id": f"018f2f4e-0400-7000-8000-{trip_idx + 1:012d}",
                    "case_id": case_id,
                    "status": "present",
                    "statement": "Đường đông không di chuyển nhanh được, khách không chờ được tự hủy.",
                    "deadline_at": (end_time + timedelta(hours=2)).isoformat(),
                    "received_at": (end_time + timedelta(minutes=10)).isoformat(),
                    "provenance": {"channel": "driver_app"},
                }
            )
        elif scen == "traffic_gridlock":
            driver_submissions.append(
                {
                    "id": f"018f2f4e-0400-7000-8000-{trip_idx + 1:012d}",
                    "case_id": case_id,
                    "status": "present",
                    "statement": "Tắc đường ngập tràn ngã tư, xe cứu thương và cảnh sát chặn đường.",
                    "deadline_at": (end_time + timedelta(hours=2)).isoformat(),
                    "received_at": (end_time + timedelta(minutes=5)).isoformat(),
                    "provenance": {"channel": "driver_app"},
                }
            )

        # Evidence Snapshot & Feature Set
        snap_id = f"018f2f4e-0300-7000-8000-{trip_idx + 1:012d}"
        feat_id = f"018f2f4e-0500-7000-8000-{trip_idx + 1:012d}"
        dossier_data = {
            "trip_id": t_id,
            "assignment_id": asgn_id,
            "scenario": scen,
            "reported_stall_seconds": 240 if scen == "intentional_dic" else 30,
        }
        evidence_snapshots.append(
            {
                "id": snap_id,
                "case_id": case_id,
                "version": 1,
                "policy_version_id": policy_id,
                "event_cutoff_at": end_time.isoformat(),
                "stage": "post_cancellation" if trip_status == "cancelled" else "pre_cancellation",
                "dossier": dossier_data,
                "dossier_hash": hash_payload(dossier_data),
                "created_at": end_time.isoformat(),
            }
        )

        stat_dur = 240 if scen == "intentional_dic" else (260 if scen == "traffic_gridlock" else 0)
        davi_val = -0.85 if scen == "intentional_dic" else (0.1 if scen == "traffic_gridlock" else 0.92)
        feature_sets.append(
            {
                "id": feat_id,
                "evidence_snapshot_id": snap_id,
                "preprocessing_version": "v1.0.0-eda",
                "window_start": matched_time.isoformat(),
                "window_end": end_time.isoformat(),
                "telemetry_coverage": 0.4 if scen == "technical_dropout" else 0.98,
                "max_gap_s": 180 if scen == "technical_dropout" else 5,
                "davi": davi_val,
                "stationary_duration_s": stat_dur,
                "traffic_observation_age_s": 45,
                "quality_flags": ["app_crashed"]
                if scen == "technical_dropout"
                else ([] if scen != "fake_gps" else ["mock_provider_active"]),
                "features": {
                    "davi": davi_val,
                    "stationary_duration_s": stat_dur,
                    "distance_to_pickup_start_m": 850,
                    "distance_to_pickup_end_m": 920 if scen == "intentional_dic" else 50,
                },
                "created_at": end_time.isoformat(),
            }
        )

        # Model Assessment
        conf = 0.92 if scen in ("intentional_dic", "fake_gps") else 0.15
        model_assessments.append(
            {
                "id": f"018f2f4e-0600-7000-8000-{trip_idx + 1:012d}",
                "evidence_snapshot_id": snap_id,
                "feature_set_id": feat_id,
                "provider": "openrouter-typesafe-jev",
                "model_id": "~typesafe/jev-latest",
                "prompt_version": "v1.2.0-fraud-assessment",
                "output_schema_version": 1,
                "status": "completed",
                "category": expected_category,
                "confidence": conf,
                "score_semantics": "calibrated_probability",
                "reason_codes": ["STATIONARY_IN_CLEAR_TRAFFIC", "NEGATIVE_DAVI"]
                if scen == "intentional_dic"
                else ["TRAFFIC_CONGESTION_EXPLAINED"],
                "evidence_refs": [{"type": "telemetry", "count": 15}],
                "forensic_brief": f"Phân tích chuyên sâu: Tài xế trong kịch bản {scen} ghi nhận chỉ số vi phạm {expected_category}.",
                "raw_response": {"category": expected_category, "confidence": conf},
                "latency_ms": 1250,
                "trace_id": f"trace_jev_{trip_idx + 1:04d}",
                "created_at": (end_time + timedelta(seconds=10)).isoformat(),
            }
        )

        # Adjudications & Sanctions (for resolved cases)
        if case_status == "resolved":
            adj_id = f"018f2f4e-0700-7000-8000-{trip_idx + 1:012d}"
            outcome = "fine" if expected_category == "ERR-02" else "dismiss"
            adjudications.append(
                {
                    "id": adj_id,
                    "case_id": case_id,
                    "evidence_snapshot_id": snap_id,
                    "policy_version_id": policy_id,
                    "analyst_id": assigned_analyst["id"],
                    "outcome": outcome,
                    "rationale": f"Hội đồng thẩm định kết luận: {outcome.upper()} căn cứ chứng cứ GPS và đối chiếu chính sách.",
                    "explicit_human_approval": True,
                    "idempotency_key": str(uuid.uuid5(uuid.NAMESPACE_URL, f"p063:adjudication:{trip_idx}")),
                    "request_hash": "\\x" + hashlib.sha256(f"adj_{trip_idx}".encode()).hexdigest(),
                    "approved_at": (end_time + timedelta(minutes=20)).isoformat(),
                }
            )
            if outcome == "fine":
                sanctions.append(
                    {
                        "id": f"018f2f4e-0800-7000-8000-{trip_idx + 1:012d}",
                        "adjudication_id": adj_id,
                        "driver_id": drv["id"],
                        "kind": "fine",
                        "amount_minor": 20000000,  # 200,000 VND
                        "currency": "VND",
                        "starts_at": None,
                        "ends_at": None,
                        "status": "simulated_delivered",
                        "external_effect_key": str(uuid.uuid5(uuid.NAMESPACE_URL, f"p063:sanction:{trip_idx}")),
                        "is_simulated": True,
                        "created_at": (end_time + timedelta(minutes=21)).isoformat(),
                    }
                )

        # Telemetry Points & Ingest Events (10 to 15 GPS points per trip)
        num_points = 12
        for step in range(num_points):
            pt_id = f"018f2f4e-0900-{trip_idx + 1:04d}-{step + 1:04d}-000000000001"
            pt_time = matched_time + timedelta(seconds=step * 20)

            # Trajectory calculation
            if scen == "intentional_dic":
                # Stalled or slightly drifting backward
                cur_lat = drv_start_lat - (step * 0.00005)
                cur_lon = drv_start_lon - (step * 0.00005)
                speed = 0.0 if step > 2 else 1.2
                gps_state = "valid"
                mock_rep = False
                app_st = "foreground"
                net_st = "online"
            elif scen == "traffic_gridlock":
                # Very slow movement
                cur_lat = drv_start_lat + (step * 0.00002)
                cur_lon = drv_start_lon + (step * 0.00002)
                speed = 0.8
                gps_state = "valid"
                mock_rep = False
                app_st = "foreground"
                net_st = "online"
            elif scen == "technical_dropout":
                if step > 6:
                    cur_lat = None
                    cur_lon = None
                    speed = None
                    gps_state = "unavailable"
                    mock_rep = False
                    app_st = "crashed"
                    net_st = "offline"
                else:
                    cur_lat = drv_start_lat + (step * 0.0002)
                    cur_lon = drv_start_lon + (step * 0.0002)
                    speed = 6.5
                    gps_state = "valid"
                    mock_rep = False
                    app_st = "foreground"
                    net_st = "online"
            elif scen == "fake_gps":
                # Teleporting or mock reported
                cur_lat = drv_start_lat + (step * 0.002)
                cur_lon = drv_start_lon + (step * 0.002)
                speed = 35.0
                gps_state = "mock_reported"
                mock_rep = True
                app_st = "foreground"
                net_st = "online"
            else:  # clean trip
                cur_lat = drv_start_lat + (step * ((lm_pickup["lat"] - drv_start_lat) / num_points))
                cur_lon = drv_start_lon + (step * ((lm_pickup["lon"] - drv_start_lon) / num_points))
                speed = 7.5
                gps_state = "valid"
                mock_rep = False
                app_st = "foreground"
                net_st = "online"

            pos_obj = {"latitude": cur_lat, "longitude": cur_lon, "accuracy_m": 8.0} if cur_lat is not None else None
            payload = {
                "position": pos_obj,
                "speed_mps": speed,
                "bearing_deg": 180.0 if speed else None,
                "app_state": app_st,
                "network_state": net_st,
                "gps_state": gps_state,
                "mock_location_reported": mock_rep,
            }

            pos_wkt = f"POINT({cur_lon:.6f} {cur_lat:.6f})" if cur_lat is not None else None

            ingest_events.append(
                {
                    "event_id": pt_id,
                    "organization_id": org_id,
                    "schema_version": 1,
                    "event_type": "telemetry.observed",
                    "source": "smartphone-app",
                    "occurred_at": pt_time.isoformat(),
                    "received_at": (pt_time + timedelta(milliseconds=200)).isoformat(),
                    "correlation_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"p063:trip:{trip_idx}")),
                    "causation_id": None,
                    "simulation_run_id": sim_run_ids[scen],
                    "trip_id": t_id,
                    "assignment_id": asgn_id,
                    "driver_id": drv["id"],
                    "producer_sequence": step + 1,
                    "payload": payload,
                    "payload_hash": hash_payload(payload),
                }
            )

            telemetry_points.append(
                {
                    "event_id": pt_id,
                    "assignment_id": asgn_id,
                    "occurred_at": pt_time.isoformat(),
                    "position": pos_wkt,
                    "speed_mps": speed,
                    "bearing_deg": 180.0 if speed else None,
                    "accuracy_m": 8.0,
                    "app_state": app_st,
                    "network_state": net_st,
                    "gps_state": gps_state,
                    "mock_location_reported": mock_rep,
                }
            )

    dataset = {
        "organization": organization,
        "analysts": analysts,
        "principal_roles": principal_roles,
        "passengers": passengers,
        "drivers": drivers,
        "vehicles": vehicles,
        "driver_vehicle_assignments": driver_vehicle_assignments,
        "policy_version": policy_version,
        "policy_chunks": policy_chunks,
        "simulation_runs": simulation_runs,
        "trips": trips,
        "trip_assignments": trip_assignments,
        "fare_quotes": fare_quotes,
        "payment_transactions": payment_transactions,
        "route_snapshots": route_snapshots,
        "traffic_observations": traffic_observations,
        "platform_incidents": platform_incidents,
        "passenger_feedback": passenger_feedback,
        "fraud_cases": fraud_cases,
        "simulation_labels": simulation_labels,
        "case_assignment_history": case_assignment_history,
        "review_leases": review_leases,
        "driver_submissions": driver_submissions,
        "evidence_snapshots": evidence_snapshots,
        "feature_sets": feature_sets,
        "model_assessments": model_assessments,
        "adjudications": adjudications,
        "sanctions": sanctions,
        "ingest_events": ingest_events,
        "telemetry_points": telemetry_points,
    }
    if __package__ in (None, ""):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.road_dataset import apply_road_dataset

    return apply_road_dataset(dataset)


def main():
    out_dir = Path("data/synthetic")
    out_dir.mkdir(parents=True, exist_ok=True)
    dataset = generate_synthetic_dataset()
    out_file = out_dir / "seed_data.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)
    print(f"Generated synthetic dataset to {out_file}:")
    print("- 1 Organization")
    print(f"- {len(dataset['analysts'])} Fraud Analysts")
    print(f"- {len(dataset['passengers'])} Passengers / Users")
    print(f"- {len(dataset['drivers'])} Drivers & Vehicles")
    print(f"- {len(dataset['trips'])} Trips & Assignments")
    print(f"- {len(dataset['fraud_cases'])} Fraud Cases")
    print(f"- {len(dataset['telemetry_points'])} Telemetry Points & Ingest Events")


if __name__ == "__main__":
    main()
