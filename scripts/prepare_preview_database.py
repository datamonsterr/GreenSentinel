"""Apply schema migrations to one authenticated Railway PR preview database."""

from __future__ import annotations

import argparse
import os

from scripts.migrate_postgres import apply_migrations, get_target_connection


def _validate_preview(pr_number: int, head_sha: str) -> str:
    expected_env = f"pr-{pr_number}"
    environment = os.environ.get("RAILWAY_ENVIRONMENT_NAME", "")
    if environment != expected_env:
        raise RuntimeError("preview database preparation requires the matching pr-* environment")
    recorded_sha = os.environ.get("P063_PREVIEW_HEAD_SHA", "")
    if not head_sha or recorded_sha != head_sha:
        raise RuntimeError("preview database preparation requires the matching preview head SHA")
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("preview DATABASE_URL is required")
    for name in ("TARGET_DATABASE_URL", "MIGRATION_DATABASE_URL"):
        override = os.environ.get(name, "")
        if override and override != database_url:
            raise RuntimeError(f"{name} conflicts with preview DATABASE_URL")
    return database_url


def prepare_preview_database(pr_number: int, head_sha: str) -> None:
    database_url = _validate_preview(pr_number, head_sha)
    conn = get_target_connection(database_url)
    try:
        apply_migrations(conn)
        with conn.cursor() as cursor:
            cursor.execute("SELECT to_regclass('app.trips');")
            if cursor.fetchone()[0] is None:
                raise RuntimeError("preview schema migration did not create app.trips")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare the isolated Railway PR preview schema")
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--head-sha", required=True)
    args = parser.parse_args()
    prepare_preview_database(args.pr, args.head_sha)


if __name__ == "__main__":
    main()
