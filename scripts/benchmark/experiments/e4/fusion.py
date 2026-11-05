"""Log-linear probability fusion and abstention for Experiment E4 (Issue #513 / Epic #494)."""

from __future__ import annotations

import math
from collections.abc import Sequence

DEFAULT_CLASSES: list[str] = [
    "no_violation",
    "ERR-01",
    "ERR-02",
    "ERR-03",
    "ERR-04",
    "ERR-05",
    "insufficient_evidence",
]


def blend_log_linear(
    p_gbm: dict[str, float],
    p_llm: dict[str, float],
    weight_gbm: float = 0.5,
    classes: Sequence[str] | None = None,
    eps: float = 1e-6,
) -> dict[str, float]:
    """Weighted log-linear blend (geometric opinion pool) of calibrated probability distributions.

    p_fused(c) ~ (p_gbm(c) + eps)^w * (p_llm(c) + eps)^(1 - w)
    Normalized so sum(p_fused) == 1.0.
    """
    if classes is None:
        classes = DEFAULT_CLASSES

    w = max(0.0, min(1.0, float(weight_gbm)))
    raw_scores: dict[str, float] = {}

    for c in classes:
        prob_g = max(float(p_gbm.get(c, 0.0)), eps)
        prob_l = max(float(p_llm.get(c, 0.0)), eps)
        # Log-linear combination
        log_score = w * math.log(prob_g) + (1.0 - w) * math.log(prob_l)
        raw_scores[c] = math.exp(log_score)

    total = sum(raw_scores.values())
    if total <= 0.0 or not math.isfinite(total):
        # Uniform fallback
        u = 1.0 / len(classes)
        return {c: u for c in classes}

    return {c: round(score / total, 6) for c, score in raw_scores.items()}


def predict_with_abstention(
    probs: dict[str, float],
    threshold: float = 0.35,
    abstain_class: str = "insufficient_evidence",
) -> tuple[str, float]:
    """Predict top category with abstention if maximum calibrated probability < threshold.

    When max probability < threshold, returns (abstain_class, max_prob).
    Otherwise returns (top_class, max_prob).
    """
    if not probs:
        return abstain_class, 0.0

    best_class, max_prob = max(probs.items(), key=lambda kv: kv[1])
    if max_prob < threshold:
        return abstain_class, round(max_prob, 4)

    return best_class, round(max_prob, 4)
