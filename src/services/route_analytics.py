"""Route analytics, candidate routing, traffic corroboration, and trip timeline calculation.

Extracted service module preventing circular imports between telemetry queue workers
and case services.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Safely cast value to float, handling None, malformed strings, and type errors."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _extract_coord_pair(val: Any) -> tuple[float, float] | None:
    """Safely extract (lon, lat) tuple from a list/tuple, GeoJSON dict, or point dict."""
    if isinstance(val, dict):
        coords = val.get("coordinates")
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            val = coords
        elif "longitude" in val and "latitude" in val:
            try:
                lon, lat = float(val["longitude"]), float(val["latitude"])
                if math.isfinite(lon) and math.isfinite(lat):
                    return (lon, lat)
            except (TypeError, ValueError):
                return None
    if isinstance(val, (list, tuple)) and len(val) >= 2:
        try:
            lon, lat = float(val[0]), float(val[1])
            if math.isfinite(lon) and math.isfinite(lat):
                return (lon, lat)
        except (TypeError, ValueError):
            return None
    return None


def _extract_coord(pt: dict[str, Any]) -> tuple[float, float] | None:
    """Extract recorded coordinates, leaving incomplete telemetry unmapped."""
    lat = pt.get("latitude")
    lon = pt.get("longitude")
    if lat is not None and lon is not None:
        try:
            coordinate = (float(lon), float(lat))
        except (TypeError, ValueError):
            return None
        if math.isfinite(coordinate[0]) and math.isfinite(coordinate[1]):
            if -180 <= coordinate[0] <= 180 and -90 <= coordinate[1] <= 90:
                return coordinate
        return None
    pos = pt.get("position")
    if isinstance(pos, dict):
        coords = pos.get("coordinates")
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            return _extract_coord({"longitude": coords[0], "latitude": coords[1]})
    return None


def parse_timestamp(val: Any) -> datetime | None:
    """Robust timestamp parser supporting ISO 8601 strings, UNIX timestamps, and datetime objects."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo is not None else val.replace(tzinfo=UTC)
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(val, tz=UTC)
        except (ValueError, OverflowError, OSError):
            return None

    s = str(val).strip()
    if not s:
        return None

    # Handle Z suffix for UTC
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        pass

    # Try common formats
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S%z"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
        except ValueError:
            continue

    return None


def detect_telemetry_missingness(
    points: list[dict[str, Any]],
    gap_threshold_s: int = 30,
    end_time: Any = None,
) -> list[dict[str, Any]]:
    """Detect telemetry gaps and anomalies in time sequence with resilient date parsing."""
    alerts: list[dict[str, Any]] = []
    if not points:
        return alerts

    for i in range(1, len(points)):
        p_prev = points[i - 1]
        p_curr = points[i]

        t_prev_raw = p_prev.get("occurred_at")
        t_curr_raw = p_curr.get("occurred_at")
        if not t_prev_raw or not t_curr_raw:
            continue

        t_prev = parse_timestamp(t_prev_raw)
        t_curr = parse_timestamp(t_curr_raw)
        if not t_prev or not t_curr:
            continue

        diff_s = (t_curr - t_prev).total_seconds()

        if diff_s <= 0:
            continue

        is_prev_invalid = _extract_coord(p_prev) is None
        is_curr_invalid = _extract_coord(p_curr) is None

        has_explicit = (
            p_curr.get("gps_state") in ("unavailable", "unknown")
            or p_prev.get("gps_state") in ("unavailable", "unknown")
            or p_curr.get("network_state") in ("offline", "degraded")
            or p_prev.get("network_state") in ("offline", "degraded")
            or p_curr.get("app_state") == "crashed"
            or p_prev.get("app_state") == "crashed"
            or is_prev_invalid
            or is_curr_invalid
        )

        if diff_s > gap_threshold_s or has_explicit:
            gap_dur = diff_s

            reason = (
                f"Thiếu dữ liệu telemetry (nguyên nhân không xác định / Unknown cause): gián đoạn tín hiệu {gap_dur}s"
            )

            # Find most specific reason
            if p_curr.get("network_state") in ("offline", "degraded"):
                reason = f"Mạng di động (Network {p_curr.get('network_state')}): mất tín hiệu telemetry kết nối trong {gap_dur}s"
            elif p_prev.get("network_state") in ("offline", "degraded"):
                reason = f"Mạng di động (Network {p_prev.get('network_state')}): mất tín hiệu telemetry kết nối trong {gap_dur}s"
            elif p_curr.get("app_state") == "crashed" or p_prev.get("app_state") == "crashed":
                reason = f"Ứng dụng tài xế bị crash (App crashed telemetry loss) trong {gap_dur}s"
            elif p_curr.get("gps_state") in ("unavailable", "unknown") or p_prev.get("gps_state") in (
                "unavailable",
                "unknown",
            ):
                reason = f"Tín hiệu GPS không khả dụng trong {gap_dur}s"
            elif is_curr_invalid or is_prev_invalid:
                reason = f"Dữ liệu tọa độ không hợp lệ hoặc bị thiếu trong {gap_dur}s"

            alerts.append(
                {
                    "alert_id": str(uuid4()),
                    "start_time": t_prev.isoformat(),
                    "end_time": t_curr.isoformat(),
                    "gap_duration_s": gap_dur,
                    "reason": reason,
                    "severity": "critical" if gap_dur >= 60 else "warning",
                }
            )

    terminal = points[-1]
    terminal_time = next(
        (parsed for point in reversed(points) if (parsed := _parse_timestamp(point.get("occurred_at")))),
        None,
    )
    recorded_end = _parse_timestamp(end_time)
    terminal_invalid = (
        _extract_coord(terminal) is None
        or terminal.get("gps_state") in ("unavailable", "unknown")
        or terminal.get("network_state") in ("offline", "degraded")
        or terminal.get("app_state") == "crashed"
    )
    if terminal_time and recorded_end and recorded_end > terminal_time and terminal_invalid:
        gap_dur = (recorded_end - terminal_time).total_seconds()
        alerts.append(
            {
                "alert_id": str(uuid4()),
                "start_time": terminal_time.isoformat(),
                "end_time": recorded_end.isoformat(),
                "gap_duration_s": gap_dur,
                "reason": f"Dữ liệu telemetry không khả dụng đến thời điểm kết thúc đã ghi nhận trong {gap_dur}s",
                "severity": "critical" if gap_dur >= 60 else "warning",
            }
        )

    return alerts


def corroborate_traffic_claim(
    road_segment: str,
    observed_at: str,
    suspect: dict[str, Any],
    peers: list[dict[str, Any]] | None = None,
    public_service: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Corroborate a traffic claim only when an actual provider or peer sample is supplied."""
    peers = peers or []
    peer_speeds = [float(p["speed_kmh"]) for p in peers if p.get("speed_kmh") is not None]
    avg_peer_speed = (sum(peer_speeds) / len(peer_speeds)) if len(peer_speeds) > 0 else 0.0

    claimed_reason = suspect.get("claimed_reason", "traffic_jam")
    suspect_speed = float(suspect.get("speed_kmh", 0.0))
    stall_dur = int(suspect.get("stall_duration_s", 0))

    if (public_service and public_service.get("congestion") == "clear") or (peer_speeds and avg_peer_speed >= 20.0):
        verdict = "refuted"
        if public_service:
            verdict_detail = (
                f"Tuyên bố kẹt xe ({claimed_reason}) bị bác bỏ (Traffic claim refuted): "
                f"Dịch vụ {public_service.get('provider', 'traffic provider')} báo đường thông suốt "
                f"(vận tốc TB: {public_service.get('average_speed_kmh')} km/h)."
            )
        else:
            verdict_detail = (
                f"Tuyên bố kẹt xe ({claimed_reason}) bị bác bỏ theo {len(peer_speeds)} mẫu xe thực tế "
                f"trên đoạn {road_segment} (vận tốc TB: {avg_peer_speed:.1f} km/h); "
                f"xe nghi vấn ghi nhận {suspect_speed:.1f} km/h trong {stall_dur}s."
            )
    elif public_service and public_service.get("congestion") == "heavy" and peer_speeds and avg_peer_speed < 10.0:
        verdict = "corroborated"
        verdict_detail = (
            f"Xác nhận kẹt xe (Traffic claim corroborated): Đoạn đường {road_segment} đang ùn ứ nghiêm trọng "
            f"(vận tốc dòng xe {avg_peer_speed:.1f} km/h), phù hợp với giải trình của tài xế."
        )
    else:
        verdict = "inconclusive"
        verdict_detail = "Dữ liệu giao thông unavailable; chưa đủ căn cứ xác thực hoặc bác bỏ."

    return {
        "road_segment": road_segment,
        "observed_at": observed_at,
        "suspect_driver": suspect,
        "peer_drivers": peers,
        "public_service": public_service,
        "verdict": verdict,
        "verdict_detail": verdict_detail,
    }


def build_trip_timeline_milestones(
    points: list[dict[str, Any]],
    pickup_pos: list[float] | None,
    dropoff_pos: list[float] | None,
    stall_duration_s: int = 0,
    alerts: list[dict[str, Any]] | None = None,
    arrived_at: str | None = None,
    ended_at: str | None = None,
    trip_status: str | None = None,
    assignment_state: str | None = None,
) -> list[dict[str, Any]]:
    """Build full trip timeline milestones (matching -> arriving -> pickup -> destination)."""
    milestones: list[dict[str, Any]] = []
    arrived_at = arrived_at if isinstance(arrived_at, str) and _parse_timestamp(arrived_at) else None
    ended_at = ended_at if isinstance(ended_at, str) and _parse_timestamp(ended_at) else None
    normalized_trip_status = str(trip_status or "").strip().lower()
    normalized_assignment_state = str(assignment_state or "").strip().lower()
    arrived_dt = _parse_timestamp(arrived_at)
    ended_dt = _parse_timestamp(ended_at)
    if arrived_dt and ended_dt and ended_dt < arrived_dt:
        arrived_at = None
        ended_at = None
        arrived_dt = None
        ended_dt = None
    completed = (
        normalized_trip_status in {"completed", "complete"}
        if normalized_trip_status
        else normalized_assignment_state in {"completed", "complete"}
    )
    if not points:
        if pickup_pos and len(pickup_pos) >= 2 and arrived_at:
            milestones.append(
                {
                    "id": "ms-pickup",
                    "timestamp": arrived_at,
                    "sequence": None,
                    "type": "pickup",
                    "title": "Điểm đón khách (Pickup Point)",
                    "description": "Tài xế tiếp cận điểm hẹn đón khách",
                    "lat": pickup_pos[1],
                    "lon": pickup_pos[0],
                    "speed_mps": None,
                    "is_anomaly": False,
                }
            )
        if dropoff_pos and len(dropoff_pos) >= 2 and completed and ended_at:
            milestones.append(
                {
                    "id": "ms-destination",
                    "timestamp": ended_at,
                    "sequence": None,
                    "type": "dropoff_destination",
                    "title": "Đích đến (Dropoff Destination)",
                    "description": "Kết thúc chuyến đi tại điểm trả khách theo định tuyến",
                    "lat": dropoff_pos[1],
                    "lon": dropoff_pos[0],
                    "speed_mps": None,
                    "is_anomaly": False,
                }
            )
        return milestones

    # 1. Matching & Start
    p0 = points[0]
    t0 = p0.get("occurred_at")
    start_coordinate = _extract_coord(p0)
    if start_coordinate:
        lon0, lat0 = start_coordinate
        milestones.append(
            {
                "id": "ms-start",
                "timestamp": t0,
                "sequence": p0.get("sequence", 0),
                "type": "start_match",
                "title": "",
                "description": "Thời gian bắt đầu hành trình",
                "lat": lat0,
                "lon": lon0,
                "speed_mps": _safe_float(p0.get("speed_mps")) if p0.get("speed_mps") is not None else None,
                "is_anomaly": False,
            }
        )

    # 2. Stall Anomaly (if applicable)
    if stall_duration_s >= 60:
        stall_pt = points[1] if len(points) > 1 else p0
        stall_coordinate = _extract_coord(stall_pt)
        if stall_coordinate:
            lon_s, lat_s = stall_coordinate
            milestones.append(
                {
                    "id": "ms-stall",
                    "timestamp": stall_pt.get("occurred_at") or t0,
                    "sequence": stall_pt.get("sequence", 1),
                    "type": "stall_anomaly",
                    "title": f"Bất thường dừng đỗ ({stall_duration_s}s)",
                    "description": f"Phát hiện xe dừng bất động kéo dài {stall_duration_s}s",
                    "lat": lat_s,
                    "lon": lon_s,
                    "speed_mps": stall_pt.get("speed_mps"),
                    "is_anomaly": True,
                }
            )

    # 3. Missingness Gaps
    if alerts:
        for alt in alerts:
            milestones.append(
                {
                    "id": f"ms-gap-{alt['alert_id'][:8]}",
                    "timestamp": alt["start_time"],
                    "type": "gap_anomaly",
                    "title": f"Mất dữ liệu ({alt['gap_duration_s']}s)",
                    "description": alt["reason"],
                    "is_anomaly": True,
                }
            )

    # 4. Pickup Point Milestone
    departure = next((pt for pt in points if pt.get("leg") == "destination"), None)
    pickup_time = arrived_at or (departure or {}).get("occurred_at")
    if pickup_pos and len(pickup_pos) >= 2:
        pickup_source = departure or points[0]
        pickup_source_matches = pickup_source.get("occurred_at") == pickup_time
        if pickup_time:
            milestones.append(
                {
                    "id": "ms-pickup",
                    "timestamp": pickup_time,
                    "sequence": pickup_source.get("sequence") if pickup_source_matches else None,
                    "type": "pickup",
                    "title": "Điểm đón khách (Pickup Point)",
                    "description": "Tài xế tiếp cận điểm hẹn đón khách",
                    "lat": pickup_pos[1],
                    "lon": pickup_pos[0],
                    "speed_mps": pickup_source.get("speed_mps") if pickup_source_matches else None,
                    "is_anomaly": False,
                }
            )

    p_last = points[-1]
    dropoff_time = ended_at if completed else None
    if dropoff_pos and len(dropoff_pos) >= 2 and dropoff_time:
        milestones.append(
            {
                "id": "ms-destination",
                "timestamp": dropoff_time,
                "sequence": p_last.get("sequence") if p_last.get("occurred_at") == dropoff_time else None,
                "type": "dropoff_destination",
                "title": "Đích đến (Dropoff Destination)",
                "description": "Kết thúc chuyến đi tại điểm trả khách theo định tuyến",
                "lat": dropoff_pos[1],
                "lon": dropoff_pos[0],
                "speed_mps": p_last.get("speed_mps") if p_last.get("occurred_at") == dropoff_time else None,
                "is_anomaly": False,
            }
        )

    return milestones


def haversine_distance_m(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    """Calculate great circle distance between two points (lon, lat) in meters."""
    lon1, lat1 = p1
    lon2, lat2 = p2
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


def calculate_bearing_deg(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    """Calculate geographic initial bearing (0-360) from p1 (lon, lat) to p2 (lon, lat)."""
    lon1, lat1 = math.radians(p1[0]), math.radians(p1[1])
    lon2, lat2 = math.radians(p2[0]), math.radians(p2[1])
    dlon = lon2 - lon1
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    bearing = math.degrees(math.atan2(y, x))
    return (bearing + 360.0) % 360.0


def heading_diff_deg(b1: float, b2: float) -> float:
    """Signed angle difference from b1 to b2 in [-180, 180]. Positive = turn right, negative = turn left."""
    return (b2 - b1 + 180.0) % 360.0 - 180.0


def parse_trajectory_maneuvers(
    points: list[dict[str, Any]],
    pickup: list[float] | None = None,
    dropoff: list[float] | None = None,
    planned_route: list[list[float]] | None = None,
    stall_duration_s: int = 0,
) -> list[dict[str, Any]]:
    """Parse raw GPS points into human and LLM-readable turn-by-turn kinematic maneuvers.

    Extracts:
    - Straight segments: "Đi thẳng {dist}m, vận tốc TB {v} km/h (v_max={max_v} km/h)"
    - Turns: "Rẽ trái ({deg}° tại [lon, lat])", "Rẽ phải ({deg}°)"
    - U-turns: "Quay đầu ({deg}°)"
    - Stops: "Dừng đỗ {duration}s tại [lon, lat], v=0 km/h (cách điểm đón {dist}m)"
    - GPS anomalies: "Mock location / speed jump ({v} km/h)"
    """
    points = [point for point in points if _extract_coord(point) is not None]
    if not points:
        return []

    maneuvers: list[dict[str, Any]] = []
    pickup_tuple = (pickup[0], pickup[1]) if (pickup and len(pickup) >= 2) else None

    # Handle edge case: single point with known stall duration
    if len(points) == 1:
        p0 = points[0]
        coord = _extract_coord(p0)
        if coord is None:
            return []
        dur = stall_duration_s
        speed = _safe_float(p0.get("speed_mps"), 0.0) * 3.6
        if dur <= 0 or speed >= 2.0:
            return []
        dist_pickup = int(haversine_distance_m(coord, pickup_tuple)) if pickup_tuple else None
        p_text = f" (cách điểm đón {dist_pickup}m)" if dist_pickup is not None else ""
        maneuvers.append(
            {
                "action": "stop",
                "instruction": f"Dừng đỗ {dur}s tại [{coord[0]:.5f}, {coord[1]:.5f}], v=0.0 km/h{p_text}",
                "duration_s": dur,
                "distance_m": 0.0,
                "avg_speed_kmh": speed,
                "max_speed_kmh": speed,
                "is_anomaly": dur >= 180,
                "coordinates": [list(coord)],
                "start_time": p0.get("occurred_at"),
                "end_time": p0.get("occurred_at"),
            }
        )
        return maneuvers

    seg_points: list[tuple[float, float]] = []
    seg_speeds: list[float] = []
    seg_start_t = None
    seg_end_t = None
    last_bearing: float | None = None

    def flush_straight() -> None:
        nonlocal seg_points, seg_speeds, seg_start_t, seg_end_t, last_bearing
        if not seg_points or len(seg_points) < 2:
            seg_points = []
            seg_speeds = []
            return
        total_dist = 0.0
        for i in range(len(seg_points) - 1):
            total_dist += haversine_distance_m(seg_points[i], seg_points[i + 1])
        speeds_kmh = [s * 3.6 for s in seg_speeds] if seg_speeds else [0.0]
        avg_v = sum(speeds_kmh) / len(speeds_kmh) if speeds_kmh else 0.0
        max_v = max(speeds_kmh) if speeds_kmh else 0.0
        t0 = parse_timestamp(seg_start_t)
        t1 = parse_timestamp(seg_end_t)
        dur = int((t1 - t0).total_seconds()) if (t0 and t1) else len(seg_points) * 5
        dur = max(dur, 1)

        bearing_txt = f" hướng {int(round(last_bearing))}°" if last_bearing is not None else ""

        # Check directional divergence from pickup point (wrong direction detection)
        is_wrong_dir = False
        dir_extra = ""
        action = "go_straight"
        policy_tag = None
        if pickup_tuple and total_dist >= 80.0 and dur >= 15:
            d_start = haversine_distance_m(seg_points[0], pickup_tuple)
            d_end = haversine_distance_m(seg_points[-1], pickup_tuple)
            # Distance increased and driver moved away from pickup
            if d_end - d_start >= 60.0:
                target_bearing = calculate_bearing_deg(seg_points[0], pickup_tuple)
                actual_bearing = calculate_bearing_deg(seg_points[0], seg_points[-1])
                angle_dev = abs(heading_diff_deg(actual_bearing, target_bearing))
                if angle_dev >= 95.0:
                    is_wrong_dir = True
                    action = "wrong_direction"
                    policy_tag = "Điều 16.1 (ERR-03)"
                    dir_extra = (
                        f" ⚠️ [CẢNH BÁO: Di chuyển ngược hướng điểm đón (cách điểm đón tăng từ {d_start:.0f}m lên {d_end:.0f}m, "
                        f"góc lệch {angle_dev:.0f}°) - {policy_tag}]"
                    )

        instruction = (
            f"Đi thẳng {total_dist:.0f}m{bearing_txt}, vận tốc TB {avg_v:.1f} km/h "
            f"(v_max={max_v:.1f} km/h, thời gian {dur}s){dir_extra}"
        )
        entry: dict[str, Any] = {
            "action": action,
            "instruction": instruction,
            "duration_s": dur,
            "distance_m": round(total_dist, 1),
            "avg_speed_kmh": round(avg_v, 1),
            "max_speed_kmh": round(max_v, 1),
            "is_anomaly": is_wrong_dir or (max_v > 120.0),
            "coordinates": [list(c) for c in seg_points],
            "start_time": seg_start_t,
            "end_time": seg_end_t,
        }
        if policy_tag:
            entry["policy_tag"] = policy_tag
        maneuvers.append(entry)
        seg_points = []
        seg_speeds = []

    def flush_stop(coord: tuple[float, float], t_start: Any, t_end: Any, count: int) -> None:
        t0 = parse_timestamp(t_start)
        t1 = parse_timestamp(t_end)
        dur = int((t1 - t0).total_seconds()) if (t0 and t1) else count * 10
        if stall_duration_s and dur < stall_duration_s:
            dur = stall_duration_s
        dur = max(dur, 1)
        dist_pickup = int(haversine_distance_m(coord, pickup_tuple)) if pickup_tuple else None
        p_text = f" (cách điểm đón {dist_pickup}m)" if dist_pickup is not None else ""
        is_anom = dur >= 180
        anom_tag = " ⚠️ [CẢNH BÁO: Dừng đỗ kéo dài >= 180s - Điều 14.2]" if is_anom else ""
        instruction = f"Dừng đỗ {dur}s tại [{coord[0]:.5f}, {coord[1]:.5f}], v=0.0 km/h{p_text}{anom_tag}"
        maneuvers.append(
            {
                "action": "stop",
                "instruction": instruction,
                "duration_s": dur,
                "distance_m": 0.0,
                "avg_speed_kmh": 0.0,
                "max_speed_kmh": 0.0,
                "is_anomaly": is_anom,
                "coordinates": [list(coord)],
                "start_time": t_start,
                "end_time": t_end,
            }
        )

    in_stop = False
    stop_coord = (0.0, 0.0)
    stop_start_t = None
    stop_end_t = None
    stop_count = 0

    for idx in range(len(points)):
        pt = points[idx]
        coord = _extract_coord(pt)
        if coord is None:
            continue
        speed = _safe_float(pt.get("speed_mps"), 0.0)
        t_curr = pt.get("occurred_at")
        mock = bool(pt.get("mock_location_reported")) or pt.get("gps_state") == "mock_reported"

        if mock:
            maneuvers.append(
                {
                    "action": "gps_anomaly",
                    "instruction": f"⚠️ Phát hiện giả lập GPS (Mock Location) tại [{coord[0]:.5f}, {coord[1]:.5f}]",
                    "duration_s": 1,
                    "distance_m": 0.0,
                    "avg_speed_kmh": round(speed * 3.6, 1),
                    "max_speed_kmh": round(speed * 3.6, 1),
                    "is_anomaly": True,
                    "coordinates": [list(coord)],
                    "start_time": t_curr,
                    "end_time": t_curr,
                }
            )

        # Check stationary condition: speed < 0.8 m/s (~3 km/h)
        if speed < 0.8:
            if not in_stop:
                flush_straight()
                in_stop = True
                stop_coord = coord
                stop_start_t = t_curr
                stop_end_t = t_curr
                stop_count = 1
            else:
                stop_end_t = t_curr
                stop_count += 1
            continue
        else:
            if in_stop:
                flush_stop(stop_coord, stop_start_t, stop_end_t, stop_count)
                in_stop = False
                stop_count = 0

        # Moving point
        if not seg_points:
            seg_points = [coord]
            seg_speeds = [speed]
            seg_start_t = t_curr
            seg_end_t = t_curr
            if pt.get("bearing_deg") is not None:
                last_bearing = _safe_float(pt["bearing_deg"])
            continue

        prev_coord = seg_points[-1]
        dist_step = haversine_distance_m(prev_coord, coord)
        step_bearing = (
            _safe_float(pt.get("bearing_deg"))
            if pt.get("bearing_deg") is not None
            else calculate_bearing_deg(prev_coord, coord)
        )

        if last_bearing is None:
            last_bearing = step_bearing

        delta_angle = heading_diff_deg(last_bearing, step_bearing)

        # Turn threshold: > 28 degrees
        if abs(delta_angle) >= 28.0 and dist_step >= 3.0:
            flush_straight()
            speed_kmh = speed * 3.6
            if abs(delta_angle) >= 145.0:
                action = "u_turn"
                instruction = f"Quay đầu xe (góc {abs(delta_angle):.0f}°) tại [{coord[0]:.5f}, {coord[1]:.5f}], v={speed_kmh:.1f} km/h"
            elif delta_angle > 0:
                action = "turn_right"
                instruction = f"Rẽ phải (góc {abs(delta_angle):.0f}°) tại [{coord[0]:.5f}, {coord[1]:.5f}], v={speed_kmh:.1f} km/h"
            else:
                action = "turn_left"
                instruction = f"Rẽ trái (góc {abs(delta_angle):.0f}°) tại [{coord[0]:.5f}, {coord[1]:.5f}], v={speed_kmh:.1f} km/h"

            maneuvers.append(
                {
                    "action": action,
                    "instruction": instruction,
                    "duration_s": 5,
                    "distance_m": round(dist_step, 1),
                    "avg_speed_kmh": round(speed_kmh, 1),
                    "max_speed_kmh": round(speed_kmh, 1),
                    "is_anomaly": False,
                    "coordinates": [list(prev_coord), list(coord)],
                    "start_time": seg_end_t or t_curr,
                    "end_time": t_curr,
                }
            )
            seg_points = [coord]
            seg_speeds = [speed]
            seg_start_t = t_curr
            seg_end_t = t_curr
            last_bearing = step_bearing
        else:
            seg_points.append(coord)
            seg_speeds.append(speed)
            seg_end_t = t_curr
            last_bearing = step_bearing

    if in_stop:
        flush_stop(stop_coord, stop_start_t, stop_end_t, stop_count)
    else:
        flush_straight()

    return maneuvers


def format_maneuvers_for_llm(
    maneuvers: list[dict[str, Any]],
    event_data: dict[str, Any] | None = None,
) -> str:
    """Format parsed trajectory maneuvers and trip metadata into a concise, high-signal
    forensic narrative prompt block for Jev Sentinel or human analyst inspection.
    """
    event_data = event_data or {}
    pickup = event_data.get("pickup")
    dropoff = event_data.get("dropoff")
    reason = event_data.get("cancellation_reason")
    actor = event_data.get("cancellation_actor")

    total_dist = sum(float(m.get("distance_m", 0.0)) for m in maneuvers)
    total_dur = sum(int(m.get("duration_s", 0)) for m in maneuvers)
    stops = [m for m in maneuvers if m.get("action") == "stop"]
    total_stop_s = sum(int(s.get("duration_s", 0)) for s in stops)
    max_stop_s = max((int(s.get("duration_s", 0)) for s in stops), default=0)
    speeds = [
        float(m.get("avg_speed_kmh", 0.0))
        for m in maneuvers
        if m.get("action") in ("go_straight", "turn_left", "turn_right", "u_turn")
    ]
    avg_speed = (sum(speeds) / len(speeds)) if speeds else 0.0

    p_coord = _extract_coord_pair(pickup)
    d_coord = _extract_coord_pair(dropoff)

    lines: list[str] = [
        "=== HỒ SƠ PHÂN TÍCH ĐỘNG HỌC & ĐIỀU HƯỚNG TÀI XẾ (KINEMATIC MANEUVER PROFILE) ===",
        f"• Tổng quãng đường di chuyển: {total_dist:.0f}m | Thời gian ghi nhận: {total_dur}s",
        f"• Vận tốc trung bình khi lăn bánh: {avg_speed:.1f} km/h",
        f"• Số lần dừng đỗ: {len(stops)} lần | Tổng thời gian dừng: {total_stop_s}s | Dừng lâu nhất: {max_stop_s}s",
    ]
    if p_coord:
        lines.append(f"• Tọa độ điểm đón khách (Pickup): [{p_coord[0]:.5f}, {p_coord[1]:.5f}]")
    if d_coord:
        lines.append(f"• Tọa độ điểm đến (Dropoff): [{d_coord[0]:.5f}, {d_coord[1]:.5f}]")
    if actor or reason:
        lines.append(f"• Thông tin hủy chuyến: Bên hủy='{actor or 'n/a'}', Lý do='{reason or 'n/a'}'")

    lines.append("\nCHI TIẾT CHUỖI ĐỘNG HỌC & CHỈ DẪN DI CHUYỂN THỰC TẾ:")
    if not maneuvers:
        lines.append("  (Không có dữ liệu điểm telemetry)")
    else:
        for i, m in enumerate(maneuvers, 1):
            t_info = ""
            if m.get("start_time"):
                t_str = str(m["start_time"])
                t_info = f"[{t_str[-8:]}] " if len(t_str) >= 8 else f"[{t_str}] "
            lines.append(f"  {i}. {t_info}{m['instruction']}")

    # Policy flags summary
    lines.append("\nDẤU HIỆU VI PHẠM THEO QUY CHẾ GREENSM 2026:")
    if max_stop_s >= 180:
        lines.append(
            f"  - [CẢNH BÁO ĐIỀU 14.2]: Phát hiện dừng đỗ {max_stop_s}s (vượt ngưỡng cho phép 180s). Nguy cơ ép khách hủy cuốc (ERR-02)."
        )
    if any(m.get("action") == "gps_anomaly" or m.get("max_speed_kmh", 0) > 120 for m in maneuvers):
        lines.append(
            "  - [CẢNH BÁO ĐIỀU 15.3]: Phát hiện can thiệp tọa độ GPS / Fake GPS / Nhảy vọt tốc độ bất khả thi (ERR-05)."
        )
    if any(m.get("action") == "u_turn" for m in maneuvers):
        lines.append(
            "  - [CHÚ Ý ĐIỀU 16.1]: Có thao tác quay đầu / đổi hướng đột ngột, cần đối chiếu lộ trình đề xuất (ERR-03)."
        )
    if not any(m.get("is_anomaly") for m in maneuvers):
        lines.append("  - [CHUẨN TẮC]: Không phát hiện bất thường động học, tài xế vận hành bình thường.")

    return "\n".join(lines)


# Backward-compatible private alias.
_parse_timestamp = parse_timestamp
