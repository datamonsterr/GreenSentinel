"""Reproducible MiPo AiSq10D geometry profile; no CRS/time assumptions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import time
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REVISION = "70a9b0140f94a1d3e2349999c621392c18c439fc"
BASE = f"https://raw.githubusercontent.com/TimeIsAFriend/trajectory_MiPo/{REVISION}/dataset/AiSq10D/"
SEED = 63


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(path: Path) -> list[list[list[float]]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def stage(normal: Path, outlier: Path) -> None:
    """Select 500 trajectory rows; retain neither complete downloaded source in Git."""
    target = ROOT / "data/mipo"
    target.mkdir(parents=True, exist_ok=True)
    records, sources = [], []
    rng = np.random.default_rng(SEED)
    for path, label, count, name in [(normal, 0, 450, "inners.txt"), (outlier, 1, 50, "outliers.txt")]:
        rows = load(path)
        sources.append(
            {
                "url": BASE + name,
                "sha256": digest(path.read_bytes()),
                "bytes": path.stat().st_size,
                "source_rows": len(rows),
                "label": label,
            }
        )
        indices = sorted(rng.choice(len(rows), min(count, len(rows)), replace=False).tolist())
        records.extend({"source_row": i, "label": label, "xy": rows[i]} for i in indices)
    content = "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in records)
    if len(content.encode()) >= 5_000_000 or len(records) > 500:
        raise ValueError("Staged slice exceeds 500 rows / 5 MB")
    (target / "sample.jsonl").write_text(content)
    manifest = {
        "revision": REVISION,
        "seed": SEED,
        "sources": sources,
        "sample_rows": len(records),
        "sample_bytes": len(content.encode()),
        "sample_sha256": digest(content.encode()),
        "sampling": "450 normal + 50 outlier without replacement",
        "crs": "unknown XY coordinate system and units; do not interpret as lon/lat",
        "license": "No license file in author repository at pinned revision; redistribution rights unresolved",
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def download_sources() -> tuple[Path, Path]:
    """Download pinned files and reject changed payloads before sampling."""
    import tempfile

    directory = Path(tempfile.mkdtemp(prefix="p063-mipo-"))
    expected = {
        "inners.txt": "578ed166d40affa6c7cae819622b967fa2aecacddf7caae8a16dd388f172684d",
        "outliers.txt": "88341797b61d1db8171f6a840e9e72e284c652b8909ccbad30b0fa5a9c1d07a9",
    }
    for name, checksum in expected.items():
        with urllib.request.urlopen(BASE + name, timeout=60) as response:
            payload = response.read(5_000_000)
        if digest(payload) != checksum:
            raise ValueError(f"Source checksum mismatch: {name}")
        (directory / name).write_bytes(payload)
    return directory / "inners.txt", directory / "outliers.txt"


def histograms(matrix: np.ndarray, names: list[str], labels: np.ndarray) -> str:
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="1000">',
        '<rect width="1000" height="1000" fill="white"/>',
    ]
    for i, name in enumerate(names):
        x, y = (i % 2) * 500 + 30, (i // 2) * 250 + 30
        bins = np.linspace(matrix[:, i].min(), matrix[:, i].max() + 1e-12, 21)
        counts = [np.histogram(matrix[labels == label, i], bins=bins)[0] for label in [0, 1]]
        maximum = max(counts[0].max(), counts[1].max(), 1)
        parts.append(f'<text x="{x}" y="{y}">{name}: counts (blue normal; red outlier)</text>')
        for label, color in [(0, "#2563eb"), (1, "#dc2626")]:
            for j, value in enumerate(counts[label]):
                height = float(value) / maximum * 160
                parts.append(
                    f'<rect x="{x + j * 21 + label * 9}" y="{y + 180 - height}" width="9" height="{height}" fill="{color}"/>'
                )
        parts.append(f'<text x="{x}" y="{y + 202}">{bins[0]:.3g} to {bins[-1]:.3g}; max bin count {maximum}</text>')
    return "\n".join(parts + ["</svg>"])


def describe(values: Any) -> dict[str, float | int]:
    a = np.asarray(values, dtype=float)
    finite = a[np.isfinite(a)]
    result: dict[str, float | int] = {"count": len(a), "nonfinite": int(len(a) - len(finite))}
    if len(finite):
        result.update(
            {
                k: float(v)
                for k, v in zip(
                    ["min", "p05", "p25", "p50", "p75", "p95", "max"],
                    np.quantile(finite, [0, 0.05, 0.25, 0.5, 0.75, 0.95, 1]),
                )
            }
        )
        result.update(mean=float(finite.mean()), std=float(finite.std()))
    return result


def geometry(row: dict[str, Any]) -> dict[str, float]:
    p = np.asarray(row["xy"], dtype=float)
    if p.ndim != 2 or p.shape[1] != 2 or len(p) < 2 or not np.isfinite(p).all():
        raise ValueError("Expected finite Nx2 trajectory with at least two points")
    d = np.diff(p, axis=0)
    steps = np.linalg.norm(d, axis=1)
    direct = float(np.linalg.norm(p[-1] - p[0]))
    valid = (steps[:-1] > 0) & (steps[1:] > 0)
    angles = np.arccos(
        np.clip(np.sum(d[:-1][valid] * d[1:][valid], axis=1) / (steps[:-1][valid] * steps[1:][valid]), -1, 1)
    )
    return {
        "points": len(p),
        "length_xy": float(steps.sum()),
        "endpoint_distance_xy": direct,
        "tortuosity": float(steps.sum() / direct) if direct else float("nan"),
        "step_p50_xy": float(np.median(steps)),
        "step_max_xy": float(steps.max()),
        "zero_step_fraction": float((steps == 0).mean()),
        "turn_mean_rad": float(angles.mean()) if len(angles) else 0.0,
    }


def lof_scores(features: np.ndarray, k: int = 20) -> np.ndarray:
    """Transductive Euclidean LOF with exactly k neighbors; deterministic index ties."""
    x = (features - features.mean(axis=0)) / np.where(features.std(axis=0) > 0, features.std(axis=0), 1)
    distance = np.linalg.norm(x[:, None, :] - x[None, :, :], axis=2)
    np.fill_diagonal(distance, np.inf)
    neighbors = np.argsort(distance, axis=1, kind="stable")[:, :k]
    kth = np.take_along_axis(distance, neighbors, axis=1)[:, -1]
    reachability = np.maximum(np.take_along_axis(distance, neighbors, axis=1), kth[neighbors])
    density = 1 / np.maximum(reachability.mean(axis=1), 1e-12)
    return (density[neighbors] / density[:, None]).mean(axis=1)


def evaluate(labels: np.ndarray, scores: np.ndarray) -> dict[str, float]:
    positive, negative = scores[labels == 1], scores[labels == 0]
    if not len(positive) or not len(negative):
        return {"auroc": float("nan"), "average_precision": float("nan")}
    auroc = float((positive[:, None] > negative).mean() + 0.5 * (positive[:, None] == negative).mean())
    # Average precision groups ties at a common threshold (order invariant).
    ap, previous_recall = 0.0, 0.0
    for threshold in np.unique(scores)[::-1]:
        selected = scores >= threshold
        tp = int(labels[selected].sum())
        recall = tp / len(positive)
        ap += (recall - previous_recall) * tp / int(selected.sum())
        previous_recall = recall
    return {"auroc": auroc, "average_precision": float(ap)}


def measure(action: Any, repeats: int = 7) -> dict[str, float | int]:
    action()  # one warm-up; exclude first invocation
    values = []
    for _ in range(repeats):
        started = time.perf_counter()
        action()
        values.append(time.perf_counter() - started)
    return {
        "repeats": repeats,
        "median_ms": float(np.median(values) * 1000),
        "min_ms": min(values) * 1000,
        "max_ms": max(values) * 1000,
    }


def render_svg(records: list[dict[str, Any]]) -> str:
    """Planar overlays with source units; deliberately no geographic basemap."""
    chosen = [r for label in [0, 1] for r in [x for x in records if x["label"] == label][:12]]
    points = np.concatenate([r["xy"] for r in chosen])
    lo, hi = points.min(axis=0), points.max(axis=0)
    pieces = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="850" height="600" viewBox="0 0 850 600">',
        '<rect width="850" height="600" fill="white"/>',
        '<text x="20" y="25">MiPo AiSq10D: planar XY; CRS/units unknown (blue normal, red injected)</text>',
    ]
    for r in chosen:
        xy = (np.asarray(r["xy"]) - lo) / np.maximum(hi - lo, 1) * [790, 510]
        coords = " ".join(f"{x + 30:.2f},{560 - y:.2f}" for x, y in xy)
        color = "#dc2626" if r["label"] else "#2563eb"
        pieces.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-opacity="0.45"/>')
    return "\n".join(pieces + ["</svg>"])


def run() -> dict[str, Any]:
    sample = ROOT / "data/mipo/sample.jsonl"
    manifest = json.loads((sample.parent / "manifest.json").read_text())
    if digest(sample.read_bytes()) != manifest["sample_sha256"]:
        raise ValueError("Sample checksum mismatch")
    records = [json.loads(line) for line in sample.read_text().splitlines()]
    features = [geometry(row) for row in records]
    names = list(features[0])
    matrix = np.array([[row[name] for name in names] for row in features])
    labels = np.array([row["label"] for row in records])
    points = np.concatenate([row["xy"] for row in records])
    steps = np.concatenate([np.linalg.norm(np.diff(row["xy"], axis=0), axis=1) for row in records])
    hashes = [digest(json.dumps(row["xy"]).encode()) for row in records]
    report: dict[str, Any] = {
        "provenance": manifest,
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "platform": platform.platform(),
            "logical_cpus": os.cpu_count(),
        },
        "rows": len(records),
        "points": len(points),
        "normal": int((labels == 0).sum()),
        "outliers": int((labels == 1).sum()),
        "exact_duplicate_trajectories": len(hashes) - len(set(hashes)),
        "coordinate_nonfinite": int((~np.isfinite(points)).sum()),
        "invalid_if_interpreted_lonlat": int(((abs(points[:, 0]) > 180) | (abs(points[:, 1]) > 90)).sum()),
        "coordinate_x": describe(points[:, 0]),
        "coordinate_y": describe(points[:, 1]),
        "segment_length_xy": describe(steps),
        "zero_segments": int((steps == 0).sum()),
        "distributions": {name: describe(matrix[:, i]) for i, name in enumerate(names)},
        "by_label": {
            str(label): {name: describe(matrix[labels == label, i]) for i, name in enumerate(names)} for label in [0, 1]
        },
        "benchmark": {
            "design": "Descriptive transductive scoring on same 500-row slice; no train/test claim",
            "prevalence_ap_baseline": float(labels.mean()),
            "tortuosity": evaluate(labels, matrix[:, names.index("tortuosity")]),
            "geometry_lof_k20": evaluate(labels, lof_scores(matrix)),
            "ingestion": measure(lambda: [json.loads(line) for line in sample.read_text().splitlines()]),
            "feature_extraction": measure(lambda: [geometry(row) for row in records]),
            "lof_fit_score": measure(lambda: lof_scores(matrix)),
        },
    }
    cpu = Path("/proc/cpuinfo")
    if cpu.exists():
        report["environment"]["cpu_model"] = next(
            (x.split(":", 1)[1].strip() for x in cpu.read_text().splitlines() if x.startswith("model name")), "unknown"
        )
    output = ROOT / "notebooks/mipo"
    output.mkdir(parents=True, exist_ok=True)
    (output / "profile.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    (output / "trajectories.svg").write_text(render_svg(records))
    (output / "distributions.svg").write_text(histograms(matrix, names, labels))
    print(json.dumps({k: report[k] for k in ["rows", "points", "normal", "outliers", "benchmark"]}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--normal-source", type=Path)
    parser.add_argument("--outlier-source", type=Path)
    args = parser.parse_args()
    if args.download:
        stage(*download_sources())
    if args.normal_source and args.outlier_source:
        stage(args.normal_source, args.outlier_source)
    run()
