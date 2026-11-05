"""EDA: Nayfeh GPS-spoofing receiver telemetry (EDA-ONLY, no license).

Labels from filenames (attack vs clean). Transductive single-threshold
kinematic benchmark on the pooled labeled rows: same AUROC convention as
docs/data/MIPO_EDA.md (pairwise, half credit for ties). Writes aggregates
only to notebooks/spoofing/profile.json. Never merges raw rows.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/gps_spoofing_nayfeh"
OUT = ROOT / "notebooks/spoofing"

FILES = {
    "testing_attack": (RAW / "testing_attack.xlsx", 1),
    "testing_clean": (RAW / "testing_clean.xlsx", 0),
    "trainval_attack": (RAW / "trainval_attack.xlsx", 1),
    "trainval_clean": (RAW / "trainval_clean.xlsx", 0),
}


def q(s: pd.Series) -> dict:
    a = pd.to_numeric(s, errors="coerce").to_numpy(dtype=float)
    a = a[np.isfinite(a)]
    out = {"count": int(len(a))}
    if len(a):
        for k, v in zip(
            ["min", "p05", "p25", "p50", "p75", "p95", "max"],
            np.quantile(a, [0, 0.05, 0.25, 0.5, 0.75, 0.95, 1]),
        ):
            out[k] = round(float(v), 6)
        out["mean"] = round(float(a.mean()), 6)
        out["std"] = round(float(a.std()), 6)
    return out


def haversine_m(lat1, lon1, lat2, lon2) -> np.ndarray:
    r = 6371000.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(lon2) - np.radians(lon1)
    h = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(h))


def auroc(labels: np.ndarray, scores: np.ndarray) -> float:
    pos, neg = scores[labels == 1], scores[labels == 0]
    if not len(pos) or not len(neg):
        return float("nan")
    return float((pos[:, None] > neg).mean() + 0.5 * (pos[:, None] == neg).mean())


def run() -> dict:
    frames = []
    for name, (path, label) in FILES.items():
        df = pd.read_excel(path)
        df["__src"] = name
        df["__label"] = label
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)

    # u-blox integer scaling: values ~4e8 are deg*1e7
    for col in ("lat", "lon"):
        v = pd.to_numeric(df[col], errors="coerce")
        if v.abs().median() > 1000:
            df[col] = v / 1e7
    for col in ("alt", "alt_ellipsoid"):
        v = pd.to_numeric(df[col], errors="coerce")
        if v.abs().median() > 100000:
            df[col] = v / 1000.0

    vel = pd.to_numeric(df["vel_m_s"], errors="coerce").to_numpy(dtype=float)
    dt = pd.to_numeric(df["timestamp_time_relative"], errors="coerce").to_numpy(dtype=float)
    lat = pd.to_numeric(df["lat"], errors="coerce").to_numpy(dtype=float)
    lon = pd.to_numeric(df["lon"], errors="coerce").to_numpy(dtype=float)

    # consecutive deltas within each source file (row order = log order)
    pos_delta, speed_jump, implied_speed = (
        np.full(len(df), np.nan),
        np.full(len(df), np.nan),
        np.full(len(df), np.nan),
    )
    for name in FILES:
        idx = np.where((df["__src"] == name).to_numpy())[0]
        if len(idx) < 2:
            continue
        la, lo = lat[idx], lon[idx]
        d = haversine_m(la[:-1], lo[:-1], la[1:], lo[1:])
        pos_delta[idx[1:]] = d
        speed_jump[idx[1:]] = np.abs(np.diff(vel[idx]))
        step_t = np.diff(dt[idx])
        step_t[~np.isfinite(step_t) | (step_t <= 0)] = np.nan
        implied_speed[idx[1:]] = d / step_t

    df["pos_delta_m"] = pos_delta
    df["speed_jump_m_s"] = speed_jump
    df["implied_speed_m_s"] = implied_speed
    labels = df["__label"].to_numpy()

    feats = [
        "vel_m_s",
        "speed_jump_m_s",
        "pos_delta_m",
        "implied_speed_m_s",
        "eph",
        "epv",
        "hdop",
        "vdop",
        "jamming_indicator",
        "noise_per_ms",
        "s_variance_m_s",
        "satellites_used",
        "cog_rad",
    ]
    ranges = {}
    for c in feats:
        a = df.loc[labels == 1, c]
        b = df.loc[labels == 0, c]
        ranges[c] = {"attack": q(a), "clean": q(b)}

    # single-threshold rules; higher score = more anomalous (negate where needed)
    cands = {
        "vel_m_s": 1,
        "speed_jump|Δvel|": 1,
        "pos_delta": 1,
        "eph": 1,
        "epv": 1,
        "hdop": 1,
        "vdop": 1,
        "jamming_indicator": 1,
        "jamming_indicator_neg": -1,
        "vel_m_s_neg": -1,
        "noise_per_ms": 1,
        "s_variance": 1,
        "s_variance_neg": -1,
        "satellites_used_neg": -1,
    }
    series = {
        "vel_m_s": pd.to_numeric(df["vel_m_s"], errors="coerce").to_numpy(dtype=float),
        "vel_m_s_neg": pd.to_numeric(df["vel_m_s"], errors="coerce").to_numpy(dtype=float),
        "speed_jump|Δvel|": speed_jump,
        "pos_delta": pos_delta,
        "eph": pd.to_numeric(df["eph"], errors="coerce").to_numpy(dtype=float),
        "epv": pd.to_numeric(df["epv"], errors="coerce").to_numpy(dtype=float),
        "hdop": pd.to_numeric(df["hdop"], errors="coerce").to_numpy(dtype=float),
        "vdop": pd.to_numeric(df["vdop"], errors="coerce").to_numpy(dtype=float),
        "jamming_indicator": pd.to_numeric(df["jamming_indicator"], errors="coerce").to_numpy(dtype=float),
        "jamming_indicator_neg": pd.to_numeric(df["jamming_indicator"], errors="coerce").to_numpy(dtype=float),
        "noise_per_ms": pd.to_numeric(df["noise_per_ms"], errors="coerce").to_numpy(dtype=float),
        "s_variance": pd.to_numeric(df["s_variance_m_s"], errors="coerce").to_numpy(dtype=float),
        "s_variance_neg": pd.to_numeric(df["s_variance_m_s"], errors="coerce").to_numpy(dtype=float),
        "satellites_used_neg": pd.to_numeric(df["satellites_used"], errors="coerce").to_numpy(dtype=float),
    }
    benchmark = {}
    for name, sign in cands.items():
        s = series[name]
        ok = np.isfinite(s)
        a = auroc(labels[ok], sign * s[ok])
        benchmark[name] = {
            "auroc": round(a, 4) if np.isfinite(a) else None,
            "n_scored": int(ok.sum()),
        }
    # implied_speed unavailable: timestamp columns are constant within files
    benchmark["implied_speed"] = {"auroc": None, "n_scored": 0, "reason": "no time base; timestamps constant"}
    best = max(benchmark, key=lambda k: benchmark[k]["auroc"] if benchmark[k]["auroc"] is not None else -1)

    # ERR-05 gate check: fraction of rows above 50 m/s by class
    gate = {}
    for lab, nm in ((1, "attack"), (0, "clean")):
        v = vel[labels == lab]
        v = v[np.isfinite(v)]
        gate[nm] = {
            "n": int(len(v)),
            "max_vel_m_s": round(float(v.max()), 4) if len(v) else None,
            "frac_above_50": round(float((v > 50).mean()), 6) if len(v) else None,
        }

    report = {
        "provenance": {
            "source": "data/raw/gps_spoofing_nayfeh (no license -> EDA-ONLY)",
            "files": {k: {"rows": int((df["__src"] == k).sum()), "label": v} for k, (_, v) in FILES.items()},
            "n_pooled": int(len(df)),
            "design": "transductive pooled-row ranking; labels for evaluation only; no train/test split",
        },
        "feature_ranges_attack_vs_clean": ranges,
        "single_threshold_auroc": benchmark,
        "best_single_rule": best,
        "implausible_speed_50_gate": gate,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "profile.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(f"n={len(df)} best={best} {benchmark[best]}")
    for nm in ("jamming_indicator", "vel_m_s", "eph", "hdop", "s_variance_m_s"):
        r = ranges[nm]
        print(
            f"{nm}: attack p50={r['attack']['p50']} clean p50={r['clean']['p50']} auroc={benchmark.get(nm, benchmark.get(nm + '_neg', {}))}"
        )
    print(f"gate50={gate}")
    return report


if __name__ == "__main__":
    run()
