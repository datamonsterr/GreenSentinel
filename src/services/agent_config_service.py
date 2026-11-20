"""Agent configuration with PO-set bounds, history/revert and kill switch (PRD-K US7, ADR-032).

Bounds are code constants (PO owned). Values are DB-backed per organisation, optionally per scope
(`global` or `rule:<code>`); a scoped lookup falls back to `global`, then to the default.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from src.services.kb_store import Store, default_store

KSGL_ROLES = frozenset({"analyst", "fraud_analyst", "senior_analyst", "admin"})
VH_ROLES = frozenset({"manager", "reviewer"})
LEAD_ROLES = frozenset({"senior_analyst", "admin", "manager"})  # may flip the kill switch

# key -> definition. owner VH|KSGL decides who may edit; bounds are inclusive.
DEFINITIONS: dict[str, dict[str, Any]] = {
    "explain_agent_enabled": {"type": "bool", "default": False, "owner": "LEAD", "group": "kill_switch",
                              "label": {"vi": "Agent giải trình v2 (kill switch)", "en": "Explanation agent v2 (kill switch)"}},
    "n_max": {"type": "int", "default": 6, "min": 1, "max": 15, "owner": "VH", "group": "limits",
              "label": {"vi": "N_max: số lượt hỏi tối đa / phiên", "en": "N_max: max questions per session"}},
    "k_dynamic": {"type": "int", "default": 3, "min": 0, "max": 5, "owner": "KSGL", "group": "limits",
                  "label": {"vi": "K: số câu động thêm vào form", "en": "K: dynamic form questions"}},
    "t_draft_minutes": {"type": "int", "default": 30, "min": 5, "max": 1440, "owner": "VH", "group": "limits",
                        "label": {"vi": "T: phút giữ nháp phiên", "en": "T: session draft retention (min)"}},
    "edit_limit": {"type": "int", "default": 2, "min": 0, "max": 5, "owner": "KSGL", "group": "limits",
                   "label": {"vi": "Số lần sửa tóm tắt tối đa", "en": "Max summary edits"}},
    "help_sla_minutes": {"type": "int", "default": 15, "min": 1, "max": 240, "owner": "VH", "group": "help",
                         "label": {"vi": "SLA kêu cứu (phút)", "en": "Help request SLA (min)"}},
    "help_ceiling": {"type": "int", "default": 20, "min": 1, "max": 200, "owner": "VH", "group": "help",
                     "label": {"vi": "Trần kêu cứu / ca", "en": "Help ceiling per shift"}},
    "help_max_per_session": {"type": "int", "default": 2, "min": 0, "max": 5, "owner": "VH", "group": "help",
                             "label": {"vi": "Số kêu cứu tối đa / phiên", "en": "Max help requests per session"}},
    "similarity_threshold": {"type": "float", "default": 0.6, "min": 0.1, "max": 0.99, "owner": "KSGL", "group": "thresholds",
                             "label": {"vi": "Ngưỡng tương đồng (novel_scenario)", "en": "Similarity threshold (novel_scenario)"}},
    "confidence_threshold": {"type": "float", "default": 0.7, "min": 0.1, "max": 0.99, "owner": "KSGL", "group": "thresholds",
                             "label": {"vi": "Ngưỡng tin cậy (kêu cứu)", "en": "Confidence threshold (ask for help)"}},
    "scenario_card_memory_enabled": {"type": "bool", "default": False, "owner": "KSGL", "group": "thresholds",
                                     "label": {"vi": "Bộ nhớ thẻ kịch bản", "en": "Scenario card memory"}},
}

REASON_MIN = 3


def _fail(status: int, detail: Any):
    raise HTTPException(status, detail)


def _validate(key: str, value: Any) -> Any:
    d = DEFINITIONS.get(key)
    if d is None:
        _fail(404, f"Unknown config key '{key}'")
    t = d["type"]
    if t == "bool":
        if not isinstance(value, bool):
            _fail(422, f"{key} must be true or false")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(422, f"{key} must be a number")
    if t == "int":
        if isinstance(value, float) and not value.is_integer():
            _fail(422, f"{key} must be an integer")
        value = int(value)
    else:
        value = float(value)
    if value < d["min"] or value > d["max"]:
        _fail(422, f"{key} must be between {d['min']} and {d['max']}")
    return value


def _can_edit(roles: frozenset[str] | set[str], key: str, kill_switch: bool = False) -> bool:
    r = set(roles)
    if "admin" in r:
        return True
    owner = DEFINITIONS[key]["owner"]
    if owner == "LEAD":
        return bool(r & LEAD_ROLES) and kill_switch
    if owner == "VH":
        return bool(r & VH_ROLES)
    return bool(r & {"analyst", "fraud_analyst", "senior_analyst"})


class AgentConfigService:
    def __init__(self, store: Store | None = None):
        self._store = store

    @property
    def store(self) -> Store:
        if self._store is None:
            self._store = default_store()
        return self._store

    # ---- read (used by the explanation agent) -------------------------------------------------
    def get(self, organization_id: str, key: str, scope: str = "global", default: Any = None) -> Any:
        d = DEFINITIONS.get(key)
        if d is None:
            return default
        for sc in ([scope, "global"] if scope != "global" else ["global"]):
            rows = self.store.find("agent_config", {"organization_id": organization_id, "key": key, "scope": sc}, limit=1)
            if rows:
                return rows[0]["value"]
        return d["default"]

    def explain_agent_enabled(self, organization_id: str) -> bool:
        return bool(self.get(organization_id, "explain_agent_enabled"))

    def n_max(self, organization_id: str, scope: str = "global") -> int:
        return int(self.get(organization_id, "n_max", scope))

    def k_dynamic(self, organization_id: str, scope: str = "global") -> int:
        return int(self.get(organization_id, "k_dynamic", scope))

    def t_draft_minutes(self, organization_id: str) -> int:
        return int(self.get(organization_id, "t_draft_minutes"))

    def edit_limit(self, organization_id: str) -> int:
        return int(self.get(organization_id, "edit_limit"))

    def help_ceiling(self, organization_id: str) -> int:
        return int(self.get(organization_id, "help_ceiling"))

    def similarity_threshold(self, organization_id: str, scope: str = "global") -> float:
        return float(self.get(organization_id, "similarity_threshold", scope))

    def confidence_threshold(self, organization_id: str, scope: str = "global") -> float:
        return float(self.get(organization_id, "confidence_threshold", scope))

    # ---- portal API ---------------------------------------------------------------------------
    def _require_read(self, actor: Any) -> None:
        if not set(actor.roles) & (KSGL_ROLES | VH_ROLES):
            _fail(403, "Insufficient role permissions")

    def list_config(self, actor: Any, scope: str = "global") -> dict[str, Any]:
        self._require_read(actor)
        org = actor.organization_id
        items = []
        for key, d in DEFINITIONS.items():
            rows = self.store.find("agent_config", {"organization_id": org, "key": key, "scope": scope}, limit=1)
            items.append({
                "key": key, "type": d["type"], "default": d["default"], "min": d.get("min"), "max": d.get("max"),
                "owner": d["owner"], "group": d["group"], "label": d["label"], "scope": scope,
                "value": rows[0]["value"] if rows else self.get(org, key, scope),
                "is_default": not rows, "updated_at": rows[0]["updated_at"] if rows else None,
                "can_edit": _can_edit(actor.roles, key, kill_switch=key == "explain_agent_enabled"),
            })
        return {"items": items, "metrics": self._metrics()}

    def _metrics(self) -> dict[str, Any]:
        # Placeholders until explanation sessions exist (S-D1 fills these in).
        return {"window_days": 30, "avg_turns": None, "pct_exhausted": None, "pct_help": None, "available": False}

    def history(self, actor: Any, key: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        self._require_read(actor)
        where: dict[str, Any] = {"organization_id": actor.organization_id}
        if key:
            where["key"] = key
        return self.store.find("agent_config_history", where, order="created_at desc", limit=limit)

    def _write(self, actor: Any, key: str, value: Any, reason: str, scope: str, kind: str) -> dict[str, Any]:
        org = actor.organization_id
        rows = self.store.find("agent_config", {"organization_id": org, "key": key, "scope": scope}, limit=1)
        old = rows[0]["value"] if rows else self.get(org, key, scope)
        if rows:
            self.store.update("agent_config", rows[0]["id"], {"value": value, "updated_by": actor.id})
        else:
            self.store.insert("agent_config", {"organization_id": org, "key": key, "scope": scope, "value": value,
                                               "updated_by": actor.id})
        self.store.insert("agent_config_history", {
            "organization_id": org, "key": key, "scope": scope, "old_value": old, "new_value": value,
            "reason": reason, "kind": kind, "changed_by": actor.id,
            "changed_by_name": self.store.principal_name(actor.id)})
        self.store.audit(org, actor.id, f"agent_config.{kind}", {"key": key, "scope": scope, "old": old, "new": value, "reason": reason})
        return {"key": key, "scope": scope, "old_value": old, "value": value}

    def set(self, actor: Any, key: str, value: Any, reason: str, scope: str = "global") -> dict[str, Any]:
        self._require_read(actor)
        if key not in DEFINITIONS:
            _fail(404, f"Unknown config key '{key}'")
        if key == "explain_agent_enabled":
            return self.set_kill_switch(actor, enabled=value, reason=reason, scope=scope)
        if not _can_edit(actor.roles, key):
            _fail(403, f"Role may not change '{key}' (owner {DEFINITIONS[key]['owner']})")
        value = _validate(key, value)
        if len((reason or "").strip()) < REASON_MIN:
            _fail(422, "A reason is required")
        return self._write(actor, key, value, reason.strip(), scope, "change")

    def set_kill_switch(self, actor: Any, enabled: Any, reason: str, scope: str = "global") -> dict[str, Any]:
        self._require_read(actor)
        if not _can_edit(actor.roles, "explain_agent_enabled", kill_switch=True):
            _fail(403, "Only a lead or admin may use the kill switch")
        value = _validate("explain_agent_enabled", enabled)
        if len((reason or "").strip()) < REASON_MIN:
            _fail(422, "A reason is required")
        return self._write(actor, "explain_agent_enabled", value, reason.strip(), scope, "kill_switch")

    def revert(self, actor: Any, history_id: str, reason: str) -> dict[str, Any]:
        self._require_read(actor)
        h = self.store.get("agent_config_history", history_id)
        if not h or str(h["organization_id"]) != str(actor.organization_id):
            _fail(404, "History entry not found")
        key = h["key"]
        if not _can_edit(actor.roles, key, kill_switch=key == "explain_agent_enabled"):
            _fail(403, f"Role may not change '{key}'")
        if len((reason or "").strip()) < REASON_MIN:
            _fail(422, "A reason is required")
        value = _validate(key, h["old_value"])  # bounds may have changed since: re-validate
        return self._write(actor, key, value, reason.strip(), h["scope"], "revert")


_service: AgentConfigService | None = None


def get_agent_config_service() -> AgentConfigService:
    global _service
    if _service is None:
        _service = AgentConfigService()
    return _service
