"""Apply one SQL file to the configured database (psycopg). Usage: uv run python scripts/apply_sql.py <file>."""

import os
import sys

import psycopg

URL = os.environ.get("DATABASE_URL", "postgres://postgres:postgrespassword@localhost:15432/postgres")

if __name__ == "__main__":
    with psycopg.connect(URL) as conn:
        conn.execute(open(sys.argv[1], encoding="utf-8").read())
        conn.commit()
    print("applied", sys.argv[1])
