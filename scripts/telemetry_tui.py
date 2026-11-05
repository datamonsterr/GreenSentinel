"""Interactive Telemetry Queue TUI & Scenario Testing Tool.

Supports targets: local, dev, preview, production.
Connects to Upstash Redis REST queue (or local Redis) and runs normal & violation scenarios.
Follows: https://upstash.com/docs/redis/tutorials/redis_queue

Usage:
  python scripts/telemetry_tui.py                    # Interactive menu
  python scripts/telemetry_tui.py --target local --scenario driver_stall
  python scripts/telemetry_tui.py --target production --scenario normal_trip
  python scripts/telemetry_tui.py --target dev --worker   # Run queue worker loop
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from src.services.telemetry_queue import RedisRestTransport, ReliableTelemetryQueue  # noqa: E402

DEFAULT_UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL", "https://famous-catfish-293799.upstash.io")
DEFAULT_UPSTASH_TOKEN = os.environ.get(
    "UPSTASH_REDIS_REST_TOKEN",
    "gQAAAAAABHunAAIgcDFhNmJlNDE1YzNjYmY0NzAxYjJlZjdmZDM4ODkwOTYxNg",
)
RAILWAY_ENV_URL = os.environ.get("RAILWAY_PUBLIC_DOMAIN") or os.environ.get("RAILWAY_URL")


def check_railway_status() -> str:
    """Check Railway deployment status if configured."""
    if not RAILWAY_ENV_URL:
        return "Railway domain: not configured (standalone/container mode)"
    url = f"https://{RAILWAY_ENV_URL}" if not RAILWAY_ENV_URL.startswith("http") else RAILWAY_ENV_URL
    try:
        res = httpx.get(f"{url}/health", timeout=3.0)
        return f"Railway {url}: {res.status_code} {res.json().get('status', 'ok')}"
    except Exception as exc:
        return f"Railway {url}: unreachable ({exc})"


def generate_event(
    scenario: str,
    trip_id: str | None = None,
    assignment_id: str | None = None,
    driver_id: str | None = None,
) -> dict[str, Any]:
    """Generate realistic scenario telemetry with Hanoi coordinates and accurate timestamps."""
    start = datetime.now(UTC)
    t_id = trip_id or str(uuid4())
    a_id = assignment_id or str(uuid4())
    d_id = driver_id or "018f2f4e-3000-7000-8000-000000000001"

    # Hanoi landmarks
    pickup = [105.8542, 21.0285]  # Phố Bà Triệu, Hoàn Kiếm
    dropoff = [105.8600, 21.0350]  # Sân bay Nội Bài / Đích đến

    points = []
    stationary_duration_s = 0
    cancellation_reason = None
    lifecycle_state = "complete"

    if scenario == "normal_trip":
        # 10 smooth points from pickup to dropoff
        for i in range(10):
            frac = i / 9.0
            lon = pickup[0] + frac * (dropoff[0] - pickup[0])
            lat = pickup[1] + frac * (dropoff[1] - pickup[1])
            pt_time = start + timedelta(seconds=i * 15)
            points.append(
                {
                    "latitude": round(lat, 6),
                    "longitude": round(lon, 6),
                    "speed_mps": round(8.5 + (i % 3) * 0.5, 2),
                    "bearing_deg": 45.0,
                    "accuracy_m": 4.5,
                    "occurred_at": pt_time.isoformat(),
                    "app_state": "foreground",
                    "network_state": "online",
                    "gps_state": "valid",
                    "mock_location_reported": False,
                }
            )

    elif scenario in ("driver_stall", "ERR-02"):
        # Driver stops for 240s without moving towards pickup
        stationary_duration_s = 240
        cancellation_reason = "Tài xế dừng đỗ quá lâu không di chuyển"
        lifecycle_state = "cancelled"
        init_lon, init_lat = 105.8512, 21.0250
        for i in range(8):
            pt_time = start + timedelta(seconds=i * 30)
            points.append(
                {
                    "latitude": round(init_lat + (i * 0.00001), 6),
                    "longitude": round(init_lon + (i * 0.00001), 6),
                    "speed_mps": 0.0,
                    "bearing_deg": 180.0,
                    "accuracy_m": 3.0,
                    "occurred_at": pt_time.isoformat(),
                    "app_state": "foreground",
                    "network_state": "online",
                    "gps_state": "valid",
                    "mock_location_reported": False,
                }
            )

    elif scenario in ("gps_spoofing", "fake_gps", "ERR-05"):
        # Telemetry with mock provider flag or sudden impossible coordinate jumps
        for i in range(6):
            pt_time = start + timedelta(seconds=i * 15)
            # Impossible teleport jump on point 3
            jump_lon = pickup[0] + (0.05 if i >= 3 else i * 0.001)
            points.append(
                {
                    "latitude": round(pickup[1] + (0.04 if i >= 3 else i * 0.001), 6),
                    "longitude": round(jump_lon, 6),
                    "speed_mps": 35.0 if i >= 3 else 8.0,
                    "bearing_deg": 90.0,
                    "accuracy_m": 15.0 if i >= 3 else 5.0,
                    "occurred_at": pt_time.isoformat(),
                    "app_state": "foreground",
                    "network_state": "online",
                    "gps_state": "mock_reported" if i >= 2 else "valid",
                    "mock_location_reported": i >= 2,
                }
            )

    elif scenario in ("route_deviation", "ERR-03"):
        # Diverts away from destination into opposite corridor
        for i in range(8):
            frac = i / 7.0
            # Moves south-west instead of north-east
            lon = pickup[0] - frac * 0.015
            lat = pickup[1] - frac * 0.012
            pt_time = start + timedelta(seconds=i * 15)
            points.append(
                {
                    "latitude": round(lat, 6),
                    "longitude": round(lon, 6),
                    "speed_mps": 9.0,
                    "bearing_deg": 225.0,
                    "accuracy_m": 4.0,
                    "occurred_at": pt_time.isoformat(),
                    "app_state": "foreground",
                    "network_state": "online",
                    "gps_state": "valid",
                    "mock_location_reported": False,
                }
            )

    elif scenario in ("unjustified_cancel", "ERR-01"):
        # Driver cancels after 10 seconds without moving
        lifecycle_state = "cancelled"
        cancellation_reason = "Tài xế tự hủy không lý do chính đáng"
        points.append(
            {
                "latitude": 21.0250,
                "longitude": 105.8512,
                "speed_mps": 0.0,
                "bearing_deg": 0.0,
                "accuracy_m": 5.0,
                "occurred_at": start.isoformat(),
                "app_state": "foreground",
                "network_state": "online",
                "gps_state": "valid",
                "mock_location_reported": False,
            }
        )
    else:
        # Default nominal point
        points.append(
            {
                "latitude": pickup[1],
                "longitude": pickup[0],
                "speed_mps": 8.0,
                "bearing_deg": 45.0,
                "accuracy_m": 5.0,
                "occurred_at": start.isoformat(),
                "app_state": "foreground",
                "network_state": "online",
                "gps_state": "valid",
                "mock_location_reported": False,
            }
        )

    return {
        "event_id": str(uuid4()),
        "trip_id": t_id,
        "assignment_id": a_id,
        "driver_id": d_id,
        "pickup": pickup,
        "dropoff": dropoff,
        "scenario": scenario,
        "points": points,
        "stationary_duration_s": stationary_duration_s,
        "cancellation_reason": cancellation_reason,
        "cancellation_actor": "driver" if cancellation_reason else None,
        "lifecycle_state": lifecycle_state,
    }


def get_queue(target: str) -> ReliableTelemetryQueue:
    """Instantiate ReliableTelemetryQueue for selected environment."""
    prefix = f"telemetry:{target}" if target != "production" else "telemetry"
    if target == "local":
        # Use local Redis REST or Upstash REST for testing
        url = os.environ.get("UPSTASH_REDIS_REST_URL", DEFAULT_UPSTASH_URL)
        token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", DEFAULT_UPSTASH_TOKEN)
        return ReliableTelemetryQueue(RedisRestTransport(url, token), prefix="telemetry:local")
    url = os.environ.get("UPSTASH_REDIS_REST_URL", DEFAULT_UPSTASH_URL)
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", DEFAULT_UPSTASH_TOKEN)
    return ReliableTelemetryQueue(RedisRestTransport(url, token), prefix=prefix)


async def inspect_queue(target: str) -> None:
    queue = get_queue(target)
    ready_items = await queue.transport.command("LLEN", queue.ready) or 0
    proc_items = await queue.transport.command("LLEN", queue.processing) or 0
    dead_items = await queue.transport.command("LLEN", queue.deadletter) or 0
    print("\n" + "=" * 50)
    print(f"  QUEUE STATUS: [{target.upper()}] (Prefix: {queue.ready.split(':')[0]})")
    print("=" * 50)
    print(f"  • Ready (telemetry:ready):       {ready_items}")
    print(f"  • Processing in-flight:         {proc_items}")
    print(f"  • Dead-letter DLQ:              {dead_items}")
    print("=" * 50 + "\n")


async def run_worker_loop(target: str) -> None:
    """Run worker listening and claiming from Upstash queue."""
    from src.services.case_service import get_case_service
    from src.services.telemetry_queue_worker import TelemetryQueueWorker

    queue = get_queue(target)
    service = get_case_service()
    worker = TelemetryQueueWorker(queue=queue, case_service=service)

    print(f"\n[Worker] Listening to {queue.ready} on target: {target.upper()}...")
    print("[Worker] Press Ctrl+C to stop.\n")
    try:
        while True:
            results = await worker.run_once()
            if results:
                for r in results:
                    category = r.get("assessment", {}).get("category")
                    case_id = r.get("case_id")
                    print(
                        f"  [PROCESSED] Trip: {r['trip_id'][:8]}.. | Category: {category} | "
                        f"Case: {case_id or 'NONE (Nominal)'} | Driver: {r['driver_id'][:8]}.."
                    )
            await asyncio.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[Worker] Stopped.")


async def drain_one(target: str) -> None:
    """Drain and process a single message from queue."""
    from src.services.case_service import get_case_service
    from src.services.telemetry_queue_worker import process_telemetry_event

    queue = get_queue(target)
    item = await queue.claim()
    if not item:
        print(f"\n[Queue {target}] No items in ready queue ({queue.ready}).\n")
        return
    print(f"\nClaimed receipt: {item['receipt']}")
    service = get_case_service()
    try:
        res = await process_telemetry_event(item["payload"], service)
        await queue.ack(item)
        print(f"Successfully processed and ACKed receipt={item['receipt']}:")
        print(json.dumps(res, indent=2, default=str))
    except Exception as exc:
        await queue.fail(item, exc)
        print(f"Failed processing item: {exc}")


async def interactive_tui() -> None:
    target = "local"
    while True:
        print("\n" + "=" * 60)
        print("  AI20K GreenSentinel: TELEMETRY QUEUE & FRAUD DETECTION TUI")
        print(f"  Target: [{target.upper()}]  |  {check_railway_status()}")
        print("=" * 60)
        print("  1. Switch Target [local / dev / preview / production]")
        print("  2. Enqueue [Normal Trip] (No violation expected)")
        print("  3. Enqueue [Driver Stall ERR-02] (240s stationary -> Case + Assign)")
        print("  4. Enqueue [GPS Spoofing ERR-05] (Mock provider -> Case + Assign)")
        print("  5. Enqueue [Route Deviation ERR-03] (Corridor drift -> Case + Assign)")
        print("  6. Enqueue [Unjustified Cancel ERR-01] (0s stall cancel -> Case)")
        print("  7. Check Queue Depth & DLQ")
        print("  8. Drain Single Item & Execute Violation Pipeline")
        print("  9. Start Continuous Queue Worker Loop")
        print("  0. Exit")
        print("=" * 60)

        choice = input("Select action [0-9]: ").strip()
        if choice == "0":
            print("Exiting TUI.")
            break
        elif choice == "1":
            new_target = input("Choose target [local/dev/preview/production] (local): ").strip().lower()
            if new_target in ("local", "dev", "preview", "production"):
                target = new_target
                print(f"Target set to: {target.upper()}")
            else:
                print("Invalid target.")
        elif choice in ("2", "3", "4", "5", "6"):
            scenario_map = {
                "2": "normal_trip",
                "3": "driver_stall",
                "4": "gps_spoofing",
                "5": "route_deviation",
                "6": "unjustified_cancel",
            }
            scen = scenario_map[choice]
            queue = get_queue(target)
            event_data = generate_event(scen)
            receipt = await queue.enqueue(event_data)
            print(f"\n[OK] Enqueued {scen} to {queue.ready}!")
            print(f"     Receipt: {receipt}")
            print(f"     Trip ID: {event_data['trip_id']}")
            print(f"     Points:  {len(event_data['points'])}")
        elif choice == "7":
            await inspect_queue(target)
        elif choice == "8":
            await drain_one(target)
        elif choice == "9":
            await run_worker_loop(target)
        else:
            print("Invalid option.")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Telemetry Queue & Scenario Testing TUI")
    parser.add_argument("--target", choices=("local", "dev", "preview", "production"), default="local")
    parser.add_argument(
        "--scenario",
        choices=("normal_trip", "driver_stall", "gps_spoofing", "route_deviation", "unjustified_cancel"),
        help="Fire scenario event non-interactively",
    )
    parser.add_argument("--trip-id", help="Explicit trip ID")
    parser.add_argument("--assignment-id", help="Explicit assignment ID")
    parser.add_argument("--driver-id", help="Explicit driver ID")
    parser.add_argument("--worker", action="store_true", help="Start continuous worker listener")
    parser.add_argument("--drain", action="store_true", help="Claim and process single message")
    parser.add_argument("--status", action="store_true", help="Check queue depths")
    args = parser.parse_args()

    if args.status:
        await inspect_queue(args.target)
    elif args.worker:
        await run_worker_loop(args.target)
    elif args.drain:
        await drain_one(args.target)
    elif args.scenario:
        queue = get_queue(args.target)
        payload = generate_event(args.scenario, args.trip_id, args.assignment_id, args.driver_id)
        receipt = await queue.enqueue(payload)
        print(f"Queued scenario '{args.scenario}' to {queue.ready} with receipt: {receipt}")
    elif len(sys.argv) > 1 and not sys.stdin.isatty():
        # Non-interactive without scenario
        queue = get_queue(args.target)
        payload = generate_event("normal_trip")
        receipt = await queue.enqueue(payload)
        print(f"Queued default normal_trip with receipt: {receipt}")
    else:
        await interactive_tui()


if __name__ == "__main__":
    asyncio.run(main())
