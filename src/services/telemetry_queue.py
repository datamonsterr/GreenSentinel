"""Small Upstash Redis REST transport and reliable telemetry queue."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx

try:
    import redis
    import redis.asyncio as aioredis
except ImportError:
    redis = None  # type: ignore[assignment]
    aioredis = None  # type: ignore[assignment]


class RedisRestTransport:
    def __init__(self, url: str, token: str, *, client: httpx.AsyncClient | None = None) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.client = client
        self._owned = client is None

    async def command(self, name: str, *args: Any) -> Any:
        client = self.client or httpx.AsyncClient(timeout=10)
        try:
            response = await client.post(
                self.url,
                json=[name, *args],
                headers={"Authorization": f"Bearer {self.token}"},
            )
            response.raise_for_status()
            return response.json().get("result")
        finally:
            if self._owned:
                await client.aclose()


class RedisNativeTransport:
    """Native Redis transport using redis-py (redis.asyncio or redis.Redis via REDIS_URL)."""

    def __init__(self, redis_url: str | None = None, *, client: Any | None = None) -> None:
        if client is not None:
            self.client = client
            self._owned = False
        else:
            url = redis_url or os.getenv("REDIS_URL") or "redis://localhost:6379/0"
            if aioredis is not None:
                self.client = aioredis.from_url(url, decode_responses=True)
            elif redis is not None:
                self.client = redis.from_url(url, decode_responses=True)
            else:
                raise ImportError("redis package is required for RedisNativeTransport")
            self._owned = True

    async def command(self, name: str, *args: Any) -> Any:
        res = self.client.execute_command(name, *args)
        if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
            return await res
        return res

    async def aclose(self) -> None:
        if self._owned and hasattr(self.client, "aclose"):
            await self.client.aclose()


@dataclass(frozen=True)
class QueueItem:
    receipt: str
    payload: dict[str, Any]


class ReliableTelemetryQueue:
    def __init__(
        self,
        transport: RedisRestTransport | RedisNativeTransport | Any | None = None,
        *,
        redis_url: str | None = None,
        prefix: str = "telemetry",
        max_retries: int = 3,
    ) -> None:
        if transport is None:
            self.transport: Any = RedisNativeTransport(redis_url=redis_url)
        elif not hasattr(transport, "command") and hasattr(transport, "execute_command"):
            self.transport = RedisNativeTransport(client=transport)
        else:
            self.transport = transport
        self.ready = f"{prefix}:ready"
        self.processing = f"{prefix}:processing"
        self.deadletter = f"{prefix}:deadletter"
        self.max_retries = max_retries

    @classmethod
    def from_url(
        cls,
        redis_url: str | None = None,
        *,
        prefix: str = "telemetry",
        max_retries: int = 3,
    ) -> ReliableTelemetryQueue:
        url = redis_url or os.getenv("REDIS_URL") or "redis://localhost:6379/0"
        if url.startswith("http://") or url.startswith("https://"):
            token = os.getenv("UPSTASH_REDIS_REST_TOKEN") or os.getenv("REDIS_REST_TOKEN") or ""
            return cls(transport=RedisRestTransport(url, token), prefix=prefix, max_retries=max_retries)
        return cls(transport=RedisNativeTransport(redis_url=url), prefix=prefix, max_retries=max_retries)

    async def enqueue(self, payload: dict[str, Any]) -> str:
        receipt = str(payload.get("event_id") or uuid4())
        envelope = json.dumps({"receipt": receipt, "payload": payload}, separators=(",", ":"))
        await self.transport.command("LPUSH", self.ready, envelope)
        return receipt

    async def claim(self) -> dict[str, Any] | None:
        raw = await self.transport.command("LMOVE", self.ready, self.processing, "RIGHT", "LEFT")
        if not raw:
            return None
        try:
            item = json.loads(raw)
            return {"receipt": str(item["receipt"]), "payload": dict(item["payload"]), "raw": raw}
        except (ValueError, KeyError, TypeError) as exc:
            await self.transport.command("LPUSH", self.deadletter, raw)
            raise ValueError("invalid telemetry queue envelope") from exc

    async def ack(self, item: dict[str, Any] | str) -> None:
        raw = item if isinstance(item, str) else str(item.get("raw") or "")
        if raw:
            await self.transport.command("LREM", self.processing, 1, raw)

    async def fail(self, item: dict[str, Any] | str, error: Exception | str) -> None:
        raw = item if isinstance(item, str) else str(item.get("raw") or "")
        if not raw:
            return
        receipt = str(item.get("receipt")) if isinstance(item, dict) else "unknown"
        retry_key = f"{self.processing}:retries:{receipt}"
        retries = int(await self.transport.command("INCR", retry_key) or 0)
        target = self.deadletter if retries > self.max_retries else self.ready
        await self.transport.command(
            "EVAL",
            "local n=redis.call('LREM',KEYS[1],1,ARGV[1]); if n==1 then redis.call('LPUSH',KEYS[2],ARGV[1]); end; return n",
            2,
            self.processing,
            target,
            raw,
        )
        if retries > self.max_retries:
            await self.transport.command("SET", f"{self.deadletter}:error:{receipt}", str(error))

    async def recover(self) -> int:
        items = await self.transport.command("LRANGE", self.processing, 0, -1) or []
        for raw in items:
            await self.transport.command(
                "EVAL",
                "local n=redis.call('LREM',KEYS[1],1,ARGV[1]); if n==1 then redis.call('LPUSH',KEYS[2],ARGV[1]); end; return n",
                2,
                self.processing,
                self.ready,
                raw,
            )
        return len(items)
