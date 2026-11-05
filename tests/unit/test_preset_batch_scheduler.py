"""Unit tests for rate scheduler with fake clock and compact snapshot (Issue #458)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.services.test_preset_batch import (
    build_trip_compact_snapshot,
    schedule_rate_limited_batches,
)


def test_build_trip_compact_snapshot():
    """Per-trip compact snapshot extracts conversation, GPS summary, and speed stats."""
    sample_trip_record = {
        "conversation": [
            {"role": "driver", "text": "Toi dang den", "sent_at_offset_s": 5},
            {"role": "customer", "text": "Em doi o cong", "sent_at_offset_s": 12},
        ],
        "telemetry": [
            {
                "latitude": 21.0285,
                "longitude": 105.8524,
                "speed_mps": 0.0,
                "accuracy_m": 4.5,
                "mock_location_reported": False,
            },
            {
                "latitude": 21.0345,
                "longitude": 105.8600,
                "speed_mps": 12.5,
                "accuracy_m": 8.0,
                "mock_location_reported": True,
            },
            {
                "latitude": 21.0400,
                "longitude": 105.8650,
                "speed_mps": 8.0,
                "accuracy_m": 5.0,
                "mock_location_reported": False,
            },
        ],
    }

    snapshot = build_trip_compact_snapshot(sample_trip_record)

    # Conversation preserved
    assert len(snapshot["conversation"]) == 2
    assert snapshot["conversation"][0]["role"] == "driver"

    # GPS summary
    gps = snapshot["gps_summary"]
    assert gps["points"] == 3
    assert gps["mock_location_count"] == 1
    assert gps["max_accuracy_m"] == 8.0
    assert gps["bbox"] == {
        "min_lat": 21.0285,
        "max_lat": 21.0400,
        "min_lon": 105.8524,
        "max_lon": 105.8650,
    }

    # Speed stats
    speed = snapshot["speed_stats"]
    assert speed["min_mps"] == 0.0
    assert speed["max_mps"] == 12.5
    assert speed["avg_mps"] == round((0.0 + 12.5 + 8.0) / 3, 2)


@pytest.mark.asyncio
async def test_schedule_rate_limited_batches_fake_clock():
    """Scheduler processes N trips per X interval using an injected clock / sleeper."""
    items = ["trip-0", "trip-1", "trip-2", "trip-3", "trip-4"]
    processed: list[str] = []
    fake_sleep = AsyncMock()

    async def worker(item: str):
        processed.append(item)

    # 5 trips, 2 per batch, 1.5s interval
    # Batch 0: trip-0, trip-1 -> sleep(1.5)
    # Batch 1: trip-2, trip-3 -> sleep(1.5)
    # Batch 2: trip-4 -> complete (no trailing sleep)
    await schedule_rate_limited_batches(
        items=items,
        trips_per_batch=2,
        interval_s=1.5,
        processor=worker,
        sleeper=fake_sleep,
    )

    assert processed == ["trip-0", "trip-1", "trip-2", "trip-3", "trip-4"]
    assert fake_sleep.call_count == 2
    fake_sleep.assert_called_with(1.5)


@pytest.mark.asyncio
async def test_schedule_rate_limited_batches_cancellation():
    """Cancellation stops pending trips without executing them."""
    items = ["trip-0", "trip-1", "trip-2", "trip-3", "trip-4"]
    processed: list[str] = []
    is_cancelled = False

    def check_cancelled():
        return is_cancelled

    async def worker(item: str):
        nonlocal is_cancelled
        processed.append(item)
        if item == "trip-1":
            # Cancel after first batch
            is_cancelled = True

    fake_sleep = AsyncMock()

    remaining_skipped = await schedule_rate_limited_batches(
        items=items,
        trips_per_batch=2,
        interval_s=1.0,
        processor=worker,
        sleeper=fake_sleep,
        is_cancelled=check_cancelled,
    )

    # Only first batch ran
    assert processed == ["trip-0", "trip-1"]
    # Remaining items returned as skipped
    assert remaining_skipped == ["trip-2", "trip-3", "trip-4"]
    # No sleep occurred after cancellation
    assert fake_sleep.call_count == 0
