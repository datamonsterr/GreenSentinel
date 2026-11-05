"""Staircase chart and registry table visualizer (Issue #497 / Epic #494).

Reads docs/data/experiments/registry.jsonl and:
1. Generates docs/data/experiments/staircase.svg and staircase.png using matplotlib.
   - Plots attempts (x) vs primary macro-F1 (y).
   - Every attempt as a point (kept green, reverted grey).
   - Best-so-far as a step line.
2. Updates docs/data/experiments/README.md table.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_registry(registry_path: Path) -> list[dict[str, Any]]:
    """Load rows from registry.jsonl."""
    if not registry_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with registry_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_from_attempts(attempts_dir: Path) -> list[dict[str, Any]]:
    """Load and sort attempts by attempt number from attempts directory."""
    if not attempts_dir.exists():
        return []
    rows: list[dict[str, Any]] = []
    for f in sorted(attempts_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("attempt") is not None:
                rows.append(data)
        except Exception:
            continue
    rows.sort(key=lambda r: int(r["attempt"]))
    return rows


def load_rows(registry_path: Path | None = None, attempts_dir: Path | None = None) -> list[dict[str, Any]]:
    """Load rows from attempts folder (if available) or registry.jsonl."""
    if attempts_dir and attempts_dir.exists():
        attempts_rows = load_from_attempts(attempts_dir)
        if attempts_rows:
            if registry_path:
                from scripts.benchmark.experiments.compare import build_registry_from_attempts

                build_registry_from_attempts(attempts_dir, registry_path)
            return attempts_rows
    if registry_path and registry_path.exists():
        return load_registry(registry_path)
    return []


def plot_staircase(rows: list[dict[str, Any]], out_svg: Path, out_png: Path) -> None:
    """Render staircase step plot and scatter points."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_svg.parent.mkdir(parents=True, exist_ok=True)
    out_png.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(10, 6), dpi=150)

    if not rows:
        ax.text(
            0.5,
            0.5,
            "No experiment attempts recorded in registry.jsonl yet.",
            ha="center",
            va="center",
            fontsize=12,
            color="#6b7280",
        )
        ax.set_axis_off()
        fig.tight_layout()
        fig.savefig(out_svg, format="svg")
        fig.savefig(out_png, format="png")
        plt.close(fig)
        return

    attempts = [r["attempt"] for r in rows]
    primaries = [r["primary"] for r in rows]
    bests = [r["best_so_far"] for r in rows]

    # Best-so-far step line
    ax.step(
        attempts,
        bests,
        where="post",
        color="#2563eb",
        linewidth=2.5,
        label="Best so far",
        zorder=2,
    )

    # Kept attempts
    kept = [r for r in rows if r["decision"] == "keep"]
    if kept:
        kx = [r["attempt"] for r in kept]
        ky = [r["primary"] for r in kept]
        ax.scatter(
            kx,
            ky,
            color="#16a34a",
            edgecolors="#14532d",
            s=90,
            label="Kept (Promoted)",
            zorder=4,
        )

    # Reverted attempts
    reverted = [r for r in rows if r["decision"] == "revert"]
    if reverted:
        rx = [r["attempt"] for r in reverted]
        ry = [r["primary"] for r in reverted]
        ax.scatter(
            rx,
            ry,
            color="#9ca3af",
            edgecolors="#4b5563",
            s=70,
            label="Reverted",
            zorder=3,
        )

    # Annotate variant names
    for r in rows:
        label_text = f"{r.get('exp_id', '')} ({r.get('variant', '')})"
        ax.annotate(
            label_text,
            (r["attempt"], r["primary"]),
            textcoords="offset points",
            xytext=(0, 8),
            ha="center",
            fontsize=8,
            color="#1f2937",
        )

    ax.set_title(
        "Trip-Fraud Classifier Research Staircase (Epic #494)",
        fontsize=14,
        fontweight="bold",
        pad=14,
    )
    ax.set_xlabel("Attempt Number", fontsize=11, labelpad=8)
    ax.set_ylabel("Primary Metric: Macro-F1 (Enum-Blind, 7 Classes)", fontsize=11, labelpad=8)
    ax.set_xticks(attempts)
    ax.grid(True, linestyle="--", alpha=0.5, zorder=1)
    ax.legend(loc="lower right", framealpha=0.9)

    # Bounds
    min_y = min(primaries + bests)
    max_y = max(primaries + bests)
    pad_y = max(0.05, (max_y - min_y) * 0.2)
    ax.set_ylim(max(0.0, min_y - pad_y), min(1.02, max_y + pad_y))

    fig.tight_layout()
    fig.savefig(out_svg, format="svg")
    fig.savefig(out_png, format="png")
    plt.close(fig)


def render_markdown_table(rows: list[dict[str, Any]], out_md: Path) -> None:
    """Generate Markdown summary table of registry attempts."""
    out_md.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        "# Classifier Research Registry & Staircase",
        "",
        "Tracking the keep-or-revert research loop for the trip-fraud classifier per [Epic #494](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/494).",
        "",
        "## Staircase Progress",
        "",
        "![Staircase Chart](staircase.png)",
        "",
        "## Decision Rule",
        "",
        "A candidate is **KEPT** if and only if:",
        "1. Primary metric (Macro-F1, enum-blind, 7 classes) improves by more than the paired-bootstrap 95% CI half-width on the same validation trips.",
        "2. All guard criteria hold:",
        "   - True `no_violation` FPR <= best + 0.005",
        "   - Adverse recall at top 5% alert budget >= best - 0.01",
        "   - No class PR-AUC drops by > 0.03",
        "   - ECE (10-bin) <= best + 0.02",
        "",
        "Otherwise, the candidate is **REVERTED**.",
        "",
        "## Registry Log",
        "",
        "| Attempt | Exp ID | Variant | Issue | PR | Primary (Macro-F1) | 95% CI | Guards | Decision | Best so far | Date |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]

    for r in rows:
        ci_str = f"[{r['ci'][0]:.4f}, {r['ci'][1]:.4f}]" if "ci" in r and r["ci"] else "N/A"
        guards_obj = r.get("guards") or {}
        guards_status = "PASS" if guards_obj.get("all_passed", True) else "FAIL"
        decision_bold = f"**{r['decision'].upper()}**"
        lines.append(
            f"| {r['attempt']} | {r['exp_id']} | {r['variant']} | {r.get('issue', '')} | {r.get('pr', '')} | "
            f"{r['primary']:.4f} | {ci_str} | {guards_status} | {decision_bold} | {r['best_so_far']:.4f} | {r.get('date', '')} |"
        )

    lines.append("")
    out_md.write_text("\n".join(lines), encoding="utf-8")


def build_staircase(
    registry_path: Path,
    out_svg: Path,
    out_png: Path,
    out_md: Path,
    attempts_dir: Path | None = None,
) -> None:
    """Build all staircase artifacts (SVG, PNG, and README.md)."""
    rows = load_rows(registry_path=registry_path, attempts_dir=attempts_dir)
    plot_staircase(rows, out_svg, out_png)
    render_markdown_table(rows, out_md)


def main():
    parser = argparse.ArgumentParser(description="GreenSentinel Staircase Generator")
    parser.add_argument(
        "--attempts-dir",
        type=Path,
        default=Path("docs/data/experiments/attempts"),
        help="Path to attempts directory",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("docs/data/experiments/registry.jsonl"),
        help="Path to registry.jsonl",
    )
    parser.add_argument(
        "--out-svg",
        type=Path,
        default=Path("docs/data/experiments/staircase.svg"),
        help="Path for output SVG",
    )
    parser.add_argument(
        "--out-png",
        type=Path,
        default=Path("docs/data/experiments/staircase.png"),
        help="Path for output PNG",
    )
    parser.add_argument(
        "--out-md",
        type=Path,
        default=Path("docs/data/experiments/README.md"),
        help="Path for output Markdown table",
    )

    args = parser.parse_args()
    build_staircase(args.registry, args.out_svg, args.out_png, args.out_md, attempts_dir=args.attempts_dir)
    print(f"Staircase generated: {args.out_svg}, {args.out_png}, {args.out_md}")


if __name__ == "__main__":
    main()
