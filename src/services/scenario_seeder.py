"""Scenario Seeder for Issue #158.

Creates isolated, reproducible, and reversible scenario data with stable IDs
and source metadata for driver dispute workflows.
Supports:
1. Normal Case: Heavy traffic gridlock, valid telemetry, corroborated.
2. Unresolved Violation: Intentional driver stall, normal traffic telemetry, uncorroborated.
3. Missing Evidence: Technical dropout, zero telemetry, explicit unavailable state.

Options:
- dry_run: Preview records without modifying storage.
- reset: Clean up only scenario run records without touching other database rows.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from src.services.case_service import CaseService, get_case_service
from src.services.driver_dispute_service import DriverDisputeService, get_driver_dispute_service

logger = logging.getLogger(__name__)

RUN_ID = "seed-driver-158"
SEED_VERSION = "1.0"
ORG_ID = "018f2f4e-0000-7000-8000-000000000001"

SCENARIOS_DEFINITIONS: dict[str, dict[str, Any]] = {
    "normal_corroborated": {
        "case_id": "018f2f4e-b000-7000-8000-000000000001",
        "case_alias": "case-scn-normal-01",
        "trip_id": "018f2f4e-b100-7000-8000-000000000001",
        "trip_alias": "trip-scn-normal-01",
        "assignment_id": "018f2f4e-b200-7000-8000-000000000001",
        "assignment_alias": "asgn-scn-normal-01",
        "driver_id": "018f2f4e-b300-7000-8000-000000000001",
        "driver_alias": "drv-scn-normal-01",
        "driver_name": "Nguyễn Văn Bình",
        "vehicle_id": "018f2f4e-b500-7000-8000-000000000001",
        "vehicle_plate": "29E-111.11",
        "suspected_category": "ERR-01",
        "confidence": 0.35,
        "telemetry_points_count": 15,
        "speed_mps_range": (0.7, 1.2),  # 2.5 - 4.3 km/h (< 5 km/h)
        "mock_location": False,
        "source_metadata": {
            "scenario": "normal_corroborated",
            "run_id": RUN_ID,
            "version": SEED_VERSION,
            "description": "Heavy traffic gridlock with slow speeds and valid GPS corroborating driver delay",
        },
    },
    "unresolved_violation": {
        "case_id": "018f2f4e-b000-7000-8000-000000000002",
        "case_alias": "case-scn-unresolved-02",
        "trip_id": "018f2f4e-b100-7000-8000-000000000002",
        "trip_alias": "trip-scn-unresolved-02",
        "assignment_id": "018f2f4e-b200-7000-8000-000000000002",
        "assignment_alias": "asgn-scn-unresolved-02",
        "driver_id": "018f2f4e-b300-7000-8000-000000000002",
        "driver_alias": "drv-scn-unresolved-02",
        "driver_name": "Lê Hoàng Long",
        "vehicle_id": "018f2f4e-b500-7000-8000-000000000002",
        "vehicle_plate": "29E-222.22",
        "suspected_category": "ERR-02",
        "confidence": 0.78,  # Strictly > 0.50
        "telemetry_points_count": 15,
        "speed_mps_range": (8.5, 11.0),  # 30.6 - 39.6 km/h (clear flow)
        "mock_location": False,
        "source_metadata": {
            "scenario": "unresolved_violation",
            "run_id": RUN_ID,
            "version": SEED_VERSION,
            "description": "Suspected intentional stall DIC with clear traffic flow and high violation confidence",
        },
    },
    "missing_evidence": {
        "case_id": "018f2f4e-b000-7000-8000-000000000003",
        "case_alias": "case-scn-missing-03",
        "trip_id": "018f2f4e-b100-7000-8000-000000000003",
        "trip_alias": "trip-scn-missing-03",
        "assignment_id": "018f2f4e-b200-7000-8000-000000000003",
        "assignment_alias": "asgn-scn-missing-03",
        "driver_id": "018f2f4e-b300-7000-8000-000000000003",
        "driver_alias": "drv-scn-missing-03",
        "driver_name": "Phạm Minh Quang",
        "vehicle_id": "018f2f4e-b500-7000-8000-000000000003",
        "vehicle_plate": "29E-333.33",
        "suspected_category": "ERR-05",
        "confidence": None,
        "telemetry_points_count": 0,
        "speed_mps_range": (0.0, 0.0),
        "mock_location": False,
        "source_metadata": {
            "scenario": "missing_evidence",
            "run_id": RUN_ID,
            "version": SEED_VERSION,
            "description": "Technical dropout with zero recorded telemetry and missing confidence assessment",
        },
    },
}

ALL_SCENARIO_CASE_IDS = [sc["case_id"] for sc in SCENARIOS_DEFINITIONS.values()]
ALL_SCENARIO_CASE_ALIASES = [sc["case_alias"] for sc in SCENARIOS_DEFINITIONS.values()]
ALL_SCENARIO_ASGN_IDS = [sc["assignment_id"] for sc in SCENARIOS_DEFINITIONS.values()]
ALL_SCENARIO_TRIP_IDS = [sc["trip_id"] for sc in SCENARIOS_DEFINITIONS.values()]
ALL_SCENARIO_DRIVER_IDS = [sc["driver_id"] for sc in SCENARIOS_DEFINITIONS.values()]
ALL_SCENARIO_VEHICLE_IDS = [sc["vehicle_id"] for sc in SCENARIOS_DEFINITIONS.values()]


class ScenarioSeeder:
    """Manages idempotent seeding and reversible cleanup of driver dispute scenarios."""

    def __init__(
        self,
        case_service: CaseService | None = None,
        dispute_service: DriverDisputeService | None = None,
    ) -> None:
        self.case_service = case_service or get_case_service()
        self.dispute_service = dispute_service or get_driver_dispute_service()

    def generate_telemetry_points(
        self,
        assignment_id: str,
        count: int,
        speed_range: tuple[float, float],
        base_time: datetime,
        mock: bool = False,
    ) -> list[dict[str, Any]]:
        """Generate deterministic GPS points along a Hanoi corridor."""
        points: list[dict[str, Any]] = []
        base_lat, base_lon = 21.0285, 105.8542
        min_spd, max_spd = speed_range
        step_spd = (max_spd - min_spd) / max(1, count - 1) if count > 1 else min_spd

        for i in range(count):
            t = base_time + timedelta(seconds=i * 10)
            spd = min_spd + step_spd * i
            lat = base_lat + (i * 0.00015)
            lon = base_lon + (i * 0.00012)
            pt = {
                "id": f"pt-{assignment_id[-8:]}-{i:03d}",
                "assignment_id": assignment_id,
                "recorded_at": t.isoformat(),
                "timestamp": t.isoformat(),
                "latitude": round(lat, 6),
                "longitude": round(lon, 6),
                "speed_mps": round(spd, 3),
                "speed_kmh": round(spd * 3.6, 2),
                "mock_location_reported": mock,
                "source": "seed_driver_scenarios",
            }
            points.append(pt)
        return points

    def seed_in_memory(
        self,
        dry_run: bool = False,
        reset: bool = False,
    ) -> dict[str, Any]:
        """Seed scenario records into in-memory structures or reset them cleanly."""
        if reset:
            deleted_counts = self.clean_in_memory()
            return {"action": "reset", "dry_run": dry_run, "deleted": deleted_counts}

        manifest: dict[str, Any] = {
            "run_id": RUN_ID,
            "version": SEED_VERSION,
            "scenarios": {},
            "counts": {"cases": 0, "drivers": 0, "trips": 0, "assignments": 0, "telemetry_points": 0},
        }

        now = datetime.now(UTC)
        deadline = now + timedelta(hours=48)

        for name, spec in SCENARIOS_DEFINITIONS.items():
            cid = spec["case_id"]
            alias = spec["case_alias"]
            did = spec["driver_id"]
            d_alias = spec["driver_alias"]
            tid = spec["trip_id"]
            aid = spec["assignment_id"]
            vid = spec["vehicle_id"]

            points = self.generate_telemetry_points(
                assignment_id=aid,
                count=spec["telemetry_points_count"],
                speed_range=spec["speed_mps_range"],
                base_time=now - timedelta(minutes=30),
                mock=spec["mock_location"],
            )

            manifest["scenarios"][name] = {
                "case_id": cid,
                "case_alias": alias,
                "driver_id": did,
                "driver_alias": d_alias,
                "driver_name": spec["driver_name"],
                "assignment_id": aid,
                "category": spec["suspected_category"],
                "confidence": spec["confidence"],
                "points_count": len(points),
            }

            if not dry_run:
                # Aliases
                self.case_service._case_aliases[alias] = cid
                self.case_service._case_aliases[cid] = cid
                self.dispute_service._driver_aliases[d_alias] = did
                self.dispute_service._driver_aliases[did] = d_alias

                # Confidence overrides
                if spec["confidence"] is not None:
                    self.dispute_service._confidence_overrides[cid] = spec["confidence"]
                    self.dispute_service._confidence_overrides[alias] = spec["confidence"]

                # Driver
                driver_obj = {
                    "id": did,
                    "display_name": spec["driver_name"],
                    "account_status": "active",
                    "source": RUN_ID,
                }
                self.case_service._drivers[did] = driver_obj
                self.case_service._drivers[d_alias] = driver_obj

                # Vehicle
                vehicle_obj = {
                    "id": vid,
                    "registration_ref": spec["vehicle_plate"],
                    "source": RUN_ID,
                }
                self.case_service._vehicles[vid] = vehicle_obj

                # Trip
                trip_obj = {
                    "id": tid,
                    "pickup_address": "Số 1 Đại Cồ Việt, Hai Bà Trưng, Hà Nội",
                    "dropoff_address": "Số 54 Liễu Giai, Ba Đình, Hà Nội",
                    "source": RUN_ID,
                }
                self.case_service._trips[tid] = trip_obj

                # Assignment
                asgn_obj = {
                    "id": aid,
                    "trip_id": tid,
                    "driver_id": did,
                    "vehicle_id": vid,
                    "source": RUN_ID,
                }
                self.case_service._assignments[aid] = asgn_obj

                # Fraud Case
                case_obj = {
                    "id": cid,
                    "organization_id": ORG_ID,
                    "assignment_id": aid,
                    "driver_id": did,
                    "trip_id": tid,
                    "status": "ready",
                    "dispute_status": "not_disputed",
                    "dispute_deadline": deadline.isoformat(),
                    "suspected_category": spec["suspected_category"],
                    "confidence": spec["confidence"],
                    "priority_score": 75,
                    "priority_tier": 1,
                    "priority_rule_version": "v1",
                    "version": 1,
                    "created_at": now.isoformat(),
                    "source_metadata": spec["source_metadata"],
                }
                self.case_service._cases[cid] = case_obj
                self.case_service._cases[alias] = case_obj

                # Telemetry Points
                # Remove prior points for aid if any
                self.case_service._telemetry_points = [
                    p for p in self.case_service._telemetry_points if p.get("assignment_id") != aid
                ]
                self.case_service._telemetry_points.extend(points)

            manifest["counts"]["cases"] += 1
            manifest["counts"]["drivers"] += 1
            manifest["counts"]["trips"] += 1
            manifest["counts"]["assignments"] += 1
            manifest["counts"]["telemetry_points"] += len(points)

        manifest["dry_run"] = dry_run
        return manifest

    def clean_in_memory(self) -> dict[str, int]:
        """Reversibly remove only scenario records from in-memory stores."""
        initial_cases = len(self.case_service._cases)
        initial_pts = len(self.case_service._telemetry_points)

        for cid in ALL_SCENARIO_CASE_IDS + ALL_SCENARIO_CASE_ALIASES:
            self.case_service._cases.pop(cid, None)
            self.case_service._case_aliases.pop(cid, None)
            self.dispute_service._confidence_overrides.pop(cid, None)
            self.dispute_service._traffic_overrides.pop(cid, None)
            self.dispute_service._audit_entries.pop(cid, None)
            self.dispute_service._dispute_statements.pop(cid, None)

        for did in ALL_SCENARIO_DRIVER_IDS:
            self.case_service._drivers.pop(did, None)
        for alias in ["drv-scn-normal-01", "drv-scn-unresolved-02", "drv-scn-missing-03"]:
            self.case_service._drivers.pop(alias, None)
            self.dispute_service._driver_aliases.pop(alias, None)

        for tid in ALL_SCENARIO_TRIP_IDS:
            self.case_service._trips.pop(tid, None)
        for aid in ALL_SCENARIO_ASGN_IDS:
            self.case_service._assignments.pop(aid, None)
        for vid in ALL_SCENARIO_VEHICLE_IDS:
            self.case_service._vehicles.pop(vid, None)

        self.case_service._telemetry_points = [
            p for p in self.case_service._telemetry_points if p.get("assignment_id") not in ALL_SCENARIO_ASGN_IDS
        ]

        # Clear processed chat requests for scenarios
        self.dispute_service._processed_chat_requests = {
            k: v
            for k, v in self.dispute_service._processed_chat_requests.items()
            if not any(sc_id in k for sc_id in ALL_SCENARIO_CASE_IDS + ALL_SCENARIO_CASE_ALIASES)
        }
        self.dispute_service._confirmation_tokens.clear()
        self.dispute_service._statement_drafts.clear()

        return {
            "cases_removed": initial_cases - len(self.case_service._cases),
            "telemetry_points_removed": initial_pts - len(self.case_service._telemetry_points),
        }

    def seed_database(self, conn: Any, dry_run: bool = False, reset: bool = False) -> dict[str, Any]:
        """Seed scenario data into PostgreSQL database or cleanly remove only scenario run IDs."""
        if reset:
            deleted = self.clean_database(conn)
            return {"action": "reset", "dry_run": dry_run, "deleted": deleted}

        manifest = self.seed_in_memory(dry_run=True)
        if dry_run:
            return manifest

        now = datetime.now(UTC)
        deadline = now + timedelta(hours=48)

        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")

            # Clean up prior scenario rows if present to preserve idempotency
            self._execute_db_cleanup(cur)

            for _name, spec in SCENARIOS_DEFINITIONS.items():
                cid = spec["case_id"]
                did = spec["driver_id"]
                tid = spec["trip_id"]
                aid = spec["assignment_id"]
                vid = spec["vehicle_id"]

                # 1. Driver
                cur.execute(
                    """
                    INSERT INTO app.drivers (id, organization_id, external_ref, display_name, account_status)
                    VALUES (%s, %s, %s, %s, 'active')
                    ON CONFLICT (id) DO UPDATE SET display_name = EXCLUDED.display_name;
                    """,
                    (did, ORG_ID, spec["driver_alias"], spec["driver_name"]),
                )

                # 2. Vehicle
                cur.execute(
                    """
                    INSERT INTO app.vehicles (id, organization_id, registration_ref, make, model)
                    VALUES (%s, %s, %s, 'VinFast', 'VF8')
                    ON CONFLICT (id) DO UPDATE SET registration_ref = EXCLUDED.registration_ref;
                    """,
                    (vid, ORG_ID, spec["vehicle_plate"]),
                )

                # 3. Trip
                cur.execute(
                    """
                    INSERT INTO app.trips (id, organization_id, pickup_address, dropoff_address, pickup, dropoff)
                    VALUES (
                        %s, %s, 'Số 1 Đại Cồ Việt, Hai Bà Trưng, Hà Nội', 'Số 54 Liễu Giai, Ba Đình, Hà Nội',
                        ST_SetSRID(ST_MakePoint(105.8542, 21.0285), 4326),
                        ST_SetSRID(ST_MakePoint(105.8115, 21.0332), 4326)
                    )
                    ON CONFLICT (id) DO NOTHING;
                    """,
                    (tid, ORG_ID),
                )

                # 4. Trip Assignment
                cur.execute(
                    """
                    INSERT INTO app.trip_assignments (id, organization_id, trip_id, driver_id, vehicle_id, state)
                    VALUES (%s, %s, %s, %s, %s, 'completed')
                    ON CONFLICT (id) DO NOTHING;
                    """,
                    (aid, ORG_ID, tid, did, vid),
                )

                # 5. Fraud Case
                cur.execute(
                    """
                    INSERT INTO app.fraud_cases (
                        id, organization_id, assignment_id, status, dispute_status,
                        dispute_deadline, suspected_category, priority_tier, priority_score,
                        priority_rule_version, version, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, 'ready', 'not_disputed', %s, %s, 1, 75, 'v1', 1, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        status = 'ready',
                        dispute_status = 'not_disputed',
                        dispute_deadline = EXCLUDED.dispute_deadline;
                    """,
                    (cid, ORG_ID, aid, deadline, spec["suspected_category"], now, now),
                )

                # 6. Telemetry Points
                points = self.generate_telemetry_points(
                    assignment_id=aid,
                    count=spec["telemetry_points_count"],
                    speed_range=spec["speed_mps_range"],
                    base_time=now - timedelta(minutes=30),
                    mock=spec["mock_location"],
                )
                for pt in points:
                    cur.execute(
                        """
                        INSERT INTO app.telemetry_points (
                            id, organization_id, assignment_id, recorded_at, location,
                            speed_mps, mock_location_reported
                        )
                        VALUES (
                            gen_random_uuid(), %s, %s, %s,
                            ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                            %s, %s
                        );
                        """,
                        (
                            ORG_ID,
                            aid,
                            pt["recorded_at"],
                            pt["longitude"],
                            pt["latitude"],
                            pt["speed_mps"],
                            pt["mock_location_reported"],
                        ),
                    )

            conn.commit()

        # Also sync in-memory structures
        self.seed_in_memory(dry_run=False)
        manifest["dry_run"] = False
        return manifest

    def _execute_db_cleanup(self, cur: Any) -> None:
        """Execute scoped cleanup queries on DB cursor."""
        cur.execute("DELETE FROM app.telemetry_points WHERE assignment_id::text = ANY(%s);", (ALL_SCENARIO_ASGN_IDS,))
        cur.execute("DELETE FROM app.fraud_cases WHERE id::text = ANY(%s);", (ALL_SCENARIO_CASE_IDS,))
        cur.execute("DELETE FROM app.trip_assignments WHERE id::text = ANY(%s);", (ALL_SCENARIO_ASGN_IDS,))
        cur.execute("DELETE FROM app.trips WHERE id::text = ANY(%s);", (ALL_SCENARIO_TRIP_IDS,))
        cur.execute("DELETE FROM app.drivers WHERE id::text = ANY(%s);", (ALL_SCENARIO_DRIVER_IDS,))
        cur.execute("DELETE FROM app.vehicles WHERE id::text = ANY(%s);", (ALL_SCENARIO_VEHICLE_IDS,))

    def clean_database(self, conn: Any) -> dict[str, int]:
        """Cleanly remove only scenario run records from database."""
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            self._execute_db_cleanup(cur)
            conn.commit()
        # Also clean in-memory state
        return self.clean_in_memory()
