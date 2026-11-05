"""Unit contracts for driver case list serialization (PR #503 review fix).

`DriverCaseSessionItem.dispute_deadline` must only ever be ISO 8601 or
``None``. No ``str()`` fallback that could emit a non-ISO repr (e.g. a raw
Python object's ``str()``) is allowed.
"""

from types import SimpleNamespace

from src.config import Settings
from src.services.driver_dispute_service import DriverDisputeService


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, query, params=None):
        pass

    def fetchall(self):
        return self._rows


def _make_service(rows):
    settings = Settings(app_env="production")
    service = DriverDisputeService(case_service=SimpleNamespace(settings=settings, _cases={}, _assignments={}))
    service._get_db_connection = lambda: SimpleNamespace(cursor=lambda: _Cursor(rows), close=lambda: None)
    return service


async def test_dispute_deadline_is_none_when_db_value_is_null():
    rows = [
        {
            "id": "018f2f4e-a000-7000-8000-000000001234",
            "assignment_id": None,
            "suspected_category": "ERR-01",
            "status": "open",
            "dispute_status": "not_disputed",
            "dispute_deadline": None,
            "created_at": "2026-01-01T00:00:00+00:00",
            "driver_id": "drv-1",
            "driver_name": "Driver One",
            "trip_id": "trip-1",
            "pickup_address": "Addr",
            "dropoff_address": "Addr2",
            "vehicle_plate": "29A-123.45",
        }
    ]
    service = _make_service(rows)

    result = await service.list_driver_cases(driver_id="drv-1", organization_id="org-1")

    assert len(result.items) == 1
    item = result.items[0]
    assert item.status == "open"
    assert item.dispute_deadline is None


async def test_dispute_deadline_serializes_as_iso8601_when_present():
    rows = [
        {
            "id": "018f2f4e-a000-7000-8000-000000005678",
            "assignment_id": None,
            "suspected_category": "ERR-02",
            "status": "investigating",
            "dispute_status": "in_dispute",
            "dispute_deadline": "2026-02-01T10:00:00+00:00",
            "created_at": "2026-01-01T00:00:00+00:00",
            "driver_id": "drv-1",
            "driver_name": "Driver One",
            "trip_id": "trip-1",
            "pickup_address": "Addr",
            "dropoff_address": "Addr2",
            "vehicle_plate": "29A-123.45",
        }
    ]
    service = _make_service(rows)

    result = await service.list_driver_cases(driver_id="drv-1", organization_id="org-1")

    item = result.items[0]
    assert item.status == "investigating"
    assert item.dispute_deadline == "2026-02-01T10:00:00+00:00"


async def test_dispute_deadline_never_falls_back_to_raw_str_of_unexpected_type():
    """A non-datetime, non-string DB value must become None, not str(value)."""

    class _WeirdDbValue:
        def __str__(self):
            return "<WeirdDbValue object>"

    rows = [
        {
            "id": "018f2f4e-a000-7000-8000-000000009999",
            "assignment_id": None,
            "suspected_category": "ERR-01",
            "status": "open",
            "dispute_status": "not_disputed",
            "dispute_deadline": _WeirdDbValue(),
            "created_at": "2026-01-01T00:00:00+00:00",
            "driver_id": "drv-1",
            "driver_name": "Driver One",
            "trip_id": "trip-1",
            "pickup_address": "Addr",
            "dropoff_address": "Addr2",
            "vehicle_plate": "29A-123.45",
        }
    ]
    service = _make_service(rows)

    result = await service.list_driver_cases(driver_id="drv-1", organization_id="org-1")

    item = result.items[0]
    assert item.dispute_deadline is None
