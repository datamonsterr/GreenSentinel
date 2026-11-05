"""Deterministic evidence and request bounds at the model input boundary."""

from __future__ import annotations

import json
from typing import Any

TOOL_DATA_MAX_CHARS = 16000
MODEL_CONTEXT_LIMIT = 128000
MAX_OUTPUT_TOKENS = 8192
PROTOCOL_RESERVE = 2048


class ContextBudgetExceededError(ValueError):
    """The current request cannot fit without removing required context."""


def serialized(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def bounded_evidence(
    case_id: str, collection: str, rows: list[dict[str, Any]], summary: dict[str, Any], *, total_samples: int
) -> dict[str, Any]:
    """Keep measured summaries and evenly spaced original records, including endpoints."""
    count = min(len(rows), 64)
    while True:
        indices = [i * (len(rows) - 1) // (count - 1) for i in range(count)] if count > 1 else [0][:count]
        selected = []
        fields_omitted = False
        for index in indices:
            row = {}
            for key, value in rows[index].items():
                size = len(serialized(value))
                if size > 1024:
                    row[key] = {"truncated": True, "original_chars": size}
                    fields_omitted = True
                else:
                    row[key] = value
            selected.append(row)
        data = {
            "case_id": case_id,
            collection: selected,
            "summary": summary,
            "total_samples": total_samples,
            "sampled_from_samples": len(rows),
            "returned_samples": count,
            "truncated": count < total_samples or fields_omitted,
            "sampling": "evenly_spaced_original_records_from_first_2000",
        }
        if len(serialized(data)) <= TOOL_DATA_MAX_CHARS:
            return data
        if count == 0:
            raise ContextBudgetExceededError("Evidence summary exceeds input budget")
        count //= 2


def fit_contents(contents: list[Any], declarations: list[dict[str, Any]], system: str, window: int) -> list[Any]:
    """Bound UTF-8 input bytes conservatively; never claim these are measured tokens.

    Reserve output and protocol capacity, include schemas/system, and keep complete
    call/result exchanges. Overlarge current requests fail locally. Stored history
    and caller-owned content objects are never changed.
    """
    messages = [content.model_copy(deep=True) for content in contents]
    for content in messages:
        for part in content.parts or []:
            response = part.function_response
            if response and len(serialized(response.response)) > TOOL_DATA_MAX_CHARS:
                response.response = {
                    "truncated": True,
                    "original_chars": len(serialized(response.response)),
                    "message": "Tool output omitted because it exceeds the context budget. Narrow the request.",
                }
    limit = min(window, MODEL_CONTEXT_LIMIT) - MAX_OUTPUT_TOKENS - PROTOCOL_RESERVE
    fixed_size = len(system.encode("utf-8")) + len(serialized(declarations).encode("utf-8"))

    def size() -> int:
        # Binary/image inputs also incur provider-specific visual tokens. Reserve
        # capacity per attachment in addition to its serialized byte size.
        image_reserve = sum(
            16384 for content in messages for part in content.parts or [] if part.inline_data or part.file_data
        )
        return (
            fixed_size
            + image_reserve
            + len(serialized([c.model_dump(exclude_none=True) for c in messages]).encode("utf-8"))
        )

    while size() > limit:
        # User text starts a turn. Function responses are part of the preceding
        # turn and must never survive removal of their matching model calls.
        starts = [
            i
            for i, content in enumerate(messages)
            if content.role == "user"
            and any(p.text or p.inline_data or p.file_data for p in content.parts or [])
            and not any(p.function_response for p in content.parts or [])
        ]
        if len(starts) > 1:
            del messages[: starts[1]]
            continue
        # Retain the current query and newest evidence; discard oldest complete
        # tool exchange if the active turn itself has accumulated too much data.
        exchange = next(
            (
                i
                for i in range(1, len(messages) - 2)
                if any(p.function_call for p in messages[i].parts or [])
                and any(p.function_response for p in messages[i + 1].parts or [])
            ),
            None,
        )
        if exchange is None:
            raise ContextBudgetExceededError("Current request exceeds model context budget")
        del messages[exchange : exchange + 2]
    return messages
