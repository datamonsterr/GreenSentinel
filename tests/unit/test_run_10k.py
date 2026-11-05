"""Offline boundary and evaluation records are explicit and non-destructive."""

import importlib
import os
import socket

import httpx
import pytest

from scripts.benchmark import run_10k


def test_import_preserves_environment_http_and_socket(monkeypatch):
    monkeypatch.setenv("PROJECT_JEV_API_KEY", "sentinel")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sentinel")
    env = dict(os.environ)
    original = (httpx.AsyncClient.post, httpx.Client.post, socket.socket.connect)
    importlib.reload(run_10k)
    assert dict(os.environ) == env
    assert original == (httpx.AsyncClient.post, httpx.Client.post, socket.socket.connect)
    service = run_10k.build_offline_service()
    assert not service.settings.project_jev_api_key and not service.settings.openrouter_api_key


@pytest.mark.asyncio
async def test_run_blocks_provider_post_and_restores_http():
    original = httpx.AsyncClient.post

    class CallingService:
        async def assess(self, inp):
            async with httpx.AsyncClient() as client:
                await client.post("https://provider.invalid", json={})

    b = {
        "telemetry": [
            {"latitude": 10, "longitude": 106, "accuracy_m": 5, "occurred_at": f"2026-10-01T00:00:{s:02d}Z"}
            for s in (0, 10)
        ]
    }
    with pytest.raises(RuntimeError, match="offline"):
        await run_10k.run_bundles([b], CallingService())
    assert httpx.AsyncClient.post is original


@pytest.mark.asyncio
async def test_records_keep_ground_truth_and_separate_evidence_sufficiency():
    b = {"trip_ref": "ambiguous-stall", "label": "ERR-02", "telemetry": []}
    rows = await run_10k.run_bundles([b], run_10k.build_offline_service())
    assert rows[0]["label"] == "ERR-02"
    assert rows[0]["evidence_sufficiency"] == "blocked"
    assert rows[0]["uncalibrated_model_confidence"] == rows[0]["confidence"]
    metrics = run_10k.compute_metrics(rows, {b["trip_ref"]: b})
    assert metrics["evidence_sufficiency_by_label"]["ERR-02"]["blocked"] == 1


@pytest.mark.asyncio
async def test_sufficiency_is_unknown_for_nonblocked_abstention_but_available_for_observed_cancel():
    points = [
        {"latitude": 10, "longitude": 106, "accuracy_m": 5, "occurred_at": f"2026-10-01T00:00:{s:02d}Z"}
        for s in (0, 10, 20)
    ]
    ambiguous = {
        "trip_ref": "ambiguous-cancel",
        "label": "ERR-01",
        "telemetry": points,
        "trip": {"lifecycle_state": "cancelled", "cancellation_actor": "passenger", "cancellation_reason": "traffic"},
    }
    observed = {
        "trip_ref": "driver-cancel",
        "label": "ERR-01",
        "telemetry": points,
        "trip": {"lifecycle_state": "cancelled", "cancellation_actor": "driver", "cancellation_reason": "unjustified"},
    }
    rows = await run_10k.run_bundles([ambiguous, observed], run_10k.build_offline_service())
    assert rows[0]["predicted_category"] == "insufficient_evidence"
    assert rows[0]["evidence_sufficiency"] == "unknown"
    assert rows[1]["predicted_category"] == "ERR-01"
    assert rows[1]["evidence_sufficiency"] == "available"


def test_analyzer_audits_actual_nested_model_input():
    from scripts.analyze_10k import audit_bundle

    b = {
        "driver_profile": {
            "name": "Driver",
            "profile_provenance": {"origin": "generator"},
            "nested": {"fraud_propensity": 1, "expected_x": 5},
        },
        "conversation": [{"role": "passenger", "text": "hello", "simulation_x": 1}],
        "label": "ERR-02",
    }
    audit = audit_bundle(b)
    assert audit["stored_profile_metadata"]
    assert audit["detector_leak_paths"] == []
    assert audit["label_mutation_input_unchanged"] is True


@pytest.mark.asyncio
async def test_relabeling_does_not_change_prediction():
    b = {"trip_ref": "same", "label": "ERR-02", "driver_profile": {"fraud_propensity": 1}, "telemetry": []}
    changed = {**b, "label": "ERR-05", "driver_profile": {"fraud_propensity": 0}}
    rows = await run_10k.run_bundles([b, changed], run_10k.build_offline_service())
    assert rows[0]["predicted_category"] == rows[1]["predicted_category"]
    assert rows[0]["reason_codes"] == rows[1]["reason_codes"]


@pytest.mark.asyncio
async def test_swallowed_provider_failure_still_fails_offline_run():
    class CallingService:
        async def assess(self, inp):
            try:
                async with httpx.AsyncClient() as client:
                    await client.post("https://provider.invalid")
            except RuntimeError:
                return await run_10k.build_offline_service().assess(inp)

    b = {
        "telemetry": [
            {"latitude": 10, "longitude": 106, "accuracy_m": 5, "occurred_at": f"2026-10-01T00:00:{s:02d}Z"}
            for s in (0, 10)
        ]
    }
    with pytest.raises(RuntimeError, match="offline"):
        await run_10k.run_bundles([b], CallingService())


def test_build_live_service_does_not_strip_provider_keys(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "live-sentinel")
    assert run_10k.build_live_service() is not None


@pytest.mark.asyncio
async def test_live_flag_bypasses_offline_guard(monkeypatch):
    """live=True must not install the offline network guard; default must."""

    async def connect_once(bundles, service, *, enum_blind=False):
        try:
            socket.create_connection(("127.0.0.1", 9), timeout=0.05)
            return "connected"
        except Exception as exc:  # noqa: BLE001 - any failure mode is the point
            return type(exc).__name__

    monkeypatch.setattr(run_10k, "_run_bundles", connect_once)
    with pytest.raises(RuntimeError, match="offline"):
        await run_10k.run_bundles([], None)
    live = await run_10k.run_bundles([], None, live=True)
    assert live != "RuntimeError"  # guard not installed for --live
