"""Unit tests for driver trips and ratings schema, generator, mapping, and idempotency (Issue #478)."""

from __future__ import annotations

from datetime import UTC
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = REPO_ROOT / "db" / "migrations" / "20261017100000_driver_trips_ratings.sql"
ROLLBACK_PATH = REPO_ROOT / "db" / "rollbacks" / "20261017100000_driver_trips_ratings.down.sql"
FEEDBACK_BANK_PATH = REPO_ROOT / "data" / "conversation_bank" / "feedback_bank.yaml"


def test_migration_files_exist_and_contract():
    """Migration and rollback files must exist and fulfill table, column, index, and constraint contracts."""
    assert MIGRATION_PATH.exists(), f"Missing migration file: {MIGRATION_PATH}"
    assert ROLLBACK_PATH.exists(), f"Missing rollback file: {ROLLBACK_PATH}"

    sql_up = MIGRATION_PATH.read_text(encoding="utf-8").lower()
    assert "create table if not exists app.driver_trips" in sql_up
    assert "create table if not exists app.trip_ratings" in sql_up
    assert "trip_id" in sql_up
    assert "driver_id" in sql_up
    assert "organization_id" in sql_up
    assert "pickup_label" in sql_up
    assert "dropoff_label" in sql_up
    assert "started_at" in sql_up
    assert "ended_at" in sql_up
    assert "distance_km" in sql_up
    assert "duration_min" in sql_up
    assert "fare_vnd" in sql_up
    assert "payment_method" in sql_up
    assert "payment_method_synthetic" in sql_up
    assert "status" in sql_up
    assert "fraud_label" in sql_up
    assert "case_id" in sql_up
    assert "stars" in sql_up
    assert "source" in sql_up
    assert "check (stars between 1 and 5)" in sql_up or "stars between 1 and 5" in sql_up
    assert "idx_driver_trips_driver_started" in sql_up
    assert "(driver_id, started_at desc)" in sql_up
    assert "idx_driver_trips_case_id" in sql_up
    # Review finding: drop unnecessary indexes
    assert "idx_driver_trips_org_driver" not in sql_up
    assert "idx_trip_ratings_stars" not in sql_up

    sql_down = ROLLBACK_PATH.read_text(encoding="utf-8").lower()
    assert "drop table if exists app.trip_ratings" in sql_down
    assert "drop table if exists app.driver_trips" in sql_down


def test_trip_record_mapping():
    """Verify mapping from raw trips.jsonl bundle to driver_trips row."""
    from scripts.seed.seed_driver_trips import map_trip_record

    raw_bundle = {
        "trip_id": "884aedff-b9d6-5e06-9ba1-f99ccce6d22e",
        "trip_ref": "rv1_v1_00001",
        "driver_id": "c0541bd4-68e4-56cd-a6be-262decca44a3",
        "driver_profile": {"organization_id": "018f2f4e-b000-7000-8000-000000000001"},
        "pickup": {"lat": 21.0231243, "lon": 105.8424197, "name": "Ga Ha Noi"},
        "dropoff": {"lat": 20.9917902, "lon": 105.8378248, "name": "Ben xe Giap Bat"},
        "trip": {
            "fare_amount_vnd": 74628,
            "status": "completed",
            "pickup_address": "Ga Ha Noi, Dong Da, Ha Noi",
            "dropoff_address": "Ben xe Giap Bat, Hoang Mai, Ha Noi",
        },
        "assignment": {"started_at": "2026-10-09T18:47:21+00:00", "ended_at": "2026-10-09T18:57:51+00:00"},
        "route": {"distance_m": 4969, "duration_s": 710},
        "label": "no_violation",
    }

    mapped = map_trip_record(raw_bundle)
    assert mapped["trip_id"] == "884aedff-b9d6-5e06-9ba1-f99ccce6d22e"
    assert mapped["driver_id"] == "c0541bd4-68e4-56cd-a6be-262decca44a3"
    assert mapped["organization_id"] == "018f2f4e-b000-7000-8000-000000000001"
    assert mapped["pickup_label"] == "Ga Ha Noi"
    assert mapped["pickup_lat"] == pytest.approx(21.0231243)
    assert mapped["pickup_lng"] == pytest.approx(105.8424197)
    assert mapped["dropoff_label"] == "Ben xe Giap Bat"
    assert mapped["dropoff_lat"] == pytest.approx(20.9917902)
    assert mapped["dropoff_lng"] == pytest.approx(105.8378248)
    assert mapped["started_at"] == "2026-10-09T18:47:21+00:00"
    assert mapped["ended_at"] == "2026-10-09T18:57:51+00:00"
    assert mapped["distance_km"] == pytest.approx(4.97)
    assert mapped["duration_min"] == pytest.approx(11.83)
    assert mapped["fare_vnd"] == 74628
    assert mapped["payment_method"] in ("wallet", "cash", "credit_card")
    assert mapped["payment_method_synthetic"] is True
    assert mapped["status"] == "completed"
    assert mapped["fraud_label"] == "no_violation"
    assert mapped["case_id"] is None


def test_fraud_trip_case_link():
    """A trip with fraud label must link to a deterministic case UUID."""
    from scripts.seed.seed_driver_trips import map_trip_record

    raw_fraud_bundle = {
        "trip_id": "d78863c2-49d4-584b-a257-fa5f3f8f295f",
        "trip_ref": "rv1_v1_00002",
        "driver_id": "966fe5ad-a7cb-5bb4-a455-b0f8bc1bcbd6",
        "assignment_id": "asg-002",
        "driver_profile": {"organization_id": "018f2f4e-b000-7000-8000-000000000001"},
        "pickup": {"lat": 21.0551699, "lon": 105.8247103, "name": "Ho Tay"},
        "dropoff": {"lat": 21.0004383, "lon": 105.8476541, "name": "Benh vien Bach Mai"},
        "trip": {"fare_amount_vnd": 126300, "status": "cancelled"},
        "assignment": {"accepted_at": "2026-10-16T01:25:55+00:00", "ended_at": "2026-10-16T01:31:10+00:00"},
        "route": {"distance_m": 9275, "duration_s": 1325},
        "label": "ERR-02",
    }

    mapped = map_trip_record(raw_fraud_bundle)
    assert mapped["fraud_label"] == "ERR-02"
    assert mapped["case_id"] is not None
    assert isinstance(mapped["case_id"], str)
    assert len(mapped["case_id"]) == 36


def test_rating_generator_proportions_and_bounds():
    """Verify ~60% rated, ~25% with comment, nullable stars, and stars between 1 and 5."""
    from scripts.seed.seed_driver_trips import RatingGenerator

    gen = RatingGenerator(seed=42)
    sample_size = 2000

    rated_count = 0
    comment_count = 0
    null_stars_with_comment = 0

    for i in range(sample_size):
        trip_id = f"test-trip-{i:05d}"
        label = "no_violation" if i % 4 != 0 else "ERR-02"
        rating = gen.generate_rating(trip_id=trip_id, label=label)

        if rating["stars"] is not None:
            rated_count += 1
            assert 1 <= rating["stars"] <= 5
        else:
            if rating["comment"] is not None:
                null_stars_with_comment += 1

        if rating["comment"] is not None:
            comment_count += 1
            assert rating["locale"] in ("vi", "en")
            assert len(rating["comment"]) > 5

    rated_pct = rated_count / sample_size
    comment_pct = comment_count / sample_size

    # ~60% rated (0.55 .. 0.65)
    assert 0.55 <= rated_pct <= 0.65, f"Rated pct was {rated_pct:.3f}"
    # ~25% with comment (0.20 .. 0.30)
    assert 0.20 <= comment_pct <= 0.30, f"Comment pct was {comment_pct:.3f}"


def test_rating_generator_fraud_skew():
    """Fraud trips must skew significantly lower in rating than normal trips."""
    from scripts.seed.seed_driver_trips import RatingGenerator

    gen = RatingGenerator(seed=42)

    normal_ratings = []
    fraud_ratings = []

    for i in range(1000):
        trip_id_n = f"normal-{i}"
        r_n = gen.generate_rating(trip_id=trip_id_n, label="no_violation")
        if r_n["stars"] is not None:
            normal_ratings.append(r_n["stars"])

        trip_id_f = f"fraud-{i}"
        r_f = gen.generate_rating(trip_id=trip_id_f, label="ERR-02")
        if r_f["stars"] is not None:
            fraud_ratings.append(r_f["stars"])

    assert len(normal_ratings) > 0
    assert len(fraud_ratings) > 0

    avg_normal = sum(normal_ratings) / len(normal_ratings)
    avg_fraud = sum(fraud_ratings) / len(fraud_ratings)

    assert avg_normal >= 4.5, f"Normal trips avg rating was too low: {avg_normal:.2f}"
    assert avg_fraud <= 2.5, f"Fraud trips avg rating was too high: {avg_fraud:.2f}"


def test_determinism_same_seed_same_row_hash():
    """Running rating and trip generation with the same seed must yield identical row hashes."""
    from scripts.seed.seed_driver_trips import RatingGenerator, compute_dataset_hash

    trip_ids = [f"det-trip-{i}" for i in range(200)]
    labels = ["no_violation" if i % 2 == 0 else "ERR-01" for i in range(200)]

    gen1 = RatingGenerator(seed=20261017)
    rows1 = [gen1.generate_rating(t, lbl) for t, lbl in zip(trip_ids, labels)]
    hash1 = compute_dataset_hash(rows1)

    gen2 = RatingGenerator(seed=20261017)
    rows2 = [gen2.generate_rating(t, lbl) for t, lbl in zip(trip_ids, labels)]
    hash2 = compute_dataset_hash(rows2)

    assert hash1 == hash2, "Identical seed must yield identical hash"

    gen3 = RatingGenerator(seed=999999)
    rows3 = [gen3.generate_rating(t, lbl) for t, lbl in zip(trip_ids, labels)]
    hash3 = compute_dataset_hash(rows3)

    assert hash1 != hash3, "Different seed must yield different hash"


def test_feedback_bank_raise_on_failure(tmp_path: Path):
    """Loading feedback bank must raise on missing file or invalid YAML; fallback bank removed."""
    import yaml

    from scripts.seed import seed_driver_trips
    from scripts.seed.seed_driver_trips import load_feedback_bank

    # Fallback bank must be removed
    assert not hasattr(seed_driver_trips, "FALLBACK_FEEDBACK_BANK"), "FALLBACK_FEEDBACK_BANK must be removed"

    # Missing file raises FileNotFoundError
    non_existent = tmp_path / "does_not_exist.yaml"
    with pytest.raises(FileNotFoundError):
        load_feedback_bank(non_existent)

    # Invalid YAML raises yaml.YAMLError or ValueError
    corrupt_file = tmp_path / "corrupt.yaml"
    corrupt_file.write_text("invalid: yaml: [unbalanced", encoding="utf-8")
    with pytest.raises((yaml.YAMLError, ValueError)):
        load_feedback_bank(corrupt_file)

    # Valid file loads cleanly
    valid_file = tmp_path / "valid.yaml"
    valid_file.write_text("praise:\n  polite:\n    - text: Good\n      lang: en\n", encoding="utf-8")
    loaded = load_feedback_bank(valid_file)
    assert "praise" in loaded


def test_verify_trips_hash_releases_v1(tmp_path: Path):
    """Trips hash verification against pinned SHA-256 for releases_v1 and repo env honor."""
    from scripts.seed.seed_driver_trips import (
        PINNED_RELEASES_V1_REVISION,
        PINNED_RELEASES_V1_SHA256,
        verify_trips_hash,
    )

    # Check pinned constants match STORAGE.md
    assert PINNED_RELEASES_V1_SHA256 == "1a0f05b3e1276d8cc0f11a1a922efbecbb554c3c50a6458b24137923592031f7"
    assert PINNED_RELEASES_V1_REVISION == "914a36560727f5892a24fba3a4173cb245c963da"

    # Valid file matching expected hash
    dummy_file = tmp_path / "dummy.jsonl"
    dummy_file.write_text("test line\n", encoding="utf-8")
    import hashlib

    expected_dummy_sha = hashlib.sha256(b"test line\n").hexdigest()

    got = verify_trips_hash(dummy_file, expected_sha256=expected_dummy_sha)
    assert got == expected_dummy_sha

    # Mismatch raises ValueError
    with pytest.raises(ValueError, match="mismatch"):
        verify_trips_hash(dummy_file, expected_sha256=PINNED_RELEASES_V1_SHA256)

    # Missing file raises FileNotFoundError
    with pytest.raises(FileNotFoundError):
        verify_trips_hash(tmp_path / "missing.jsonl")


@pytest.mark.asyncio
async def test_list_driver_trips_keyset_pagination_in_memory():
    """Verify keyset pagination in memory path using opaque cursor."""
    from src.services.driver_service import (
        _memory_driver_trips,
        _memory_trip_ratings,
        decode_trip_cursor,
        list_driver_trips,
    )

    _memory_driver_trips.clear()
    _memory_trip_ratings.clear()

    driver_id = "018f2f4e-b300-7000-8000-000000000001"
    # Seed 5 trips with distinct descending started_at
    for i in range(5):
        tid = f"018f2f4e-b100-7000-8000-00000000000{i}"
        _memory_driver_trips[tid] = {
            "trip_id": tid,
            "driver_id": driver_id,
            "pickup_label": f"Pickup {i}",
            "dropoff_label": f"Dropoff {i}",
            "started_at": f"2026-10-15T0{i + 1}:00:00Z",
            "status": "completed",
        }

    # Page 1: limit=2 (should get trips 4 and 3)
    p1 = await list_driver_trips(driver_id=driver_id, limit=2)
    assert len(p1["trips"]) == 2
    assert p1["trips"][0]["trip_id"] == "018f2f4e-b100-7000-8000-000000000004"
    assert p1["trips"][1]["trip_id"] == "018f2f4e-b100-7000-8000-000000000003"
    assert p1["next_cursor"] is not None

    # Cursor should be opaque base64 string, not just an integer offset
    assert not p1["next_cursor"].isdigit()
    decoded = decode_trip_cursor(p1["next_cursor"])
    assert decoded is not None
    assert decoded[1] == "018f2f4e-b100-7000-8000-000000000003"

    # Page 2: with cursor (should get trips 2 and 1)
    p2 = await list_driver_trips(driver_id=driver_id, cursor=p1["next_cursor"], limit=2)
    assert len(p2["trips"]) == 2
    assert p2["trips"][0]["trip_id"] == "018f2f4e-b100-7000-8000-000000000002"
    assert p2["trips"][1]["trip_id"] == "018f2f4e-b100-7000-8000-000000000001"
    assert p2["next_cursor"] is not None

    # Page 3: with cursor (should get trip 0)
    p3 = await list_driver_trips(driver_id=driver_id, cursor=p2["next_cursor"], limit=2)
    assert len(p3["trips"]) == 1
    assert p3["trips"][0]["trip_id"] == "018f2f4e-b100-7000-8000-000000000000"
    assert p3["next_cursor"] is None


def test_parse_anchor():
    """Anchor parser supports None (today in VN), ISO date, and ISO datetime strings."""
    from datetime import date, datetime
    from zoneinfo import ZoneInfo

    from scripts.seed.seed_driver_trips import parse_anchor

    vn_tz = ZoneInfo("Asia/Ho_Chi_Minh")
    # None defaults to today in Asia/Ho_Chi_Minh
    a_none = parse_anchor(None)
    assert a_none.tzinfo == vn_tz
    today_vn = datetime.now(vn_tz).date()
    assert a_none.date() == today_vn

    # ISO date string
    a_str = parse_anchor("2026-10-19")
    assert a_str.date() == date(2026, 10, 19)
    assert a_str.tzinfo == vn_tz

    # ISO datetime with offset
    a_dt = parse_anchor("2026-10-19T10:00:00+07:00")
    assert a_dt.year == 2026 and a_dt.month == 10 and a_dt.day == 19
    assert a_dt.hour == 10

    # UTC datetime
    a_utc = parse_anchor("2026-10-19T03:00:00Z")
    assert a_utc.astimezone(UTC).hour == 3


def test_generate_demo_trips_deterministic_and_slice():
    """Verify deterministic picking of N trips with fixed seed, 15% fraud trips, and uuid5 ids."""
    import json
    import uuid

    from scripts.seed.seed_driver_trips import generate_demo_trips, map_trip_record

    sample_path = REPO_ROOT / "data" / "benchmark-10k" / "v1" / "sample_100.jsonl"
    with open(sample_path, encoding="utf-8") as f:
        corpus = [map_trip_record(json.loads(line)) for line in f if line.strip()]

    driver_id = "018f2f4e-c000-7000-8000-000000000001"
    org_id = "018f2f4e-c000-7000-8000-000000000002"

    demo1 = generate_demo_trips(
        corpus_trips=corpus,
        driver_id=driver_id,
        organization_id=org_id,
        count=60,
        window_days=75,
        anchor="2026-10-19",
        seed=42,
    )
    assert len(demo1) == 60

    # Determinism: same seed produces identical trip slice
    demo2 = generate_demo_trips(
        corpus_trips=corpus,
        driver_id=driver_id,
        organization_id=org_id,
        count=60,
        window_days=75,
        anchor="2026-10-19",
        seed=42,
    )
    assert [t["trip_id"] for t in demo1] == [t["trip_id"] for t in demo2]
    assert [t["started_at"] for t in demo1] == [t["started_at"] for t in demo2]

    # Different seed produces different trips/order
    demo3 = generate_demo_trips(
        corpus_trips=corpus,
        driver_id=driver_id,
        organization_id=org_id,
        count=60,
        window_days=75,
        anchor="2026-10-19",
        seed=9999,
    )
    assert [t["trip_id"] for t in demo1] != [t["trip_id"] for t in demo3]

    # At least 15% flagged trips (>= 9 of 60)
    flagged = [t for t in demo1 if t["fraud_label"] != "no_violation"]
    assert len(flagged) >= 9, f"Expected >= 9 flagged trips, got {len(flagged)}"

    # Id format and isolation
    corpus_by_id = {t["trip_id"]: t for t in corpus}
    for t in demo1:
        assert t["driver_id"] == driver_id
        assert t["organization_id"] == org_id
        # Trip id is valid UUID5 derived from demo-{driver_id}-{orig_trip_id}
        assert t["trip_id"] not in corpus_by_id, "Demo trip_id must not collide with corpus"
        # Find original trip by looking for matching uuid5
        matched_orig = None
        for orig_id, orig_row in corpus_by_id.items():
            expected_uuid5 = str(uuid.uuid5(uuid.NAMESPACE_URL, f"demo-{driver_id}-{orig_id}"))
            if expected_uuid5 == t["trip_id"]:
                matched_orig = orig_row
                break
        assert matched_orig is not None, f"Could not find matching original for {t['trip_id']}"

        # Fare and distance preserved without fabrication
        assert t["fare_vnd"] == matched_orig["fare_vnd"]
        assert t["distance_km"] == matched_orig["distance_km"]
        assert t["duration_min"] == matched_orig["duration_min"]

        # Case ID rule: demo copies never link to the corpus driver's case
        assert t["case_id"] is None


def test_generate_demo_trips_never_reuses_corpus_case_id():
    """Demo copies must not inherit the corpus driver's case_id, even when the source row has one."""
    from scripts.seed.seed_driver_trips import generate_demo_trips

    def corpus_row(idx: int, fraud_label: str, case_id: str | None) -> dict:
        return {
            "trip_id": f"00000000-0000-5000-8000-{idx:012d}",
            "driver_id": "966fe5ad-a7cb-5bb4-a455-b0f8bc1bcbd6",
            "organization_id": "018f2f4e-b000-7000-8000-000000000001",
            "pickup_label": "Ho Tay",
            "pickup_lat": 21.0551699,
            "pickup_lng": 105.8247103,
            "dropoff_label": "Benh vien Bach Mai",
            "dropoff_lat": 21.0004383,
            "dropoff_lng": 105.8476541,
            "started_at": "2026-10-16T01:25:55+00:00",
            "ended_at": "2026-10-16T01:31:10+00:00",
            "distance_km": 9.275,
            "duration_min": 5.25,
            "fare_vnd": 126300,
            "payment_method": "cash",
            "payment_method_synthetic": True,
            "status": "completed",
            "fraud_label": fraud_label,
            "case_id": case_id,
        }

    corpus = [
        corpus_row(1, "ERR-02", "11111111-1111-5111-8111-111111111111"),
        corpus_row(2, "ERR-03", "22222222-2222-5222-8222-222222222222"),
        corpus_row(3, "no_violation", None),
        corpus_row(4, "no_violation", None),
    ]

    demo = generate_demo_trips(
        corpus_trips=corpus,
        driver_id="018f2f4e-c000-7000-8000-000000000001",
        organization_id="018f2f4e-c000-7000-8000-000000000002",
        count=4,
        anchor="2026-10-19",
        seed=42,
    )

    assert len(demo) == 4
    assert all(t["case_id"] is None for t in demo)
    assert any(t["fraud_label"] != "no_violation" for t in demo)
    source_case_ids = {t["case_id"] for t in corpus if t["case_id"]}
    assert source_case_ids, "fixture must contain corpus case ids"
    assert not source_case_ids.intersection(t["case_id"] for t in demo)


def test_demo_trips_rebase_spread_and_duration():
    """Verify started_at/ended_at are spread over D days before anchor and duration is preserved."""
    import json
    import uuid
    from datetime import datetime, timedelta

    from scripts.seed.seed_driver_trips import generate_demo_trips, map_trip_record

    sample_path = REPO_ROOT / "data" / "benchmark-10k" / "v1" / "sample_100.jsonl"
    with open(sample_path, encoding="utf-8") as f:
        corpus = [map_trip_record(json.loads(line)) for line in f if line.strip()]

    driver_id = "018f2f4e-c000-7000-8000-000000000001"
    anchor = "2026-10-19T23:59:59+07:00"
    window_days = 75
    demo = generate_demo_trips(
        corpus_trips=corpus,
        driver_id=driver_id,
        count=60,
        window_days=window_days,
        anchor=anchor,
        seed=42,
    )

    anchor_dt = datetime.fromisoformat(anchor)
    min_window_dt = anchor_dt - timedelta(days=window_days)

    started_timestamps = []
    for t in demo:
        st = datetime.fromisoformat(t["started_at"])
        et = datetime.fromisoformat(t["ended_at"])
        started_timestamps.append(st)

        # Within [anchor - D days, anchor]
        assert st >= min_window_dt
        assert st <= anchor_dt
        assert et >= st

        # Find matching original trip to check exact duration preservation
        matched_orig = None
        for orig in corpus:
            expected_uuid5 = str(uuid.uuid5(uuid.NAMESPACE_URL, f"demo-{driver_id}-{orig['trip_id']}"))
            if expected_uuid5 == t["trip_id"]:
                matched_orig = orig
                break
        assert matched_orig is not None
        orig_st = datetime.fromisoformat(matched_orig["started_at"])
        orig_et = datetime.fromisoformat(matched_orig["ended_at"])
        assert (et - st) == (orig_et - orig_st)

    # Trips are spread out across multiple days and months
    dates = {st.date() for st in started_timestamps}
    assert len(dates) >= 40, f"Expected trips across >= 40 distinct dates, got {len(dates)}"
    months = {st.strftime("%Y-%m") for st in started_timestamps}
    assert len(months) >= 3, f"Expected trips across >= 3 months (Aug, Sep, Oct), got {months}"


def test_demo_trips_ratings_and_only_demo():
    """Verify ratings rules on demo trips and --only-demo behavior."""
    import json

    from scripts.seed.seed_driver_trips import (
        generate_demo_ratings,
        generate_demo_trips,
        map_trip_record,
        seed_driver_trips,
    )

    sample_path = REPO_ROOT / "data" / "benchmark-10k" / "v1" / "sample_100.jsonl"
    with open(sample_path, encoding="utf-8") as f:
        corpus = [map_trip_record(json.loads(line)) for line in f if line.strip()]

    driver_id = "018f2f4e-c000-7000-8000-000000000001"
    demo_trips = generate_demo_trips(
        corpus_trips=corpus,
        driver_id=driver_id,
        count=60,
        seed=42,
    )

    ratings, unrated = generate_demo_ratings(demo_trips=demo_trips, seed=42)
    assert len(ratings) + len(unrated) == 60
    # ~60% rated (within reasonable small-sample range 45%..75%)
    assert 25 <= len(ratings) <= 45

    for r in ratings:
        assert r["source"] == "seed"
        if r["stars"] is not None:
            assert 1 <= r["stars"] <= 5

    # Test seed_driver_trips with only_demo on dry-run (conn=None)
    stats = seed_driver_trips(
        conn=None,
        jsonl_path=sample_path,
        seed=42,
        demo_driver_id=driver_id,
        demo_trip_count=60,
        only_demo=True,
    )
    assert stats["trips_count"] == 60
    assert stats["demo_trips_count"] == 60
    assert stats["ratings_count"] == len(ratings)

    # only_demo without demo_driver_id raises ValueError
    with pytest.raises(ValueError, match="--only-demo requires"):
        seed_driver_trips(conn=None, jsonl_path=sample_path, only_demo=True)


def test_script_entrypoint_resolves_scripts_package(tmp_path):
    """Running the file directly must find the `scripts` package (repo root on sys.path).

    Regression: `python scripts/seed/seed_driver_trips.py` died with
    ModuleNotFoundError: No module named 'scripts' when the dataset fetch ran.
    A bogus profile reaches fetch (proving the import works) and fails fast
    with ValueError instead of ModuleNotFoundError.
    """
    import subprocess
    import sys

    script = REPO_ROOT / "scripts" / "seed" / "seed_driver_trips.py"
    env = {k: v for k, v in __import__("os").environ.items() if k != "PYTHONPATH"}
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--jsonl",
            str(tmp_path / "missing.jsonl"),
            "--profile",
            "bogus-profile-xyz",
            "--dry-run",
        ],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    combined = proc.stdout + proc.stderr
    assert "No module named 'scripts'" not in combined
    assert "unknown profile" in combined


def test_demo_ratings_created_at_matches_trip_ended_at():
    """trip_ratings.created_at must equal the trip ended_at, spreading weekly trends."""
    import json

    from scripts.seed.seed_driver_trips import generate_demo_ratings, generate_demo_trips, map_trip_record

    sample_path = REPO_ROOT / "data" / "benchmark-10k" / "v1" / "sample_100.jsonl"
    with open(sample_path, encoding="utf-8") as f:
        corpus = [map_trip_record(json.loads(line)) for line in f if line.strip()]

    driver_id = "018f2f4e-c000-7000-8000-000000000001"
    demo_trips = generate_demo_trips(corpus_trips=corpus, driver_id=driver_id, count=20, seed=42)
    ratings, _ = generate_demo_ratings(demo_trips=demo_trips, seed=42)

    assert ratings, "expected some rated demo trips"
    ended_by_trip = {t["trip_id"]: (t["ended_at"] or t["started_at"]) for t in demo_trips}
    for r in ratings:
        assert r["created_at"] is not None
        assert r["created_at"] == ended_by_trip[r["trip_id"]]

    # Weekly trend spreads over real trip weeks, not a single seed timestamp.
    weeks = {r["created_at"][:7] for r in ratings}
    assert len(weeks) >= 2, f"ratings must spread across months, got {weeks}"


def test_demo_ratings_never_english_comment_with_vi_locale():
    """Demo comments match the rating locale: vi locale implies Vietnamese text."""
    import json

    from scripts.seed.seed_driver_trips import (
        generate_demo_ratings,
        generate_demo_trips,
        load_feedback_bank,
        map_trip_record,
    )

    bank = load_feedback_bank()
    vi_texts = {
        e.get("text")
        for polarity in bank.values()
        for entries in polarity.values()
        for e in entries
        if e.get("lang") == "vi"
    }
    assert vi_texts, "bank must carry Vietnamese comments"

    sample_path = REPO_ROOT / "data" / "benchmark-10k" / "v1" / "sample_100.jsonl"
    with open(sample_path, encoding="utf-8") as f:
        corpus = [map_trip_record(json.loads(line)) for line in f if line.strip()]

    driver_id = "018f2f4e-c000-7000-8000-000000000001"
    demo_trips = generate_demo_trips(corpus_trips=corpus, driver_id=driver_id, count=60, seed=42)
    ratings, _ = generate_demo_ratings(demo_trips=demo_trips, seed=42, locale="vi")

    commented = [r for r in ratings if r["comment"] is not None]
    assert commented, "expected some commented demo ratings"
    for r in commented:
        assert r["locale"] == "vi", f"demo rating locale must be vi, got {r['locale']}"
        assert r["comment"] in vi_texts, f"non-Vietnamese text with vi locale: {r['comment']!r}"


def test_rating_generator_falls_back_when_no_vi_comment():
    """A bank without vi entries still yields a rating; locale follows the chosen entry."""
    from scripts.seed.seed_driver_trips import RatingGenerator

    bank = {"praise": {"polite": [{"text": "Good ride", "lang": "en"}]}}
    gen = RatingGenerator(seed=7, feedback_bank=bank)
    seen_comment = False
    for i in range(50):
        r = gen.generate_rating(trip_id=f"fallback-{i}", label="no_violation", locale="vi")
        if r["comment"] is not None:
            seen_comment = True
            assert r["locale"] == "en"
            assert r["comment"] == "Good ride"
    assert seen_comment, "expected at least one praise comment in 50 draws"
