#!/usr/bin/env python3
"""CLI utility to seed and reset isolated driver dispute scenarios (#158).

Usage:
    python3 scripts/seed_driver_scenarios.py [--dry-run] [--reset] [--target in-memory|database] [--db-url URL]
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.services.scenario_seeder import ScenarioSeeder

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_driver_scenarios")


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Seed driver dispute scenarios for Issue #158.")
    parser.add_argument(
        "--target",
        choices=["in-memory", "database", "db"],
        default="in-memory",
        help="Target storage for scenario data (default: in-memory).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview scenario manifest without persisting any changes.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Cleanly remove only scenario run records without touching other rows.",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="PostgreSQL connection string (overrides DATABASE_URL env).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON manifest only.",
    )

    args = parser.parse_args()
    seeder = ScenarioSeeder()

    target = args.target
    if target in ("database", "db"):
        db_url = (
            args.db_url
            or os.environ.get("TARGET_DATABASE_URL")
            or os.environ.get("DATABASE_URL")
            or os.environ.get("MIGRATION_DATABASE_URL")
        )
        if not db_url:
            logger.error("Database target requested but no DATABASE_URL or --db-url provided.")
            return 1

        import psycopg

        logger.info(f"Connecting to database target: {db_url.split('@')[-1]}")
        try:
            with psycopg.connect(db_url, autocommit=False) as conn:
                res: dict[str, Any] = seeder.seed_database(conn=conn, dry_run=args.dry_run, reset=args.reset)
        except Exception as e:
            logger.error(f"Database operation failed: {e}")
            return 2
    else:
        res = seeder.seed_in_memory(dry_run=args.dry_run, reset=args.reset)

    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        action = "RESET" if args.reset else ("PREVIEW" if args.dry_run else "SEEDED")
        logger.info(f"Scenario operation complete: [{action}] on target [{target}]")
        print(json.dumps(res, indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
