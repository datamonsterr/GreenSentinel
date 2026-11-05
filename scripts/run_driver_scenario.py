#!/usr/bin/env python3
"""CLI utility to execute driver dispute scenarios (#158).

Usage:
    python3 scripts/run_driver_scenario.py [--scenario all|normal_corroborated|unresolved_violation|missing_evidence]
                                          [--choice continue_appeal|no_further_appeal]
                                          [--simulate-timeout]
                                          [--json]
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.services.driver_scenario_runner import DriverScenarioRunner
from src.services.scenario_seeder import SCENARIOS_DEFINITIONS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run_driver_scenario")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run driver dispute scenarios for Issue #158.")
    parser.add_argument(
        "--scenario",
        choices=["all", *SCENARIOS_DEFINITIONS.keys()],
        default="all",
        help="Scenario to run (default: all).",
    )
    parser.add_argument(
        "--choice",
        choices=["continue_appeal", "no_further_appeal"],
        default=None,
        help="Driver decision choice for unresolved_violation.",
    )
    parser.add_argument(
        "--simulate-timeout",
        action="store_true",
        help="Simulate 48h silence deadline expiration on unresolved_violation.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON execution trace.",
    )

    args = parser.parse_args()
    runner = DriverScenarioRunner()

    res: dict[str, Any]
    if args.scenario == "all":
        res = await runner.run_all_scenarios()
    else:
        res = await runner.run_scenario(
            scenario_name=args.scenario,
            driver_choice=args.choice,
            simulate_timeout=args.simulate_timeout,
        )

    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        logger.info(f"Scenario run execution completed: scenario={args.scenario}")
        print(json.dumps(res, indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
