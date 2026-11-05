"""Print per-class null rate for evidence state measurements on dev300."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from scripts.benchmark.run_10k import bundle_to_input
from src.services.jev_state_builder import build_jev_state


def main() -> None:
    dev300_path = Path("/home/dat/releases_v2_1/dev300.jsonl")
    if not dev300_path.exists():
        print(f"Error: {dev300_path} not found.")
        return

    with open(dev300_path, encoding="utf-8") as f:
        trips = [json.loads(line) for line in f]

    print(f"Total trips loaded: {len(trips)}")

    class_counts: dict[str, int] = defaultdict(int)
    null_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    measurements_sample: dict = {}

    for t in trips:
        lbl = t.get("label", "unknown")
        class_counts[lbl] += 1
        jev_inp, _pts, _trip_data = bundle_to_input(t)
        state = build_jev_state(jev_inp, variant="evidence")
        meas = state.get("telemetry", {}).get("measurements", {})
        if not measurements_sample:
            measurements_sample = meas

        for k, v in meas.items():
            if v.get("value") is None:
                null_counts[lbl][k] += 1

    print("\n================ DEV300 EVIDENCE MEASUREMENTS COVERAGE ================")
    for lbl in sorted(class_counts.keys()):
        n = class_counts[lbl]
        print(f"\nClass {lbl} (n={n}):")
        for k in sorted(measurements_sample.keys()):
            cnt = null_counts[lbl][k]
            pct = (cnt / n) * 100.0
            print(f"  {k:35s}: {cnt:3d}/{n:3d} ({pct:5.1f}% null)")

    print("\n=======================================================================")


if __name__ == "__main__":
    main()
