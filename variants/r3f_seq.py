"""Top-level variants shortcut forwarding to scripts.benchmark.experiments.variants.r3f_seq."""

from __future__ import annotations

from scripts.benchmark.experiments.variants.r3f_seq import (
    DEFAULT_MODEL_PATH,
    get_model_path,
    predict_r3f_probabilities,
    r3f_assess_async,
    r3f_seq_variant,
)

__all__ = [
    "DEFAULT_MODEL_PATH",
    "get_model_path",
    "predict_r3f_probabilities",
    "r3f_assess_async",
    "r3f_seq_variant",
]
