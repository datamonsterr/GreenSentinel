"""Clerk Directory Client for driver search and linked profile resolution (Issue #464).

Privacy & Security Hygiene:
- Never logs emails, usernames, or the secret key.
- Explicit HTTP timeout prevents hanging async workers.
- Fails safe with ClerkSecretMissingError when secret key is unset.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class ClerkDirectoryError(Exception):
    """Base exception for Clerk directory operations."""


class ClerkSecretMissingError(ClerkDirectoryError):
    """Raised when CLERK_SECRET_KEY is not configured."""


class ClerkTimeoutError(ClerkDirectoryError):
    """Raised when Clerk Backend API request times out."""


class ClerkAPIError(ClerkDirectoryError):
    """Raised when Clerk Backend API returns an error response."""


class ClerkDirectoryClient:
    """Lightweight async client for Clerk Backend Users API."""

    def __init__(
        self,
        secret_key: str | None = None,
        base_url: str = "https://api.clerk.com/v1",
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.secret_key = secret_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport

    def _headers(self) -> dict[str, str]:
        if not self.secret_key:
            raise ClerkSecretMissingError("CLERK_SECRET_KEY is missing or empty")
        return {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
        }

    async def search_users(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search Clerk users by email address or query string without logging sensitive parameters."""
        headers = self._headers()
        trimmed_query = query.strip()
        client_kwargs: dict[str, Any] = {"timeout": self.timeout}
        if self.transport is not None:
            client_kwargs["transport"] = self.transport

        async with httpx.AsyncClient(**client_kwargs) as client:
            try:
                # If query contains '@', attempt exact email lookup first
                if "@" in trimmed_query:
                    params: list[tuple[str, Any]] = [("email_address", trimmed_query), ("limit", limit)]
                    resp = await client.get(f"{self.base_url}/users", headers=headers, params=params)
                    resp.raise_for_status()
                    data = resp.json()
                    results = data if isinstance(data, list) else data.get("data", [])
                    if results:
                        return results[:limit]

                # Fall back to query search
                params = [("query", trimmed_query), ("limit", limit)]
                resp = await client.get(f"{self.base_url}/users", headers=headers, params=params)
                resp.raise_for_status()
                data = resp.json()
                results = data if isinstance(data, list) else data.get("data", [])
                return results[:limit]
            except httpx.TimeoutException as exc:
                logger.warning("Clerk API timeout during user search")
                raise ClerkTimeoutError("Clerk API timeout during user search") from exc
            except httpx.HTTPStatusError as exc:
                logger.warning("Clerk API returned HTTP %s during user search", exc.response.status_code)
                raise ClerkAPIError(f"Clerk API error {exc.response.status_code}") from exc
            except Exception as exc:
                if isinstance(exc, (ClerkDirectoryError, ClerkSecretMissingError)):
                    raise
                logger.warning("Clerk API connection failure during user search")
                raise ClerkAPIError(f"Clerk API network failure: {exc}") from exc

    async def get_users_by_ids(self, user_ids: list[str]) -> list[dict[str, Any]]:
        """Fetch Clerk users in batches by their external user IDs."""
        if not user_ids:
            return []
        headers = self._headers()
        client_kwargs: dict[str, Any] = {"timeout": self.timeout}
        if self.transport is not None:
            client_kwargs["transport"] = self.transport

        async with httpx.AsyncClient(**client_kwargs) as client:
            try:
                # Query with repeated user_id params
                params: list[tuple[str, Any]] = [("user_id", uid) for uid in user_ids]
                params.append(("limit", max(len(user_ids), 10)))
                resp = await client.get(f"{self.base_url}/users", headers=headers, params=params)
                resp.raise_for_status()
                data = resp.json()
                results = data if isinstance(data, list) else data.get("data", [])
                return results
            except httpx.TimeoutException as exc:
                logger.warning("Clerk API timeout during batched user lookup")
                raise ClerkTimeoutError("Clerk API timeout during user lookup") from exc
            except httpx.HTTPStatusError as exc:
                logger.warning("Clerk API returned HTTP %s during user lookup", exc.response.status_code)
                raise ClerkAPIError(f"Clerk API error {exc.response.status_code}") from exc
            except Exception as exc:
                if isinstance(exc, (ClerkDirectoryError, ClerkSecretMissingError)):
                    raise
                logger.warning("Clerk API connection failure during user lookup")
                raise ClerkAPIError(f"Clerk API network failure: {exc}") from exc

    @staticmethod
    def extract_primary_email(user: dict[str, Any]) -> str:
        """Extract primary email without inventing an address."""
        primary_id = user.get("primary_email_address_id")
        email_addresses = user.get("email_addresses") or []
        for item in email_addresses:
            if isinstance(item, dict) and item.get("id") == primary_id:
                return str(item.get("email_address") or "").strip()
        if email_addresses and isinstance(email_addresses[0], dict):
            return str(email_addresses[0].get("email_address") or "").strip()
        return ""

    @staticmethod
    def extract_display_name(user: dict[str, Any]) -> str:
        """Extract display name from first/last, username, or email prefix."""
        first = str(user.get("first_name") or "").strip()
        last = str(user.get("last_name") or "").strip()
        full = f"{first} {last}".strip()
        if full:
            return full
        if user.get("username"):
            return str(user["username"]).strip()
        email = ClerkDirectoryClient.extract_primary_email(user)
        if email:
            return email.split("@")[0]
        return str(user.get("id") or "Driver")
