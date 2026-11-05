"""Produce 100-row parquet samples of each source dataset for investigation.

Samples are small enough to inspect locally and to publish for the source
datasets whose license permits redistribution. Heavier raw files (Porto 533 MB
zip, PaySim 493 MB csv) are streamed and truncated, never fully loaded.

Usage::

    python scripts/benchmark/make_sample_100.py --raw-dir <data/raw> --out data/raw_samples

Each sample is written as ``<name>_sample_100.parquet`` plus a
``<name>_sample_100.provenance.json`` sidecar (source url, license, rows, sha).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[2]

# Publishable only when the source license allows redistribution.
LICENSE = {
    "porto": ("CC BY 4.0", "Luis Moreira-Matias et al., UCI Taxi Service Trajectory (train.csv)"),
    "nyc": ("Public domain (NYC Open Data / TLC)", "NYC TLC yellow_tripdata_2024-01"),
    "paysim": ("MIT", "theman10/paysim on Hugging Face"),
    "multiwoz": ("MIT", "budzianowski/multiwoz (MultiWOZ 2.2)"),
    "sgd": ("CC BY-SA 4.0", "Google DSTC8 Schema-Guided Dialogue"),
    "mipo": ("No license stated (EDA-only, do not redistribute)", "TimeIsAFriend/trajectory_MiPo"),
    "nayfeh": ("No license stated (EDA-only, do not redistribute)", "Nayfeh GNSS spoofing dataset"),
}
REDISTRIBUTABLE = {"porto", "nyc", "paysim", "multiwoz", "sgd"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _csv_head(path_or_fh, n: int = 100) -> pa.Table:
    reader = pacsv.open_csv(path_or_fh)
    rows: list[dict] = []
    for batch in reader:
        rows.extend(batch.to_pylist())
        if len(rows) >= n:
            break
    return pa.Table.from_pylist(rows[:n])


def _json_table(rows: list[dict]) -> pa.Table:
    return pa.Table.from_pylist(rows)


def _dialogues(head: list[dict]) -> list[dict]:
    out = []
    for d in head:
        turns = d.get("turns") or d.get("dialogue") or []
        out.append(
            {
                "dialogue_id": d.get("dialogue_id") or d.get("dialogue_idx"),
                "n_turns": len(turns),
                "domains": json.dumps(d.get("services") or d.get("domains") or []),
                "dialogue": json.dumps(d, ensure_ascii=False),
            }
        )
    return out


def sample_porto(raw: Path, n: int) -> pa.Table:
    with zipfile.ZipFile(raw / "porto_taxi_uci" / "train.csv.zip") as zf:
        csv_member = next(m for m in zf.namelist() if m.endswith(".csv"))
        with zf.open(csv_member) as fh:
            return _csv_head(fh, n)


def sample_nyc(raw: Path, n: int) -> pa.Table:
    path = raw / "nyc_tlc_sample" / "yellow_tripdata_2024-01.parquet"
    return pq.read_table(path).slice(0, n)


def sample_paysim(raw: Path, n: int) -> pa.Table:
    return _csv_head(raw / "paysim" / "paysim.csv", n)


def sample_nayfeh(raw: Path, n: int) -> pa.Table:
    return _csv_head(raw / "gps_spoofing_nayfeh" / "raspberry_pi_data.csv", n)


def _first_dialogues_file(base: Path) -> Path:
    return sorted(base.glob("dialogues_*.json"))[0]


def sample_multiwoz(raw: Path, n: int) -> pa.Table:
    base = raw / "multiwoz" / "multiwoz-master" / "data" / "MultiWOZ_2.2"
    for split in ("train", "dev", "test"):
        files = sorted((base / split).glob("dialogues_*.json"))
        if files:
            return _json_table(_dialogues(json.loads(files[0].read_text())[:n]))
    raise FileNotFoundError("no MultiWOZ dialogues_*.json found")


def sample_sgd(raw: Path, n: int) -> pa.Table:
    base = raw / "sgd_dialogue" / "dstc8-schema-guided-dialogue-master"
    for split in ("train", "dev", "test"):
        files = sorted((base / split).glob("dialogues_*.json"))
        if files:
            return _json_table(_dialogues(json.loads(files[0].read_text())[:n]))
    raise FileNotFoundError("no SGD dialogues_*.json found")


def sample_mipo(raw: Path, n: int) -> pa.Table:
    base = raw / "mipo_variants"
    rows: list[dict] = []
    for variant in ("AiSq5D", "AiSq10D", "UnCh10M", "StSt10M"):
        for label, fname in (("inner", "inners.txt"), ("outlier", "outliers.txt")):
            path = base / variant / fname
            if not path.exists():
                continue
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    if len(rows) >= n:
                        break
                    rows.append({"variant": variant, "label": label, "trajectory": line.strip()})
        if len(rows) >= n:
            break
    return _json_table(rows[:n])


SOURCES = {
    "porto": sample_porto,
    "nyc": sample_nyc,
    "paysim": sample_paysim,
    "nayfeh": sample_nayfeh,
    "multiwoz": sample_multiwoz,
    "sgd": sample_sgd,
    "mipo": sample_mipo,
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "raw_samples")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--only", nargs="*", choices=sorted(SOURCES), default=None)
    args = ap.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    selected = args.only or sorted(SOURCES)
    failures = 0
    for name in selected:
        try:
            table = SOURCES[name](args.raw_dir, args.n)
            parquet = args.out / f"{name}_sample_100.parquet"
            pq.write_table(table, parquet)
            license_name, attribution = LICENSE[name]
            prov = {
                "source": name,
                "license": license_name,
                "attribution": attribution,
                "rows": table.num_rows,
                "columns": table.column_names,
                "redistributable": name in REDISTRIBUTABLE,
                "sample_file": parquet.name,
                "sample_sha256": sha256_file(parquet),
            }
            (args.out / f"{name}_sample_100.provenance.json").write_text(
                json.dumps(prov, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            print(f"{name:10s} rows={table.num_rows:3d} cols={len(table.column_names):2d}  {parquet.name}")
        except Exception as exc:  # noqa: BLE001 - report and continue
            failures += 1
            print(f"{name:10s} FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 1 if failures == len(selected) else 0


if __name__ == "__main__":
    sys.exit(main())
