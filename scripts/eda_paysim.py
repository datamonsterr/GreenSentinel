"""EDA: PaySim prevalence reference (EDA-ONLY, payments domain).

Streams data/raw/paysim/paysim.csv in chunks; deterministic systematic
sample of <=1M rows. Reports sampled isFraud rate + fraud-vs-legit amount
distribution. Writes aggregates only to notebooks/paysim/profile.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "data/raw/paysim/paysim.csv"
OUT = ROOT / "notebooks/paysim"

CHUNKSIZE = 200_000
STRIDE = 12  # ~530k of 6.36M rows
USECOLS = ["step", "type", "amount", "isFraud", "isFlaggedFraud"]


def q(a: np.ndarray) -> dict:
    a = np.asarray(a, dtype=float)
    a = a[np.isfinite(a)]
    out = {"count": int(len(a))}
    if len(a):
        for k, v in zip(
            ["min", "p05", "p25", "p50", "p75", "p95", "max"],
            np.quantile(a, [0, 0.05, 0.25, 0.5, 0.75, 0.95, 1]),
        ):
            out[k] = round(float(v), 4)
        out["mean"] = round(float(a.mean()), 4)
        out["std"] = round(float(a.std()), 4)
    return out


def run() -> dict:
    parts, total_rows = [], 0
    for i, chunk in enumerate(pd.read_csv(CSV, usecols=USECOLS, chunksize=CHUNKSIZE)):
        total_rows += len(chunk)
        parts.append(chunk.iloc[i % STRIDE :: STRIDE])
    sample = pd.concat(parts, ignore_index=True)
    fraud = sample[sample["isFraud"] == 1]
    legit = sample[sample["isFraud"] == 0]

    by_type = {}
    for t, g in sample.groupby("type"):
        gf = g[g["isFraud"] == 1]
        by_type[str(t)] = {
            "n": int(len(g)),
            "n_fraud": int(len(gf)),
            "fraud_rate": round(float(len(gf) / len(g)), 6) if len(g) else None,
        }

    report = {
        "provenance": {
            "source": "data/raw/paysim/paysim.csv (HF mirror, MIT card; payments domain, EDA-ONLY)",
            "method": f"streaming chunksize={CHUNKSIZE}, systematic stride={STRIDE} (offset rotates per chunk)",
            "rows_scanned": int(total_rows),
            "rows_sampled": int(len(sample)),
        },
        "sampled_fraud": {
            "n_fraud": int(len(fraud)),
            "n_legit": int(len(legit)),
            "sampled_isFraud_rate": round(float(len(fraud) / len(sample)), 6),
            "flagged_rate_overall": round(float((sample["isFlaggedFraud"] == 1).mean()), 6),
        },
        "amount_fraud_vs_legit": {
            "fraud": q(fraud["amount"].to_numpy()),
            "legit": q(legit["amount"].to_numpy()),
        },
        "by_type": by_type,
        "benchmark_mix_note": (
            "Our benchmark class mix is deliberate enrichment for detection evaluation, "
            "not natural prevalence: PaySim-scale natural fraud prevalence is ~0.1% "
            "(8,213/6,362,620 = 0.129% per manifest), at which a detector's alert burden "
            "and precision cannot be meaningfully benchmarked on a 10k-case set. "
            "Enriched mixes (e.g. ~10% like the MiPo slice) measure ranking quality "
            "(AUROC/AP) under controlled conditions; they must not be presented as "
            "production precision, and thresholds set on enriched data must be "
            "recalibrated to the deployment base rate before any operational use."
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "profile.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"scanned={total_rows} sampled={len(sample)} fraud={len(fraud)} rate={len(fraud) / len(sample):.6f}")
    print(
        f"fraud_amount_p50={report['amount_fraud_vs_legit']['fraud']['p50']} legit_p50={report['amount_fraud_vs_legit']['legit']['p50']}"
    )
    print(f"by_type={by_type}")
    return report


if __name__ == "__main__":
    run()
