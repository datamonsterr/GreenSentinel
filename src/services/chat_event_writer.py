"""Ordered case-bound SSE events from actual execution boundaries."""

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


class ChatEventWriter:
    def __init__(
        self,
        *,
        request_id: str,
        case_id: str,
        session_id: str,
        turn_id: str,
        run_id: str | None = None,
        message_id: str | None = None,
    ):
        self.identity = dict(
            request_id=request_id,
            case_id=case_id,
            session_id=session_id,
            turn_id=turn_id,
            run_id=run_id or str(uuid4()),
            message_id=message_id or str(uuid4()),
        )
        self.events: list[dict[str, Any]] = []
        self.pending: dict[str, str] = {}
        self.terminal = False
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def emit(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.terminal:
            raise ValueError("No events may follow terminal state")
        event = dict(
            schema_version="1.1",
            event_id=str(uuid4()),
            sequence=len(self.events),
            timestamp=datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            type=event_type,
            payload=payload,
            **self.identity,
        )
        self.events.append(event)
        self.queue.put_nowait(event)
        if event_type in {"run.completed", "run.error"}:
            self.terminal = True
        return event

    def tool_start(self, tool_id: str, call_id: str) -> None:
        if call_id in self.pending:
            raise ValueError("Duplicate tool invocation")
        self.emit(
            "tool.start", {"tool_id": tool_id, "tool_name": tool_id, "tool_call_id": call_id, "label": "Đang tra cứu"}
        )
        self.pending[call_id] = tool_id

    def tool_end(
        self,
        tool_id: str,
        call_id: str,
        *,
        status: str,
        duration_ms: int,
        summary: str | None = None,
        output: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        if self.pending.get(call_id) != tool_id:
            raise ValueError("Unmatched tool result")
        payload = dict(tool_id=tool_id, tool_name=tool_id, tool_call_id=call_id, status=status, duration_ms=duration_ms)
        if status == "succeeded":
            payload["summary"] = summary or "Đã tra cứu thông tin"
            if output is not None:
                payload["output"] = output
        elif status == "failed" and error:
            payload["error"] = error
        else:
            raise ValueError("Invalid tool result")
        self.emit("tool.end", payload)
        del self.pending[call_id]

    def complete(self, *, status: str = "completed", **details: Any) -> None:
        if self.pending:
            raise ValueError("Run completion leaves tools pending")
        self.emit("run.completed", {"status": status, **details})

    def fail(self, code: str, message: str, retryable: bool) -> None:
        if self.terminal:
            return
        for call_id, tool_id in list(self.pending.items()):
            self.tool_end(
                tool_id,
                call_id,
                status="failed",
                duration_ms=0,
                error={"code": "INTERRUPTED", "message": "Thao tác bị gián đoạn", "retryable": True},
            )
        self.emit("run.error", {"code": code, "message": message, "retryable": retryable})


def encode_sse(event: dict[str, Any]) -> str:
    return f"id: {event['event_id']}\nevent: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False, sort_keys=True)}\n\n"
