#!/usr/bin/env python3
"""Trip stream simulation script for GreenSM platform.

Connects to Redis (localhost:6379) AND PostgreSQL (localhost:54322).
Simulates trips with lifecycle states:
  1. 'coming' (driver en route to pickup)
  2. 'picked_up' / 'on_trip' (in transit or stall / GPS anomaly)
  3. 'complete' (or 'cancelled' if passenger aborted)

Enforces Driver Suspension Invariant:
  Queries app.drivers.account_status via PostgreSQL.
  If driver is 'suspended', the trip is rejected and cannot proceed!

DB Insertions per trip:
  - app.trips
  - app.trip_assignments
  - (telemetry_queue_worker handles app.telemetry_points / fraud_cases / model_assessments)

Round-robin analyst assignment from 10 principals.
1-in-3 trips triggers fraud alert scenario.

CLI Flags:
  --interval 10  (every 10s simulates a trip)
  --count <number of trips>  (<= 0 for infinite)
  --redis-host / --redis-port
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

# datetime.UTC exists only on Python 3.11+; self-hosted runners still ship 3.10,
# where this script previously died with ImportError before sending one trip.
UTC = timezone.utc  # noqa: UP017 - deployment runners ship Python 3.10, which has no datetime.UTC

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402
import redis  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import telemetry_generation as tg  # noqa: E402

# ── Logging setup ─────────────────────────────────────────────────────────────
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "trip_simulation.log"

_fmt = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=_fmt,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_FILE), mode="a", encoding="utf-8"),
    ],
)
logger = logging.getLogger("simulate_trip_stream")

# ── Static seed data (matches DB rows) ────────────────────────────────────────
ORG_ID = "018f2f4e-0000-7000-8000-000000000001"

DRIVER_IDS = [f"018f2f4e-3000-7000-8000-{i:012d}" for i in range(1, 21)]
VEHICLE_IDS = [f"018f2f4e-4000-7000-8000-{i:012d}" for i in range(1, 21)]
PASSENGER_IDS = [f"018f2f4e-2000-7000-8000-{i:012d}" for i in range(1, 11)]

# 10 principals as analyst pool
ANALYST_PRINCIPAL_IDS = [f"018f2f4e-1000-7000-8000-{i:012d}" for i in range(1, 11)]
ANALYST_NAMES = [
    "Nguyen Thi Lan",
    "Tran Van Binh",
    "Le Hoang Nam",
    "Pham Minh Duc",
    "Vu Thi Mai",
    "Doan Quang Huy",
    "Hoang Thu Thao",
    "Bui Anh Tuan",
    "Dang Ngoc Linh",
    "Ngo Quoc Bao",
]

# 1-in-3 trips is fraud — must match /api/v1/simulations/{scenario} allowed values:
# intentional_dic | traffic_gridlock | technical_dropout | fake_gps | gps_jitter | driver_stall_cancel | gps_spoofing
FRAUD_SCENARIOS = ["driver_stall_cancel", "gps_spoofing", "intentional_dic"]
NORMAL_SCENARIOS = ["normal_trip", "normal_trip"]  # 2 normals per 1 fraud

# ── Remote API config (override via env or --api-url CLI flag) ────────────────
RAILWAY_API_URL = os.getenv("GREENSM_API_URL", "https://greensentinel-backend-production.up.railway.app")
DEFAULT_ANALYST_ID = os.getenv("DEFAULT_ANALYST_ID", "018f2f4e-1000-7000-8000-000000000001")
DEFAULT_SCENARIO = os.getenv("DEFAULT_SCENARIO", "driver_stall_cancel")
DEFAULT_DRIVER_ID: str | None = os.getenv("DEFAULT_DRIVER_ID", None)

# Hanoi pickup zone coords (lat, lon)
HANOI_LOCATIONS = [
    (21.0285, 105.8542),  # Opera House
    (21.0227, 105.8412),  # Hoan Kiem Lake
    (21.0035, 105.8412),  # Hanoi Railway Station
    (21.0456, 105.8371),  # West Lake
    (21.0158, 105.8363),  # Old Quarter North
    (21.0067, 105.8436),  # Ba Dinh Square
    (21.0315, 105.7916),  # Cau Giay
    (21.0001, 105.8667),  # Dong Da
]


# ── DB helpers ────────────────────────────────────────────────────────────────
def get_db_conn() -> psycopg2.extensions.connection:
    """Open psycopg2 connection to Supabase/PostgreSQL."""
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = int(os.getenv("DB_PORT", "54322"))
    db_name = os.getenv("DB_NAME", "postgres")
    db_user = os.getenv("DB_USER", "postgres")
    db_pass = os.getenv("DB_PASSWORD", "postgres")
    conn = psycopg2.connect(
        host=db_host,
        port=db_port,
        dbname=db_name,
        user=db_user,
        password=db_pass,
        connect_timeout=5,
    )
    conn.autocommit = False
    return conn


def is_driver_suspended_db(driver_id: str) -> bool:
    """Check driver account_status in PostgreSQL."""
    try:
        conn = get_db_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT account_status FROM app.drivers WHERE id = %s",
                (driver_id,),
            )
            row = cur.fetchone()
        conn.close()
        return bool(row and row["account_status"] == "suspended")
    except Exception as e:
        logger.warning("DB suspension check failed (%s), assuming not suspended", e)
        return False


def insert_trip_to_db(
    trip_id: str,
    passenger_id: str,
    driver_id: str,
    vehicle_id: str,
    loc_pickup: tuple[float, float],
    loc_dropoff: tuple[float, float],
    scenario: str,
    analyst_id: str,
) -> str | None:
    """Insert app.trips + app.trip_assignments. Returns assignment_id or None on error."""
    now = datetime.now(UTC) + timedelta(days=1)
    is_fraud_scenario = scenario not in ("normal_trip",)
    trip_status = "in_progress" if is_fraud_scenario else "in_progress"

    assignment_id = str(uuid4())
    try:
        conn = get_db_conn()
        with conn.cursor() as cur:
            # Insert trip
            cur.execute(
                """
                INSERT INTO app.trips
                  (id, organization_id, passenger_id, requested_at,
                   pickup, dropoff, requested_service_class, status)
                VALUES (%s, %s, %s, %s,
                        ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                        ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                        %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    trip_id,
                    ORG_ID,
                    passenger_id,
                    now,
                    loc_pickup[1],  # lon
                    loc_pickup[0],  # lat
                    loc_dropoff[1],
                    loc_dropoff[0],
                    "economy",
                    trip_status,
                ),
            )
            # Insert trip_assignment
            cur.execute(
                """
                INSERT INTO app.trip_assignments
                  (id, trip_id, driver_id, vehicle_id, state, offered_at, accepted_at, started_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    assignment_id,
                    trip_id,
                    driver_id,
                    vehicle_id,
                    "started",
                    now,
                    now,
                    now,
                ),
            )
        conn.commit()
        conn.close()
        logger.info(
            "[DB] Inserted trip %s (assignment %s) driver=%s scenario=%s analyst=%s",
            trip_id,
            assignment_id,
            driver_id,
            scenario,
            analyst_id,
        )
        return assignment_id
    except Exception as e:
        logger.error("[DB] Failed to insert trip %s: %s", trip_id, e)
        try:
            conn.rollback()
            conn.close()
        except Exception:
            pass
        return None


# ── OSRM Shortest Path & Route Snapshot helpers ──────────────────────────────
def fetch_osrm_route(
    loc_pickup: tuple[float, float],
    loc_dropoff: tuple[float, float],
) -> dict[str, Any]:
    """Fetch shortest driving path from public OSRM Hanoi router, with local fallback."""
    lat1, lon1 = loc_pickup
    lat2, lon2 = loc_dropoff
    url = (
        f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=full&geometries=geojson"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GreenSM-Fraud-Sentinel/1.0"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode())
            if data.get("code") == "Ok" and data.get("routes"):
                route = data["routes"][0]
                coords = route["geometry"]["coordinates"]  # [[lon, lat], ...]
                return {
                    "coordinates": coords,
                    "distance_m": int(route.get("distance", 3500)),
                    "duration_s": int(route.get("duration", 600)),
                }
    except Exception as e:
        logger.debug("OSRM fetch error (%s), using interpolated road waypoints", e)

    # Fallback to realistic road points between pickup and dropoff
    steps = 8
    coords = [
        [round(lon1 + (lon2 - lon1) * (i / steps), 6), round(lat1 + (lat2 - lat1) * (i / steps), 6)]
        for i in range(steps + 1)
    ]
    return {
        "coordinates": coords,
        "distance_m": 3500,
        "duration_s": 600,
    }


def insert_route_snapshot_to_db(
    assignment_id: str,
    route_info: dict[str, Any],
) -> str | None:
    """Insert calculated shortest path into app.route_snapshots."""
    route_id = str(uuid4())
    now = datetime.now(UTC) + timedelta(days=1)
    coords = route_info.get("coordinates") or []
    if len(coords) < 2:
        return None

    linestring_wkt = f"LINESTRING({', '.join(f'{c[0]} {c[1]}' for c in coords)})"
    try:
        conn = get_db_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app.route_snapshots
                  (id, assignment_id, calculated_at, provider, routing_profile, map_version, route, distance_m, duration_s, provenance)
                VALUES (%s, %s, %s, %s, %s, %s,
                        ST_GeogFromText(%s),
                        %s, %s, %s::jsonb)
                ON CONFLICT DO NOTHING
                """,
                (
                    route_id,
                    assignment_id,
                    now,
                    "osrm-hanoi",
                    "driving-car",
                    "2026.09-vn",
                    linestring_wkt,
                    route_info.get("distance_m", 3500),
                    route_info.get("duration_s", 600),
                    json.dumps({"origin": "osrm", "profile": "driving-car"}),
                ),
            )
        conn.commit()
        conn.close()
        logger.info("[DB] Inserted route snapshot %s (assignment %s, points=%d)", route_id, assignment_id, len(coords))
        return route_id
    except Exception as e:
        logger.error("[DB] Failed to insert route snapshot: %s", e)
        try:
            conn.rollback()
            conn.close()
        except Exception:
            pass
        return None


# ── Telemetry frame builder ───────────────────────────────────────────────────
_STALL_SCENARIOS = ("driver_stall_cancel", "intentional_dic", "stall")


def build_trip_lifecycle_frames(
    trip_id: str,
    assignment_id: str,
    driver_id: str,
    scenario: str,
    loc_pickup: tuple[float, float],
    loc_dropoff: tuple[float, float],
    route_coords: list[list[float]] | None = None,
    analyst_id: str | None = None,
    *,
    noise: str = "happy",
    seed: int | None = None,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Generate telemetry frames: coming → picked_up/on_trip → complete/cancelled.

    Points come from ``scripts/telemetry_generation.py`` (config/telemetry_distribution.yaml):
    every point has ``occurred_at`` and ``sequence``. ``loc_pickup``/``loc_dropoff`` are
    ``(lat, lon)``. ``route_coords`` is accepted for interface stability; the approach path
    is generated from the config. The stream per trip is derived from ``trip_id``.
    """
    del route_coords  # geometry comes from the distribution config
    cfg = config or tg.load_config()
    now = datetime.now(UTC)
    lat_pickup, lon_pickup = loc_pickup
    lat_drop, lon_drop = loc_dropoff
    rng = tg.make_rng(cfg, seed, stream=uuid5(NAMESPACE_URL, f"greensentinel:sim:{trip_id}").int % 2**32)
    trip = tg.generate_trip(
        cfg,
        "normal_trip" if scenario == "phantom_booking" else scenario,
        (lon_pickup, lat_pickup),
        now,
        rng,
        noise=noise,
        dropoff_lonlat=(lon_drop, lat_drop),
    )

    def points_in(*phases: str) -> list[dict[str, Any]]:
        return [p for p, phase in zip(trip.points, trip.phases, strict=True) if phase in phases]

    base = {
        "trip_id": trip_id,
        "assignment_id": assignment_id,
        "driver_id": driver_id,
        "scenario": scenario,
        "timestamp": now.isoformat(),
        "analyst_id": analyst_id,
    }
    coming = points_in("approach") or trip.points[:1]
    frames: list[dict[str, Any]] = [
        {**base, "event_id": str(uuid4()), "lifecycle_state": "coming", "points": coming},
    ]

    if scenario in _STALL_SCENARIOS:
        stall_pts = points_in("stall") or trip.points[-1:]
        # Simulation ground truth (planned stall length), kept under the key existing
        # consumers read. The server measures SSD itself in FeatureWindow and stores this
        # value only as declared_stationary_duration_s.
        planned_stall_s = round(sum(leg.duration_s for leg in trip.plan.legs if leg.phase == "stall"))
        stall_fields = {
            "stationary_duration_s": planned_stall_s,
            "cancellation_reason": "driver_stalled_too_long",
            "cancellation_actor": "passenger",
        }
        frames.append(
            {**base, "event_id": str(uuid4()), "lifecycle_state": "picked_up", "points": stall_pts, **stall_fields}
        )
        frames.append(
            {
                **base,
                "event_id": str(uuid4()),
                "lifecycle_state": "cancelled",
                **stall_fields,
                "cancellation_reason": "Tài xế dừng đỗ không di chuyển quá 3 phút (driver stalled)",
                "points": stall_pts,
            }
        )
        return frames

    middle = points_in("teleport", "wait", "on_trip") or trip.points[-1:]
    frame: dict[str, Any] = {**base, "event_id": str(uuid4()), "lifecycle_state": "on_trip", "points": middle}
    if scenario == "phantom_booking":
        frame["phantom_booking"] = True
    frames.append(frame)
    frames.append({**base, "event_id": str(uuid4()), "lifecycle_state": "complete", "points": trip.points[-1:]})
    return frames


# ── Single trip simulation ────────────────────────────────────────────────────
def simulate_single_trip(
    driver_id: str,
    vehicle_id: str,
    passenger_id: str,
    scenario: str,
    analyst_id: str,
    loc_pickup: tuple[float, float],
    loc_dropoff: tuple[float, float],
    redis_client: redis.Redis | None = None,
    stream_key: str = "telemetry:stream",
    channel: str = "telemetry:events",
    noise: str = "happy",
    seed: int | None = None,
) -> dict[str, Any]:
    """Execute a single trip simulation adhering to driver suspension invariants."""
    # Step 1: Check driver suspension
    if is_driver_suspended_db(driver_id):
        err_msg = f"Driver {driver_id} is currently suspended"
        logger.error("[REJECTED] %s", err_msg)
        return {"status": "rejected", "driver_id": driver_id, "scenario": scenario, "reason": "driver_suspended"}

    # Step 2: Insert trip to DB
    trip_id = str(uuid4())
    assignment_id = insert_trip_to_db(
        trip_id=trip_id,
        passenger_id=passenger_id,
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        loc_pickup=loc_pickup,
        loc_dropoff=loc_dropoff,
        scenario=scenario,
        analyst_id=analyst_id,
    )
    if not assignment_id:
        logger.error("[SKIP] DB insert failed for trip %s, skipping Redis publish", trip_id)
        return {"status": "db_error", "trip_id": trip_id}

    # Step 3: Fetch OSRM route & save route snapshot
    route_info = fetch_osrm_route(loc_pickup, loc_dropoff)
    insert_route_snapshot_to_db(assignment_id, route_info)

    # Step 4: Build frames with real assignment_id and route coordinates
    frames = build_trip_lifecycle_frames(
        trip_id,
        assignment_id,
        driver_id,
        scenario,
        loc_pickup,
        loc_dropoff,
        route_info.get("coordinates"),
        analyst_id,
        noise=noise,
        seed=seed,
    )

    # Step 5: Publish to Redis
    published_count = 0
    if redis_client is not None:
        try:
            for frame in frames:
                payload_str = json.dumps(frame)
                redis_client.xadd(stream_key, {"data": payload_str})
                redis_client.publish(channel, payload_str)
                published_count += 1
            logger.info(
                "[PUBLISHED] trip=%s scenario=%s driver=%s frames=%d analyst=%s",
                trip_id,
                scenario,
                driver_id,
                published_count,
                analyst_id,
            )
        except Exception as e:
            logger.warning("Redis publish error: %s", e)

    return {
        "status": "simulated",
        "trip_id": trip_id,
        "assignment_id": assignment_id,
        "driver_id": driver_id,
        "passenger_id": passenger_id,
        "scenario": scenario,
        "analyst_id": analyst_id,
        "published_count": published_count,
    }


# ── Remote API dispatch ───────────────────────────────────────────────────────
def dispatch_simulation_to_api(
    api_url: str,
    scenario: str,
    analyst_id: str,
    driver_id: str | None = None,
    seed: int = 42,
    timeout: int = 30,
) -> dict:
    """POST /api/v1/simulations/{scenario} to Railway backend directly.

    Returns parsed JSON response or raises on HTTP/network error.
    """
    payload: dict = {"analyst_id": analyst_id, "seed": seed}
    if driver_id:
        payload["driver_id"] = driver_id

    data = json.dumps(payload).encode("utf-8")
    url = f"{api_url.rstrip('/')}/api/v1/simulations/{scenario}"
    logger.info("Dispatching fraud scenario '%s' to %s", scenario, url)
    logger.info("Payload: %s", json.dumps(payload, indent=2))

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            result = json.loads(body)
            logger.info("API response [%d]: %s", resp.status, json.dumps(result, indent=2))
            return result
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.error("API HTTP %d: %s", e.code, body)
        raise
    except Exception as e:
        logger.error("API dispatch failed: %s", e)
        raise


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="GreenSM Trip Stream & Telemetry Simulation Script")
    parser.add_argument("--interval", type=float, default=10.0, help="Interval in seconds between simulated trips")
    parser.add_argument("--count", type=int, default=0, help="Total trips to simulate (<= 0 for infinite loop)")
    parser.add_argument("--redis-host", type=str, default="localhost", help="Redis host")
    parser.add_argument("--redis-port", type=int, default=6379, help="Redis port")
    parser.add_argument("--stream-key", type=str, default="telemetry:stream", help="Redis stream key")
    parser.add_argument("--channel", type=str, default="telemetry:events", help="Redis channel name")
    parser.add_argument("--noise", choices=tg.NOISE_MODES, default="happy", help="telemetry noise mode")
    parser.add_argument("--seed", type=int, default=None, help="override the telemetry config seed")
    # Remote API dispatch flags
    parser.add_argument(
        "--api-url", type=str, default=RAILWAY_API_URL, help=f"Backend API base URL (default: {RAILWAY_API_URL})"
    )
    parser.add_argument(
        "--dispatch-fraud",
        action="store_true",
        help="Dispatch one fraud scenario directly to the Railway backend API and exit",
    )
    parser.add_argument(
        "--scenario",
        type=str,
        default=DEFAULT_SCENARIO,
        help=f"Fraud scenario to dispatch (default: {DEFAULT_SCENARIO})",
    )
    parser.add_argument(
        "--driver-id",
        type=str,
        default=DEFAULT_DRIVER_ID,
        help="Override driver ID for dispatch (default: first driver from pool)",
    )
    parser.add_argument(
        "--analyst-id",
        type=str,
        default=DEFAULT_ANALYST_ID,
        help=f"Analyst ID for dispatch (default: {DEFAULT_ANALYST_ID})",
    )
    args = parser.parse_args()

    # ── Direct API dispatch mode (--dispatch-fraud) ───────────────────────────
    if args.dispatch_fraud:
        logger.info("=== Direct API dispatch mode ===")
        result = dispatch_simulation_to_api(
            api_url=args.api_url,
            scenario=args.scenario,
            analyst_id=args.analyst_id,
            driver_id=args.driver_id,
        )
        print(json.dumps(result, indent=2))
        return

    # Redis connection
    r_client: redis.Redis | None = None
    try:
        r_client = redis.Redis(host=args.redis_host, port=args.redis_port, decode_responses=True)
        r_client.ping()
        logger.info("Connected to Redis at %s:%d", args.redis_host, args.redis_port)
    except Exception as e:
        logger.warning("Cannot connect to Redis (%s). Dry-run mode.", e)
        r_client = None

    # DB connectivity check
    try:
        conn = get_db_conn()
        conn.close()
        logger.info("Connected to PostgreSQL at localhost:54322")
    except Exception as e:
        logger.error("Cannot connect to PostgreSQL: %s", e)

    trips_run = 0
    # Round-robin indices
    driver_idx = 0
    passenger_idx = 0
    analyst_idx = 0
    location_idx = 0

    # Build cycling scenario list: [fraud, normal, normal, fraud, normal, normal, ...]
    def _next_scenario(trip_num: int) -> str:
        """Return fraud scenario every 3rd trip (trip_num 1-indexed)."""
        if trip_num % 3 == 1:
            return FRAUD_SCENARIOS[(trip_num // 3) % len(FRAUD_SCENARIOS)]
        return "normal_trip"

    logger.info("=== GreenSM Trip Simulation starting. interval=%.1fs count=%d ===", args.interval, args.count)

    try:
        while True:
            trips_run += 1
            scenario = _next_scenario(trips_run)

            driver_id = DRIVER_IDS[driver_idx % len(DRIVER_IDS)]
            vehicle_id = VEHICLE_IDS[driver_idx % len(VEHICLE_IDS)]  # 1:1 driver→vehicle
            passenger_id = PASSENGER_IDS[passenger_idx % len(PASSENGER_IDS)]
            analyst_id = ANALYST_PRINCIPAL_IDS[analyst_idx % len(ANALYST_PRINCIPAL_IDS)]
            analyst_name = ANALYST_NAMES[analyst_idx % len(ANALYST_NAMES)]

            loc_idx = location_idx % len(HANOI_LOCATIONS)
            loc_pickup = HANOI_LOCATIONS[loc_idx]
            loc_dropoff = HANOI_LOCATIONS[(loc_idx + 3) % len(HANOI_LOCATIONS)]

            logger.info(
                "--- Trip #%d | scenario=%s | driver=%s | passenger=%s | analyst=%s (%s) ---",
                trips_run,
                scenario,
                driver_id,
                passenger_id,
                analyst_id,
                analyst_name,
            )

            result = simulate_single_trip(
                driver_id=driver_id,
                vehicle_id=vehicle_id,
                passenger_id=passenger_id,
                scenario=scenario,
                analyst_id=analyst_id,
                loc_pickup=loc_pickup,
                loc_dropoff=loc_dropoff,
                redis_client=r_client,
                stream_key=args.stream_key,
                channel=args.channel,
                noise=args.noise,
                seed=args.seed,
            )

            if result["status"] == "rejected":
                logger.warning("Trip #%d rejected (driver suspended). Rotating driver.", trips_run)
                driver_idx += 1  # Skip suspended driver
            elif result["status"] == "db_error":
                logger.error("Trip #%d DB error. Will retry with different driver next time.", trips_run)
            else:
                logger.info(
                    "Trip #%d done: trip_id=%s frames_published=%d",
                    trips_run,
                    result.get("trip_id"),
                    result.get("published_count", 0),
                )
                driver_idx += 1
                passenger_idx += 1
                analyst_idx += 1
                location_idx += 1

            if args.count > 0 and trips_run >= args.count:
                logger.info("Reached count=%d, stopping simulation.", args.count)
                break

            logger.info("Waiting %.1f seconds...", args.interval)
            time.sleep(args.interval)

    except KeyboardInterrupt:
        logger.info("Simulation interrupted by user after %d trips.", trips_run)


if __name__ == "__main__":
    main()
