"""Seed realistic driver dispute mock data into Supabase (app schema)."""

import os
from datetime import UTC, datetime, timedelta

import psycopg

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres.ptikthkarnimijeorwsa:GreenSentinel_GsmFraud_2026_SecureDb!@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres",
)


def seed_supabase_driver_data():
    print(f"Connecting to Supabase at {DATABASE_URL.split('@')[-1]}...")
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")

            # 1. Update Flagship Case 26 (Kim Mã Gridlock -> Autonomous Exoneration demo)
            case_26 = "018f2f4e-a000-7000-8000-000000000026"
            deadline_active = datetime.now(UTC) + timedelta(days=2)
            cur.execute(
                """
                UPDATE app.fraud_cases
                SET suspected_category = 'ERR-02',
                    status = 'ready',
                    dispute_status = 'in_dispute',
                    dispute_deadline = %s,
                    updated_at = now()
                WHERE id::text = %s;
                """,
                (deadline_active, case_26),
            )
            print(f"Updated case {case_26} -> ERR-02, ready, in_dispute, deadline: {deadline_active}")

            # 2. Update Case 01 (Late Pickup -> Manual Review)
            case_01 = "018f2f4e-a000-7000-8000-000000000001"
            cur.execute(
                """
                UPDATE app.fraud_cases
                SET suspected_category = 'ERR-01',
                    status = 'driver_disputed',
                    dispute_status = 'in_dispute',
                    dispute_deadline = %s,
                    updated_at = now()
                WHERE id::text = %s;
                """,
                (deadline_active, case_01),
            )
            print(f"Updated case {case_01} -> ERR-01, driver_disputed, in_dispute")

            # 3. Update Case 02 (Liễu Giai GPS Drop -> Already auto dismissed)
            case_02 = "018f2f4e-a000-7000-8000-000000000002"
            cur.execute(
                """
                UPDATE app.fraud_cases
                SET suspected_category = 'ERR-05',
                    status = 'auto_dismissed',
                    dispute_status = 'auto_dismissed',
                    dispute_deadline = %s,
                    updated_at = now()
                WHERE id::text = %s;
                """,
                (datetime.now(UTC) - timedelta(days=1), case_02),
            )
            print(f"Updated case {case_02} -> ERR-05, auto_dismissed")

            # 4. Ensure other cases have valid dispute statuses and active 48h deadlines
            cur.execute(
                """
                UPDATE app.fraud_cases
                SET dispute_status = CASE
                        WHEN random() < 0.25 THEN 'auto_dismissed'
                        WHEN random() < 0.5 THEN 'in_dispute'
                        ELSE 'not_disputed'
                    END,
                    dispute_deadline = now() + interval '42 hours',
                    updated_at = now()
                WHERE id::text NOT IN (%s, %s, %s);
                """,
                (case_26, case_01, case_02),
            )
            print("Enriched remaining fraud cases with realistic dispute statuses and deadlines.")

            # 5. Ensure driver info for case 26's driver is named Nguyễn Văn A
            cur.execute(
                """
                UPDATE app.drivers
                SET display_name = 'Nguyễn Văn A'
                WHERE id IN (
                    SELECT driver_id FROM app.trip_assignments WHERE id = (
                        SELECT assignment_id FROM app.fraud_cases WHERE id::text = %s
                    )
                );
                """,
                (case_26,),
            )
            print(f"Ensured driver name 'Nguyễn Văn A' for case {case_26}.")

            # 6. Ensure case 26 telemetry points reflect Kim Mã crawl speed (< 5 km/h)
            cur.execute(
                """
                UPDATE app.telemetry_points
                SET speed_mps = 0.8,
                    mock_location_reported = false,
                    gps_state = 'valid'
                WHERE assignment_id = (SELECT assignment_id FROM app.fraud_cases WHERE id::text = %s);
                """,
                (case_26,),
            )
            cur.execute(
                """
                SELECT count(*), avg(speed_mps) * 3.6, bool_and(NOT mock_location_reported)
                FROM app.telemetry_points
                WHERE assignment_id = (SELECT assignment_id FROM app.fraud_cases WHERE id::text = %s);
                """,
                (case_26,),
            )
            cnt, avg_speed, is_valid_gps = cur.fetchone()
            print(
                f"Case 26 telemetry verification: {cnt} points, avg speed {avg_speed:.2f} km/h, GPS valid: {is_valid_gps}"
            )

            conn.commit()
            print("Successfully seeded all driver mock data into Supabase!")


if __name__ == "__main__":
    seed_supabase_driver_data()
