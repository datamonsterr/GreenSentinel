"""Register a benchmark dataset row (issue #251).

Dry run (no DB needed) prints the INSERT statement + params::

    python scripts/import_benchmark.py --dry-run --name road-v1 --version 1.0.0

Live run needs ``psycopg`` and ``DATABASE_URL``::

    python scripts/import_benchmark.py --name road-v1 --version 1.0.0
"""

from __future__ import annotations

import argparse
import json
import os
import sys

try:
    import psycopg  # type: ignore[import-not-found]
except ImportError:
    psycopg = None  # type: ignore[assignment]

INSERT_DATASET = (
    "insert into app.benchmark_datasets "
    "(name, version, source, license, artifact_sha256, row_count, fields, "
    "acquired_at, provenance) "
    "values (%(name)s, %(version)s, %(source)s, %(license)s, "
    "%(artifact_sha256)s, %(row_count)s, %(fields)s::jsonb, "
    "%(acquired_at)s, %(provenance)s::jsonb) "
    "on conflict (name) do update set "
    "version = excluded.version, artifact_sha256 = excluded.artifact_sha256, "
    "row_count = excluded.row_count, fields = excluded.fields, "
    "acquired_at = excluded.acquired_at, provenance = excluded.provenance "
    "returning id;"
)


def build_params(args: argparse.Namespace) -> dict:
    return {
        "name": args.name,
        "version": args.version,
        "source": args.source,
        "license": args.license,
        "artifact_sha256": args.artifact_sha256,
        "row_count": args.row_count,
        "fields": json.dumps(json.loads(args.fields)),
        "acquired_at": args.acquired_at,
        "provenance": json.dumps(json.loads(args.provenance)),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Register a benchmark dataset row.")
    p.add_argument("--name", required=True, help="Dataset registry name.")
    p.add_argument("--version", default=None, help="Dataset version string.")
    p.add_argument("--source", default=None, help="Dataset source description.")
    p.add_argument("--license", default=None, help="Dataset license string.")
    p.add_argument("--artifact-sha256", default=None, dest="artifact_sha256")
    p.add_argument("--row-count", type=int, default=None, dest="row_count")
    p.add_argument("--fields", default="{}")
    p.add_argument("--acquired-at", default=None, dest="acquired_at")
    p.add_argument("--provenance", default="{}")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        params = build_params(args)
    except json.JSONDecodeError as exc:
        print(f"invalid JSON argument: {exc}", file=sys.stderr)
        return 2
    if args.dry_run:
        print("-- dry-run: statement not executed")
        print(INSERT_DATASET)
        print("-- params: " + json.dumps(params, indent=2, default=str))
        return 0
    if psycopg is None:
        print("psycopg not installed; cannot execute (use --dry-run).", file=sys.stderr)
        return 1
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL not set; cannot execute (use --dry-run).", file=sys.stderr)
        return 1
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(INSERT_DATASET, params)
        print(cur.fetchone()[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
