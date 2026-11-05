from unittest.mock import MagicMock

from src.config import Settings
from src.services.case_service import CaseService


def test_list_simulation_actors_scopes_owned_rows_and_published_policies():
    service = CaseService(settings=Settings(app_env="test", database_url="postgres://unused"))
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.side_effect = [
        [{"id": "d-a", "display_name": "Driver A"}],
        [{"id": "p-a", "display_name": "Passenger A"}],
        [{"id": "v-a", "display_name": "Vehicle A"}],
        [{"id": "pol-1", "display_name": "2026.1"}],
    ]
    service._get_db_connection = lambda: conn  # type: ignore[method-assign]

    result = service.list_simulation_actors("org-a")

    assert result == {
        "drivers": [{"id": "d-a", "display_name": "Driver A"}],
        "passengers": [{"id": "p-a", "display_name": "Passenger A"}],
        "vehicles": [{"id": "v-a", "display_name": "Vehicle A"}],
        "policies": [{"id": "pol-1", "display_name": "2026.1"}],
    }
    assert cur.execute.call_count == 4
    assert cur.execute.call_args_list[0].args[1] == ("org-a",)
    assert cur.execute.call_args_list[1].args[1] == ("org-a",)
    assert cur.execute.call_args_list[2].args[1] == ("org-a",)
    assert "status = 'published'" in cur.execute.call_args_list[3].args[0]


def test_list_simulation_actors_returns_empty_explicitly_when_test_db_unavailable():
    service = CaseService(settings=Settings(app_env="test", database_url=""))
    assert service.list_simulation_actors("org-a") == {"drivers": [], "passengers": [], "vehicles": [], "policies": []}
