"""Build the merged ``releases_v1`` corpus (combined 30k + evidence-v4 10k).

The two sources share seed 20261011 and reference prefixes, so a naive
concatenation duplicates ``trip_ref`` and identity UUIDs. This tool re-indexes
``trip_ref`` to ``rv1_<release>_<n>`` and re-derives every identity UUID with
``uuid5`` so the merged file has globally unique keys. Each row gains a
``release`` field. Output: ``trips.jsonl``, ``labels.csv``, ``manifest.json``.

Usage::

    python scripts/benchmark/merge_releases.py \
        --combined <build>/data/benchmark-10k/combined_trips.jsonl \
        --v4 <worktree>/data/benchmark-10k/profiles/evidence-v4/trips.jsonl \
        --out <dir>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from pathlib import Path

RELEASE_NS = uuid.uuid5(uuid.NAMESPACE_URL, "p063-benchmark-releases-v1")
PREFIX_RELEASE = {"bm_v1_": "v1", "bm_v2_": "feedback-v2", "bm_v3_": "g1g2-v3"}
ID_FIELDS = ("trip_id", "assignment_id", "driver_id", "passenger_id", "vehicle_id")


def _release_combined(trip_ref: str) -> str:
    for prefix, name in PREFIX_RELEASE.items():
        if trip_ref.startswith(prefix):
            return name
    raise ValueError(f"unknown combined trip_ref prefix: {trip_ref}")


def _new_id(release: str, old: str) -> str:
    return str(uuid.uuid5(RELEASE_NS, f"{release}:{old}"))


def _sources(combined: Path | None, v4: Path | None):
    if combined:
        yield combined, _release_combined
    if v4:
        yield v4, lambda _tr: "evidence-v4"


def _build_map(path: Path, release_of) -> tuple[dict, dict, dict]:
    ref_map: dict[tuple[str, str], str] = {}
    id_map: dict[tuple[str, str], str] = {}
    counters: dict[str, int] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            rel = release_of(row["trip_ref"])
            counters[rel] = counters.get(rel, 0) + 1
            ref_map[(rel, row["trip_ref"])] = f"rv1_{rel}_{counters[rel]:05d}"
            for field in ID_FIELDS:
                old = row.get(field)
                if old is not None:
                    id_map[(rel, old)] = _new_id(rel, old)
    return ref_map, id_map, counters


def _rewrite(row: dict, rel: str, ref_map: dict, id_map: dict) -> dict:
    row["trip_ref"] = ref_map[(rel, row["trip_ref"])]
    row["release"] = rel
    for field in ID_FIELDS:
        old = row.get(field)
        if old is not None:
            row[field] = id_map[(rel, old)]
    if isinstance(row.get("driver_profile"), dict) and row["driver_profile"].get("id"):
        row["driver_profile"]["id"] = id_map[(rel, row["driver_profile"]["id"])]
    if isinstance(row.get("driver_analytics"), dict) and row["driver_analytics"].get("driver_id"):
        row["driver_analytics"]["driver_id"] = id_map[(rel, row["driver_analytics"]["driver_id"])]
    if isinstance(row.get("vehicle"), dict) and row["vehicle"].get("id"):
        row["vehicle"]["id"] = id_map[(rel, row["vehicle"]["id"])]
    for event in row.get("driver_ledger") or []:
        if event.get("trip_ref"):
            event["trip_ref"] = ref_map.get((rel, event["trip_ref"]), event["trip_ref"])
        if event.get("driver_id"):
            event["driver_id"] = id_map.get((rel, event["driver_id"]), event["driver_id"])
    return row


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--combined", type=Path, default=None)
    ap.add_argument("--v4", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    if not args.combined and not args.v4:
        raise SystemExit("provide --combined and/or --v4")

    sources = list(_sources(args.combined, args.v4))
    ref_map: dict = {}
    id_map: dict = {}
    counters: dict = {}
    for path, release_of in sources:
        rm, im, c = _build_map(path, release_of)
        ref_map.update(rm)
        id_map.update(im)
        for k, v in c.items():
            counters[k] = counters.get(k, 0) + v

    args.out.mkdir(parents=True, exist_ok=True)
    trips = args.out / "trips.jsonl"
    labels = args.out / "labels.csv"
    class_counts: dict = {}
    release_counts: dict = {}
    digest = hashlib.sha256()
    with trips.open("w", encoding="utf-8") as out, labels.open("w", encoding="utf-8") as lab:
        lab.write("trip_ref,label,release\n")
        for path, release_of in sources:
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    rel = release_of(row["trip_ref"])
                    row = _rewrite(row, rel, ref_map, id_map)
                    payload = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                    out.write(payload + "\n")
                    digest.update((payload + "\n").encode())
                    lab.write(f"{row['trip_ref']},{row['label']},{rel}\n")
                    class_counts[row["label"]] = class_counts.get(row["label"], 0) + 1
                    release_counts[rel] = release_counts.get(rel, 0) + 1

    manifest = {
        "release": "releases_v1",
        "total_trips": sum(release_counts.values()),
        "release_counts": dict(sorted(release_counts.items())),
        "class_counts": dict(sorted(class_counts.items())),
        "trips_sha256": digest.hexdigest(),
        "id_namespace": str(RELEASE_NS),
        "note": "merged combined (v1+feedback-v2+g1g2-v3) + evidence-v4; trip_ref and identity UUIDs re-indexed for global uniqueness",
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"trips_sha256": manifest["trips_sha256"], "total": manifest["total_trips"], "releases": release_counts},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
