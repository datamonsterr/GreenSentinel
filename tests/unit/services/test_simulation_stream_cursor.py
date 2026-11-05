"""Reconnects replay only unseen events; missing cursors require REST reconciliation."""

from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest

from src.config import Settings
from src.models.test_simulation import TestStreamEvent as StreamEvent
from src.services.test_simulation_repository import TestSimulationRepository as Repository
from src.services.test_simulation_runner import SimulationRunner


@pytest.mark.asyncio
async def test_stream_cursor_replays_only_events_after_acknowledged_id():
    settings = Settings(app_env="test", test_database_url="")
    runner = SimulationRunner(repository=Repository(settings), settings=settings)
    run_id = uuid4()
    first, second = [
        StreamEvent(event_type="step.progress", run_id=run_id, step_index=i, simulation_clock=datetime.now(UTC))
        for i in range(2)
    ]
    await runner.broadcast_event(run_id, first)
    await runner.broadcast_event(run_id, second)
    queue = runner.subscribe_stream(run_id, last_event_id=str(first.event_id))
    assert queue.get_nowait() == second
    assert queue.empty()


@pytest.mark.asyncio
async def test_stream_emits_stable_sse_id_and_passes_cursor_after_ownership_check(monkeypatch):
    from src.api import test_routes
    from src.api.auth import Principal

    settings = Settings(app_env="test", test_database_url="")
    runner = SimulationRunner(repository=Repository(settings), settings=settings)
    run_id = uuid4()
    first, last = [
        StreamEvent(event_type=kind, run_id=run_id, step_index=i, simulation_clock=datetime.now(UTC))
        for i, kind in enumerate(["step.progress", "run.completed"])
    ]
    await runner.broadcast_event(run_id, first)
    await runner.broadcast_event(run_id, last)
    get_run = Mock(return_value=object())
    monkeypatch.setattr(runner.repository, "get_run", get_run)
    monkeypatch.setattr(test_routes, "get_simulation_runner", lambda: runner)
    response = await test_routes.stream_run_events(
        run_id, "true", Principal("member", "org-a", frozenset()), str(first.event_id), None
    )
    frames = [frame async for frame in response.body_iterator]
    get_run.assert_called_once_with(run_id, organization_id="org-a")
    assert len(frames) == 2  # connect + unseen terminal event
    assert f"id: {last.event_id}\n" in frames[1]
    assert '"organization_id": "org-a"' in frames[1]
    assert str(first.event_id) not in frames[1]
    assert runner._event_subscribers[run_id] == []


@pytest.mark.asyncio
async def test_unknown_cursor_replays_available_history_for_dedup_and_reconciliation():
    settings = Settings(app_env="test", test_database_url="")
    runner = SimulationRunner(repository=Repository(settings), settings=settings)
    run_id = uuid4()
    event = StreamEvent(event_type="run.completed", run_id=run_id, step_index=5, simulation_clock=datetime.now(UTC))
    await runner.broadcast_event(run_id, event)
    queue = runner.subscribe_stream(run_id, last_event_id=str(uuid4()))
    assert queue.get_nowait() == event
    assert queue.empty()
