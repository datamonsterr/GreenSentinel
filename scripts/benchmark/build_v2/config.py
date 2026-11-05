"""Configuration dataclass and default parameters for releases_v2 generator."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class GeneratorV2Config:
    seed: int = 20261017
    n_trips: int = 40000
    total_drivers: int = 2000
    total_passengers: int = 8000

    split_ratios: dict[str, float] = field(
        default_factory=lambda: {
            "train": 0.70,
            "validation": 0.15,
            "test": 0.15,
        }
    )

    class_mix_shares: dict[str, float] = field(
        default_factory=lambda: {
            "no_violation": 0.70,
            "ERR-01": 0.05,
            "ERR-02": 0.08,
            "ERR-03": 0.05,
            "ERR-04": 0.03,
            "ERR-05": 0.03,
            "insufficient_evidence": 0.06,
        }
    )

    prevalence_target_fraud: float = 0.01
    prevalence_target_honest: float = 0.99

    # Telemetry sampling & noise parameters calibrated to Porto, Posisi, and NYC TLC
    ping_profiles: tuple[tuple[float, float], ...] = (
        (15.0, 0.50),  # Porto-style 15s urban taxi cadence
        (5.0, 0.30),  # Medium responsiveness 5s cadence
        (1.0, 0.20),  # Posisi-style 1s high-frequency cadence
    )
    missed_ping_prob: float = 0.05
    clock_jitter_sd: float = 0.20

    # Position accuracy lognormal (mode ~9m, median ~11.6m, p95 ~26m, clip 127m)
    accuracy_lognormal_mu: float = 2.45
    accuracy_lognormal_sigma: float = 0.50
    accuracy_clip_max: float = 127.0
    accuracy_null_rate: float = 0.03

    # Urban canyon multipath outliers (50-200m)
    multipath_outlier_rate: float = 0.02
    multipath_min_m: float = 50.0
    multipath_max_m: float = 200.0

    # Device reported speed: displacement speed + small Gaussian noise, consistent with displacement
    device_speed_noise_sd: float = 0.30
    device_speed_null_rate: float = 0.05

    # Bearing noise
    bearing_noise_sd: float = 5.0

    # Urban speed calibration: Hanoi/HCMC empirical traffic (JICA Urban Transport Study, TomTom Index)
    # Typical city cruise ~20-30 km/h (5.5-8.3 m/s), arterial p95 ~60 km/h (16.7 m/s), device cap 23.6 m/s (85 km/h)
    speed_urban_avg_min_mps: float = 5.5
    speed_urban_avg_max_mps: float = 8.5
    speed_arterial_p95_mps: float = 16.7
    speed_device_cap_mps: float = 23.6

    # Downsample option (CLI --max-points)
    max_points_per_trip: int | None = None

    # Customer report presence rates (breaks 'report presence = fraud')
    customer_report_honest_rate: float = 0.18
    customer_report_fraud_rate: float = 0.45

    # Hard negatives share among honest trips
    hard_negative_share: float = 0.15

    # Mock location reported rates (mitigating perfect shortcuts)
    # Real spoofers often hide mock flag (root/Xposed); honest devices occasionally report it (dev options)
    mock_flag_err05_rate: float = 0.50
    mock_flag_honest_rate: float = 0.003

    # Driver objection presence rates across classes (mitigating objection presence shortcut)
    # Honest drivers dispute too (gridlock stalls, detours, GPS teleports, ratings); some fraud drivers never object
    driver_objection_rates: dict[str, float] = field(
        default_factory=lambda: {
            "no_violation": 0.04,  # ~3-5%
            "insufficient_evidence": 0.20,  # ~15-25%
            "ERR-01": 0.45,  # 30-60%
            "ERR-02": 0.50,  # 30-60%
            "ERR-03": 0.40,  # 30-60%
            "ERR-04": 0.35,  # 30-60%
            "ERR-05": 0.40,  # 30-60%
        }
    )

    # Release naming & metadata
    release_name: str = "releases_v2.1"
    generator_version: str = "v2.1.0-realistic"

    @property
    def mock_location_err05_rate(self) -> float:
        return self.mock_flag_err05_rate

    @property
    def mock_location_honest_rate(self) -> float:
        return self.mock_flag_honest_rate

    # Corridors file location
    corridors_path: Path = REPO_ROOT / "data" / "benchmark-10k" / "vietnam_road_corridors.json"

    def calculate_class_counts(self, n: int | None = None) -> dict[str, int]:
        total = n if n is not None else self.n_trips
        counts: dict[str, int] = {}
        allocated = 0
        sorted_classes = sorted(self.class_mix_shares.items(), key=lambda kv: kv[1], reverse=True)
        for i, (cls, share) in enumerate(sorted_classes):
            if i == len(sorted_classes) - 1:
                counts[cls] = total - allocated
            else:
                c = int(round(total * share))
                counts[cls] = c
                allocated += c
        return counts

    def calculate_prevalence_weight(self, label: str) -> float:
        """Calculate per-row weight so the test split can be reweighted to ~1% fraud.

        Fraud classes (ERR-01..ERR-05) have natural prevalence ~1%, while honest is ~99%.
        """
        fraud_classes = {"ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05"}
        total_fraud_share = sum(self.class_mix_shares.get(c, 0.0) for c in fraud_classes)
        honest_share = self.class_mix_shares.get("no_violation", 0.70)

        if label in fraud_classes:
            return round(self.prevalence_target_fraud / total_fraud_share, 6)
        elif label == "no_violation":
            return round(self.prevalence_target_honest / honest_share, 6)
        else:
            # Neutral / technical dropout
            return 1.0
