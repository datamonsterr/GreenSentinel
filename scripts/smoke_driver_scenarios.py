#!/usr/bin/env python3
"""Smoke test script for Driver Dispute API scenarios (#158).

Runs end-to-end API smoke verification against all 3 seeded driver scenarios:
1. Normal Case: Heavy traffic gridlock, valid GPS, low confidence -> driver confirms resolution -> closed with zero sanction.
2. Unresolved Case: Suspected DIC stall, clear traffic, high confidence -> driver continues appeal -> escalated to analyst.
3. Missing Evidence Case: Zero telemetry, missing confidence -> explicit unavailable state -> escalated to analyst HITL.
Also verifies:
- Cross-driver forbidden access (403)
- Non-existent case not found (404)
- Idempotent request replay

Usage:
    python3 scripts/smoke_driver_scenarios.py [--base-url http://localhost:8000] [--reset] [--json]
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.main import app
from src.services.scenario_seeder import SCENARIOS_DEFINITIONS, ScenarioSeeder

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("smoke_driver_scenarios")


async def run_smoke_test(base_url: str | None = None, reset_after: bool = False) -> dict[str, Any]:
    seeder = ScenarioSeeder()
    seeder.seed_in_memory()

    results: dict[str, Any] = {
        "status": "RUNNING",
        "scenarios_tested": {},
        "authorization_checks": {},
        "idempotency_checks": {},
    }

    # Set up client (ASGI transport if no base_url given)
    transport = None if base_url else ASGITransport(app=app)
    client_base = base_url or "http://testserver"

    async with AsyncClient(transport=transport, base_url=client_base) as client:
        # -----------------------------------------------------------------
        # 1. Normal Corroborated Scenario Smoke
        # -----------------------------------------------------------------
        sc1 = SCENARIOS_DEFINITIONS["normal_corroborated"]
        cid1 = sc1["case_id"]
        did1 = sc1["driver_id"]

        # GET Context
        res = await client.get(
            f"/api/v1/driver/cases/{cid1}/dispute",
            headers={"X-Driver-ID": did1, "X-Role": "driver"},
        )
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        ctx1 = res.json()
        assert ctx1["case_id"] == cid1

        # Turn 1: Explanation
        t1_id = f"smoke-turn-1-{uuid4().hex[:6]}"
        res_turn1 = await client.post(
            f"/api/v1/driver/cases/{cid1}/chat",
            json={
                "case_id": cid1,
                "driver_id": did1,
                "message": "Tôi bị kẹt xe trên đường Kim Mã tắc cứng 15 phút.",
                "claim_type": "traffic_gridlock",
                "turn_id": t1_id,
            },
            headers={"X-Driver-ID": did1, "X-Role": "driver"},
        )
        assert res_turn1.status_code == 200, f"Expected 200, got {res_turn1.status_code}: {res_turn1.text}"
        data_turn1 = res_turn1.json()
        assert data_turn1["dispute_status"] == "pending_confirmation"

        # Turn 2: Driver Confirmation
        t2_id = f"smoke-turn-2-{uuid4().hex[:6]}"
        res_turn2 = await client.post(
            f"/api/v1/driver/cases/{cid1}/chat",
            json={
                "case_id": cid1,
                "driver_id": did1,
                "message": "Tôi đồng ý xác nhận kết thúc khiếu nại.",
                "turn_id": t2_id,
            },
            headers={"X-Driver-ID": did1, "X-Role": "driver"},
        )
        assert res_turn2.status_code == 200, f"Expected 200, got {res_turn2.status_code}: {res_turn2.text}"
        data_turn2 = res_turn2.json()
        assert data_turn2["dispute_status"] == "resolved"

        results["scenarios_tested"]["normal_corroborated"] = {
            "status": "PASS",
            "case_id": cid1,
            "final_dispute_status": data_turn2["dispute_status"],
            "is_auto_dismissed": data_turn2["is_auto_dismissed"],
        }

        # -----------------------------------------------------------------
        # 2. Unresolved Violation Scenario Smoke
        # -----------------------------------------------------------------
        sc2 = SCENARIOS_DEFINITIONS["unresolved_violation"]
        cid2 = sc2["case_id"]
        did2 = sc2["driver_id"]

        # Turn 1: Explanation
        t21_id = f"smoke-unres-1-{uuid4().hex[:6]}"
        res_unres1 = await client.post(
            f"/api/v1/driver/cases/{cid2}/chat",
            json={
                "case_id": cid2,
                "driver_id": did2,
                "message": "Tôi gặp sự cố xe chết máy trên đường.",
                "claim_type": "vehicle_breakdown",
                "turn_id": t21_id,
            },
            headers={"X-Driver-ID": did2, "X-Role": "driver"},
        )
        assert res_unres1.status_code == 200, res_unres1.text
        data_unres1 = res_unres1.json()
        assert data_unres1["dispute_status"] == "pending_confirmation"

        # Turn 2: Continue Appeal -> Escalates to Analyst
        t22_id = f"smoke-unres-2-{uuid4().hex[:6]}"
        res_unres2 = await client.post(
            f"/api/v1/driver/cases/{cid2}/chat",
            json={
                "case_id": cid2,
                "driver_id": did2,
                "message": "Tôi tiếp tục khiếu nại lên Chuyên viên giám sát.",
                "turn_id": t22_id,
            },
            headers={"X-Driver-ID": did2, "X-Role": "driver"},
        )
        assert res_unres2.status_code == 200, res_unres2.text
        data_unres2 = res_unres2.json()
        assert data_unres2["dispute_status"] == "in_dispute"
        assert data_unres2["needs_analyst_review"] is True

        results["scenarios_tested"]["unresolved_violation"] = {
            "status": "PASS",
            "case_id": cid2,
            "final_dispute_status": data_unres2["dispute_status"],
            "needs_analyst_review": data_unres2["needs_analyst_review"],
        }

        # -----------------------------------------------------------------
        # 3. Missing Evidence Scenario Smoke
        # -----------------------------------------------------------------
        sc3 = SCENARIOS_DEFINITIONS["missing_evidence"]
        cid3 = sc3["case_id"]
        did3 = sc3["driver_id"]

        t31_id = f"smoke-miss-1-{uuid4().hex[:6]}"
        res_miss1 = await client.post(
            f"/api/v1/driver/cases/{cid3}/chat",
            json={
                "case_id": cid3,
                "driver_id": did3,
                "message": "Điện thoại mất sóng 4G cả đoạn đường, không có tín hiệu mạng.",
                "claim_type": "technical_dropout",
                "turn_id": t31_id,
            },
            headers={"X-Driver-ID": did3, "X-Role": "driver"},
        )
        assert res_miss1.status_code == 200, res_miss1.text
        data_miss1 = res_miss1.json()
        assert data_miss1["dispute_status"] == "in_dispute"
        assert data_miss1["needs_analyst_review"] is True

        results["scenarios_tested"]["missing_evidence"] = {
            "status": "PASS",
            "case_id": cid3,
            "final_dispute_status": data_miss1["dispute_status"],
            "needs_analyst_review": data_miss1["needs_analyst_review"],
        }

        # -----------------------------------------------------------------
        # 4. Authorization & Security Checks
        # -----------------------------------------------------------------
        # Foreign driver access to cid1 -> 403 Forbidden
        res_auth_mismatch = await client.get(
            f"/api/v1/driver/cases/{cid1}/dispute",
            headers={"X-Driver-ID": did2, "X-Role": "driver"},
        )
        assert res_auth_mismatch.status_code == 403
        assert "Driver identity mismatch" in res_auth_mismatch.json()["detail"]

        # Missing case -> 404 Not Found
        res_404 = await client.get(
            "/api/v1/driver/cases/018f2f4e-0000-0000-0000-000000000404/dispute",
            headers={"X-Driver-ID": did1, "X-Role": "driver"},
        )
        assert res_404.status_code == 404

        results["authorization_checks"] = {
            "foreign_driver_403": "PASS",
            "missing_case_404": "PASS",
        }

        # -----------------------------------------------------------------
        # 5. Idempotent Retry Check
        # -----------------------------------------------------------------
        res_retry = await client.post(
            f"/api/v1/driver/cases/{cid3}/chat",
            json={
                "case_id": cid3,
                "driver_id": did3,
                "message": "Điện thoại mất sóng 4G cả đoạn đường, không có tín hiệu mạng.",
                "claim_type": "technical_dropout",
                "turn_id": t31_id,
            },
            headers={"X-Driver-ID": did3, "X-Role": "driver"},
        )
        assert res_retry.status_code == 200
        assert res_retry.json()["reply"] == data_miss1["reply"]

        results["idempotency_checks"] = {
            "retry_identical_response": "PASS",
        }

    if reset_after:
        seeder.clean_in_memory()
        results["reset"] = "CLEANED"

    results["status"] = "ALL_PASS"
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Driver Dispute API smoke test for Issue #158.")
    parser.add_argument("--base-url", default=None, help="Target API URL (e.g., http://localhost:8000).")
    parser.add_argument("--reset", action="store_true", help="Clean up seeded test data after execution.")
    parser.add_argument("--json", action="store_true", help="Output raw JSON results only.")

    args = parser.parse_args()

    results = asyncio.run(run_smoke_test(base_url=args.base_url, reset_after=args.reset))

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        logger.info("Driver dispute API smoke tests passed successfully!")
        print(json.dumps(results, indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
