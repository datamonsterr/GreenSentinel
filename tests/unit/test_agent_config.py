from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.services import agent_config_service as acs
from src.services.agent_config_service import AgentConfigService
from src.services.kb_store import MemoryStore

ORG = "org-1"


def who(role, pid="u"):
    return SimpleNamespace(id=pid, organization_id=ORG, roles=frozenset({role}))


ANALYST, ADMIN, VH, DRIVER = who("fraud_analyst", "a"), who("admin", "b"), who("manager", "m"), who("driver", "d")


@pytest.fixture()
def cfg():
    return AgentConfigService(MemoryStore())


def test_defaults_and_kill_switch_off_by_default(cfg):
    assert cfg.get(ORG, "n_max") == 6
    assert cfg.get(ORG, "k_dynamic") == 3
    assert cfg.explain_agent_enabled(ORG) is False
    assert cfg.get(ORG, "unknown_key", default="d") == "d"


def test_getters_for_downstream_slice(cfg):
    assert cfg.n_max(ORG) >= 1 and cfg.k_dynamic(ORG) >= 0 and cfg.t_draft_minutes(ORG) > 0
    assert cfg.edit_limit(ORG) >= 0 and cfg.help_ceiling(ORG) >= 1
    assert 0 < cfg.similarity_threshold(ORG) <= 1


def test_list_includes_bounds_owner_and_metrics(cfg):
    out = cfg.list_config(ANALYST)
    n = next(i for i in out["items"] if i["key"] == "n_max")
    assert n["min"] == 1 and n["max"] > n["min"] and n["owner"] == "VH" and n["value"] == 6
    assert out["metrics"]["window_days"] == 30


def test_change_records_history_and_applies(cfg):
    cfg.set(ADMIN, "n_max", 4, reason="tighten")
    assert cfg.get(ORG, "n_max") == 4
    h = cfg.history(ADMIN, key="n_max")
    assert h[0]["old_value"] == 6 and h[0]["new_value"] == 4 and h[0]["reason"] == "tighten"


def test_bounds_enforced(cfg):
    for bad in (0, 99, "x", 2.5, True):
        with pytest.raises(HTTPException) as e:
            cfg.set(ADMIN, "n_max", bad, reason="x")
        assert e.value.status_code == 422
    with pytest.raises(HTTPException):
        cfg.set(ADMIN, "similarity_threshold", 1.5, reason="x")
    with pytest.raises(HTTPException):
        cfg.set(ADMIN, "explain_agent_enabled", "yes", reason="x")


def test_reason_required(cfg):
    with pytest.raises(HTTPException) as e:
        cfg.set(ADMIN, "n_max", 4, reason="")
    assert e.value.status_code == 422


def test_owner_permissions(cfg):
    cfg.set(ANALYST, "k_dynamic", 2, reason="ksgl owns K")
    with pytest.raises(HTTPException) as e:  # N_max is owned by VH
        cfg.set(ANALYST, "n_max", 4, reason="x")
    assert e.value.status_code == 403
    cfg.set(VH, "n_max", 5, reason="vh owns n_max")
    with pytest.raises(HTTPException):
        cfg.set(VH, "k_dynamic", 1, reason="x")
    with pytest.raises(HTTPException):
        cfg.set(DRIVER, "n_max", 5, reason="x")
    with pytest.raises(HTTPException):
        cfg.list_config(DRIVER)


def test_kill_switch_and_history(cfg):
    out = cfg.set_kill_switch(ADMIN, enabled=True, reason="pilot start")
    assert out["value"] is True and cfg.explain_agent_enabled(ORG) is True
    cfg.set_kill_switch(ADMIN, enabled=False, reason="incident")
    assert cfg.explain_agent_enabled(ORG) is False
    h = cfg.history(ADMIN, key="explain_agent_enabled")
    assert [x["kind"] for x in h] == ["kill_switch", "kill_switch"]
    with pytest.raises(HTTPException):
        cfg.set_kill_switch(ANALYST, enabled=True, reason="analyst is not a lead")


def test_revert_to_previous(cfg):
    cfg.set(ADMIN, "n_max", 4, reason="first")
    cfg.set(ADMIN, "n_max", 3, reason="second")
    h = cfg.history(ADMIN, key="n_max")
    cfg.revert(ADMIN, h[0]["id"], reason="undo b")
    assert cfg.get(ORG, "n_max") == 4
    assert cfg.history(ADMIN, key="n_max")[0]["kind"] == "revert"


def test_scope_falls_back_to_global(cfg):
    cfg.set(ADMIN, "n_max", 4, reason="global")
    cfg.set(ADMIN, "n_max", 2, reason="rule", scope="rule:ERR-02")
    assert cfg.get(ORG, "n_max", scope="rule:ERR-02") == 2
    assert cfg.get(ORG, "n_max", scope="rule:ERR-05") == 4


def test_bounds_table_sane():
    for d in acs.DEFINITIONS.values():
        if d["type"] in ("int", "float"):
            assert d["min"] <= d["default"] <= d["max"]


def test_metrics_only_count_sessions_from_last_30_days(cfg):
    now = datetime.now(UTC)

    def session(age_days, turns):
        cfg.store.insert(
            "explain_session",
            {
                "organization_id": ORG,
                "case_id": f"c{age_days}",
                "mode": "agent",
                "state": "submitted",
                "turns_used": turns,
                "ai_inconclusive": False,
                "asked_for_help": False,
                "created_at": now - timedelta(days=age_days),
            },
        )

    session(100, 6)
    m = cfg.list_config(ANALYST)["metrics"]
    assert m["available"] is False
    session(5, 2)
    m = cfg.list_config(ANALYST)["metrics"]
    assert m["available"] is True and m["sessions"] == 1 and m["avg_turns"] == 2
