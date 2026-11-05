#!/usr/bin/env python3
"""
Seed PostgreSQL driver_trips and trip_ratings tables from HF releases_v1 40k corpus.

Issue: #478 (GreenSentinel)
Specification: docs/design/driver-app-redesign/PLAN.md
Idempotent upsert with deterministic rating generation.

To seed a dev demo driver with a deterministic slice of trips and ratings:
    python scripts/seed/seed_driver_trips.py --database-url $DEV_DATABASE_URL --only-demo --demo-driver-id <drivers.id>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import random
import sys
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_driver_trips")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JSONL = REPO_ROOT / "data" / "benchmark-10k" / "releases_v1" / "trips.jsonl"
FEEDBACK_BANK_PATH = REPO_ROOT / "data" / "conversation_bank" / "feedback_bank.yaml"
DEFAULT_ORG_ID = "018f2f4e-b000-7000-8000-000000000001"
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

PAYMENT_METHODS = ("wallet", "credit_card", "cash")

PINNED_RELEASES_V1_SHA256 = "1a0f05b3e1276d8cc0f11a1a922efbecbb554c3c50a6458b24137923592031f7"
PINNED_RELEASES_V1_REVISION = "914a36560727f5892a24fba3a4173cb245c963da"
DEFAULT_HF_REPO = os.environ.get("GREENSENTINEL_BENCHMARK_HF_REPO", "datamonsterr/green-sentinel-synthesized-trips")


def verify_trips_hash(trips_path: Path, expected_sha256: str = PINNED_RELEASES_V1_SHA256) -> str:
    """Verify trips.jsonl sha256 checksum against expected pinned hash."""
    if not trips_path.exists():
        raise FileNotFoundError(f"Missing {trips_path}")
    digest = hashlib.sha256()
    with trips_path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    got = digest.hexdigest()
    if got != expected_sha256:
        raise ValueError(f"Checksum mismatch for {trips_path}:\n  expected {expected_sha256}\n  got      {got}")
    return got


def load_feedback_bank(path: Path = FEEDBACK_BANK_PATH) -> dict[str, Any]:
    """Load passenger feedback comment templates from YAML file.

    Raises on load failure or missing file.
    """
    if not path.exists():
        raise FileNotFoundError(f"Feedback bank file not found: {path}")
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if not isinstance(data, dict):
                raise ValueError(f"Invalid feedback bank YAML structure in {path}, expected dict")
            return data
    except (yaml.YAMLError, OSError) as e:
        logger.error("Failed to load feedback bank from %s: %s", path, e)
        raise


class RatingGenerator:
    """Deterministic rating generator respecting ~60% rated, ~25% comments, and fraud skews."""

    def __init__(self, seed: int = 42, feedback_bank: dict[str, Any] | None = None) -> None:
        self.seed = int(seed)
        self.bank = feedback_bank or load_feedback_bank()

    def generate_rating(
        self,
        trip_id: str,
        label: str = "no_violation",
        locale: str = "vi",
        rated_at: str | None = None,
    ) -> dict[str, Any]:
        """Generate deterministic rating for a trip based on trip_id and fraud label.

        Comment language always matches the requested locale (default vi):
        when the bank carries entries in that language they win; otherwise the
        full category pool is used and the locale follows the chosen entry.
        `rated_at` stamps the rating on the trip's own timeline (ended_at).
        """
        # Per-trip deterministic RNG independent of iteration order
        hash_digest = hashlib.sha256(f"{self.seed}:{trip_id}".encode()).hexdigest()
        trip_seed = int(hash_digest[:16], 16)
        rng = random.Random(trip_seed)

        # ~60% rated
        is_rated = rng.random() < 0.60
        is_fraud = bool(label and label != "no_violation")

        if is_rated:
            u = rng.random()
            if is_fraud:
                # Fraud trips skew lower: mostly 1 or 2 stars
                if u < 0.58:
                    stars = 1
                elif u < 0.88:
                    stars = 2
                elif u < 0.96:
                    stars = 3
                elif u < 0.98:
                    stars = 4
                else:
                    stars = 5
            else:
                # Normal trips skew higher: mostly 5 or 4 stars
                if u < 0.80:
                    stars = 5
                elif u < 0.95:
                    stars = 4
                elif u < 0.98:
                    stars = 3
                elif u < 0.99:
                    stars = 2
                else:
                    stars = 1
        else:
            stars = None

        # ~25% with comment
        has_comment = rng.random() < 0.25
        comment = None
        want_locale = (locale or "vi").strip().lower() or "vi"
        out_locale = None

        if has_comment:
            if stars in (1, 2) or (stars is None and is_fraud):
                polarity = "complaint"
                categories = ("late_pickup", "rude_driver", "unsafe_driving", "overcharge_dispute", "no_show_ghost")
                category = rng.choice(categories)
            elif stars == 3:
                polarity = "neutral" if rng.random() < 0.6 else "complaint"
                category = "general" if polarity == "neutral" else "late_pickup"
            else:
                polarity = "praise"
                categories = ("polite", "clean_car", "fast_pickup", "safe_driving")
                category = rng.choice(categories)

            pool = self.bank.get(polarity, {}).get(category, [])
            localized = [e for e in pool if str(e.get("lang", "")).lower() == want_locale]
            use_pool = localized or pool
            if use_pool:
                chosen = rng.choice(use_pool)
                comment = chosen.get("text")
                chosen_lang = str(chosen.get("lang", "")).lower()
                out_locale = chosen_lang if chosen_lang in ("vi", "en") else want_locale

        return {
            "trip_id": trip_id,
            "stars": stars,
            "comment": comment,
            "locale": out_locale,
            "source": "seed",
            "created_at": rated_at,
        }


def map_trip_record(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a raw trip bundle from trips.jsonl to driver_trips schema row.

    Note: payment_method is synthesized (not present in raw benchmark corpus),
    marked with payment_method_synthetic=True.
    """
    trip_id = raw["trip_id"]
    driver_id = raw["driver_id"]
    org_id = raw.get("driver_profile", {}).get("organization_id") or raw.get("organization_id") or DEFAULT_ORG_ID

    pickup = raw.get("pickup") or {}
    dropoff = raw.get("dropoff") or {}
    trip = raw.get("trip") or {}
    asg = raw.get("assignment") or {}
    route = raw.get("route") or {}

    pickup_label = pickup.get("name") or trip.get("pickup_address") or "Điểm đón"
    pickup_lat = pickup.get("lat")
    pickup_lng = pickup.get("lon")

    dropoff_label = dropoff.get("name") or trip.get("dropoff_address") or "Điểm đến"
    dropoff_lat = dropoff.get("lat")
    dropoff_lng = dropoff.get("lon")

    started_at = asg.get("started_at") or asg.get("accepted_at") or raw.get("requested_at")
    ended_at = asg.get("ended_at") or trip.get("completed_at") or trip.get("cancelled_at")

    dist_m = route.get("distance_m") or 0.0
    distance_km = round(float(dist_m) / 1000.0, 2)

    dur_s = route.get("duration_s") or 0.0
    duration_min = round(float(dur_s) / 60.0, 2)

    fare_vnd = int(trip.get("fare_amount_vnd") or trip.get("fare_amount") or 0)

    # Payment method fallback (synthesized)
    pm = raw.get("payment_method") or trip.get("payment_method")
    if not pm:
        h = int(hashlib.sha256(trip_id.encode()).hexdigest(), 16) % 100
        if h < 65:
            pm = "wallet"
        elif h < 85:
            pm = "credit_card"
        else:
            pm = "cash"

    status = trip.get("status") or "completed"
    fraud_label = raw.get("label") or "no_violation"

    # Linked case UUID for fraud / violation trips
    if fraud_label != "no_violation":
        asg_id = raw.get("assignment_id") or trip_id
        case_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"bm-case-{asg_id}"))
    else:
        case_id = None

    return {
        "trip_id": trip_id,
        "driver_id": driver_id,
        "organization_id": org_id,
        "pickup_label": pickup_label,
        "pickup_lat": pickup_lat,
        "pickup_lng": pickup_lng,
        "dropoff_label": dropoff_label,
        "dropoff_lat": dropoff_lat,
        "dropoff_lng": dropoff_lng,
        "started_at": started_at,
        "ended_at": ended_at,
        "distance_km": distance_km,
        "duration_min": duration_min,
        "fare_vnd": fare_vnd,
        "payment_method": pm,
        "payment_method_synthetic": True,
        "status": status,
        "fraud_label": fraud_label,
        "case_id": case_id,
    }


def compute_dataset_hash(rows: list[dict[str, Any]]) -> str:
    """Compute deterministic SHA-256 hash over canonical representation of rows."""
    canonical_str = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()


def parse_anchor(anchor: str | datetime | date | None) -> datetime:
    """Parse anchor date/datetime into timezone-aware datetime in Asia/Ho_Chi_Minh."""
    if anchor is None:
        today = datetime.now(VN_TZ).date()
        return datetime(today.year, today.month, today.day, 23, 59, 59, tzinfo=VN_TZ)
    if isinstance(anchor, datetime):
        return anchor if anchor.tzinfo else anchor.replace(tzinfo=VN_TZ)
    if isinstance(anchor, date):
        return datetime(anchor.year, anchor.month, anchor.day, 23, 59, 59, tzinfo=VN_TZ)
    val = str(anchor).strip()
    try:
        dt = datetime.fromisoformat(val)
        return dt if dt.tzinfo else dt.replace(tzinfo=VN_TZ)
    except ValueError:
        d = date.fromisoformat(val)
        return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=VN_TZ)


def generate_demo_trips(
    corpus_trips: list[dict[str, Any]],
    driver_id: str,
    organization_id: str | None = None,
    count: int = 60,
    window_days: int = 75,
    anchor: str | datetime | date | None = None,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Deterministically pick N trips from the corpus and rebase for a demo driver."""
    try:
        uuid.UUID(str(driver_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"Invalid demo_driver_id UUID: {driver_id}") from exc

    if organization_id is not None:
        try:
            uuid.UUID(str(organization_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError(f"Invalid demo_organization_id UUID: {organization_id}") from exc

    anchor_dt = parse_anchor(anchor)
    window_days = max(1, int(window_days))
    n = max(0, min(int(count), len(corpus_trips)))
    if n == 0:
        return []

    # Partition corpus into flagged and normal trips, sorted by trip_id for stability
    flagged = [t for t in corpus_trips if t.get("fraud_label") and t.get("fraud_label") != "no_violation"]
    normal = [t for t in corpus_trips if not t.get("fraud_label") or t.get("fraud_label") == "no_violation"]
    flagged.sort(key=lambda x: str(x["trip_id"]))
    normal.sort(key=lambda x: str(x["trip_id"]))

    # Pick at least 15% flagged/fraud trips if available
    min_flagged = math.ceil(n * 0.15)
    num_flagged = min(min_flagged, len(flagged))
    num_normal = min(n - num_flagged, len(normal))
    if num_flagged + num_normal < n and len(flagged) > num_flagged:
        num_flagged = min(len(flagged), n - num_normal)

    rng = random.Random(seed)
    picked_flagged = rng.sample(flagged, num_flagged)
    picked_normal = rng.sample(normal, num_normal)
    picked = picked_flagged + picked_normal
    rng.shuffle(picked)

    window_start = anchor_dt - timedelta(days=window_days)
    total_span_s = window_days * 86400.0

    demo_rows: list[dict[str, Any]] = []
    for i, orig in enumerate(picked):
        orig_trip_id = str(orig["trip_id"])
        new_trip_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"demo-{driver_id}-{orig_trip_id}"))

        # Rebase timestamps: spread over D days before anchor
        offset_s = (i + 1) * total_span_s / (len(picked) + 1)
        new_started_dt = (window_start + timedelta(seconds=int(round(offset_s)))).replace(microsecond=0)

        if orig.get("started_at") and orig.get("ended_at"):
            orig_started = datetime.fromisoformat(str(orig["started_at"]).replace("Z", "+00:00"))
            orig_ended = datetime.fromisoformat(str(orig["ended_at"]).replace("Z", "+00:00"))
            duration = orig_ended - orig_started
            new_ended_dt = new_started_dt + duration
            new_ended_str = new_ended_dt.astimezone(UTC).isoformat()
        else:
            new_ended_str = None

        new_started_str = new_started_dt.astimezone(UTC).isoformat()

        # Organization override or keep original
        org_id = str(organization_id) if organization_id else str(orig.get("organization_id") or DEFAULT_ORG_ID)

        # Demo copies never link to a case: the corpus case belongs to another driver.
        case_id = None

        demo_rows.append(
            {
                "trip_id": new_trip_id,
                "driver_id": str(driver_id),
                "organization_id": org_id,
                "pickup_label": orig["pickup_label"],
                "pickup_lat": orig["pickup_lat"],
                "pickup_lng": orig["pickup_lng"],
                "dropoff_label": orig["dropoff_label"],
                "dropoff_lat": orig["dropoff_lat"],
                "dropoff_lng": orig["dropoff_lng"],
                "started_at": new_started_str,
                "ended_at": new_ended_str,
                "distance_km": orig["distance_km"],
                "duration_min": orig["duration_min"],
                "fare_vnd": orig["fare_vnd"],
                "payment_method": orig["payment_method"],
                "payment_method_synthetic": orig.get("payment_method_synthetic", True),
                "status": orig["status"],
                "fraud_label": orig["fraud_label"],
                "case_id": case_id,
            }
        )

    return demo_rows


def _rating_timestamp(trip: dict[str, Any]) -> str:
    """Rating time follows the trip timeline: ended_at, else started_at, else now."""
    return str(trip.get("ended_at") or trip.get("started_at") or datetime.now(UTC).isoformat())


def generate_demo_ratings(
    demo_trips: list[dict[str, Any]],
    seed: int = 42,
    feedback_bank: dict[str, Any] | None = None,
    locale: str = "vi",
) -> tuple[list[dict[str, Any]], list[str]]:
    """Generate ratings rows and unrated trip ids for demo trips using RatingGenerator."""
    gen = RatingGenerator(seed=seed, feedback_bank=feedback_bank)
    ratings_rows: list[dict[str, Any]] = []
    unrated_trip_ids: list[str] = []

    for t in demo_trips:
        r_row = gen.generate_rating(
            trip_id=t["trip_id"],
            label=t["fraud_label"],
            locale=locale,
            rated_at=_rating_timestamp(t),
        )
        if r_row["stars"] is not None or r_row["comment"] is not None:
            ratings_rows.append(r_row)
        else:
            unrated_trip_ids.append(t["trip_id"])

    return ratings_rows, unrated_trip_ids


def seed_driver_trips(
    conn: Any,
    jsonl_path: Path,
    seed: int = 42,
    batch_size: int = 1000,
    schema: str = "app",
    demo_driver_id: str | None = None,
    demo_organization_id: str | None = None,
    demo_trip_count: int = 60,
    demo_window_days: int = 75,
    demo_anchor: str | None = None,
    only_demo: bool = False,
) -> dict[str, Any]:
    """Read jsonl, map driver_trips, generate deterministic ratings, and execute idempotent upsert."""
    if only_demo and not demo_driver_id:
        raise ValueError("--only-demo requires demo_driver_id")

    gen = RatingGenerator(seed=seed)
    trips_rows: list[dict[str, Any]] = []
    ratings_rows: list[dict[str, Any]] = []
    unrated_trip_ids: list[str] = []

    logger.info("Reading trips from %s...", jsonl_path)
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            t_row = map_trip_record(item)
            trips_rows.append(t_row)

            if not only_demo:
                r_row = gen.generate_rating(
                    trip_id=t_row["trip_id"],
                    label=t_row["fraud_label"],
                    rated_at=_rating_timestamp(t_row),
                )
                # Record rating row when either stars or comment is present
                if r_row["stars"] is not None or r_row["comment"] is not None:
                    ratings_rows.append(r_row)
                else:
                    unrated_trip_ids.append(t_row["trip_id"])

    demo_trips_rows: list[dict[str, Any]] = []
    demo_ratings_rows: list[dict[str, Any]] = []
    demo_unrated_trip_ids: list[str] = []

    if demo_driver_id:
        logger.info("Generating %d demo trips for driver %s...", demo_trip_count, demo_driver_id)
        demo_trips_rows = generate_demo_trips(
            corpus_trips=trips_rows,
            driver_id=demo_driver_id,
            organization_id=demo_organization_id,
            count=demo_trip_count,
            window_days=demo_window_days,
            anchor=demo_anchor,
            seed=seed,
        )
        demo_ratings_rows, demo_unrated_trip_ids = generate_demo_ratings(
            demo_trips=demo_trips_rows,
            seed=seed,
            feedback_bank=gen.bank,
        )

    if only_demo:
        trips_to_upsert = demo_trips_rows
        ratings_to_upsert = demo_ratings_rows
        unrated_to_delete = demo_unrated_trip_ids
    elif demo_driver_id:
        trips_to_upsert = trips_rows + demo_trips_rows
        ratings_to_upsert = ratings_rows + demo_ratings_rows
        unrated_to_delete = unrated_trip_ids + demo_unrated_trip_ids
    else:
        trips_to_upsert = trips_rows
        ratings_to_upsert = ratings_rows
        unrated_to_delete = unrated_trip_ids

    total_trips = len(trips_to_upsert)
    total_ratings = len(ratings_to_upsert)
    total_unrated = len(unrated_to_delete)
    logger.info("Parsed %d trips, generated %d ratings (%d unrated)", total_trips, total_ratings, total_unrated)

    # Compute determinism hash over mapped trips and ratings
    dataset_hash = hashlib.sha256(
        (compute_dataset_hash(trips_to_upsert) + ":" + compute_dataset_hash(ratings_to_upsert)).encode()
    ).hexdigest()

    upsert_trips_sql = f"""
        INSERT INTO {schema}.driver_trips (
            trip_id, driver_id, organization_id, pickup_label, pickup_lat, pickup_lng,
            dropoff_label, dropoff_lat, dropoff_lng, started_at, ended_at,
            distance_km, duration_min, fare_vnd, payment_method, payment_method_synthetic,
            status, fraud_label, case_id
        ) VALUES (
            %(trip_id)s, %(driver_id)s, %(organization_id)s, %(pickup_label)s, %(pickup_lat)s, %(pickup_lng)s,
            %(dropoff_label)s, %(dropoff_lat)s, %(dropoff_lng)s, %(started_at)s, %(ended_at)s,
            %(distance_km)s, %(duration_min)s, %(fare_vnd)s, %(payment_method)s, %(payment_method_synthetic)s,
            %(status)s, %(fraud_label)s, %(case_id)s
        )
        ON CONFLICT (trip_id) DO UPDATE SET
            driver_id = EXCLUDED.driver_id,
            organization_id = EXCLUDED.organization_id,
            pickup_label = EXCLUDED.pickup_label,
            pickup_lat = EXCLUDED.pickup_lat,
            pickup_lng = EXCLUDED.pickup_lng,
            dropoff_label = EXCLUDED.dropoff_label,
            dropoff_lat = EXCLUDED.dropoff_lat,
            dropoff_lng = EXCLUDED.dropoff_lng,
            started_at = EXCLUDED.started_at,
            ended_at = EXCLUDED.ended_at,
            distance_km = EXCLUDED.distance_km,
            duration_min = EXCLUDED.duration_min,
            fare_vnd = EXCLUDED.fare_vnd,
            payment_method = EXCLUDED.payment_method,
            payment_method_synthetic = EXCLUDED.payment_method_synthetic,
            status = EXCLUDED.status,
            fraud_label = EXCLUDED.fraud_label,
            case_id = EXCLUDED.case_id;
    """

    upsert_ratings_sql = f"""
        INSERT INTO {schema}.trip_ratings (
            trip_id, stars, comment, locale, source, created_at
        ) VALUES (
            %(trip_id)s, %(stars)s, %(comment)s, %(locale)s, 'seed', %(created_at)s
        )
        ON CONFLICT (trip_id) DO UPDATE SET
            stars = EXCLUDED.stars,
            comment = EXCLUDED.comment,
            locale = EXCLUDED.locale,
            source = EXCLUDED.source,
            created_at = EXCLUDED.created_at
        WHERE {schema}.trip_ratings.source = 'seed';
    """

    delete_unrated_seed_sql = f"""
        DELETE FROM {schema}.trip_ratings
        WHERE trip_id = ANY(%(trip_ids)s) AND source = 'seed';
    """

    if conn is not None:
        with conn.cursor() as cur:
            # Batch upsert driver_trips
            logger.info("Upserting %d driver_trips in batches of %d...", total_trips, batch_size)
            for i in range(0, total_trips, batch_size):
                chunk = trips_to_upsert[i : i + batch_size]
                cur.executemany(upsert_trips_sql, chunk)

            # Delete seed ratings for trips that now get no rating
            if unrated_to_delete:
                logger.info("Deleting seed ratings for %d unrated trips...", len(unrated_to_delete))
                for i in range(0, len(unrated_to_delete), batch_size):
                    chunk_ids = unrated_to_delete[i : i + batch_size]
                    cur.execute(delete_unrated_seed_sql, {"trip_ids": chunk_ids})

            # Batch upsert trip_ratings
            logger.info("Upserting %d trip_ratings in batches of %d...", total_ratings, batch_size)
            for i in range(0, total_ratings, batch_size):
                chunk = ratings_to_upsert[i : i + batch_size]
                cur.executemany(upsert_ratings_sql, chunk)

        if hasattr(conn, "commit"):
            conn.commit()
        logger.info("Successfully seeded driver_trips and trip_ratings!")

    res = {
        "trips_count": total_trips,
        "ratings_count": total_ratings,
        "dataset_hash": dataset_hash,
    }
    if demo_driver_id:
        res["demo_trips_count"] = len(demo_trips_rows)
        res["demo_ratings_count"] = len(demo_ratings_rows)
    return res


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonl", "--in", type=Path, default=DEFAULT_JSONL, help="Path to trips.jsonl")
    parser.add_argument("--profile", default="releases_v1", help="Dataset profile to fetch if file missing")
    parser.add_argument("--revision", default=None, help="Pinned revision override for dataset fetch")
    parser.add_argument("--seed", type=int, default=42, help="Fixed deterministic seed")
    parser.add_argument("--batch-size", type=int, default=1000, help="Batch size for database upserts")
    parser.add_argument("--database-url", default=None, help="Postgres DATABASE_URL override")
    parser.add_argument("--schema", default="app", help="Target database schema (default: app)")
    parser.add_argument("--dry-run", action="store_true", help="Parse and hash without database operations")
    parser.add_argument("--demo-driver-id", default=None, help="UUID of driver to seed demo trips for")
    parser.add_argument("--demo-organization-id", default=None, help="Optional UUID of organization for demo trips")
    parser.add_argument(
        "--demo-trip-count", type=int, default=60, help="Number of demo trips to generate (default: 60)"
    )
    parser.add_argument(
        "--demo-window-days", type=int, default=75, help="Window in days before anchor for demo trips (default: 75)"
    )
    parser.add_argument(
        "--demo-anchor", default=None, help="Anchor ISO date for demo trips (default: today in Asia/Ho_Chi_Minh)"
    )
    parser.add_argument("--only-demo", action="store_true", help="Skip bulk 40k upsert and only write demo rows")
    args = parser.parse_args(argv)

    if args.only_demo and not args.demo_driver_id:
        parser.error("--only-demo requires --demo-driver-id")

    jsonl_path = args.jsonl
    repo = os.environ.get("GREENSENTINEL_BENCHMARK_HF_REPO", DEFAULT_HF_REPO)
    revision = args.revision or (PINNED_RELEASES_V1_REVISION if args.profile == "releases_v1" else None)

    if not jsonl_path.exists():
        logger.info(
            "Dataset %s missing; fetching via fetch_dataset.py from %s (rev: %s)...", jsonl_path, repo, revision
        )
        from scripts.benchmark.fetch_dataset import fetch

        out_root = REPO_ROOT / "data" / "benchmark-10k"
        fetch(repo=repo, profile=args.profile, out=out_root, revision=revision)
        jsonl_path = out_root / args.profile / "trips.jsonl"

    if args.profile == "releases_v1" or (jsonl_path.name == "trips.jsonl" and jsonl_path.parent.name == "releases_v1"):
        logger.info("Verifying %s against pinned SHA-256 (%s)...", jsonl_path, PINNED_RELEASES_V1_SHA256)
        verify_trips_hash(jsonl_path, expected_sha256=PINNED_RELEASES_V1_SHA256)

    if args.dry_run:
        logger.info("Dry-run requested; skipping database connection.")
        result = seed_driver_trips(
            conn=None,
            jsonl_path=jsonl_path,
            seed=args.seed,
            batch_size=args.batch_size,
            schema=args.schema,
            demo_driver_id=args.demo_driver_id,
            demo_organization_id=args.demo_organization_id,
            demo_trip_count=args.demo_trip_count,
            demo_window_days=args.demo_window_days,
            demo_anchor=args.demo_anchor,
            only_demo=args.only_demo,
        )
        print(json.dumps(result, indent=2))
        return 0

    db_url = args.database_url or os.environ.get("DATABASE_URL") or os.environ.get("MIGRATION_DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL must be set or passed via --database-url")
        return 1

    import psycopg

    logger.info("Connecting to Postgres...")
    with psycopg.connect(db_url) as conn:
        result = seed_driver_trips(
            conn=conn,
            jsonl_path=jsonl_path,
            seed=args.seed,
            batch_size=args.batch_size,
            schema=args.schema,
            demo_driver_id=args.demo_driver_id,
            demo_organization_id=args.demo_organization_id,
            demo_trip_count=args.demo_trip_count,
            demo_window_days=args.demo_window_days,
            demo_anchor=args.demo_anchor,
            only_demo=args.only_demo,
        )
        print(json.dumps(result, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
