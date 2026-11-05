"""Unit tests for Clerk directory client (Issue #464)."""

from __future__ import annotations

import httpx
import pytest

from src.services.clerk_directory import (
    ClerkAPIError,
    ClerkDirectoryClient,
    ClerkSecretMissingError,
    ClerkTimeoutError,
)


@pytest.mark.asyncio
async def test_clerk_secret_missing_raises_error():
    """Missing Clerk secret key raises ClerkSecretMissingError."""
    client = ClerkDirectoryClient(secret_key=None)
    with pytest.raises(ClerkSecretMissingError):
        await client.search_users("test@example.com")

    with pytest.raises(ClerkSecretMissingError):
        await client.get_users_by_ids(["user_123"])


@pytest.mark.asyncio
async def test_clerk_search_users_exact_email():
    """Exact email search queries Clerk API with email_address."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json=[
                {
                    "id": "user_clerk_001",
                    "first_name": "Nguyen",
                    "last_name": "Van A",
                    "email_addresses": [{"id": "idn_1", "email_address": "driver.a@example.com"}],
                    "primary_email_address_id": "idn_1",
                }
            ],
        )
    )

    client = ClerkDirectoryClient(
        secret_key="sk_test_fake_key",
        transport=transport,
    )
    users = await client.search_users("driver.a@example.com")
    assert len(users) == 1
    assert users[0]["id"] == "user_clerk_001"
    assert ClerkDirectoryClient.extract_primary_email(users[0]) == "driver.a@example.com"
    assert ClerkDirectoryClient.extract_display_name(users[0]) == "Nguyen Van A"


@pytest.mark.asyncio
async def test_clerk_search_users_partial_query():
    """Partial search queries Clerk API with query parameter."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json=[
                {
                    "id": "user_clerk_002",
                    "first_name": "Tran",
                    "last_name": "Van B",
                    "email_addresses": [{"id": "idn_2", "email_address": "tran.b@example.com"}],
                    "primary_email_address_id": "idn_2",
                }
            ],
        )
    )

    client = ClerkDirectoryClient(
        secret_key="sk_test_fake_key",
        transport=transport,
    )
    users = await client.search_users("tran")
    assert len(users) == 1
    assert users[0]["id"] == "user_clerk_002"
    assert ClerkDirectoryClient.extract_display_name(users[0]) == "Tran Van B"


@pytest.mark.asyncio
async def test_clerk_get_users_by_ids_batched():
    """Batch lookup fetches users by list of user IDs."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert "user_id=user_1" in str(request.url)
        return httpx.Response(
            200,
            json=[
                {
                    "id": "user_1",
                    "first_name": "Nguyen",
                    "last_name": "One",
                    "email_addresses": [{"id": "idn_1", "email_address": "one@example.com"}],
                    "primary_email_address_id": "idn_1",
                },
                {
                    "id": "user_2",
                    "first_name": "Le",
                    "last_name": "Two",
                    "email_addresses": [{"id": "idn_2", "email_address": "two@example.com"}],
                    "primary_email_address_id": "idn_2",
                },
            ],
        )

    client = ClerkDirectoryClient(
        secret_key="sk_test_fake_key",
        transport=httpx.MockTransport(handler),
    )
    users = await client.get_users_by_ids(["user_1", "user_2"])
    assert len(users) == 2
    assert users[0]["id"] == "user_1"
    assert users[1]["id"] == "user_2"


@pytest.mark.asyncio
async def test_clerk_timeout_handling():
    """Clerk timeout raises ClerkTimeoutError."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("Connection timed out")

    client = ClerkDirectoryClient(
        secret_key="sk_test_fake_key",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ClerkTimeoutError):
        await client.search_users("test@example.com")


@pytest.mark.asyncio
async def test_clerk_api_error_handling():
    """Clerk HTTP error raises ClerkAPIError."""
    transport = httpx.MockTransport(lambda request: httpx.Response(500, json={"error": "internal"}))
    client = ClerkDirectoryClient(
        secret_key="sk_test_fake_key",
        transport=transport,
    )
    with pytest.raises(ClerkAPIError):
        await client.search_users("test@example.com")
