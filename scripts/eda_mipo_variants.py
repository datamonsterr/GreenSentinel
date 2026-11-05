"""MiPo variant EDA: 8-feature stats + tortuosity transductive benchmark per variant.

Reuses geometry/describe/lof_scores/evaluate from scripts/eda_mipo.py (AiSq10D
method, MIPO_EDA.md). Labels from filename, evaluation only. No CRS/time claims.
Writes notebooks/mipo_variants/profile.json.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from eda_mipo import describe, evaluate, geometry, lof_scores  # noqa: E402

VARIANTS = ["AiSq5D", "StSt10M", "UnCh10M"]
REVISION = "70a9b0140f94a1d3e2349999c621392c18c439fc"
OUT = ROOT / "notebooks/mipo_variants/profile.json"
# ERR-03 prior from config/telemetry_distribution.yaml route.tortuosity_quantiles (AiSq10D)
PRIOR = {"normal": {"p05": 1.2562, "p95": 1.4688}, "detour": {"p05": 1.3584, "p95": 1.7888}}


def run() -> dict:
    report: dict = {
        "revision": REVISION,
        "method": "same 8-feature geometry + transductive tortuosity/LOF benchmark as MIPO_EDA.md; labels evaluation-only",
        "environment": {"python": platform.python_version(), "numpy": np.__version__},
        "prior_err03_tortuosity": PRIOR,
        "variants": {},
    }
    for v in VARIANTS:
        recs = []
        for name, label in [("inners.txt", 0), ("outliers.txt", 1)]:
            p = ROOT / f"data/raw/mipo_variants/{v}/{name}"
            lines = [ln for ln in p.read_text().splitlines() if ln.strip()]
            if label == 0:
                report.setdefault("sha256", {})[f"{v}/{name}"] = hashlib.sha256(p.read_bytes()).hexdigest()
            else:
                report["sha256"][f"{v}/{name}"] = hashlib.sha256(p.read_bytes()).hexdigest()
            recs.extend({"label": label, "xy": json.loads(ln)} for ln in lines)
        feats = [geometry(r) for r in recs]
        names = list(feats[0])
        mat = np.array([[f[n] for n in names] for f in feats])
        lab = np.array([r["label"] for r in recs])
        pts = np.concatenate([np.asarray(r["xy"]) for r in recs])
        tort = mat[:, names.index("tortuosity")]
        vd = {
            "n": len(recs),
            "normal": int((lab == 0).sum()),
            "outliers": int((lab == 1).sum()),
            "prevalence": float(lab.mean()),
            "coordinate_x_range": [float(pts[:, 0].min()), float(pts[:, 0].max())],
            "coordinate_y_range": [float(pts[:, 1].min()), float(pts[:, 1].max())],
            "distributions": {n: describe(mat[:, i]) for i, n in enumerate(names)},
            "by_label": {str(lb): {n: describe(mat[lab == lb, i]) for i, n in enumerate(names)} for lb in [0, 1]},
            "benchmark": {
                "tortuosity": evaluate(lab, tort),
                "geometry_lof_k20": evaluate(lab, lof_scores(mat)),
                "ap_baseline": float(lab.mean()),
            },
        }
        report["variants"][v] = vd
        print(v, vd["n"], vd["benchmark"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


if __name__ == "__main__":
    run()
