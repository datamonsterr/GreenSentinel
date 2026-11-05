"""Clean, leak-audited feature extraction for Experiment R3C (Issue #546 / Epic #494).

Re-exports core feature extraction logic from src.services.fraud_classifier.features_tabular
to maintain a single source of truth across research and production.
"""

from __future__ import annotations

from src.services.fraud_classifier.features_tabular import (
    CANDIDATE_FEATURE_NAMES,
    FEATURE_NAMES,
    calculate_bearing_deg,
    extract_candidate_features,
    extract_features,
    haversine_distance_m,
)

__all__ = [
    "CANDIDATE_FEATURE_NAMES",
    "FEATURE_NAMES",
    "calculate_bearing_deg",
    "extract_candidate_features",
    "extract_features",
    "haversine_distance_m",
]
