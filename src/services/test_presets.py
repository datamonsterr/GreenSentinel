"""Preset trip library for the tester console.

Presets expose published benchmark example trips so an operator can launch a
representative simulation without hand-authoring coordinates. The published
corpus lives on the Hugging Face Hub; the per-preset sample trips are read from
the committed 100-row sample files when present, so the endpoint works offline.

Truthfulness rules:
- Metadata reports the *published* release identity (revision and class counts).
- ``sample_trips`` only ever contains rows that were actually read and parsed.
- A preset whose detection rule is not yet verified is listed as unavailable
  with an explicit reason instead of offering unverified evidence.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from src.models.test_simulation import (
    GroupedLabelCounts,
    PresetDistributions,
    TestPreset,
    TestPresetDetailResponse,
    TestPresetListResponse,
    TestPresetTrip,
)

PINNED_REVISION = "914a36560727f5892a24fba3a4173cb245c963da"
PINNED_REVISION_VIETNAM = "a914d500b1c536f1dbfb59f8ea4c961bd38b5c7e"
VIETNAM_TRIPS_SHA256 = "c4c80903a998420b3a5d68ced5ffb5bb06709fc9ef12817651ab8b89baa628a2"
DEFAULT_REPO = os.environ.get("GREENSENTINEL_BENCHMARK_HF_REPO", "datamonsterr/green-sentinel-synthesized-trips")
DEFAULT_PROFILE = "releases_v1"

# Published release identity (object storage manifest, not a local checksum).
PUBLISHED_TRIPS = 40000
PUBLISHED_NO_VIOLATION = 28000
PUBLISHED_CLASS_COUNTS: dict[str, int] = {
    "no_violation": 28000,
    "ERR-01": 2000,
    "ERR-02": 3200,
    "ERR-03": 2000,
    "ERR-04": 1200,
    "ERR-05": 1200,
    "insufficient_evidence": 2400,
}

_DATA_ROOT = Path(__file__).resolve().parents[2] / "data" / "benchmark-10k"
_SAMPLE_FILES: tuple[tuple[str, Path], ...] = (
    ("v1", _DATA_ROOT / "v1" / "sample_100.jsonl"),
    ("v2", _DATA_ROOT / "v2" / "sample_100.jsonl"),
    ("v3", _DATA_ROOT / "v3" / "sample_100.jsonl"),
    ("evidence-v4", _DATA_ROOT / "profiles" / "evidence-v4" / "sample_100.jsonl"),
    ("synthesized_vietnam_trip", _DATA_ROOT / "profiles" / "synthesized_vietnam_trip" / "sample_100.jsonl"),
)


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    radius = 6371000.0
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(h)))


def _load_sample_trips() -> list[dict[str, Any]]:
    trips: list[dict[str, Any]] = []
    for release, path in _SAMPLE_FILES:
        if not path.exists():
            continue
        try:
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    record.setdefault("_release", release)
                    trips.append(record)
        except OSError:
            continue
    return trips


def _trip_summary(record: dict[str, Any]) -> TestPresetTrip:
    telemetry = record.get("telemetry") or []
    points = [(float(t.get("latitude", 0.0)), float(t.get("longitude", 0.0))) for t in telemetry]
    distance_m = 0.0
    for prev, curr in zip(points, points[1:]):
        distance_m += _haversine_m(prev, curr)

    duration_s: float | None = None
    times = [t.get("occurred_at") for t in telemetry if t.get("occurred_at")]
    if len(times) >= 2:
        from datetime import datetime

        try:
            start = datetime.fromisoformat(str(times[0]).replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(times[-1]).replace("Z", "+00:00"))
            duration_s = max(0.0, (end - start).total_seconds())
        except ValueError:
            duration_s = None

    assignment = record.get("assignment") or {}
    driver_profile = record.get("driver_profile") or {}
    pickup = record.get("pickup") or {}
    dropoff = record.get("dropoff") or {}
    vehicle = record.get("vehicle") or {}

    label = str(record.get("label") or "unknown")
    severity = record.get("severity")
    if severity is None:
        if label == "no_violation":
            severity = "no_violation"
        elif label == "ERR-05":
            severity = "P0"
        elif label in ("ERR-02", "ERR-03"):
            severity = "P1"
        elif label in ("ERR-01", "ERR-04"):
            severity = "P2"

    city = record.get("city") or (record.get("geography_provenance") or {}).get("city")
    license_plate = vehicle.get("license_plate") or vehicle.get("plate")
    driver_name = driver_profile.get("display_name")

    return TestPresetTrip(
        trip_ref=str(record.get("trip_ref") or record.get("trip_id") or ""),
        label=label,
        source=record.get("_release"),
        pickup_name=pickup.get("name"),
        dropoff_name=dropoff.get("name"),
        driver_display_name=driver_name,
        driver_name=driver_name,
        license_plate=license_plate,
        city=city,
        severity=severity,
        scenario=record.get("scenario"),
        distance_m=round(distance_m, 1) if points else None,
        duration_s=duration_s,
        telemetry_points=len(telemetry),
        cancellation_actor=assignment.get("cancellation_actor"),
        cancellation_reason=assignment.get("cancellation_reason"),
    )


def load_preset_records(preset_id: str) -> list[dict[str, Any]]:
    """Load all available records for a specific preset ID."""
    if preset_id == "synthesized-vietnam":
        vn_bulk_file = _DATA_ROOT / "profiles" / "synthesized_vietnam_trip" / "trips.jsonl"
        if vn_bulk_file.exists():
            records: list[dict[str, Any]] = []
            try:
                with vn_bulk_file.open(encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            try:
                                rec = json.loads(line)
                                rec.setdefault("_release", "synthesized_vietnam_trip")
                                records.append(rec)
                            except json.JSONDecodeError:
                                continue
                if records:
                    return records
            except OSError:
                pass

        vn_sample_file = _DATA_ROOT / "profiles" / "synthesized_vietnam_trip" / "sample_100.jsonl"
        records = []
        if vn_sample_file.exists():
            try:
                with vn_sample_file.open(encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            try:
                                rec = json.loads(line)
                                rec.setdefault("_release", "synthesized_vietnam_trip")
                                records.append(rec)
                            except json.JSONDecodeError:
                                continue
            except OSError:
                pass
        return records

    all_samples = _load_sample_trips()
    if preset_id == "all-normal":
        return [r for r in all_samples if r.get("label") == "no_violation"]
    elif preset_id == "wrong-direction":
        return [r for r in all_samples if r.get("label") == "ERR-03"]
    elif preset_id == "default":
        return all_samples
    else:
        return [r for r in all_samples if r.get("preset_id") == preset_id or r.get("_release") == preset_id]


def compute_preset_distributions(preset_id_or_records: str | list[dict[str, Any]]) -> PresetDistributions:
    if isinstance(preset_id_or_records, str):
        records = load_preset_records(preset_id_or_records)
    else:
        records = preset_id_or_records

    total = len(records)
    fraud = 0
    no_violation = 0
    insufficient_evidence = 0
    per_code: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_scenario: dict[str, int] = {}
    by_city: dict[str, int] = {}
    by_cancellation_actor: dict[str, int] = {}

    for r in records:
        lbl = str(r.get("label") or "unknown")
        per_code[lbl] = per_code.get(lbl, 0) + 1
        if lbl.startswith("ERR-"):
            fraud += 1
        elif lbl == "no_violation":
            no_violation += 1
        elif lbl == "insufficient_evidence":
            insufficient_evidence += 1
        else:
            fraud += 1

        sev = r.get("severity")
        if sev is None:
            if lbl == "no_violation":
                sev = "no_violation"
            elif lbl == "ERR-05":
                sev = "P0"
            elif lbl in ("ERR-02", "ERR-03"):
                sev = "P1"
            elif lbl in ("ERR-01", "ERR-04"):
                sev = "P2"
            else:
                sev = "none"
        sev_str = str(sev)
        by_severity[sev_str] = by_severity.get(sev_str, 0) + 1

        scen = str(r.get("scenario") or "unknown")
        by_scenario[scen] = by_scenario.get(scen, 0) + 1

        city = r.get("city") or (r.get("geography_provenance") or {}).get("city") or "Unknown"
        city_str = str(city)
        by_city[city_str] = by_city.get(city_str, 0) + 1

        actor = (r.get("assignment") or {}).get("cancellation_actor") or "none"
        actor_str = str(actor)
        by_cancellation_actor[actor_str] = by_cancellation_actor.get(actor_str, 0) + 1

    grouped = {
        "fraud": fraud,
        "no_violation": no_violation,
        "insufficient_evidence": insufficient_evidence,
    }
    by_label = GroupedLabelCounts(
        fraud=fraud,
        no_violation=no_violation,
        insufficient_evidence=insufficient_evidence,
        grouped=grouped,
        per_code=per_code,
    )
    return PresetDistributions(
        total_records=total,
        by_label=by_label,
        per_code=per_code,
        by_severity=by_severity,
        by_scenario=by_scenario,
        by_city=by_city,
        by_cancellation_actor=by_cancellation_actor,
    )


def get_preset_detail(preset_id: str, sample_limit: int = 5) -> TestPresetDetailResponse:
    from fastapi import HTTPException

    preset_list = list_presets(sample_limit=sample_limit)
    preset = next((p for p in preset_list.presets if p.id == preset_id), None)
    if not preset:
        raise HTTPException(status_code=404, detail=f"Preset not found: {preset_id}")

    records = load_preset_records(preset_id)
    distributions = compute_preset_distributions(records)

    if preset_id == "synthesized-vietnam":
        source_release = "synthesized_vietnam_trip"
        revision = PINNED_REVISION_VIETNAM
        trips_sha256 = VIETNAM_TRIPS_SHA256
        license_str = "ODbL (OpenStreetMap contributors / OSRM)"
        pub_counts = {
            "published_trips": 1000,
            "published_no_violation": 700,
            "published_class_counts": {
                "no_violation": 700,
                "ERR-01": 75,
                "ERR-02": 70,
                "ERR-03": 65,
                "ERR-04": 60,
                "ERR-05": 30,
            },
            "class_counts": {
                "no_violation": 700,
                "ERR-01": 75,
                "ERR-02": 70,
                "ERR-03": 65,
                "ERR-04": 60,
                "ERR-05": 30,
            },
        }
    else:
        source_release = "releases_v1"
        revision = PINNED_REVISION
        trips_sha256 = None
        license_str = "CC BY 4.0 / Synthetic"
        pub_counts = {
            "published_trips": PUBLISHED_TRIPS,
            "published_no_violation": PUBLISHED_NO_VIOLATION,
            "published_class_counts": PUBLISHED_CLASS_COUNTS,
            "class_counts": PUBLISHED_CLASS_COUNTS,
        }

    sample_records = records[:sample_limit]
    sample_trips = [_trip_summary(r) for r in sample_records]

    info = {
        "id": preset.id,
        "title": preset.title,
        "description": preset.description,
        "source_release": source_release,
        "revision": revision,
        "trips_sha256": trips_sha256,
        "license": license_str,
        "trip_count": len(records),
        "available": preset.available,
        "unavailable_reason": preset.unavailable_reason,
        "published_release_counts": pub_counts,
    }

    return TestPresetDetailResponse(
        id=preset.id,
        title=preset.title,
        description=preset.description,
        kind=preset.kind,
        available=preset.available,
        unavailable_reason=preset.unavailable_reason,
        source_label=preset.source_label,
        selection_size=preset.selection_size,
        available_trips=len(records),
        metadata={**preset.metadata, **pub_counts},
        metrics=preset.metrics,
        sample_trips=sample_trips,
        source_release=source_release,
        revision=revision,
        trips_sha256=trips_sha256,
        license=license_str,
        trip_count=len(records),
        published_release_counts=pub_counts,
        distributions=distributions,
        info=info,
    )


def _metrics(trips: list[TestPresetTrip]) -> dict[str, Any]:
    distances = [t.distance_m for t in trips if t.distance_m is not None]
    durations = [t.duration_s for t in trips if t.duration_s is not None]
    labels: dict[str, int] = {}
    for t in trips:
        labels[t.label] = labels.get(t.label, 0) + 1
    return {
        "sample_size": len(trips),
        "telemetry_points_total": sum(t.telemetry_points for t in trips),
        "median_distance_m": round(sorted(distances)[len(distances) // 2], 1) if distances else None,
        "median_duration_s": round(sorted(durations)[len(durations) // 2], 1) if durations else None,
        "label_counts": labels,
    }


def _select(records: list[dict[str, Any]], label: str | None, limit: int) -> list[dict[str, Any]]:
    if label is None:
        return records[:limit]
    return [r for r in records if r.get("label") == label][:limit]


def list_presets(sample_limit: int = 5) -> TestPresetListResponse:
    records = _load_sample_trips()

    default_records = _select(records, None, sample_limit)
    normal_records = _select(records, "no_violation", sample_limit)
    wrong_direction_records = _select(records, "ERR-03", sample_limit)
    vietnam_records = [r for r in records if r.get("_release") == "synthesized_vietnam_trip"][:sample_limit]
    if not vietnam_records:
        vn_sample_file = _DATA_ROOT / "profiles" / "synthesized_vietnam_trip" / "sample_100.jsonl"
        if vn_sample_file.exists():
            with vn_sample_file.open(encoding="utf-8") as fh:
                for line in fh:
                    if len(vietnam_records) >= sample_limit:
                        break
                    line = line.strip()
                    if line:
                        try:
                            rec = json.loads(line)
                            rec["_release"] = "synthesized_vietnam_trip"
                            vietnam_records.append(rec)
                        except json.JSONDecodeError:
                            continue

    default_trips = [_trip_summary(r) for r in default_records]
    normal_trips = [_trip_summary(r) for r in normal_records]
    wrong_direction_trips = [_trip_summary(r) for r in wrong_direction_records]
    vietnam_trips = [_trip_summary(r) for r in vietnam_records]

    presets = [
        TestPreset(
            id="default",
            title="Default",
            description="Balanced mix of published example trips across every recorded class",
            kind="default",
            source_label=None,
            available=True,
            selection_size=PUBLISHED_TRIPS,
            available_trips=PUBLISHED_TRIPS,
            metadata={
                "provider": "huggingface",
                "repository": DEFAULT_REPO,
                "profile": DEFAULT_PROFILE,
                "revision": PINNED_REVISION,
                "published_trips": PUBLISHED_TRIPS,
            },
            metrics=_metrics(default_trips),
            sample_trips=default_trips,
        ),
        TestPreset(
            id="all-normal",
            title="All normal trips",
            description="Trips recorded with no violation; the nominal pipeline baseline",
            kind="normal",
            source_label="no_violation",
            available=True,
            selection_size=PUBLISHED_NO_VIOLATION,
            available_trips=PUBLISHED_NO_VIOLATION,
            metadata={
                "provider": "huggingface",
                "repository": DEFAULT_REPO,
                "profile": DEFAULT_PROFILE,
                "revision": PINNED_REVISION,
                "label": "no_violation",
            },
            metrics=_metrics(normal_trips),
            sample_trips=normal_trips,
        ),
        TestPreset(
            id="wrong-direction",
            title="Driver going wrong direction",
            description="Route-deviation trips used to study wrong-direction detection",
            kind="wrong_direction",
            source_label="ERR-03",
            available=False,
            unavailable_reason=(
                "Unavailable until movement away from the pickup is verified; "
                "route deviation alone is not evidence of wrong direction."
            ),
            selection_size=PUBLISHED_CLASS_COUNTS.get("ERR-03"),
            available_trips=PUBLISHED_CLASS_COUNTS.get("ERR-03"),
            metadata={
                "provider": "huggingface",
                "repository": DEFAULT_REPO,
                "profile": DEFAULT_PROFILE,
                "revision": PINNED_REVISION,
                "label": "ERR-03",
            },
            metrics=_metrics(wrong_direction_trips),
            sample_trips=wrong_direction_trips,
        ),
        TestPreset(
            id="synthesized-vietnam",
            title="Vietnam trips (synthesized)",
            description="Grounded Vietnamese road coordinates and traffic scenarios across Hanoi and Ho Chi Minh City",
            kind="vietnam",
            source_label=None,
            available=True,
            selection_size=1000,
            available_trips=1000,
            metadata={
                "provider": "huggingface",
                "repository": DEFAULT_REPO,
                "profile": "synthesized_vietnam_trip",
                "status": "published",
                "revision": PINNED_REVISION_VIETNAM,
                "trips_sha256": VIETNAM_TRIPS_SHA256,
                "published_trips": 1000,
            },
            metrics=_metrics(vietnam_trips),
            sample_trips=vietnam_trips,
        ),
    ]

    return TestPresetListResponse(
        presets=presets,
        source={
            "provider": "huggingface",
            "repository": DEFAULT_REPO,
            "url": f"https://huggingface.co/datasets/{DEFAULT_REPO}",
            "profile": DEFAULT_PROFILE,
            "revision": PINNED_REVISION,
            "published_trips": PUBLISHED_TRIPS,
            "published_no_violation": PUBLISHED_NO_VIOLATION,
            "published_class_counts": PUBLISHED_CLASS_COUNTS,
            "samples_loaded": len(records),
            "corpus_verified_locally": False,
        },
    )


def _find_trip_record(trip_ref: str, preset_id: str | None = None) -> dict[str, Any] | None:
    """Find a trip record from bulk profile, committed sample, or 40k fixtures."""
    # 1. Check synthesized_vietnam_trip bulk file, then sample file
    if preset_id in ("synthesized-vietnam", None):
        vn_bulk_file = _DATA_ROOT / "profiles" / "synthesized_vietnam_trip" / "trips.jsonl"
        if vn_bulk_file.exists():
            try:
                with vn_bulk_file.open(encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            try:
                                rec = json.loads(line)
                                if rec.get("trip_ref") == trip_ref or rec.get("trip_id") == trip_ref:
                                    rec.setdefault("_release", "synthesized_vietnam_trip")
                                    return rec
                            except json.JSONDecodeError:
                                continue
            except OSError:
                pass

        vn_sample_file = _DATA_ROOT / "profiles" / "synthesized_vietnam_trip" / "sample_100.jsonl"
        if vn_sample_file.exists():
            try:
                with vn_sample_file.open(encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            try:
                                rec = json.loads(line)
                                if rec.get("trip_ref") == trip_ref or rec.get("trip_id") == trip_ref:
                                    rec.setdefault("_release", "synthesized_vietnam_trip")
                                    return rec
                            except json.JSONDecodeError:
                                continue
            except OSError:
                pass

    # 2. Check releases_v1 bulk file if present
    releases_bulk = _DATA_ROOT / "releases_v1" / "trips.jsonl"
    if releases_bulk.exists():
        try:
            with releases_bulk.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            rec = json.loads(line)
                            if rec.get("trip_ref") == trip_ref or rec.get("trip_id") == trip_ref:
                                return rec
                        except json.JSONDecodeError:
                            continue
        except OSError:
            pass

    # 3. Check loaded sample fixtures
    for r in _load_sample_trips():
        if r.get("trip_ref") == trip_ref or r.get("trip_id") == trip_ref:
            return r
    return None


def materialize_preset_simulation_input(
    trip_record_or_ref: dict[str, Any] | str,
    organization_id: UUID | str,
    preset_id: str | None = None,
) -> dict[str, Any]:
    """Materialize a preset trip record into a simulation input payload.

    Truthfulness & Tenant Isolation guarantees:
    - Organization ownership MUST be assigned from active authorized context;
      source fixture org_id is never used across tenants.
    - Persisted trip/assignment/driver/passenger identities are mapped through
      the organization namespace to eliminate cross-tenant collisions.
    - Validates finite geometry (no NaN/Inf coordinates) and non-zero route distance.
    - Synthetic actors have no fabricated principal credentials.
    """
    if isinstance(trip_record_or_ref, str):
        match = _find_trip_record(trip_record_or_ref, preset_id=preset_id)
        if not match:
            raise ValueError(f"Preset trip not found for reference: {trip_record_or_ref}")
        record = match
    else:
        record = trip_record_or_ref

    from uuid import NAMESPACE_URL, uuid5

    org_uuid = str(UUID(str(organization_id)))

    route = record.get("route") or {}
    geom = route.get("geometry") or {}
    coords = geom.get("coordinates") or []
    if not coords or len(coords) < 2:
        telemetry = record.get("telemetry") or []
        coords = [
            [float(pt["longitude"]), float(pt["latitude"])]
            for pt in telemetry
            if pt.get("longitude") is not None and pt.get("latitude") is not None
        ]
    if len(coords) < 2:
        raise ValueError("Trip has insufficient coordinates for simulation")

    for c in coords:
        lon, lat = float(c[0]), float(c[1])
        if math.isnan(lon) or math.isnan(lat) or math.isinf(lon) or math.isinf(lat):
            raise ValueError(f"Non-finite coordinate encountered: [{lon}, {lat}]")

    distance_m = route.get("distance_m")
    if distance_m is None or distance_m <= 0:
        telemetry = record.get("telemetry") or []
        pts = [(float(t.get("latitude", 0.0)), float(t.get("longitude", 0.0))) for t in telemetry]
        d = 0.0
        for p1, p2 in zip(pts, pts[1:]):
            d += _haversine_m(p1, p2)
        distance_m = round(d, 1)

    if distance_m <= 0:
        raise ValueError("Trip has non-positive route distance")

    src_trip_id = str(record.get("trip_id") or record.get("trip_ref") or "trip-sim-001")
    src_driver_id = str(record.get("driver_id") or "drv-sim-001")
    src_passenger_id = str(record.get("passenger_id") or "pass-sim-001")
    src_vehicle_id = str((record.get("vehicle") or {}).get("id") or record.get("vehicle_id") or "veh-sim-001")

    # Map persisted identities through organization namespace to prevent cross-tenant collision
    mapped_trip_id = str(uuid5(NAMESPACE_URL, f"greensentinel:test-console:trip:{org_uuid}:{src_trip_id}"))
    mapped_driver_id = str(uuid5(NAMESPACE_URL, f"greensentinel:test-console:actor:{org_uuid}:driver:{src_driver_id}"))
    mapped_passenger_id = str(uuid5(NAMESPACE_URL, f"greensentinel:test-console:actor:{org_uuid}:passenger:{src_passenger_id}"))
    mapped_vehicle_id = str(uuid5(NAMESPACE_URL, f"greensentinel:test-console:actor:{org_uuid}:vehicle:{src_vehicle_id}"))

    driver_profile = dict(record.get("driver_profile") or {})
    driver_profile["organization_id"] = org_uuid
    driver_profile["source_driver_id"] = src_driver_id
    driver_profile["id"] = mapped_driver_id

    payload = {
        "trip_id": mapped_trip_id,
        "trip_ref": record.get("trip_ref") or src_trip_id,
        "source_trip_id": src_trip_id,
        "organization_id": org_uuid,
        "label": record.get("label", "no_violation"),
        "driver_id": mapped_driver_id,
        "source_driver_id": src_driver_id,
        "driver_profile": driver_profile,
        "passenger_id": mapped_passenger_id,
        "source_passenger_id": src_passenger_id,
        "vehicle_id": mapped_vehicle_id,
        "source_vehicle_id": src_vehicle_id,
        "pickup": record.get("pickup"),
        "dropoff": record.get("dropoff"),
        "route_geometry": {"type": "LineString", "coordinates": coords},
        "distance_m": distance_m,
        "telemetry": record.get("telemetry", []),
        "cancellation_actor": (record.get("assignment") or {}).get("cancellation_actor"),
        "cancellation_reason": (record.get("assignment") or {}).get("cancellation_reason"),
        "conversation": record.get("conversation", []),
    }
    return payload


def create_preset_plan(
    preset_id: str,
    trip_ref: str | None,
    organization_id: UUID | str,
    created_by: str | None = None,
    title: str | None = None,
    runner: Any | None = None,
    driver_id: str | None = None,
) -> Any:
    """Resolve preset trip bytes and materialize a canonical test plan and definition revision.

    Strict security & isolation rules:
    - Organization ownership is derived strictly from the authenticated principal context.
    - Rejects unavailable presets with explicit reason.
    - Driver must be an active Clerk-linked driver of the organization (422).
    - Resolves from full corpus when present or gracefully falls back to committed sample.
    """
    from fastapi import HTTPException

    from src.models.test_simulation import (
        DriverSimConfig,
        GeoJsonLineString,
        LatLon,
        PassengerSimConfig,
        SimDialogueMessage,
        TestDefinitionRevisionCreate,
        TestPlanCreate,
        TestPresetPlanResponse,
        TestStopSnapshot,
    )
    from src.services.driver_directory import get_driver_directory
    from src.services.test_simulation_runner import get_simulation_runner

    if runner is None:
        runner = get_simulation_runner()

    org_uuid = str(UUID(str(organization_id)))

    # Driver validation: must be active Clerk-linked driver in the caller org
    dir_svc = get_driver_directory()
    if driver_id:
        active_driver = dir_svc.get_active_driver(org_uuid, driver_id)
        if not active_driver:
            raise HTTPException(
                status_code=422,
                detail=f"Driver '{driver_id}' is not an active Clerk-linked driver in this organization",
            )
    else:
        active_drivers = dir_svc.list_active_drivers(org_uuid)
        if not active_drivers:
            raise HTTPException(
                status_code=422,
                detail="No active Clerk-linked driver found in this organization",
            )
        active_driver = active_drivers[0]

    preset_resp = list_presets()
    presets_map = {p.id: p for p in preset_resp.presets}
    preset = presets_map.get(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail=f"Preset not found: {preset_id}")
    if not preset.available:
        raise HTTPException(
            status_code=400,
            detail=preset.unavailable_reason or f"Preset {preset_id} is currently unavailable",
        )

    resolved_ref = trip_ref
    if not resolved_ref:
        if preset.sample_trips:
            resolved_ref = preset.sample_trips[0].trip_ref
        else:
            raise HTTPException(status_code=404, detail=f"No trips available in preset {preset_id}")

    try:
        materialized = materialize_preset_simulation_input(resolved_ref, organization_id=org_uuid, preset_id=preset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    coords = materialized["route_geometry"]["coordinates"]
    initial_snap = TestStopSnapshot(
        location=LatLon(latitude=coords[0][1], longitude=coords[0][0]),
        address=(materialized.get("pickup") or {}).get("address") or "Vị trí xuất phát",
    )
    pickup_snap = TestStopSnapshot(
        location=LatLon(latitude=coords[0][1], longitude=coords[0][0]),
        address=(materialized.get("pickup") or {}).get("address") or "Điểm đón khách",
    )
    dest_snap = TestStopSnapshot(
        location=LatLon(latitude=coords[-1][1], longitude=coords[-1][0]),
        address=(materialized.get("dropoff") or {}).get("address") or "Điểm đến",
    )

    messages: list[SimDialogueMessage] = []
    for idx, msg in enumerate(materialized.get("conversation") or []):
        sender: Literal["DRIVER", "PASSENGER"] = (
            "DRIVER" if str(msg.get("role", "")).upper() == "DRIVER" else "PASSENGER"
        )
        content = msg.get("text") or msg.get("content") or ""
        if content:
            messages.append(
                SimDialogueMessage(
                    sender_role=sender,
                    content=content,
                    offset_seconds=int(msg.get("offset_seconds", idx * 5)),
                )
            )

    plan_name = title or f"{preset.title} · {materialized.get('trip_ref') or resolved_ref}"
    plan_create = TestPlanCreate(name=plan_name, description=f"Materialized from preset {preset_id}")
    plan = runner.repository.create_plan(plan_create, organization_id=org_uuid, created_by=created_by)

    speed_mps = 12.0
    distance_m = float(materialized.get("distance_m", 0.0))
    def_create = TestDefinitionRevisionCreate(
        plan_id=plan.id,
        route_geometry=GeoJsonLineString(**materialized["route_geometry"]),
        driver_config=DriverSimConfig(
            driver_id=str(active_driver.driver_id),
            vehicle_plate=active_driver.license_plate or "29A-888.88",
            speed_mps=speed_mps,
            update_cadence_s=1,
        ),
        passenger_config=PassengerSimConfig(
            passenger_id=materialized["passenger_id"],
            name="Khách mô phỏng",
        ),
        fault_configs=[],
        messages=messages,
        initial_snapshot=initial_snap,
        pickup_snapshot=pickup_snap,
        destination_snapshot=dest_snap,
    )
    def_rev = runner.repository.create_definition_revision(def_create, organization_id=org_uuid)

    telemetry = materialized.get("telemetry") or []
    return TestPresetPlanResponse(
        plan=plan,
        definition=def_rev,
        preset_id=preset_id,
        trip_ref=materialized.get("trip_ref") or resolved_ref,
        label=materialized.get("label") or "no_violation",
        distance_m=distance_m,
        telemetry_points=len(telemetry),
        initial_snapshot=initial_snap,
        pickup_snapshot=pickup_snap,
        destination_snapshot=dest_snap,
        telemetry=telemetry,
    )
