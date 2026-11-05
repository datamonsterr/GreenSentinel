"""Import the pinned MiPo sample as research-only planar trajectories.

The coordinates are intentionally kept in ``points_xy``. The sample CRS is
unknown, so this command never inserts them into operational geography columns.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

SOURCE = "mipo-aisq10"
REVISION = "70a9b0140f94a1d3e2349999c621392c18c439fc"


def normalize_trajectory(row: dict, source_row: int) -> dict:
    points = row.get("xy", row.get("trajectory"))
    if not isinstance(points, list) or not points:
        raise ValueError(f"trajectory {source_row} has no points")
    clean = [[float(point[0]), float(point[1])] for point in points]
    label = int(row.get("label", 0))
    return {
        "source_row": source_row,
        "variant": "outlier" if label else "normal",
        "label": str(label),
        "points_xy": clean,
        "point_count": len(clean),
        "coordinate_reference": "unknown_planar",
    }


def import_sample(path: Path, database_url: str, limit: int | None = None) -> int:
    import psycopg

    raw = path.read_bytes()
    source_sha256 = hashlib.sha256(raw).hexdigest()
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if limit is not None:
        rows = rows[:limit]
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        for index, row in enumerate(rows):
            item = normalize_trajectory(row, int(row.get("source_row", index)))
            cur.execute(
                """
                insert into app.research_trajectories
                    (source, source_revision, source_sha256, source_row, variant,
                     label, points_xy, point_count)
                values (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                on conflict (source, source_revision, source_row) do update set
                    source_sha256 = excluded.source_sha256,
                    variant = excluded.variant,
                    label = excluded.label,
                    points_xy = excluded.points_xy,
                    point_count = excluded.point_count
                """,
                (
                    SOURCE,
                    REVISION,
                    source_sha256,
                    item["source_row"],
                    item["variant"],
                    item["label"],
                    json.dumps(item["points_xy"]),
                    item["point_count"],
                ),
            )
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=Path("data/mipo/sample.jsonl"))
    parser.add_argument(
        "--download", action="store_true", help="Download and stage MIPO dataset from GitHub before import"
    )
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    if args.download or not args.path.exists():
        from scripts.eda_mipo import download_sources, stage

        print("Downloading and staging MiPo AiSq10D dataset...")
        normal_src, outlier_src = download_sources()
        try:
            stage(normal_src, outlier_src)
        finally:
            if normal_src.parent.exists():
                import shutil

                shutil.rmtree(normal_src.parent, ignore_errors=True)

    database_url = os.environ.get("DATABASE_URL") or os.environ.get("MIGRATION_DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL or MIGRATION_DATABASE_URL is required")
    print(f"Imported {import_sample(args.path, database_url, args.limit)} research trajectories")


if __name__ == "__main__":
    main()
