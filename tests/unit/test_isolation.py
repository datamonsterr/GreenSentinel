import os

from src.services import case_service, jev_precedent_service, tool_execution
from src.services.case_service import get_case_service
from tests.support.runtime_reset import reset_runtime_state


def test_unit_scope_fails_closed_for_backends():
    service = get_case_service()

    assert os.environ["DATABASE_URL"] == ""
    assert os.environ["REDIS_URL"] == ""
    assert os.environ["QDRANT_URL"] == ""
    assert service._get_db_connection() is None
    assert service.get_redis_client() is None


def test_runtime_state_reset_clears_test_constructed_service_and_singletons():
    tool_execution.set_workflow_service(object())
    case_service._case_service_instance = object()
    jev_precedent_service._jev_precedent_service_instance = object()
    reset_runtime_state()

    assert tool_execution._workflow_service is None
    assert case_service._case_service_instance is None
    assert jev_precedent_service._jev_precedent_service_instance is None
