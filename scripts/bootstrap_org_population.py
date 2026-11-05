#!/usr/bin/env python3
"""S4-ACTORS #295 CLI: idempotent 100 drivers / 1000 customers bootstrap per org.

Usage:
    python scripts/bootstrap_org_population.py --org-id <uuid>
        [--template-version v1] [--seed greensentinel-s4-actors]
        [--database-url $DATABASE_URL]

Exit codes: 0 ready, 1 failed (safe to retry: rerun the same command),
2 usage error. Never prints secrets.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.services.org_bootstrap import (  # noqa: E402
    DEFAULT_SEED,
    DEFAULT_TEMPLATE_VERSION,
    BootstrapError,
    DatabaseUnavailableError,
    bootstrap_org_population,
)


def _connect(database_url: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError:
        print("psycopg is required (pip install psycopg[binary])", file=sys.stderr)
        sys.exit(2)
    try:
        return psycopg.connect(database_url, row_factory=dict_row, autocommit=False, connect_timeout=10)
    except Exception as exc:
        raise DatabaseUnavailableError(f"cannot connect: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bootstrap 100 drivers + 1000 customers for one org (idempotent).")
    parser.add_argument("--org-id", required=True, help="Organization UUID to bootstrap")
    parser.add_argument("--template-version", default=DEFAULT_TEMPLATE_VERSION)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", ""))
    args = parser.parse_args(argv)

    if not args.database_url:
        print("error: --database-url or DATABASE_URL is required", file=sys.stderr)
        return 2
    try:
        result = bootstrap_org_population(
            args.org_id,
            lambda: _connect(args.database_url),
            template_version=args.template_version,
            seed=args.seed,
        )
    except (BootstrapError, DatabaseUnavailableError) as exc:
        print(
            json.dumps(
                {"ok": False, "error": str(exc), "retry": "safe: rerun this exact command; deterministic IDs converge"}
            )
        )
        return 1
    print(json.dumps({"ok": bool(result.get("ready")), **result}))
    return 0 if result.get("ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
