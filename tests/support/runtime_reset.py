"""Reset process-global runtime state between isolated test boundaries."""

from src.config import get_settings


def reset_runtime_state() -> None:
    """Drop lazy service instances and executor state created by a test."""
    from src.agents import driver_agent
    from src.services import case_service, driver_dispute_service, jev_precedent_service, tool_execution

    tool_execution._workflow_service = None
    case_service._case_service_instance = None
    driver_dispute_service._driver_dispute_service_instance = None
    jev_precedent_service._jev_precedent_service_instance = None
    driver_agent._cached_driver_graph = None
    get_settings.cache_clear()
