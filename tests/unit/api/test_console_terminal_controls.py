from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.api import test_routes
from src.api.auth import Principal
from src.models.test_simulation import TestControlCommand


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["COMPLETED", "FAILED", "CANCELLED"])
@pytest.mark.parametrize("command", ["PAUSE", "RESUME", "CANCEL", "FAST_COMPLETE"])
async def test_terminal_run_rejects_control(monkeypatch, state, command):
    run_id = uuid4()
    runner = SimpleNamespace(
        repository=SimpleNamespace(
            get_run=lambda *_args, **_kwargs: SimpleNamespace(
                status=state, cancellation_actor="driver", cancellation_reason="original"
            )
        )
    )
    monkeypatch.setattr(test_routes, "get_simulation_runner", lambda: runner)
    with pytest.raises(HTTPException) as exc:
        await test_routes.apply_control(
            run_id,
            TestControlCommand(command=command),
            "true",
            Principal("p", "org", frozenset()),
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_repeated_cancel_with_same_evidence_is_idempotent(monkeypatch):
    run_id = uuid4()
    runner = SimpleNamespace(
        repository=SimpleNamespace(
            get_run=lambda *_args, **_kwargs: SimpleNamespace(
                status="CANCELLED", cancellation_actor="driver", cancellation_reason="stalled"
            )
        )
    )
    monkeypatch.setattr(test_routes, "get_simulation_runner", lambda: runner)
    result = await test_routes.apply_control(
        run_id,
        TestControlCommand(command="CANCEL", payload={"actor": "driver", "reason": "stalled"}),
        "true",
        Principal("p", "org", frozenset()),
    )
    assert result == {"status": "accepted", "command": "CANCEL"}
