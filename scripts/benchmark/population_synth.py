"""Benchmark population synthesizer (issue #253).

Seeded deterministic synthesis of benchmark driver/passenger populations and
per-driver analytics windows. All randomness flows from a caller-supplied
``random.Random`` instance; no global RNG, clock, or I/O is touched.

Every numeric parameter below is a documented demo assumption: public
ride-hailing sources publish no honest-vs-fraud driver distributions
(docs/data/RIDE_HAILING_RESEARCH.md section 3). Each constant carries an
``[ASSUMPTION]`` tag so calibration work can find and replace it.

Deferred-scope note: driver-passenger pair counters and per-driver baseline
deviations (RIDE_HAILING_RESEARCH.md section 2, signals 7-8) are NOT detector
features here. Analytics windows below are trip-attached metadata only.
"""

from __future__ import annotations

import math
import random
import uuid
from typing import Any

GENERATOR_VERSION = "v1"

PROVENANCE: dict[str, Any] = {"synthetic": True, "generator": "population_synth", "version": GENERATOR_VERSION}

BENCHMARK_ORG_ID = "018f2f4e-b000-7000-8000-000000000001"

# --- Population parameters ([ASSUMPTION] = demo value, no public distribution) ---
FRAUD_SHARE_DEFAULT = 0.12  # [ASSUMPTION] latent fraud-prone driver share
PARTNER_MIX = (("fleet", 0.45), ("owner_driver", 0.40), ("rent_to_own", 0.15))  # [ASSUMPTION] partner-type mix
RATING_MEAN = 4.6  # [ASSUMPTION] truncated-normal mean
RATING_SD = 0.3  # [ASSUMPTION] truncated-normal sd
RATING_FLOOR = 3.0  # per spec: floor 3.0
RATING_CAP = 5.0  # DB check constraint rating <= 5.0
TENURE_LOG_MEAN = math.log(400)  # [ASSUMPTION] lognormal-ish tenure, median ~400d
TENURE_LOG_SD = 0.7  # [ASSUMPTION] lognormal-ish tenure spread
TENURE_MIN_DAYS = 7  # [ASSUMPTION] minimum tenure
TENURE_MAX_DAYS = 2500  # [ASSUMPTION] maximum tenure
TRIPS_PER_DAY_MEAN = 8.0  # [ASSUMPTION] mean daily trip rate
TRIPS_PER_DAY_SD = 2.0  # [ASSUMPTION] daily trip rate spread
BASE_CANCEL_RATE_MEAN = 0.02  # [ASSUMPTION] honest prior cancellation rate mean
BASE_CANCEL_RATE_SD = 0.01  # [ASSUMPTION] honest prior cancellation rate spread
FRAUD_CANCEL_MULT_LO = 2.0  # per spec: fraud prior 2-4x honest
FRAUD_CANCEL_MULT_HI = 4.0  # per spec: fraud prior 2-4x honest
SANCTIONS_LAMBDA_HONEST = 0.05  # [ASSUMPTION] honest prior sanctions Poisson lambda
SANCTIONS_LAMBDA_FRAUD = 0.8  # [ASSUMPTION] fraud-prone prior sanctions Poisson lambda
BASE_COMPLAINT_RATE_MEAN = 0.01  # [ASSUMPTION] honest complaint rate mean
BASE_COMPLAINT_RATE_SD = 0.005  # [ASSUMPTION] honest complaint rate spread
FRAUD_COMPLAINT_MULT = 3.0  # [ASSUMPTION] fraud complaint-rate multiplier
ACCEPT_RATE_MEAN = 92.0  # [ASSUMPTION] acceptance rate mean (percent)
ACCEPT_RATE_SD = 4.0  # [ASSUMPTION] acceptance rate spread

# Exact app.drivers column set (0001_poc_core + 20260923181144 + 20260926130000).
DRIVER_COLUMNS = frozenset(
    {
        "id",
        "organization_id",
        "principal_id",
        "external_ref",
        "partner_type",
        "account_status",
        "is_synthetic",
        "created_at",
        "display_name",
        "birth_date",
        "profile_provenance",
        "avatar_url",
        "rating",
        "acceptance_rate",
        "cancellation_rate",
        "total_trips",
    }
)

# Exact app.passengers column set (0001_poc_core).
PASSENGER_COLUMNS = frozenset({"id", "organization_id", "principal_id", "external_ref", "is_synthetic", "created_at"})

# Vietnamese name pools, same style as scripts/generate_synthetic_data.py.
_FAMILY = ["Nguyen", "Tran", "Le", "Pham", "Hoang", "Vu", "Phan", "Bui", "Do", "Dang"]
_MID = ["Van", "Thi", "Minh", "Thu", "Ngoc", "Duc", "Thanh", "Quang", "Gia", "Hai"]
_GIVEN = ["An", "Binh", "Chau", "Dung", "Hanh", "Khoa", "Linh", "Mai", "Nam", "Phuc"]


def _det_uuid(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def _poisson(rng: random.Random, lam: float) -> int:
    """Knuth Poisson sampler driven only by rng (small-lambda regime)."""
    threshold = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= threshold:
            return k - 1


def _truncated_rating(rng: random.Random) -> float:
    for _ in range(100):
        v = rng.gauss(RATING_MEAN, RATING_SD)
        if RATING_FLOOR <= v <= RATING_CAP:
            return round(v, 2)
    return round(min(max(rng.gauss(RATING_MEAN, RATING_SD), RATING_FLOOR), RATING_CAP), 2)


def _partner_type(rng: random.Random) -> str:
    roll = rng.random()
    cutoff = 0.0
    for name, weight in PARTNER_MIX:
        cutoff += weight
        if roll < cutoff:
            return name
    return PARTNER_MIX[-1][0]


def synthesize_drivers(rng: random.Random, n: int, *, fraud_share: float = FRAUD_SHARE_DEFAULT) -> list[dict[str, Any]]:
    """Synthesize n driver dicts with exact app.drivers column keys.

    Latent ``fraud_propensity`` (~fraud_share) and non-column attributes
    (tenure_days, priors) live inside ``profile_provenance``; ``birth_date``
    stays None (unused PII).
    """
    drivers: list[dict[str, Any]] = []
    for i in range(n):
        fraud_prone = rng.random() < fraud_share
        tenure_days = int(
            min(max(math.exp(rng.gauss(TENURE_LOG_MEAN, TENURE_LOG_SD)), TENURE_MIN_DAYS), TENURE_MAX_DAYS)
        )
        trips_per_day = max(1.0, rng.gauss(TRIPS_PER_DAY_MEAN, TRIPS_PER_DAY_SD))
        total_trips = int(tenure_days * trips_per_day)
        base_cancel = min(max(rng.gauss(BASE_CANCEL_RATE_MEAN, BASE_CANCEL_RATE_SD), 0.002), 0.08)
        if fraud_prone:
            prior_cancel = base_cancel * rng.uniform(FRAUD_CANCEL_MULT_LO, FRAUD_CANCEL_MULT_HI)
        else:
            prior_cancel = base_cancel
        prior_sanctions = _poisson(rng, SANCTIONS_LAMBDA_FRAUD if fraud_prone else SANCTIONS_LAMBDA_HONEST)
        base_complaint = max(0.001, rng.gauss(BASE_COMPLAINT_RATE_MEAN, BASE_COMPLAINT_RATE_SD))
        complaint_rate = base_complaint * (FRAUD_COMPLAINT_MULT if fraud_prone else 1.0)
        rating = _truncated_rating(rng)
        acceptance = round(min(max(rng.gauss(ACCEPT_RATE_MEAN, ACCEPT_RATE_SD), 50.0), 100.0), 1)
        name = f"{rng.choice(_FAMILY)} {rng.choice(_MID)} {rng.choice(_GIVEN)}"
        external_ref = f"drv_bm_{i + 1:04d}"
        provenance: dict[str, Any] = {
            **PROVENANCE,
            "tenure_days": tenure_days,
            "fraud_propensity": fraud_prone,
            "prior_cancellation_rate": round(prior_cancel, 4),
            "prior_sanctions_count": prior_sanctions,
            "complaint_rate": round(complaint_rate, 4),
        }
        drivers.append(
            {
                "id": _det_uuid(rng),
                "organization_id": BENCHMARK_ORG_ID,
                "principal_id": None,
                "external_ref": external_ref,
                "partner_type": _partner_type(rng),
                "account_status": "active",
                "is_synthetic": True,
                "created_at": "2026-09-22T06:00:00+00:00",
                "display_name": name,
                "birth_date": None,
                "profile_provenance": provenance,
                "avatar_url": f"https://api.dicebear.com/7.x/bottts/svg?seed={external_ref}",
                "rating": rating,
                "acceptance_rate": acceptance,
                "cancellation_rate": round(prior_cancel * 100, 2),
                "total_trips": total_trips,
            }
        )
    return drivers


def sample_fraud_driver_ids(
    rng: random.Random, drivers: list[dict[str, Any]], share: float = FRAUD_SHARE_DEFAULT
) -> list[str]:
    """Sample ~share of driver ids as the caller-side fraud cohort."""
    k = int(len(drivers) * share)
    if k <= 0 or not drivers:
        return []
    return [d["id"] for d in rng.sample(drivers, k)]


def synthesize_passengers(rng: random.Random, n: int) -> list[dict[str, Any]]:
    """Synthesize n passenger dicts with exact app.passengers column keys."""
    passengers: list[dict[str, Any]] = []
    for i in range(n):
        passengers.append(
            {
                "id": _det_uuid(rng),
                "organization_id": BENCHMARK_ORG_ID,
                "principal_id": None,
                "external_ref": f"pax_bm_{i + 1:04d}",
                "is_synthetic": True,
                "created_at": "2026-09-22T06:00:00+00:00",
            }
        )
    return passengers


def _binomial(rng: random.Random, n: int, p: float) -> int:
    return sum(1 for _ in range(n) if rng.random() < p)


def synthesize_driver_analytics(
    rng: random.Random, driver: dict[str, Any], trip_context: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build 7d/30d analytics windows correlated with the driver's priors.

    Caller owns labels: output carries no fraud/violation/expected-category
    judgment, only counts and rates sampled around the driver's documented
    prior rates.
    """
    provenance = driver.get("profile_provenance", {}) or {}
    prior_cancel = float(provenance.get("prior_cancellation_rate", BASE_CANCEL_RATE_MEAN))
    prior_sanctions = int(provenance.get("prior_sanctions_count", 0))
    complaint_rate = float(provenance.get("complaint_rate", BASE_COMPLAINT_RATE_MEAN))
    ctx = trip_context or {}
    trips_7d = int(ctx.get("recent_trips_7d", 25))
    trips_30d = int(ctx.get("recent_trips_30d", 100))
    cancel_7d = _binomial(rng, trips_7d, min(max(prior_cancel, 0.0), 1.0))
    cancel_30d = _binomial(rng, trips_30d, min(max(prior_cancel, 0.0), 1.0))
    complaints_7d = _binomial(rng, trips_7d, min(max(complaint_rate, 0.0), 1.0))
    complaints_30d = _binomial(rng, trips_30d, min(max(complaint_rate, 0.0), 1.0))
    return {
        "driver_id": driver.get("id"),
        "window_7d": {
            "trips": trips_7d,
            "cancellations": cancel_7d,
            "cancellation_rate": round(cancel_7d / trips_7d, 4) if trips_7d else 0.0,
            "complaints": complaints_7d,
        },
        "window_30d": {
            "trips": trips_30d,
            "cancellations": cancel_30d,
            "cancellation_rate": round(cancel_30d / trips_30d, 4) if trips_30d else 0.0,
            "complaints": complaints_30d,
        },
        "dispute_history_count": complaints_30d,
        "prior_sanctions_count": prior_sanctions,
        "historical_cancellation_ratio": round(prior_cancel, 4),
    }
