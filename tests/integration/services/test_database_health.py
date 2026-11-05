"""Health checks must reflect real database availability."""

from unittest.mock import AsyncMock

import pytest

from src.config import Settings
from src.services.case_service import CaseService

pytestmark = pytest.mark.docker


async def test_database_health_is_disconnected_when_both_backends_fail():
    service = CaseService(Settings(database_url="", supabase_secret_key=""))
    service.supabase.is_connected = AsyncMock(return_value=False)

    assert await service.check_database_health() == "disconnected"
