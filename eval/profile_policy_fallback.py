"""Paired CPU benchmark of actual old/new policy fallback methods; no network or DB."""

from __future__ import annotations

import argparse
import ast
import cProfile
import hashlib
import inspect
import json
import platform
import pstats
import random
import statistics
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from eval.baselines.policy_fallback_dede4b0 import SOURCE_COMMIT
from eval.baselines.policy_fallback_dede4b0 import _fallback_local_search as pinned_baseline
from src.rag import store as store_module
from src.rag.store import QdrantPolicyStore

QUERIES = ("appeal evidence review", "delivery cancellation", "policy guardrail", "driver dispute")
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = "dede4b0"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def baseline_ast_sha256(source: str) -> str:
    """Fingerprint executable AST while ignoring version-specific empty fields."""

    def canonical(value: Any) -> Any:
        if isinstance(value, ast.AST):
            fields = {
                name: canonical(child) for name, child in ast.iter_fields(value) if child is not None and child != []
            }
            return {"node": type(value).__name__, "fields": fields}
        if isinstance(value, list):
            return [canonical(child) for child in value]
        return value

    return hashlib.sha256(json.dumps(canonical(ast.parse(source).body[0]), sort_keys=True).encode()).hexdigest()


def load_baseline(ref: str = DEFAULT_BASELINE) -> Callable[..., Any]:
    """Extract the exact checked-in method, preserving its original globals/contracts."""
    if ref in {DEFAULT_BASELINE, SOURCE_COMMIT}:
        return pinned_baseline
    source = git("show", f"{ref}:src/rag/store.py")
    tree = ast.parse(source)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "QdrantPolicyStore")
    function = next(
        node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "_fallback_local_search"
    )
    namespace = dict(vars(store_module))
    exec(compile(ast.Module(body=[function], type_ignores=[]), f"baseline:{ref}", "exec"), namespace)
    return namespace["_fallback_local_search"]


def dataset_fingerprint() -> dict[str, str]:
    manifest = ROOT / "data/processed/manifest.json"
    files = [manifest]
    for item in json.loads(manifest.read_text(encoding="utf-8")):
        path = manifest.parent / f"{item.get('slug')}.md"
        if path.is_file():
            files.append(path)
    return {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for path in sorted(set(files))
    }


def profile(function: Callable[..., Any], store: QdrantPolicyStore) -> list[dict[str, Any]]:
    profiler = cProfile.Profile()
    profiler.enable()
    for query in QUERIES:
        function(store, query, top_k=4)
    profiler.disable()
    entries: dict[tuple[str, int, str], Any] = getattr(pstats.Stats(profiler), "stats")
    relevant = [
        (key, value) for key, value in entries.items() if key[2] in {"escape", "search", "_compile", "read_text"}
    ]
    return [
        {"function": key[2], "calls": value[1], "own_seconds": value[2], "cumulative_seconds": value[3]}
        for key, value in sorted(relevant, key=lambda entry: entry[1][3], reverse=True)
    ]


def run(repeats: int = 60, ref: str = DEFAULT_BASELINE) -> dict[str, Any]:
    if repeats < 2:
        raise ValueError("at least two pairs required")
    before = load_baseline(ref)
    after = QdrantPolicyStore._fallback_local_search
    store = QdrantPolicyStore.__new__(QdrantPolicyStore)
    versions = dataset_fingerprint()
    # Compare complete dictionaries, including ordering, content, source metadata and scores.
    for query in QUERIES:
        if before(store, query, top_k=4) != after(store, query, top_k=4):
            raise AssertionError(f"functional regression for query {query!r}")
    for function in (before, after):
        for query in QUERIES:
            function(store, query, top_k=4)
    samples: dict[str, list[float]] = {"baseline": [], "candidate": []}
    for pair in range(repeats):
        order = [("baseline", before), ("candidate", after)]
        if pair % 2:
            order.reverse()
        for name, function in order:
            start = time.perf_counter_ns()
            for query in QUERIES:
                function(store, query, top_k=4)
            samples[name].append((time.perf_counter_ns() - start) / 1e6)
    if versions != dataset_fingerprint():
        raise ValueError("policy corpus changed during paired measurement")
    delta = [candidate - baseline for baseline, candidate in zip(samples["baseline"], samples["candidate"])]
    rng = random.Random(69)
    resampled = sorted(statistics.mean(rng.choices(delta, k=repeats)) for _ in range(2000))
    means = {name: statistics.mean(values) for name, values in samples.items()}
    return {
        "benchmark": "policy-fallback-cpu-v1",
        "scope": "local repository-document microbenchmark; no model, DB, hosted or human MTTR evidence",
        "baseline_commit": SOURCE_COMMIT if ref in {DEFAULT_BASELINE, SOURCE_COMMIT} else git("rev-parse", ref),
        "candidate_parent_commit": git("rev-parse", "HEAD"),
        "candidate_method_sha256": hashlib.sha256(inspect.getsource(after).encode()).hexdigest(),
        "dataset_files_sha256": versions,
        "dataset_sha256": hashlib.sha256(json.dumps(versions, sort_keys=True).encode()).hexdigest(),
        "query_ids": {f"policy-{i + 1:02d}": query for i, query in enumerate(QUERIES)},
        "repeats": repeats,
        "baseline_mean_ms": means["baseline"],
        "candidate_mean_ms": means["candidate"],
        "speedup_percent": (means["baseline"] - means["candidate"]) / means["baseline"] * 100,
        "paired_delta_mean_ms": statistics.mean(delta),
        "paired_delta_bootstrap95_ms": [resampled[49], resampled[1949]],
        "uncertainty": "2000 seeded paired resamples; alternating order with warm-up; local scheduler/cache variance, four queries only",
        "functional_regressions": [],
        "complete_result_equality": True,
        "hotspots": {"baseline": profile(before, store), "candidate": profile(after, store)},
        "samples_ms": samples,
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", default=DEFAULT_BASELINE)
    parser.add_argument("--repeats", type=int, default=60)
    parser.add_argument("--output", type=Path, default=Path("docs/testing/artifacts/issue69/policy_profile.json"))
    args = parser.parse_args()
    result = run(args.repeats, args.baseline_ref)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "baseline_mean_ms",
                    "candidate_mean_ms",
                    "speedup_percent",
                    "paired_delta_bootstrap95_ms",
                    "complete_result_equality",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
