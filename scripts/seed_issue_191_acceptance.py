"""Seed the deterministic Issue #191 acceptance case into an authorized dev database."""

import argparse

import psycopg
from enrich_demo_data import seed_issue_191_traffic_acceptance


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--allow-remote-seed", action="store_true")
    args = parser.parse_args()
    if not args.allow_remote_seed:
        parser.error("remote acceptance seeding requires --allow-remote-seed")

    with psycopg.connect(args.database_url) as conn, conn.cursor() as cur:
        cur.execute("SET search_path = app, extensions, public;")
        cur.execute("SET session_replication_role = 'replica';")
        peer_count = seed_issue_191_traffic_acceptance(cur)
        cur.execute("SET session_replication_role = 'origin';")
        conn.commit()
    print(f"Issue #191 acceptance seed ready with {peer_count} peer trips.")


if __name__ == "__main__":
    main()
