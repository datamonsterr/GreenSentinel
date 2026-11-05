"""Queue contract and durable processing regression tests."""

import copy
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest

from src.config import Settings
from src.services import telemetry_queue_worker as worker
from src.services.case_service import CaseService

pytestmark = pytest.mark.docker


def event():
    return {
        "event_id": str(uuid4()),
        "trip_id": str(uuid4()),
        "assignment_id": str(uuid4()),
        "driver_id": "018f2f4e-3000-7000-8000-000000000001",
        "pickup": [105.852, 21.027],
        "dropoff": [105.854, 21.028],
        "points": [
            {"longitude": 105.851, "latitude": 21.026, "occurred_at": "2026-09-20T08:00:00Z", "speed_mps": 8},
            {"longitude": 105.852, "latitude": 21.027, "occurred_at": "2026-09-20T08:01:00Z", "speed_mps": 8},
            {"longitude": 105.854, "latitude": 21.028, "occurred_at": "2026-09-20T08:02:00Z", "speed_mps": 8},
        ],
    }


def service():
    result = CaseService(Settings(database_url=""))
    return result


async def test_normal_trip_does_not_create_fraud_case_and_replay_is_idempotent():
    svc = service()
    payload = event()
    before = len(svc._cases)
    first = await worker.process_telemetry_event(payload, svc)
    second = await worker.process_telemetry_event(payload, svc)
    assert first["case_id"] is None
    assert second == first
    assert len(svc._cases) == before
    points = [p for p in svc._telemetry_points if p["assignment_id"] == payload["assignment_id"]]
    assert len(points) == 3
    assert [p["occurred_at"] for p in points] == [p["occurred_at"] for p in payload["points"]]
    assert svc._trips[payload["trip_id"]]["pickup"]["coordinates"] == payload["pickup"]


async def test_persistence_failure_propagates_without_mutating_cache():
    svc = service()
    payload = event()
    svc._get_db_connection = MagicMock(return_value=MagicMock())
    svc._get_db_connection.return_value.cursor.side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError):
        await worker.process_telemetry_event(payload, svc)
    assert payload["trip_id"] not in svc._trips


async def test_reused_event_id_with_changed_payload_rejected():
    svc = service()
    payload = event()
    await worker.process_telemetry_event(payload, svc)
    changed = copy.deepcopy(payload)
    changed["points"][0]["speed_mps"] = 9
    with pytest.raises(ValueError, match="different payload"):
        await worker.process_telemetry_event(changed, svc)


async def test_rest_transport_sends_auth_header_not_url():
    from src.services.telemetry_queue import RedisRestTransport

    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"result": 1})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        transport = RedisRestTransport("https://example.upstash.io", "private", client=client)
        assert await transport.command("LPUSH", "jobs", "{}") == 1
    assert requests[0].headers["authorization"] == "Bearer private"
    assert "private" not in str(requests[0].url)


async def test_worker_acknowledges_only_after_success_and_retries_failures():
    from src.services.telemetry_queue import ReliableTelemetryQueue

    queue = MagicMock(spec=ReliableTelemetryQueue)
    queue.claim = AsyncMock(return_value={"receipt": "abc", "payload": event()})
    queue.ack = AsyncMock()
    queue.fail = AsyncMock()
    queue.recover = AsyncMock()
    process = AsyncMock(side_effect=RuntimeError("db down"))
    consumer = worker.TelemetryQueueWorker(queue=queue, processor=process)
    assert await consumer.run_once() == []
    queue.ack.assert_not_awaited()
    queue.fail.assert_awaited_once()
    process.side_effect = None
    process.return_value = {"status": "processed"}
    assert await consumer.run_once() == [{"status": "processed"}]
    queue.ack.assert_awaited_once()


async def test_native_redis_transport_and_worker_client(monkeypatch):
    from src.services.telemetry_queue import RedisNativeTransport, ReliableTelemetryQueue

    mock_client = AsyncMock()
    mock_client.execute_command = AsyncMock(return_value="OK")
    transport = RedisNativeTransport(client=mock_client)
    res = await transport.command("SET", "key", "val")
    assert res == "OK"
    mock_client.execute_command.assert_awaited_once_with("SET", "key", "val")

    # Queue with native transport
    queue = ReliableTelemetryQueue(transport=transport)
    assert queue.transport == transport

    # ReliableTelemetryQueue.from_url native
    q_native = ReliableTelemetryQueue.from_url("redis://localhost:6379/0")
    assert isinstance(q_native.transport, RedisNativeTransport)

    # Worker get_client with REDIS_URL
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/1")
    consumer = worker.TelemetryQueueWorker()
    client = consumer.get_client()
    assert client is not None
    # Client should point to db 1
    assert client.connection_pool.connection_kwargs.get("db") == 1
