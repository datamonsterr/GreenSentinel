"""Jev Criteria definitions and variants (Issue #496, #547).

Provides criteria dictionaries for Jev Anomaly Assessment:
- 'semantic': (default) behaviour definitions per class, no numeric thresholds.
- 'baseline': the standard 6 single-trip fraud classes (ERR-01 to ERR-05, no_violation).
- 'risk_bands': 6 classes + 'insufficient_evidence' choice, with each criterion
  explicitly referencing normal vs high-risk numeric ranges.
"""

from __future__ import annotations

CRITERIA_SEMANTIC: dict[str, str] = {
    "ERR-01": "Driver unjustified cancellation or passenger pickup evasion without valid cause (Điều 14.1)",
    "ERR-02": "Driver prolonged stationary stall waiting out passenger to force passenger cancellation (Điều 14.2)",
    "ERR-03": "Driver intentional route detour, significant divergence, or moving away from pickup (Điều 16.1)",
    "ERR-04": "Ghost trip or fake completion without genuine passenger pickup or transport (Điều 15.1)",
    "ERR-05": "Mock location provider flag, simulated GPS coordinates, or physically impossible instant teleportation (Điều 15.3)",
    "no_violation": "Legitimate trip, normal route progression, accepted cancellation reason, or verified traffic delay",
}

CRITERIA_BASELINE: dict[str, str] = {
    "ERR-01": "Driver unjustified cancellation without valid cause (Điều 14.1)",
    "ERR-02": "Driver prolonged stationary stall >= 180s forcing passenger cancellation (Điều 14.2)",
    "ERR-03": "Driver intentional route divergence / wrong direction > 35% (Điều 16.1)",
    "ERR-04": "Ghost trip / fake completion without carrying passenger (Điều 15.1)",
    "ERR-05": "Mock location / fake GPS manipulation / teleportation (Điều 15.3)",
    "no_violation": "Nominal valid ride, traffic congestion, or technical platform issue without fraud",
}

CRITERIA_RISK_BANDS: dict[str, str] = {
    "ERR-01": "Driver unjustified cancellation without valid cause (Điều 14.1; bad-faith intent or unilateral cancellation)",
    "ERR-02": "Driver prolonged stationary stall (Điều 14.2; approach SSD >= 180s high risk, 90-179s elevated; passenger cancellation)",
    "ERR-03": "Intentional route divergence / wrong direction (Điều 16.1; detour ratio > 1.35 or > 35% high risk, 1.15-1.35 elevated; DAVI < -0.2)",
    "ERR-04": "Ghost trip / fake completion (Điều 15.1; trip completed without genuine passenger pickup, zero progress, or passenger denial)",
    "ERR-05": "Mock location / fake GPS manipulation / teleportation (Điều 15.3; teleport jump > 200 km/h high risk, 120-200 km/h elevated, or mock flag)",
    "no_violation": "Nominal valid ride (detour <= 1.15, SSD < 90s, DAVI > 0.3, normal speeds, no mock flag, no fraud)",
    "insufficient_evidence": "Insufficient telemetry evidence or technical platform dropout/outage preventing conclusive classification",
}


def get_jev_criteria(variant: str = "semantic") -> dict[str, str]:
    """Return Jev decision criteria for the given variant. Default is 'semantic'."""
    if variant == "semantic":
        return dict(CRITERIA_SEMANTIC)
    if variant == "baseline":
        return dict(CRITERIA_BASELINE)
    if variant == "risk_bands":
        return dict(CRITERIA_RISK_BANDS)
    raise ValueError(f"Unknown criteria variant: {variant}")
