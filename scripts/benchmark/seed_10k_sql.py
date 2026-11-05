"""Emit INSERT SQL seeding the 10k benchmark dataset into Postgres (Issue #254).

Reads data/benchmark-10k/v1/{trips.jsonl,manifest.json}; writes seed_data.sql.
--dry-run (default): write the file only, no database needed (no psycopg import).
--execute: apply via DATABASE_URL (psycopg imported lazily, only in this mode).

Column shapes match db/migrations/0001_poc_core.sql plus
20260923181144 (driver profile), 20260926130000 (driver metrics, trip fare),
20260924061235 (trip addresses), 20261007090000 (extended simulation_labels
categories), 20261007100000 (benchmark_datasets/runs).
Core tables need PostGIS (geography columns); benchmark_* tables are vanilla.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid as _uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ORG_ID = "018f2f4e-b000-7000-8000-000000000001"
ORIGIN = "2026-09-22T06:00:00+00:00"

SCENARIO_FOR_LABEL = {
    "no_violation": "normal_trip",
    "ERR-02": "driver_stall_cancel",
    "ERR-01": "driver_stall_cancel",
    "ERR-03": "route_deviation",
    "ERR-04": "normal_trip",
    "ERR-05": "gps_spoofing",
    "insufficient_evidence": "technical_dropout",
}

BATCH = 500


class Raw(str):
    """Pre-rendered SQL fragment passed through unquoted."""


def lit(v) -> str:
    if isinstance(v, Raw):
        return str(v)
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def js(v) -> Raw:
    return Raw(
        "'" + json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).replace("'", "''") + "'::jsonb"
    )


def geo(lon: float | None, lat: float | None) -> Raw | None:
    if lon is None or lat is None:
        return None
    return Raw(f"ST_GeogFromText('SRID=4326;POINT({lon} {lat})')")


def batch_insert(table: str, cols: list[str], rows: list[tuple]) -> str:
    out = []
    for i in range(0, len(rows), BATCH):
        vals = ",".join("(" + ",".join(lit(v) for v in r) + ")" for r in rows[i : i + BATCH])
        out.append(f"INSERT INTO {table} ({', '.join(cols)}) VALUES {vals};")
    return "\n".join(out)


def build_sql(bundles: list[dict], manifest: dict) -> str:
    lines = [
        "-- Benchmark 10k seed (build_10k, builder/config from manifest). Requires PostGIS for core tables.",
        f"-- manifest sha256 {manifest.get('trips_sha256')} seed {manifest.get('seed')}",
        "BEGIN;",
        "INSERT INTO app.organizations (id, name) VALUES "
        f"('{ORG_ID}','Benchmark Synthetic Org') ON CONFLICT (id) DO NOTHING;",
    ]

    seen, drv_rows, veh_map = set(), [], {}
    for b in bundles:
        d = b["driver_profile"]
        if d["id"] not in seen:
            seen.add(d["id"])
            drv_rows.append(
                (
                    d["id"],
                    d["organization_id"],
                    d.get("principal_id"),
                    d["external_ref"],
                    d["partner_type"],
                    d["account_status"],
                    True,
                    d["created_at"],
                    d["display_name"],
                    d.get("birth_date"),
                    js(d["profile_provenance"]),
                    d["avatar_url"],
                    d["rating"],
                    d["acceptance_rate"],
                    d["cancellation_rate"],
                    d["total_trips"],
                )
            )
        veh_map[b["vehicle_id"]] = b["vehicle"]
    lines.append(
        batch_insert(
            "app.drivers",
            [
                "id",
                "organization_id",
                "principal_id",
                "external_ref",
                "partner_type",
                "account_status",
                "is_synthetic",
                "created_at",
                "display_name",
                "birth_date",
                "profile_provenance",
                "avatar_url",
                "rating",
                "acceptance_rate",
                "cancellation_rate",
                "total_trips",
            ],
            drv_rows,
        )
    )
    lines.append(
        batch_insert(
            "app.passengers",
            ["id", "organization_id", "principal_id", "external_ref", "is_synthetic", "created_at"],
            [(b["passenger_id"], ORG_ID, None, None, True, b["requested_at"]) for b in bundles],
        )
    )
    lines.append(
        batch_insert(
            "app.vehicles",
            [
                "id",
                "organization_id",
                "registration_ref",
                "vehicle_type",
                "service_class",
                "telemetry_source",
                "model",
                "created_at",
            ],
            [
                (
                    v["id"],
                    v["organization_id"],
                    v["registration_ref"],
                    v["vehicle_type"],
                    v["service_class"],
                    v["telemetry_source"],
                    v.get("model"),
                    v["created_at"],
                )
                for v in veh_map.values()
            ],
        )
    )

    trip_rows, asg_rows = [], []
    for b in bundles:
        t = b["trip"]
        trip_rows.append(
            (
                b["trip_id"],
                ORG_ID,
                b["passenger_id"],
                b["requested_at"],
                geo(b["pickup"]["lon"], b["pickup"]["lat"]),
                geo(b["dropoff"]["lon"], b["dropoff"]["lat"]),
                "standard",
                t["status"],
                t["cancelled_at"],
                t["completed_at"],
                b["requested_at"],
                t["match_type"],
                t["fare_amount_vnd"],
                t["pickup_address"],
                t["dropoff_address"],
                t["district"],
            )
        )
        a = b["assignment"]
        asg_rows.append(
            (
                b["assignment_id"],
                b["trip_id"],
                b["driver_id"],
                b["vehicle_id"],
                a["state"],
                a["offered_at"],
                a["accepted_at"],
                a["arrived_at"],
                a["started_at"],
                a["ended_at"],
                a["cancellation_actor"],
                a["cancellation_reason"],
                b["requested_at"],
            )
        )
    lines.append(
        batch_insert(
            "app.trips",
            [
                "id",
                "organization_id",
                "passenger_id",
                "requested_at",
                "pickup",
                "dropoff",
                "requested_service_class",
                "status",
                "cancelled_at",
                "completed_at",
                "created_at",
                "match_type",
                "fare_amount_vnd",
                "pickup_address",
                "dropoff_address",
                "district",
            ],
            trip_rows,
        )
    )
    lines.append(
        batch_insert(
            "app.trip_assignments",
            [
                "id",
                "trip_id",
                "driver_id",
                "vehicle_id",
                "state",
                "offered_at",
                "accepted_at",
                "arrived_at",
                "started_at",
                "ended_at",
                "cancellation_actor",
                "cancellation_reason",
                "created_at",
            ],
            asg_rows,
        )
    )

    builder = str(manifest.get("builder", "build_10k v1"))
    config_version = str(manifest.get("config_version", "0.3.1-benchmark"))
    run_ids = {sc: str(_uuid.uuid5(_uuid.NAMESPACE_URL, f"bm-v1-{sc}")) for sc in SCENARIO_FOR_LABEL.values()}
    # G1/G2 subset scenarios ride their own simulation_runs rows (CHECK extended
    # by 20261012090000); label fallback keeps old bundles working.
    for b in bundles:
        sc = b.get("scenario")
        if sc and sc not in run_ids:
            run_ids[sc] = str(_uuid.uuid5(_uuid.NAMESPACE_URL, f"bm-v1-{sc}"))
    lines.append(
        batch_insert(
            "app.simulation_runs",
            ["id", "organization_id", "scenario", "seed", "generator_version", "status", "simulated_clock_origin"],
            [(rid, ORG_ID, sc, manifest.get("seed", 0), builder, "completed", ORIGIN) for sc, rid in run_ids.items()],
        )
    )

    ds_id = str(_uuid.uuid5(_uuid.NAMESPACE_URL, "bm-dataset-v1"))
    run_id = str(_uuid.uuid5(_uuid.NAMESPACE_URL, f"bm-run-v1-{manifest.get('seed')}"))
    lines.append(
        batch_insert(
            "app.benchmark_datasets",
            [
                "id",
                "name",
                "version",
                "source",
                "license",
                "artifact_sha256",
                "row_count",
                "fields",
                "acquired_at",
                "provenance",
                "created_at",
            ],
            [
                (
                    ds_id,
                    "fraud-benchmark-10k",
                    str(manifest.get("version", "v1")),
                    f"synthetic {builder}",
                    "internal",
                    manifest.get("trips_sha256"),
                    manifest.get("trip_count"),
                    Raw("'{}'::jsonb"),
                    ORIGIN,
                    Raw("'{\"synthetic\": true}'::jsonb"),
                    ORIGIN,
                )
            ],
        )
    )
    lines.append(
        batch_insert(
            "app.benchmark_runs",
            [
                "id",
                "dataset_id",
                "generator_version",
                "seed",
                "config",
                "class_mix",
                "trip_count",
                "started_at",
                "completed_at",
                "status",
            ],
            [
                (
                    run_id,
                    ds_id,
                    builder,
                    manifest.get("seed", 0),
                    Raw('\'{"config_version": "' + config_version + "\"}'::jsonb"),
                    js(manifest.get("class_counts", {})),
                    manifest.get("trip_count"),
                    ORIGIN,
                    ORIGIN,
                    "completed",
                )
            ],
        )
    )

    label_rows, case_rows, ev_rows, tp_rows = [], [], [], []
    for b in bundles:
        sc = b.get("scenario") or SCENARIO_FOR_LABEL[b["label"]]
        guard = "blocked" if b["label"] == "insufficient_evidence" else "pass"
        label_rows.append((run_ids[sc], b["assignment_id"], b["label"], guard, b["scenario"]))
        tier = 0 if b["label"].startswith("ERR-") else (1 if b["label"] == "insufficient_evidence" else 2)
        case_rows.append(
            (
                str(_uuid.uuid5(_uuid.NAMESPACE_URL, f"bm-case-{b['assignment_id']}")),
                ORG_ID,
                b["assignment_id"],
                "ready",
                b["label"],
                tier,
                tier * 10 + 5,
                "benchmark-v1",
                "analyst",
                b["requested_at"],
                b["requested_at"],
            )
        )
        for p in b["telemetry"]:
            eid = str(_uuid.uuid5(_uuid.NAMESPACE_URL, f"{b['assignment_id']}-{p.get('sequence')}"))
            payload = {
                "position": {
                    "latitude": p.get("latitude"),
                    "longitude": p.get("longitude"),
                    "accuracy_m": p.get("accuracy_m"),
                },
                "speed_mps": p.get("speed_mps"),
                "bearing_deg": p.get("bearing_deg"),
                "app_state": p.get("app_state"),
                "network_state": p.get("network_state"),
                "gps_state": p.get("gps_state"),
                "mock_location_reported": p.get("mock_location_reported"),
            }
            h = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            ev_rows.append(
                (
                    eid,
                    ORG_ID,
                    1,
                    "telemetry.observed",
                    "simulator",
                    p.get("occurred_at"),
                    b["requested_at"],
                    b["trip_id"],
                    b["assignment_id"],
                    b["driver_id"],
                    p.get("sequence"),
                    js(payload),
                    Raw(f"'\\x{h}'::bytea"),
                )
            )
            tp_rows.append(
                (
                    eid,
                    b["assignment_id"],
                    p.get("occurred_at"),
                    geo(p.get("longitude"), p.get("latitude")),
                    p.get("speed_mps"),
                    p.get("bearing_deg"),
                    p.get("accuracy_m"),
                    p.get("app_state"),
                    p.get("network_state"),
                    p.get("gps_state"),
                    p.get("mock_location_reported"),
                    None,
                    None,
                )
            )
    lines.append(
        batch_insert(
            "app.simulation_labels",
            ["simulation_run_id", "assignment_id", "expected_category", "expected_guardrail", "expected_outcome"],
            label_rows,
        )
    )
    lines.append(
        batch_insert(
            "app.fraud_cases",
            [
                "id",
                "organization_id",
                "assignment_id",
                "status",
                "suspected_category",
                "priority_tier",
                "priority_score",
                "priority_rule_version",
                "required_role",
                "created_at",
                "updated_at",
            ],
            case_rows,
        )
    )
    lines.append(
        batch_insert(
            "app.ingest_events",
            [
                "event_id",
                "organization_id",
                "schema_version",
                "event_type",
                "source",
                "occurred_at",
                "received_at",
                "correlation_id",
                "trip_id",
                "assignment_id",
                "driver_id",
                "producer_sequence",
                "payload",
                "payload_hash",
            ],
            ev_rows,
        )
    )
    lines.append(
        batch_insert(
            "app.telemetry_points",
            [
                "event_id",
                "assignment_id",
                "occurred_at",
                "position",
                "speed_mps",
                "bearing_deg",
                "accuracy_m",
                "app_state",
                "network_state",
                "gps_state",
                "mock_location_reported",
                "anomaly_type",
                "anomaly_score",
            ],
            tp_rows,
        )
    )

    fb_rows = []
    for b in bundles:
        fb = b.get("passenger_feedback")
        if not fb:
            continue
        submitted = (b.get("assignment") or {}).get("ended_at") or b["requested_at"]
        fb_rows.append(
            (
                b["assignment_id"],
                submitted,
                fb.get("category"),
                fb.get("text"),
                fb.get("rating"),
                True,
            )
        )
    if fb_rows:
        lines.append(
            batch_insert(
                "app.passenger_feedback",
                [
                    "assignment_id",
                    "submitted_at",
                    "reason_code",
                    "statement",
                    "rating_smallint",
                    "is_synthetic",
                ],
                fb_rows,
            )
        )
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Emit benchmark 10k INSERT SQL")
    ap.add_argument("--in", dest="indir", default="data/benchmark-10k/v1")
    ap.add_argument("--out", dest="outfile", default="data/benchmark-10k/v1/seed_data.sql")
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--execute", action="store_true", default=False)
    ap.add_argument("--database-url", default=None)
    ap.add_argument("--hub-repo", default=None, help="fetch the corpus from this HF dataset repo before seeding")
    ap.add_argument("--profile", default="releases_v1", choices=("releases_v1",))
    args = ap.parse_args(argv)

    indir = Path(args.indir)
    if args.hub_repo:
        from scripts.benchmark.fetch_dataset import fetch as _fetch
        from scripts.benchmark.fetch_dataset import verify as _verify

        profile_dir = _fetch(args.hub_repo, args.profile, indir)
        digest = _verify(profile_dir)
        print(f"fetched {profile_dir} (trips.jsonl sha256 {digest})")
        indir = profile_dir

    with open(indir / "trips.jsonl", encoding="utf-8") as f:
        bundles = [json.loads(line) for line in f]
    with open(indir / "manifest.json", encoding="utf-8") as f:
        manifest = json.load(f)
    sql = build_sql(bundles, manifest)

    if args.execute:
        import os

        url = args.database_url or os.environ.get("DATABASE_URL")
        if not url:
            print("ERROR: --execute requires DATABASE_URL", file=sys.stderr)
            return 2
        try:
            import psycopg  # lazy: only needed for --execute
        except ImportError:
            print("ERROR: psycopg not installed; cannot --execute", file=sys.stderr)
            return 2
        with psycopg.connect(url) as conn:
            conn.execute(sql)
        print(f"executed seed for {len(bundles)} trips")
        return 0

    Path(args.outfile).parent.mkdir(parents=True, exist_ok=True)
    Path(args.outfile).write_text(sql, encoding="utf-8")
    print(f"dry-run: wrote {args.outfile} ({len(sql) / 1e6:.1f} MB, {len(bundles)} trips)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
