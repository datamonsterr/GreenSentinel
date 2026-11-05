"""RED tests for issue #261: sustained-offline rule (recover 1232 deferred honest).

Defect: ``evaluate_telemetry_window`` aggregates per-point blocks, so ONE
isolated ``network_state == "offline"`` blip blocks the whole window
(``src/services/guardrails.py`` point rule 2 + window loop). Per-point
offline 0.5% x ~40 pts ~= 18% honest deferral; blocked honest carry
offline-share p50 2.7%.

Required post-fix behavior:
- single isolated blip (normal cadence, no gap) -> NOT blocked, flag kept
- sustained offline (consecutive pings) OR gap-correlated (>30 s) -> blocked
- true dropout (all/mostly offline) -> still blocked (deny-by-default)

TDD status (pre-fix): ``test_single_*_not_blocked`` FAIL (single blip
currently blocks). Sustained/gap/dropout tests PASS pre-fix and lock in
deny-by-default so the fix cannot overcorrect into never-blocking.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.services.guardrails import (
    GuardrailReason,
    QualityFlag,
    evaluate_telemetry_point,
    evaluate_telemetry_window,
)

_BASE = datetime(2026, 10, 3, 15, 19, 58, tzinfo=UTC)
_CADENCE = timedelta(seconds=15)


def _pt(ts: datetime, network_state: str = "online", **overrides) -> dict:
    return {
        "latitude": 21.0285,
        "longitude": 105.8542,
        "speed_mps": 8.5,
        "occurred_at": ts.isoformat(),
        "app_state": "foreground",
        "network_state": network_state,
        "gps_state": "valid",
        "mock_location_reported": False,
        **overrides,
    }


def _healthy_window(n: int = 40, start: datetime = _BASE) -> list[dict]:
    return [_pt(start + i * _CADENCE) for i in range(n)]


# --- Core RED: single isolated blip must NOT block -------------------------


def test_single_isolated_blip_does_not_block_window():
    """One offline ping amid healthy 15 s cadence is a blip, not a dropout."""
    points = _healthy_window()
    points[20] = _pt(_BASE + 20 * _CADENCE, network_state="offline")

    result = evaluate_telemetry_window(points)

    assert result.blocked is False
    assert result.reason is None


def test_single_blip_keeps_network_offline_quality_flag():
    """Downgraded blip stays visible for forensics via quality flag."""
    points = _healthy_window()
    points[20] = _pt(_BASE + 20 * _CADENCE, network_state="offline")

    result = evaluate_telemetry_window(points)

    assert QualityFlag.NETWORK_OFFLINE in result.quality_flags


# --- Safety locks: sustained / gap-correlated / true dropout still block ---


def test_sustained_consecutive_offline_blocks_window():
    """Consecutive offline pings are a sustained outage -> block NETWORK_LOSS."""
    points = _healthy_window()
    for i in range(20, 23):
        points[i] = _pt(_BASE + i * _CADENCE, network_state="offline")

    result = evaluate_telemetry_window(points)

    assert result.blocked is True
    assert result.reason == GuardrailReason.NETWORK_LOSS


def test_gap_correlated_single_offline_blocks_window():
    """Isolated offline ping adjacent to a >30 s timestamp gap -> block."""
    points = _healthy_window()
    gap_at = _BASE + 20 * _CADENCE
    points[20] = _pt(gap_at, network_state="offline")
    # telemetry resumes >30 s late after the offline ping
    for i in range(21, 40):
        points[i] = _pt(gap_at + timedelta(seconds=135) + (i - 21) * _CADENCE)

    result = evaluate_telemetry_window(points)

    assert result.blocked is True
    assert result.reason == GuardrailReason.NETWORK_LOSS


def test_gap_correlated_via_data_gap_s_blocks_window():
    """Isolated offline ping carrying data_gap_s > 30 -> block."""
    points = _healthy_window()
    points[20] = _pt(_BASE + 20 * _CADENCE, network_state="offline", data_gap_s=135.0)

    result = evaluate_telemetry_window(points)

    assert result.blocked is True
    assert result.reason == GuardrailReason.NETWORK_LOSS


def test_true_dropout_all_offline_still_blocked():
    """Deny-by-default preserved: full-window outage still blocks."""
    points = [_pt(_BASE + i * _CADENCE, network_state="offline") for i in range(40)]

    result = evaluate_telemetry_window(points)

    assert result.blocked is True
    assert result.reason == GuardrailReason.NETWORK_LOSS


# --- Fix 1+2 probes: co-reason suppression ----------------------------------


def test_isolated_offline_with_gps_unavailable_still_blocks():
    """Suppressed NETWORK_LOSS must not drop co-occurring GPS_UNAVAILABLE."""
    points = _healthy_window()
    points[20] = _pt(_BASE + 20 * _CADENCE, network_state="offline", gps_state="unavailable")

    result = evaluate_telemetry_window(points)

    assert result.blocked is True
    assert result.reason == GuardrailReason.GPS_UNAVAILABLE


def test_isolated_offline_with_invalid_coords_still_blocks():
    """Suppressed NETWORK_LOSS must not drop co-occurring INVALID_TELEMETRY."""
    points = _healthy_window()
    points[20] = _pt(_BASE + 20 * _CADENCE, network_state="offline", latitude=999)

    result = evaluate_telemetry_window(points)

    assert result.blocked is True
    assert result.reason == GuardrailReason.INVALID_TELEMETRY


def test_isolated_offline_with_app_crash_still_blocks():
    """Suppressed NETWORK_LOSS must not drop co-occurring APP_CRASH."""
    points = _healthy_window()
    points[20] = _pt(_BASE + 20 * _CADENCE, network_state="offline", app_state="crashed")

    result = evaluate_telemetry_window(points)

    assert result.blocked is True
    assert result.reason == GuardrailReason.APP_CRASH


# --- Fix 3 probe: mixed naive/aware occurred_at ------------------------------


def test_mixed_naive_aware_occurred_at_does_not_raise():
    """Mixed naive/aware timestamps must not raise; gap decision falls back."""
    points = _healthy_window()
    # aware base timestamps; make offline point naive
    naive_ts = (_BASE + 20 * _CADENCE).replace(tzinfo=None)
    points[20] = _pt(naive_ts, network_state="offline")
    points[20]["occurred_at"] = naive_ts.isoformat()  # naive, no offset
    assert points[21]["occurred_at"].endswith("+00:00")

    result = evaluate_telemetry_window(points)  # must not raise TypeError

    assert result.blocked is False
    assert result.reason is None


def test_mixed_naive_aware_with_data_gap_blocks():
    """With mixed tz but data_gap_s>30, gap evidence still blocks."""
    naive_ts = (_BASE + 20 * _CADENCE).replace(tzinfo=None)
    points = _healthy_window()
    points[20] = _pt(naive_ts, network_state="offline", data_gap_s=135.0)
    points[20]["occurred_at"] = naive_ts.isoformat()

    result = evaluate_telemetry_window(points)

    assert result.blocked is True
    assert result.reason == GuardrailReason.NETWORK_LOSS


# --- Reviewer MINOR lock-ins -------------------------------------------------


def test_lone_network_loss_incident_with_healthy_points_blocks():
    """Lone network_loss incident + healthy points still blocks NETWORK_LOSS."""
    points = _healthy_window()
    incidents = [{"incident_type": "network_loss"}]

    result = evaluate_telemetry_window(points, incidents=incidents)

    assert result.blocked is True
    assert result.reason == GuardrailReason.NETWORK_LOSS


def test_degenerate_single_point_offline_window_blocks():
    """Single-point offline window blocks (deny-by-default)."""
    points = [_pt(_BASE, network_state="offline")]

    result = evaluate_telemetry_window(points)

    assert result.blocked is True
    assert result.reason == GuardrailReason.NETWORK_LOSS


def test_point_level_single_offline_still_blocks():
    """Point-level tripwire preserved: single offline point blocks."""
    pt = _pt(_BASE, network_state="offline")

    result = evaluate_telemetry_point(pt)

    assert result.blocked is True
    assert result.reason == GuardrailReason.NETWORK_LOSS


def test_unparseable_occurred_at_with_data_gap_blocks():
    """Unparseable occurred_at + data_gap_s>30 still blocks via gap fallback."""
    points = _healthy_window()
    points[20] = _pt(
        _BASE + 20 * _CADENCE,
        network_state="offline",
        data_gap_s=135.0,
        occurred_at="not-a-timestamp",
    )

    result = evaluate_telemetry_window(points)

    assert result.blocked is True
    assert result.reason == GuardrailReason.NETWORK_LOSS


def test_non_dict_point_handling_blocks_invalid_telemetry():
    """Non-dict window point is INVALID_TELEMETRY, not a crash."""
    points = _healthy_window()
    points[20] = "not-a-dict"  # type: ignore[list-item]

    result = evaluate_telemetry_window(points)  # type: ignore[arg-type]

    assert result.blocked is True
    assert result.reason == GuardrailReason.INVALID_TELEMETRY


def test_empty_window_blocks_invalid_telemetry():
    """Empty window can never support classification."""
    result = evaluate_telemetry_window([])

    assert result.blocked is True
    assert result.reason == GuardrailReason.INVALID_TELEMETRY
