from typing import Any

import httpx

from src.config import Settings, get_settings


class SupabaseRestClient:
    """Async PostgREST client for Supabase."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.base_url = self.settings.supabase_rest_url.rstrip("/")
        self.api_key = self.settings.supabase_secret_key
        self.headers = {
            "apikey": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    async def is_connected(self) -> bool:
        """Check if Supabase PostgREST or local endpoint is reachable."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(f"{self.base_url}/", headers=self.headers)
                return res.status_code in (200, 404, 406)
        except Exception:
            return False

    async def get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        async with httpx.AsyncClient(timeout=5.0) as client:
            return await client.get(url, headers=self.headers, params=params)

    async def post(self, path: str, data: Any) -> httpx.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        async with httpx.AsyncClient(timeout=5.0) as client:
            return await client.post(url, headers=self.headers, json=data)

    async def patch(self, path: str, data: Any, params: dict[str, Any] | None = None) -> httpx.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        async with httpx.AsyncClient(timeout=5.0) as client:
            return await client.patch(url, headers=self.headers, json=data, params=params)
