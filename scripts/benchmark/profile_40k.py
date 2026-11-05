"""Profile the 40,000 trips in data/benchmark-10k/releases_v1/trips.jsonl.

Measures:
- Geography distribution (Vietnam, Portugal, US, etc.)
- Schema analysis & nested fields comparison
- Label and severity breakdown
- Route distance and duration distributions
- Driver statistics and train/test split
"""

from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    return 2.0 * radius * math.asin(min(1.0, math.sqrt(a)))


def classify_geo(lat: float | None, lon: float | None, provenance: str | None = None) -> str:
    if lat is None or lon is None:
        return "missing_coords"
    if 8.0 <= lat <= 24.0 and 102.0 <= lon <= 110.0:
        return "Vietnam"
    if 40.0 <= lat <= 43.0 and -10.0 <= lon <= -6.0:
        return "Portugal (Porto)"
    if 24.0 <= lat <= 50.0 and -125.0 <= lon <= -66.0:
        return "US (NYC/other)"
    return f"Other ({round(lat, 2)}, {round(lon, 2)})"


def profile_dataset(trips_path: Path) -> dict:
    total_trips = 0
    releases = Counter()
    labels = Counter()
    geographies = Counter()
    pickup_names = Counter()
    dropoff_names = Counter()
    geo_provenances = Counter()

    distances: list[float] = []
    durations: list[float] = []
    telemetry_counts: list[int] = []
    drivers = Counter()
    org_ids = Counter()

    # Nested field presence trackers
    top_level_keys = Counter()
    assignment_keys = Counter()
    driver_profile_keys = Counter()
    telemetry_keys = Counter()

    print(f"Profiling {trips_path}...")
    with trips_path.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            if not line.strip():
                continue
            total_trips += 1
            if total_trips % 10000 == 0:
                print(f"Processed {total_trips} trips...")

            rec = json.loads(line)
            for k in rec.keys():
                top_level_keys[k] += 1

            release = rec.get("release", "unknown")
            releases[release] += 1

            lbl = rec.get("label", "unknown")
            labels[lbl] += 1

            geo_prov = str(rec.get("geography_provenance"))
            geo_provenances[geo_prov] += 1

            # Geography
            pickup = rec.get("pickup") or {}
            plat = pickup.get("lat") or pickup.get("latitude")
            plon = pickup.get("lon") or pickup.get("longitude")
            pname = pickup.get("name")
            if pname:
                pickup_names[pname] += 1

            dropoff = rec.get("dropoff") or {}
            dname = dropoff.get("name")
            if dname:
                dropoff_names[dname] += 1

            geo_cat = classify_geo(plat, plon, geo_prov)
            geographies[geo_cat] += 1

            # Telemetry points & distance
            telemetry = rec.get("telemetry") or []
            telemetry_counts.append(len(telemetry))

            dist = 0.0
            pts = []
            for t in telemetry:
                for tk in t.keys():
                    telemetry_keys[tk] += 1
                tlat = t.get("latitude")
                tlon = t.get("longitude")
                if tlat is not None and tlon is not None:
                    pts.append((float(tlat), float(tlon)))
            for p1, p2 in zip(pts, pts[1:]):
                dist += haversine_m(p1[0], p1[1], p2[0], p2[1])
            distances.append(dist)

            # Duration
            duration = None
            times = [t.get("occurred_at") for t in telemetry if t.get("occurred_at")]
            if len(times) >= 2:
                try:
                    t_start = datetime.fromisoformat(str(times[0]).replace("Z", "+00:00"))
                    t_end = datetime.fromisoformat(str(times[-1]).replace("Z", "+00:00"))
                    duration = max(0.0, (t_end - t_start).total_seconds())
                    durations.append(duration)
                except Exception:
                    pass

            # Assignment
            assign = rec.get("assignment") or {}
            for ak in assign.keys():
                assignment_keys[ak] += 1

            # Driver
            driver_prof = rec.get("driver_profile") or {}
            for dk in driver_prof.keys():
                driver_profile_keys[dk] += 1
            drv_id = rec.get("driver_id") or driver_prof.get("id") or driver_prof.get("display_name")
            if drv_id:
                drivers[drv_id] += 1
            org_id = driver_prof.get("organization_id")
            org_ids[str(org_id)] += 1

    def stats(vals: list[float]) -> dict:
        if not vals:
            return {}
        s = sorted(vals)
        n = len(s)
        return {
            "count": n,
            "min": round(s[0], 2),
            "p5": round(s[int(n * 0.05)], 2),
            "p25": round(s[int(n * 0.25)], 2),
            "median": round(s[n // 2], 2),
            "p75": round(s[int(n * 0.75)], 2),
            "p95": round(s[int(n * 0.95)], 2),
            "max": round(s[-1], 2),
            "mean": round(sum(s) / n, 2),
        }

    return {
        "total_trips": total_trips,
        "releases": dict(releases),
        "labels": dict(labels),
        "geography": {
            "distribution": dict(geographies),
            "proportions": {k: round(v / total_trips, 4) for k, v in geographies.items()},
            "provenances": dict(geo_provenances.most_common(10)),
            "top_pickups": dict(pickup_names.most_common(10)),
            "top_dropoffs": dict(dropoff_names.most_common(10)),
        },
        "distance_m": stats(distances),
        "duration_s": stats(durations),
        "telemetry_points": stats([float(c) for c in telemetry_counts]),
        "drivers": {
            "distinct_drivers": len(drivers),
            "trips_per_driver": stats([float(c) for c in drivers.values()]),
        },
        "organizations": dict(org_ids),
        "schema": {
            "top_level_keys": {k: v for k, v in top_level_keys.items()},
            "assignment_keys": {k: v for k, v in assignment_keys.items()},
            "driver_profile_keys": {k: v for k, v in driver_profile_keys.items()},
            "telemetry_keys": {k: v for k, v in telemetry_keys.items()},
        },
    }


if __name__ == "__main__":
    path = Path("data/benchmark-10k/releases_v1/trips.jsonl")
    result = profile_dataset(path)
    out_path = Path("data/benchmark-10k/releases_v1/profile_40k_results.json")
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Profile saved to {out_path}")
    print("\n=== SUMMARY RESULTS ===")
    print(f"Total trips: {result['total_trips']}")
    print("Releases:", result["releases"])
    print("Labels:", result["labels"])
    print("Geography distribution:", result["geography"]["distribution"])
    print("Geography proportions:", result["geography"]["proportions"])
    print("Distance stats (m):", result["distance_m"])
    print("Duration stats (s):", result["duration_s"])
    print("Telemetry point stats:", result["telemetry_points"])
    print("Distinct drivers:", result["drivers"]["distinct_drivers"])
    print("Organizations in driver_profile:", result["organizations"])
