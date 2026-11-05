"""Single-trip generator for releases_v2 realistic corpus with all 7 classes, hard negatives, and calibrated kinematics."""

from __future__ import annotations

import math
import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from scripts.benchmark.build_v2.config import GeneratorV2Config
from scripts.benchmark.build_v2.dialogue import (
    synthesize_realistic_customer_report,
    synthesize_realistic_dialogue,
    synthesize_realistic_driver_objection,
)
from scripts.benchmark.build_v2.geometry import (
    PinnedCorridor,
    bearing_deg,
    haversine_m,
    interpolate_along_polyline,
    polyline_cumulative_distances,
    sample_sub_corridor,
)
from scripts.benchmark.build_v2.noise import (
    apply_gps_noise,
    calculate_device_bearing,
    calculate_device_speed,
    sample_ping_cadence,
    sample_step_interval,
)
from scripts.benchmark.population_synth import synthesize_driver_analytics

SEVERITY_POLICY = {
    "no_violation": None,
    "ERR-01": "P2",
    "ERR-02": "P1",
    "ERR-03": "P1",
    "ERR-04": "P2",
    "ERR-05": "P0",
    "insufficient_evidence": None,
}

SCENARIO_FOR_LABEL = {
    "no_violation": "normal_trip",
    "ERR-01": "driver_stall_cancel",
    "ERR-02": "driver_stall_cancel",
    "ERR-03": "route_deviation",
    "ERR-04": "phantom_ride",
    "ERR-05": "gps_spoofing",
    "insufficient_evidence": "technical_dropout",
}


def build_v2_trip(
    idx: int,
    label: str,
    split: str,
    driver: dict[str, Any],
    passenger: dict[str, Any],
    corridors: list[PinnedCorridor],
    config: GeneratorV2Config,
    trip_rng: random.Random,
) -> dict[str, Any]:
    # Sample corridor sub-path
    corr, sub_polyline, trip_distance_m, start_street, end_street, is_reversed = sample_sub_corridor(
        trip_rng, corridors, min_dist_m=1200.0, max_dist_m=14000.0
    )

    city = corr.city
    p_start_lon, p_start_lat = sub_polyline[0]
    p_end_lon, p_end_lat = sub_polyline[-1]

    pickup = {
        "lat": round(p_start_lat, 7),
        "lon": round(p_start_lon, 7),
        "name": f"{start_street}, {city}",
        "street": start_street,
        "city": city,
    }
    dropoff = {
        "lat": round(p_end_lat, 7),
        "lon": round(p_end_lon, 7),
        "name": f"{end_street}, {city}",
        "street": end_street,
        "city": city,
    }

    # Start timestamp
    base_dt = datetime(2026, 10, 1, 6, 0, 0, tzinfo=UTC)
    t0 = base_dt + timedelta(
        days=trip_rng.randint(0, 27),
        hours=trip_rng.randint(0, 23),
        minutes=trip_rng.randint(0, 59),
        seconds=trip_rng.randint(0, 59),
    )

    cadence_s = sample_ping_cadence(trip_rng, config)
    sub_cum_dist = polyline_cumulative_distances(sub_polyline)
    total_road_m = sub_cum_dist[-1]

    # Driving speed: calibrated to Hanoi / HCMC urban traffic (JICA Urban Transport Study, TomTom Index)
    # Typical city average ~20-30 km/h (5.5 - 8.3 m/s), arterial corridor p95 ~60 km/h (16.7 m/s)
    if total_road_m > 6000.0 and trip_rng.random() < 0.25:
        moving_speed_mps = trip_rng.uniform(10.0, config.speed_arterial_p95_mps)
    else:
        moving_speed_mps = trip_rng.uniform(config.speed_urban_avg_min_mps, config.speed_urban_avg_max_mps)

    nominal_duration_s = max(60.0, total_road_m / moving_speed_mps)

    points: list[dict[str, Any]] = []

    is_hard_negative = False
    hard_neg_type = "none"
    err03_subtype = None
    departure_mode = "none"

    m_per_deg_lat = 111139.0
    cos_lat = math.cos(math.radians(p_start_lat))
    m_per_deg_lon = 111139.0 * cos_lat

    # 1. NO VIOLATION
    if label == "no_violation":
        has_mock_flag = trip_rng.random() < config.mock_flag_honest_rate
        if has_mock_flag:
            is_hard_negative = True
            hard_neg_type = "mock_flag"
        elif trip_rng.random() < config.hard_negative_share:
            is_hard_negative = True
            hard_neg_type = trip_rng.choice(["gridlock", "signal_loss", "one_way_start", "legit_detour"])

        if hard_neg_type == "gridlock":
            # Gridlock stop-and-go with hard negative prolonged stop (>= 180s)
            cur_time = t0
            cur_m = 0.0
            seq = 1
            has_long_stop = False
            while cur_m < total_road_m:
                # 40% of gridlock hard negatives experience a prolonged honest stop >= 180s (accident/railway crossing)
                if not has_long_stop and trip_rng.random() < 0.40:
                    stop_s = trip_rng.uniform(185.0, 240.0)
                    has_long_stop = True
                else:
                    stop_s = trip_rng.uniform(20.0, 50.0)

                n_stop_pings = max(1, int(round(stop_s / cadence_s)))
                raw_lon, raw_lat, _ = interpolate_along_polyline(sub_polyline, sub_cum_dist, cur_m)
                for _ in range(n_stop_pings):
                    dt = sample_step_interval(trip_rng, cadence_s, config, allow_misses=False)
                    cur_time += timedelta(seconds=dt)
                    n_lon, n_lat, acc, is_out = apply_gps_noise(trip_rng, raw_lon, raw_lat, config, is_stationary=True)
                    points.append(
                        {
                            "occurred_at": cur_time.isoformat().replace("+00:00", "Z"),
                            "latitude": n_lat,
                            "longitude": n_lon,
                            "speed_mps": 0.0,
                            "bearing_deg": None,
                            "accuracy_m": acc,
                            "sequence": seq,
                            "mock_location_reported": has_mock_flag,
                            "app_state": "FOREGROUND",
                            "network_state": "CONNECTED_4G",
                            "gps_state": "MOCK_REPORTED" if has_mock_flag else "FINE",
                            "latency_ms": int(trip_rng.uniform(40, 120)),
                            "data_gap_s": round(dt, 2),
                            "davi_score": 0.02,
                            "distance_to_pickup_m": 0.0,
                            "is_multipath_outlier": is_out,
                        }
                    )
                    seq += 1

                # Crawl leg: 20-50m at 1.0-2.5 m/s
                crawl_m = trip_rng.uniform(20.0, 50.0)
                cur_m = min(total_road_m, cur_m + crawl_m)
                raw_lon, raw_lat, _ = interpolate_along_polyline(sub_polyline, sub_cum_dist, cur_m)
                dt = sample_step_interval(trip_rng, cadence_s, config, allow_misses=True)
                cur_time += timedelta(seconds=dt)
                n_lon, n_lat, acc, is_out = apply_gps_noise(trip_rng, raw_lon, raw_lat, config, is_stationary=False)
                prev_p = points[-1]
                disp = haversine_m(prev_p["longitude"], prev_p["latitude"], n_lon, n_lat)
                crawl_sp = crawl_m / max(1e-3, dt)
                sp = calculate_device_speed(trip_rng, disp, dt, config, is_stationary=False, true_speed_mps=crawl_sp)
                b = calculate_device_bearing(
                    trip_rng, bearing_deg(prev_p["longitude"], prev_p["latitude"], n_lon, n_lat), is_stationary=False
                )
                points.append(
                    {
                        "occurred_at": cur_time.isoformat().replace("+00:00", "Z"),
                        "latitude": n_lat,
                        "longitude": n_lon,
                        "speed_mps": sp,
                        "bearing_deg": b,
                        "accuracy_m": acc,
                        "sequence": seq,
                        "mock_location_reported": has_mock_flag,
                        "app_state": "FOREGROUND",
                        "network_state": "CONNECTED_4G",
                        "gps_state": "MOCK_REPORTED" if has_mock_flag else "FINE",
                        "latency_ms": int(trip_rng.uniform(40, 120)),
                        "data_gap_s": round(dt, 2),
                        "davi_score": 0.02,
                        "distance_to_pickup_m": 0.0,
                        "is_multipath_outlier": is_out,
                    }
                )
                seq += 1

        else:
            # Standard smooth or one_way / legit_detour
            n_steps = max(12, int(round(nominal_duration_s / cadence_s)))
            cur_time = t0
            prev_target_m = 0.0

            for k in range(n_steps):
                frac = k / max(1, n_steps - 1)
                target_m = frac * total_road_m
                raw_lon, raw_lat, _ = interpolate_along_polyline(sub_polyline, sub_cum_dist, target_m)

                # Hard negative: one way start heads away 150m first
                if hard_neg_type == "one_way_start" and k < 4:
                    away_m = (4 - k) * 35.0
                    raw_lon -= away_m / m_per_deg_lon
                    raw_lat -= away_m / m_per_deg_lat

                # Hard negative: legit detour creates temporary curvature
                if hard_neg_type == "legit_detour" and int(n_steps * 0.3) <= k <= int(n_steps * 0.6):
                    detour_offset_m = math.sin(math.pi * (k - n_steps * 0.3) / (n_steps * 0.3)) * 40.0
                    raw_lon += detour_offset_m / m_per_deg_lon
                    raw_lat += detour_offset_m / m_per_deg_lat

                dt = sample_step_interval(trip_rng, cadence_s, config, allow_misses=True)
                # Hard negative: brief signal loss gap of 20s
                if hard_neg_type == "signal_loss" and k == int(n_steps * 0.5):
                    dt = 22.0

                cur_time += timedelta(seconds=dt)
                is_stat = k == 0
                n_lon, n_lat, acc, is_out = apply_gps_noise(trip_rng, raw_lon, raw_lat, config, is_stationary=is_stat)

                if k == 0:
                    sp = 0.0
                    b = round(
                        bearing_deg(sub_polyline[0][0], sub_polyline[0][1], sub_polyline[1][0], sub_polyline[1][1]), 1
                    )
                else:
                    prev_p = points[-1]
                    disp = haversine_m(prev_p["longitude"], prev_p["latitude"], n_lon, n_lat)
                    true_sp = (target_m - prev_target_m) / max(1e-3, dt)
                    sp = calculate_device_speed(trip_rng, disp, dt, config, is_stationary=False, true_speed_mps=true_sp)
                    b = calculate_device_bearing(
                        trip_rng,
                        bearing_deg(prev_p["longitude"], prev_p["latitude"], n_lon, n_lat),
                        is_stationary=False,
                    )

                points.append(
                    {
                        "occurred_at": cur_time.isoformat().replace("+00:00", "Z"),
                        "latitude": n_lat,
                        "longitude": n_lon,
                        "speed_mps": sp,
                        "bearing_deg": b,
                        "accuracy_m": acc,
                        "sequence": k + 1,
                        "mock_location_reported": has_mock_flag,
                        "app_state": "FOREGROUND",
                        "network_state": "CONNECTED_4G",
                        "gps_state": "MOCK_REPORTED" if has_mock_flag else "FINE",
                        "latency_ms": int(trip_rng.uniform(40, 120)),
                        "data_gap_s": round(dt, 2),
                        "davi_score": 0.02,
                        "distance_to_pickup_m": 0.0,
                        "is_multipath_outlier": is_out,
                    }
                )
                prev_target_m = target_m

    # 2. ERR-01: Driver unjustified cancel after approach leg and short stall (45s - 90s)
    elif label == "ERR-01":
        # Approach movement: driver drives towards pickup for 4 to 8 pings
        n_approach = trip_rng.randint(4, 8)
        approach_dist_m = trip_rng.uniform(250.0, 600.0)
        approach_speed_mps = trip_rng.uniform(5.5, 8.5)
        cur_time = t0
        seq = 1

        nom_b = bearing_deg(sub_polyline[0][0], sub_polyline[0][1], sub_polyline[-1][0], sub_polyline[-1][1])
        appr_b = (nom_b + 180.0) % 360.0
        rad = math.radians(appr_b)

        cur_lon = p_start_lon + (approach_dist_m * math.sin(rad)) / m_per_deg_lon
        cur_lat = p_start_lat + (approach_dist_m * math.cos(rad)) / m_per_deg_lat

        for _ in range(n_approach):
            dt = sample_step_interval(trip_rng, cadence_s, config, allow_misses=False)
            cur_time += timedelta(seconds=dt)
            step_m = approach_speed_mps * dt
            cur_lon -= (step_m * math.sin(rad)) / m_per_deg_lon
            cur_lat -= (step_m * math.cos(rad)) / m_per_deg_lat
            n_lon, n_lat, acc, is_out = apply_gps_noise(trip_rng, cur_lon, cur_lat, config, is_stationary=False)
            prev_p = points[-1] if points else None
            disp = haversine_m(prev_p["longitude"], prev_p["latitude"], n_lon, n_lat) if prev_p else 0.0
            sp = calculate_device_speed(
                trip_rng, disp, dt, config, is_stationary=False, true_speed_mps=approach_speed_mps
            )
            b = calculate_device_bearing(trip_rng, (appr_b + 180.0) % 360.0, is_stationary=False)
            dist_to_pickup = haversine_m(cur_lon, cur_lat, p_start_lon, p_start_lat)
            points.append(
                {
                    "occurred_at": cur_time.isoformat().replace("+00:00", "Z"),
                    "latitude": n_lat,
                    "longitude": n_lon,
                    "speed_mps": sp,
                    "bearing_deg": b,
                    "accuracy_m": acc,
                    "sequence": seq,
                    "mock_location_reported": False,
                    "app_state": "FOREGROUND",
                    "network_state": "CONNECTED_4G",
                    "gps_state": "FINE",
                    "latency_ms": int(trip_rng.uniform(40, 120)),
                    "data_gap_s": round(dt, 2),
                    "davi_score": 0.02,
                    "distance_to_pickup_m": round(dist_to_pickup, 1),
                    "is_multipath_outlier": is_out,
                }
            )
            seq += 1

        # Stall leg: 45s - 90s stationary before cancel
        stall_duration_s = trip_rng.uniform(45.0, 90.0)
        n_stall = max(3, int(round(stall_duration_s / cadence_s)))
        for _ in range(n_stall):
            dt = sample_step_interval(trip_rng, cadence_s, config, allow_misses=False)
            cur_time += timedelta(seconds=dt)
            n_lon, n_lat, acc, is_out = apply_gps_noise(trip_rng, cur_lon, cur_lat, config, is_stationary=True)
            dist_to_pickup = haversine_m(cur_lon, cur_lat, p_start_lon, p_start_lat)
            points.append(
                {
                    "occurred_at": cur_time.isoformat().replace("+00:00", "Z"),
                    "latitude": n_lat,
                    "longitude": n_lon,
                    "speed_mps": 0.0,
                    "bearing_deg": None,
                    "accuracy_m": acc,
                    "sequence": seq,
                    "mock_location_reported": False,
                    "app_state": "FOREGROUND",
                    "network_state": "CONNECTED_4G",
                    "gps_state": "FINE",
                    "latency_ms": int(trip_rng.uniform(40, 120)),
                    "data_gap_s": round(dt, 2),
                    "davi_score": 0.05,
                    "distance_to_pickup_m": round(dist_to_pickup, 1),
                    "is_multipath_outlier": is_out,
                }
            )
            seq += 1

    # 3. ERR-02: Prolonged stall (>= 180s, e.g. 195s - 340s) after approach/movement
    elif label == "ERR-02":
        # Approach leg: driver approaches towards pickup area for 4 to 8 pings
        n_approach = trip_rng.randint(4, 8)
        approach_dist_m = trip_rng.uniform(350.0, 750.0)
        approach_speed_mps = trip_rng.uniform(5.0, 8.0)
        cur_time = t0
        seq = 1

        nom_b = bearing_deg(sub_polyline[0][0], sub_polyline[0][1], sub_polyline[-1][0], sub_polyline[-1][1])
        appr_b = (nom_b + 180.0) % 360.0
        rad = math.radians(appr_b)

        cur_lon = p_start_lon + (approach_dist_m * math.sin(rad)) / m_per_deg_lon
        cur_lat = p_start_lat + (approach_dist_m * math.cos(rad)) / m_per_deg_lat

        for _ in range(n_approach):
            dt = sample_step_interval(trip_rng, cadence_s, config, allow_misses=False)
            cur_time += timedelta(seconds=dt)
            step_m = approach_speed_mps * dt
            cur_lon -= (step_m * math.sin(rad)) / m_per_deg_lon
            cur_lat -= (step_m * math.cos(rad)) / m_per_deg_lat
            n_lon, n_lat, acc, is_out = apply_gps_noise(trip_rng, cur_lon, cur_lat, config, is_stationary=False)
            prev_p = points[-1] if points else None
            disp = haversine_m(prev_p["longitude"], prev_p["latitude"], n_lon, n_lat) if prev_p else 0.0
            sp = calculate_device_speed(
                trip_rng, disp, dt, config, is_stationary=False, true_speed_mps=approach_speed_mps
            )
            b = calculate_device_bearing(trip_rng, (appr_b + 180.0) % 360.0, is_stationary=False)
            dist_to_pickup = haversine_m(cur_lon, cur_lat, p_start_lon, p_start_lat)
            points.append(
                {
                    "occurred_at": cur_time.isoformat().replace("+00:00", "Z"),
                    "latitude": n_lat,
                    "longitude": n_lon,
                    "speed_mps": sp,
                    "bearing_deg": b,
                    "accuracy_m": acc,
                    "sequence": seq,
                    "mock_location_reported": False,
                    "app_state": "FOREGROUND",
                    "network_state": "CONNECTED_4G",
                    "gps_state": "FINE",
                    "latency_ms": int(trip_rng.uniform(40, 120)),
                    "data_gap_s": round(dt, 2),
                    "davi_score": 0.02,
                    "distance_to_pickup_m": round(dist_to_pickup, 1),
                    "is_multipath_outlier": is_out,
                }
            )
            seq += 1

        # Prolonged stall leg: >= 180s (195s - 340s) within 100-300m of pickup
        stall_duration_s = trip_rng.uniform(195.0, 340.0)
        n_stall = max(14, int(round(stall_duration_s / cadence_s)))
        for _ in range(n_stall):
            dt = sample_step_interval(trip_rng, cadence_s, config, allow_misses=False)
            cur_time += timedelta(seconds=dt)
            n_lon, n_lat, acc, is_out = apply_gps_noise(trip_rng, cur_lon, cur_lat, config, is_stationary=True)
            dist_to_pickup = haversine_m(cur_lon, cur_lat, p_start_lon, p_start_lat)
            points.append(
                {
                    "occurred_at": cur_time.isoformat().replace("+00:00", "Z"),
                    "latitude": n_lat,
                    "longitude": n_lon,
                    "speed_mps": 0.0,
                    "bearing_deg": None,
                    "accuracy_m": acc,
                    "sequence": seq,
                    "mock_location_reported": False,
                    "app_state": "FOREGROUND",
                    "network_state": "CONNECTED_4G",
                    "gps_state": "FINE",
                    "latency_ms": int(trip_rng.uniform(40, 120)),
                    "data_gap_s": round(dt, 2),
                    "davi_score": 0.12,
                    "distance_to_pickup_m": round(dist_to_pickup, 1),
                    "is_multipath_outlier": is_out,
                }
            )
            seq += 1

    # 4. ERR-03: Route deviation (Both approach wrong direction AND in-trip detour)
    elif label == "ERR-03":
        err03_subtype = "approach_wrong_direction" if trip_rng.random() < 0.50 else "in_trip_detour"
        departure_mode = err03_subtype
        n_steps = max(14, int(round(nominal_duration_s / cadence_s)))
        cur_time = t0

        if err03_subtype == "approach_wrong_direction":
            # Heading away from pickup
            away_heading = (
                bearing_deg(sub_polyline[0][0], sub_polyline[0][1], sub_polyline[-1][0], sub_polyline[-1][1]) + 180.0
            ) % 360.0
            rad = math.radians(away_heading)
            cur_lon, cur_lat = p_start_lon, p_start_lat
            for k in range(n_steps):
                dt = sample_step_interval(trip_rng, cadence_s, config, allow_misses=True)
                cur_time += timedelta(seconds=dt)
                step_dist = moving_speed_mps * dt
                cur_lon += (step_dist * math.sin(rad)) / m_per_deg_lon
                cur_lat += (step_dist * math.cos(rad)) / m_per_deg_lat
                n_lon, n_lat, acc, is_out = apply_gps_noise(trip_rng, cur_lon, cur_lat, config, is_stationary=False)
                prev_p = points[-1] if points else None
                disp = haversine_m(prev_p["longitude"], prev_p["latitude"], n_lon, n_lat) if prev_p else 0.0
                sp = calculate_device_speed(
                    trip_rng, disp, dt, config, is_stationary=False, true_speed_mps=moving_speed_mps
                )
                b = calculate_device_bearing(trip_rng, away_heading, is_stationary=False)
                points.append(
                    {
                        "occurred_at": cur_time.isoformat().replace("+00:00", "Z"),
                        "latitude": n_lat,
                        "longitude": n_lon,
                        "speed_mps": sp,
                        "bearing_deg": b,
                        "accuracy_m": acc,
                        "sequence": k + 1,
                        "mock_location_reported": False,
                        "app_state": "FOREGROUND",
                        "network_state": "CONNECTED_4G",
                        "gps_state": "FINE",
                        "latency_ms": int(trip_rng.uniform(40, 120)),
                        "data_gap_s": round(dt, 2),
                        "davi_score": -0.65,
                        "distance_to_pickup_m": round(step_dist * (k + 1), 1),
                        "is_multipath_outlier": is_out,
                    }
                )
        else:
            # in_trip_detour: departs corridor with excessive loop (actual > 1.5x road length)
            detour_heading = None
            prev_target_m = 0.0
            for k in range(n_steps):
                frac = k / max(1, n_steps - 1)
                target_m = frac * total_road_m
                raw_lon, raw_lat, _ = interpolate_along_polyline(sub_polyline, sub_cum_dist, target_m)
                if k >= int(n_steps * 0.35):
                    # Detour away from road
                    steps_away = k - int(n_steps * 0.35) + 1
                    detour_m = min(600.0, steps_away * 45.0)
                    if detour_heading is None:
                        nom_b = bearing_deg(raw_lon, raw_lat, sub_polyline[-1][0], sub_polyline[-1][1])
                        detour_heading = (nom_b + 90.0) % 360.0
                    rad = math.radians(detour_heading)
                    raw_lon += (detour_m * math.sin(rad)) / m_per_deg_lon
                    raw_lat += (detour_m * math.cos(rad)) / m_per_deg_lat

                dt = sample_step_interval(trip_rng, cadence_s, config, allow_misses=True)
                cur_time += timedelta(seconds=dt)
                n_lon, n_lat, acc, is_out = apply_gps_noise(trip_rng, raw_lon, raw_lat, config, is_stationary=False)
                prev_p = points[-1] if points else None
                disp = haversine_m(prev_p["longitude"], prev_p["latitude"], n_lon, n_lat) if prev_p else 0.0
                true_sp = (target_m - prev_target_m) / max(1e-3, dt) if k > 0 else 0.0
                sp = calculate_device_speed(
                    trip_rng, disp, dt, config, is_stationary=(k == 0), true_speed_mps=max(true_sp, moving_speed_mps)
                )
                b = calculate_device_bearing(
                    trip_rng, bearing_deg(prev_p["longitude"], prev_p["latitude"], n_lon, n_lat) if prev_p else 0.0
                )
                points.append(
                    {
                        "occurred_at": cur_time.isoformat().replace("+00:00", "Z"),
                        "latitude": n_lat,
                        "longitude": n_lon,
                        "speed_mps": sp,
                        "bearing_deg": b,
                        "accuracy_m": acc,
                        "sequence": k + 1,
                        "mock_location_reported": False,
                        "app_state": "FOREGROUND",
                        "network_state": "CONNECTED_4G",
                        "gps_state": "FINE",
                        "latency_ms": int(trip_rng.uniform(40, 120)),
                        "data_gap_s": round(dt, 2),
                        "davi_score": 0.45 if k >= int(n_steps * 0.35) else 0.02,
                        "distance_to_pickup_m": 0.0,
                        "is_multipath_outlier": is_out,
                    }
                )
                prev_target_m = target_m

    # 5. ERR-04: Phantom trip (driver drives along road without passenger)
    elif label == "ERR-04":
        n_steps = max(12, int(round(nominal_duration_s / cadence_s)))
        cur_time = t0
        prev_target_m = 0.0
        for k in range(n_steps):
            frac = k / max(1, n_steps - 1)
            target_m = frac * total_road_m
            raw_lon, raw_lat, _ = interpolate_along_polyline(sub_polyline, sub_cum_dist, target_m)
            dt = sample_step_interval(trip_rng, cadence_s, config, allow_misses=True)
            cur_time += timedelta(seconds=dt)
            n_lon, n_lat, acc, is_out = apply_gps_noise(trip_rng, raw_lon, raw_lat, config, is_stationary=(k == 0))
            prev_p = points[-1] if points else None
            disp = haversine_m(prev_p["longitude"], prev_p["latitude"], n_lon, n_lat) if prev_p else 0.0
            true_sp = (target_m - prev_target_m) / max(1e-3, dt) if k > 0 else 0.0
            sp = calculate_device_speed(
                trip_rng, disp, dt, config, is_stationary=(k == 0), true_speed_mps=max(true_sp, moving_speed_mps)
            )
            b = calculate_device_bearing(
                trip_rng, bearing_deg(prev_p["longitude"], prev_p["latitude"], n_lon, n_lat) if prev_p else 0.0
            )
            points.append(
                {
                    "occurred_at": cur_time.isoformat().replace("+00:00", "Z"),
                    "latitude": n_lat,
                    "longitude": n_lon,
                    "speed_mps": sp,
                    "bearing_deg": b,
                    "accuracy_m": acc,
                    "sequence": k + 1,
                    "mock_location_reported": False,
                    "app_state": "FOREGROUND",
                    "network_state": "CONNECTED_4G",
                    "gps_state": "FINE",
                    "latency_ms": int(trip_rng.uniform(40, 120)),
                    "data_gap_s": round(dt, 2),
                    "davi_score": 0.02,
                    "distance_to_pickup_m": 0.0,
                    "is_multipath_outlier": is_out,
                }
            )
            prev_target_m = target_m

    # 6. ERR-05: Fake GPS / spoofing (urban speed with discrete teleport jumps / mock flags)
    elif label == "ERR-05":
        departure_mode = "gps_teleportation_spoof"
        n_steps = max(12, int(round(nominal_duration_s / cadence_s)))
        k_teleport = max(4, int(n_steps * 0.45))
        cur_time = t0
        prev_target_m = 0.0
        flags_mock = trip_rng.random() < config.mock_flag_err05_rate

        for k in range(n_steps):
            frac = k / max(1, n_steps - 1)
            target_m = frac * total_road_m
            raw_lon, raw_lat, _ = interpolate_along_polyline(sub_polyline, sub_cum_dist, target_m)
            is_spoof_segment = k >= k_teleport
            is_mock_point = is_spoof_segment and flags_mock

            # Discrete teleport jump at k_teleport step
            if k == k_teleport:
                jump_m = 1200.0
                raw_lon += jump_m / m_per_deg_lon
                raw_lat += jump_m / m_per_deg_lat
            elif is_spoof_segment:
                # Moderate parallel offset; vehicle moves at normal urban speed
                raw_lon += 250.0 / m_per_deg_lon
                raw_lat += 250.0 / m_per_deg_lat

            dt = sample_step_interval(trip_rng, cadence_s, config, allow_misses=True)
            cur_time += timedelta(seconds=dt)
            n_lon, n_lat, acc, is_out = apply_gps_noise(
                trip_rng, raw_lon, raw_lat, config, is_stationary=(k == 0 and not is_mock_point)
            )
            prev_p = points[-1] if points else None
            disp = haversine_m(prev_p["longitude"], prev_p["latitude"], n_lon, n_lat) if prev_p else 0.0

            # Device speed remains in calibrated urban range (~20-30 km/h)
            true_sp = moving_speed_mps if k > 0 else 0.0
            sp = calculate_device_speed(trip_rng, disp, dt, config, is_stationary=(k == 0), true_speed_mps=true_sp)
            b = calculate_device_bearing(
                trip_rng, bearing_deg(prev_p["longitude"], prev_p["latitude"], n_lon, n_lat) if prev_p else 0.0
            )

            points.append(
                {
                    "occurred_at": cur_time.isoformat().replace("+00:00", "Z"),
                    "latitude": n_lat,
                    "longitude": n_lon,
                    "speed_mps": sp,
                    "bearing_deg": b,
                    "accuracy_m": 1.0 if is_mock_point else acc,
                    "sequence": k + 1,
                    "mock_location_reported": is_mock_point,
                    "app_state": "BACKGROUND" if is_mock_point else "FOREGROUND",
                    "network_state": "DISCONNECTED" if is_mock_point else "CONNECTED_4G",
                    "gps_state": "MOCK_REPORTED" if is_mock_point else "FINE",
                    "latency_ms": int(trip_rng.uniform(10, 40) if is_mock_point else trip_rng.uniform(40, 120)),
                    "data_gap_s": round(dt, 2),
                    "davi_score": 0.95 if is_mock_point else 0.02,
                    "distance_to_pickup_m": 0.0,
                    "is_multipath_outlier": is_out,
                }
            )
            prev_target_m = target_m

    # 7. INSUFFICIENT EVIDENCE (Technical dropout: crash or network offline > 30s)
    else:  # label == "insufficient_evidence"
        n_steps = max(10, int(round(nominal_duration_s / cadence_s)))
        k_dropout = max(2, int(n_steps * 0.3))
        dropout_s = trip_rng.uniform(65.0, 180.0)
        cur_time = t0
        prev_target_m = 0.0
        for k in range(n_steps):
            frac = k / max(1, n_steps - 1)
            target_m = frac * total_road_m
            raw_lon, raw_lat, _ = interpolate_along_polyline(sub_polyline, sub_cum_dist, target_m)

            dt = sample_step_interval(trip_rng, cadence_s, config, allow_misses=True)
            if k == k_dropout:
                dt = dropout_s

            cur_time += timedelta(seconds=dt)
            is_offline = k >= k_dropout
            n_lon, n_lat, acc, is_out = apply_gps_noise(trip_rng, raw_lon, raw_lat, config, is_stationary=(k == 0))
            prev_p = points[-1] if points else None
            disp = haversine_m(prev_p["longitude"], prev_p["latitude"], n_lon, n_lat) if prev_p else 0.0
            true_sp = (target_m - prev_target_m) / max(1e-3, dt) if k > 0 else 0.0
            sp = calculate_device_speed(
                trip_rng, disp, dt, config, is_stationary=(k == 0), true_speed_mps=max(true_sp, moving_speed_mps)
            )
            b = calculate_device_bearing(
                trip_rng, bearing_deg(prev_p["longitude"], prev_p["latitude"], n_lon, n_lat) if prev_p else 0.0
            )

            points.append(
                {
                    "occurred_at": cur_time.isoformat().replace("+00:00", "Z"),
                    "latitude": n_lat,
                    "longitude": n_lon,
                    "speed_mps": sp,
                    "bearing_deg": b,
                    "accuracy_m": acc,
                    "sequence": k + 1,
                    "mock_location_reported": False,
                    "app_state": "CRASHED" if is_offline else "FOREGROUND",
                    "network_state": "OFFLINE" if is_offline else "CONNECTED_4G",
                    "gps_state": "UNAVAILABLE" if is_offline else "FINE",
                    "latency_ms": int(trip_rng.uniform(40, 120)),
                    "data_gap_s": round(dt, 2),
                    "davi_score": 0.02,
                    "distance_to_pickup_m": 0.0,
                    "is_multipath_outlier": is_out,
                }
            )
            prev_target_m = target_m

    # Downsample points if max_points_per_trip configured
    if config.max_points_per_trip is not None and len(points) > config.max_points_per_trip:
        max_pts = config.max_points_per_trip
        step = (len(points) - 1) / max(1, max_pts - 1)
        indices = [int(round(i * step)) for i in range(max_pts)]
        unique_indices = sorted(list(dict.fromkeys(indices)))
        points = [points[i] for i in unique_indices]
        for seq_i, pt in enumerate(points, 1):
            pt["sequence"] = seq_i

    first_ts = points[0]["occurred_at"]
    last_ts = points[-1]["occurred_at"]

    # Lifecycles
    if label in ("ERR-01", "ERR-02", "ERR-03"):
        actor = "driver" if label == "ERR-01" else "passenger"
        reason = {
            "ERR-01": "driver_cancelled_unjustified",
            "ERR-02": "driver_stalled_no_show",
            "ERR-03": "route_deviation",
        }[label]
        trip_status, cancelled_at, completed_at = "cancelled", last_ts, None
        assign_state, arrived_at, started_at, ended_at = "cancelled", None, None, last_ts
    elif label == "ERR-04":
        trip_status, cancelled_at, completed_at = "completed", None, last_ts
        actor, reason = None, None
        assign_state, arrived_at, started_at, ended_at = "completed", None, None, last_ts
    elif label == "insufficient_evidence":
        trip_status, cancelled_at, completed_at = "cancelled", last_ts, None
        actor, reason = "platform", "network_timeout"
        assign_state, arrived_at, started_at, ended_at = "cancelled", None, None, last_ts
    else:  # no_violation, ERR-05
        trip_status, cancelled_at, completed_at = "completed", None, last_ts
        actor, reason = None, None
        assign_state, arrived_at, started_at, ended_at = "completed", first_ts, first_ts, last_ts

    # Traffic observation: populated with real road traffic context
    # Needed to cleanly separate ERR-02 (stalling in clear traffic) from honest gridlock (heavy traffic)
    is_gridlock_jam = is_hard_negative and hard_neg_type == "gridlock"
    if is_gridlock_jam:
        traffic_level = round(trip_rng.uniform(0.85, 0.98), 2)
        congestion = "heavy"
        avg_speed = round(trip_rng.uniform(1.2, 3.2), 1)
    else:
        rand_val = trip_rng.random()
        if rand_val < 0.65:
            congestion = "clear"
            traffic_level = round(trip_rng.uniform(0.05, 0.30), 2)
            avg_speed = round(trip_rng.uniform(6.5, 12.0), 1)
        elif rand_val < 0.90:
            congestion = "moderate"
            traffic_level = round(trip_rng.uniform(0.35, 0.65), 2)
            avg_speed = round(trip_rng.uniform(4.0, 6.5), 1)
        else:
            congestion = "heavy"
            traffic_level = round(trip_rng.uniform(0.70, 0.85), 2)
            avg_speed = round(trip_rng.uniform(2.5, 4.0), 1)

    traffic = {
        "congestion_level": congestion,
        "traffic_level": traffic_level,
        "average_speed_mps": avg_speed,
        "source": "provider",
        "is_simulated": True,
        "observed_at": first_ts,
        "valid_until": last_ts,
        "corridor_id": corr.corridor_id,
    }

    platform_incident = None
    if label == "insufficient_evidence":
        platform_incident = {
            "id": f"inc-{idx + 1:06d}",
            "kind": "NETWORK_OUTAGE",
            "occurred_at": first_ts,
            "resolved_at": last_ts,
            "severity": "P1",
        }
    elif label == "ERR-05":
        platform_incident = {
            "id": f"inc-{idx + 1:06d}",
            "kind": "TELEMETRY_ANOMALY",
            "occurred_at": first_ts,
            "resolved_at": last_ts,
            "severity": "P0",
        }

    # Dialogue & reports
    weak_evidence = trip_rng.random() < 0.20
    dialogue = (
        []
        if weak_evidence
        else synthesize_realistic_dialogue(
            trip_rng, label, SCENARIO_FOR_LABEL[label], is_hard_negative=is_hard_negative
        )
    )
    cust_report = synthesize_realistic_customer_report(trip_rng, label, weak_evidence=weak_evidence, config=config)
    driver_objection = synthesize_realistic_driver_objection(trip_rng, label, config=config)

    # Identifiers
    trip_ref = f"rv2_{split}_{idx + 1:06d}"
    ns = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
    trip_id = str(uuid.uuid5(ns, f"greensentinel:v2:trip:{trip_ref}"))
    assign_id = str(uuid.uuid5(ns, f"greensentinel:v2:assignment:{trip_ref}"))

    clean_driver = dict(driver)
    clean_driver["organization_id"] = None
    driver_analytics = synthesize_driver_analytics(trip_rng, clean_driver)

    fare_amount = max(35000, int(round((total_road_m / 1000.0) * 14000 + 15000, -3)))
    prevalence_weight = config.calculate_prevalence_weight(label)

    return {
        "trip_id": trip_id,
        "trip_ref": trip_ref,
        "assignment_id": assign_id,
        "release": config.release_name,
        "split": split,
        "city": city,
        "label": label,
        "requested_at": t0.isoformat().replace("+00:00", "Z"),
        "pickup": pickup,
        "dropoff": dropoff,
        "route": {
            "distance_m": int(round(total_road_m)),
            "duration_s": int(round(nominal_duration_s)),
            "geometry": {"type": "LineString", "coordinates": sub_polyline},
            "corridor_id": corr.corridor_id,
            "street_names": corr.street_names,
        },
        "planned_route": {
            "distance_m": int(round(total_road_m)),
            "duration_s": int(round(nominal_duration_s)),
            "geometry": {"type": "LineString", "coordinates": sub_polyline},
            "provider": "OSRM / OpenStreetMap contributors",
            "provenance": "OSRM / OpenStreetMap contributors",
            "license": "ODbL - OpenStreetMap contributors",
        },
        "telemetry": points,
        "trip": {
            "id": trip_id,
            "status": trip_status,
            "fare_amount": fare_amount,
            "currency": "VND",
            "cancelled_at": cancelled_at,
            "completed_at": completed_at,
        },
        "assignment": {
            "id": assign_id,
            "state": assign_state,
            "offered_at": t0.isoformat().replace("+00:00", "Z"),
            "accepted_at": t0.isoformat().replace("+00:00", "Z"),
            "arrived_at": arrived_at,
            "started_at": started_at,
            "ended_at": ended_at,
            "cancellation_actor": actor,
            "cancellation_reason": reason,
        },
        "vehicle": {
            "id": clean_driver.get("vehicle_id", f"veh-v2-{idx + 1:06d}"),
            "license_plate": f"{29 if city == 'Hanoi' else 51}{trip_rng.choice(['A', 'E', 'F', 'G'])}-{trip_rng.randint(100, 999)}.{trip_rng.randint(10, 99)}",
            "make": trip_rng.choice(["VinFast", "Toyota", "Hyundai", "Honda"]),
            "model": trip_rng.choice(["VF e34", "VF 5 Plus", "Vios", "Accent", "City"]),
        },
        "vehicle_id": clean_driver.get("vehicle_id", f"veh-v2-{idx + 1:06d}"),
        "driver_id": clean_driver["id"],
        "driver_profile": clean_driver,
        "driver_analytics": driver_analytics,
        "passenger_id": passenger["id"],
        "scenario": SCENARIO_FOR_LABEL[label],
        "conversation": dialogue,
        "customer_report": cust_report,
        "driver_objection": driver_objection,
        "traffic_observation": traffic,
        "platform_incident": platform_incident,
        "prevalence_weight": prevalence_weight,
        "geography_provenance": {
            "country": "VN",
            "city": city,
            "locale": "vi-VN",
            "provider": "OSRM / OpenStreetMap contributors",
            "license": "ODbL",
            "attribution": "© OpenStreetMap contributors",
            "corridor_id": corr.corridor_id,
        },
        "simulation_audit": {
            "generator_version": config.generator_version,
            "corridor_id": corr.corridor_id,
            "departure_mode": departure_mode,
            "err03_subtype": err03_subtype,
            "is_hard_negative": is_hard_negative,
            "hard_neg_type": hard_neg_type,
            "is_reversed": is_reversed,
            "severity": SEVERITY_POLICY[label],
            "scenario": SCENARIO_FOR_LABEL[label],
            "ping_profile_s": cadence_s,
        },
    }
