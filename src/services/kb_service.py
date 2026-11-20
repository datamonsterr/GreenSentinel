"""Knowledge base service (PRD-K, ADR-032): versioned kb objects, lifecycle, 4-eyes publish,
policy documents, proposals queue, agent registry and demo seed.

Agents read only `published` rows through `get_published` / `list_published`. Humans act through the
portal routes; every mutation writes an audit event (`app.audit_events`).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from src.services.kb_formula import (
    PARAMETER_CATALOGUE,
    FormulaError,
    evaluate_formula,
    validate_formula,
)
from src.services.kb_similarity import SimilarityScorer, default_scorer, indexing_status_for_new_document
from src.services.kb_store import Store, default_store

TYPES = ("parameter", "motive", "behavior", "scenario", "workflow")
STATUSES = ("draft", "ready_for_test", "trial", "published", "retired")
KSGL_ROLES = frozenset({"analyst", "fraud_analyst", "senior_analyst", "admin"})
APPROVER_ROLES = frozenset({"senior_analyst", "admin"})
AUTHOR_ROLES = KSGL_ROLES
GATE_MIN_COMPUTABLE = 0.5  # replay gate: share of cases the object can be computed on
REJECT_REASONS = ("wrong_source", "wrong_motive", "duplicate", "out_of_scope", "other")
PROPOSAL_SOURCES = ("policy_analysis", "help_reply", "closed_case", "monitoring", "manual")

# Tools a kb_workflow step may call (PRD-K 8.4, driver-agent tools only).
TOOL_CATALOGUE = ("identify_behavior", "list_motives", "compute_motive", "match_scenario", "get_workflow",
                  "request_help", "propose_knowledge")
_FORBIDDEN = re.compile(r"mức phạt|truy thu|hướng xử lý|\bphạt\b|\bfines?\b|\bpenalt(?:y|ies)\b|\bclawback\b", re.IGNORECASE)
_CODE = re.compile(r"^[A-Za-z0-9_.-]{2,64}$")

AGENTS = [
    {"id": "driver_agent", "name": {"vi": "Agent giải trình tài xế", "en": "Driver explanation agent"},
     "instruction_version": "driver-explain@2.0.0", "model": "z-ai/glm-5.3-flash", "controlled_by": "explain_agent_enabled",
     "knowledge_types": ["motive", "behavior", "scenario", "workflow"], "uses_policy_documents": False,
     "tools": ["identify_behavior", "list_motives", "compute_motive", "match_scenario", "get_workflow", "request_help", "propose_knowledge"],
     "memory_layers": ["session", "knowledge_base", "proposal_queue"], "reads": "published"},
    {"id": "policy_analysis_agent", "name": {"vi": "Agent phân tích tri thức", "en": "Knowledge analysis agent"},
     "instruction_version": "policy-analysis@1.0.0", "model": "z-ai/glm-5.3-flash", "controlled_by": None,
     "knowledge_types": ["parameter", "motive", "behavior", "scenario", "workflow"], "uses_policy_documents": True,
     "tools": ["extract_payout_rules", "search_knowledge", "list_parameters", "propose_knowledge", "replay_cases"],
     "memory_layers": ["knowledge_base", "proposal_queue"], "reads": "published"},
    {"id": "monitoring_agent", "name": {"vi": "Agent giám sát", "en": "Monitoring agent"},
     "instruction_version": "monitoring@1.0.0", "model": "z-ai/glm-5.3-flash", "controlled_by": None,
     "knowledge_types": ["motive", "behavior", "workflow"], "uses_policy_documents": False,
     "tools": ["search_knowledge", "propose_knowledge"], "memory_layers": ["knowledge_base", "proposal_queue"], "reads": "published",
     "status": "planned"},
]


def _fail(status: int, detail: Any):
    raise HTTPException(status, detail)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _strings(v: Any) -> list[str]:
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        return [s for x in v.values() for s in _strings(x)]
    if isinstance(v, (list, tuple)):
        return [s for x in v for s in _strings(x)]
    return []


def validate_body(type_: str, body: dict[str, Any], name: str = "") -> list[dict[str, Any]]:
    """Return a list of {path, code, message}; empty means valid."""
    errs: list[dict[str, Any]] = []

    def add(path: str, code: str, message: str, position: int | None = None):
        errs.append({"path": path, "code": code, "message": message, **({"position": position} if position is not None else {})})

    if not isinstance(body, dict):
        return [{"path": "body", "code": "invalid", "message": "Body must be an object"}]
    for s in [name, *_strings(body)]:
        if _FORBIDDEN.search(s):
            add("body", "forbidden_content", "Knowledge must not contain fines, clawbacks or handling directions")
            break

    def formula(path: str, key: str):
        f = body.get(key)
        if not isinstance(f, str) or not f.strip():
            add(path, "required", "Formula is required")
            return
        r = validate_formula(f)
        for e in r["errors"]:
            add(path, e["code"], e["message"], e.get("position"))

    if type_ == "motive":
        formula("body.formula", "formula")
    elif type_ == "behavior":
        formula("body.condition", "condition")
        for sig in body.get("signals") or []:
            if sig not in PARAMETER_CATALOGUE:
                add("body.signals", "unknown_param", f"Unknown parameter '{sig}'")
    elif type_ == "scenario":
        for k in ("motive_code", "behavior_code", "workflow_code"):
            if not isinstance(body.get(k), str) or not body[k].strip():
                add(f"body.{k}", "required", f"{k} is required")
    elif type_ == "workflow":
        if not isinstance(body.get("ask_first", []), list):
            add("body.ask_first", "invalid", "ask_first must be a list")
        steps = body.get("steps", [])
        if not isinstance(steps, list):
            add("body.steps", "invalid", "steps must be a list")
            steps = []
        for i, st in enumerate(steps):
            if not isinstance(st, dict) or not str(st.get("question", "")).strip():
                add(f"body.steps[{i}]", "required", "Step needs a question")
                continue
            tool = st.get("tool")
            if tool and tool not in TOOL_CATALOGUE:
                add(f"body.steps[{i}].tool", "unknown_tool", f"Tool '{tool}' is not in the tool catalogue")
    elif type_ == "parameter":
        for k in ("unit", "source"):
            if not str(body.get(k, "")).strip():
                add(f"body.{k}", "required", f"{k} is required")
    return errs


class KbService:
    def __init__(self, store: Store | None = None, scorer: SimilarityScorer | None = None, config: Any = None):
        self._store = store
        self.scorer = scorer or default_scorer()
        self._config = config

    @property
    def store(self) -> Store:
        if self._store is None:
            self._store = default_store()
        return self._store

    # ---- helpers ------------------------------------------------------------------------------
    @staticmethod
    def _require(actor: Any, roles: frozenset[str], what: str = "Insufficient role permissions") -> None:
        if not set(actor.roles) & roles:
            _fail(403, what)

    def _load(self, actor: Any, object_id: str) -> dict[str, Any]:
        o = self.store.get("kb_object", object_id)
        if not o or str(o["organization_id"]) != str(actor.organization_id):
            _fail(404, "Knowledge object not found")
        return o

    def _hist(self, o: dict[str, Any], actor: Any, action: str, note: str = "") -> list[dict[str, Any]]:
        entry = {"at": _now(), "by": actor.id, "by_name": self.store.principal_name(actor.id), "action": action, "note": note}
        return [*(o.get("history") or []), entry]

    def _save(self, o: dict[str, Any], actor: Any, action: str, patch: dict[str, Any], note: str = "",
              expect: str | tuple[str, ...] | None = None) -> dict[str, Any]:
        patch = {**patch, "history": self._hist(o, actor, action, note)}
        where = {"status": list(expect) if isinstance(expect, tuple) else expect} if expect else None
        out = self.store.update("kb_object", o["id"], patch, where=where)
        if out is None:
            _fail(409, "Object changed concurrently; reload and retry")
        self.store.audit(o["organization_id"], actor.id, f"kb.object.{action}",
                         {"object_id": o["id"], "type": o["type"], "code": o["code"], "version": o["version"], "note": note})
        return out

    # ---- agent-facing read API (S-D1) ---------------------------------------------------------
    def get_published(self, organization_id: str, type_: str, code: str) -> dict[str, Any] | None:
        rows = self.store.find("kb_object", {"organization_id": organization_id, "type": type_, "code": code, "status": "published"}, limit=1)
        return rows[0] if rows else None

    def list_published(self, organization_id: str, type_: str) -> list[dict[str, Any]]:
        rows = self.store.find("kb_object", {"organization_id": organization_id, "type": type_, "status": "published"}, order="code asc")
        return rows

    # ---- CRUD ---------------------------------------------------------------------------------
    def list_objects(self, actor: Any, type: str | None = None, status: str | None = None, q: str | None = None) -> list[dict[str, Any]]:
        self._require(actor, KSGL_ROLES)
        where: dict[str, Any] = {"organization_id": actor.organization_id}
        if type:
            where["type"] = type
        if status:
            where["status"] = status
        rows = self.store.find("kb_object", where, order="code asc, version desc")
        if q:
            ql = q.lower()
            rows = [r for r in rows if ql in f"{r['code']} {r['name']}".lower()]
        return rows

    def get_object(self, actor: Any, object_id: str) -> dict[str, Any]:
        self._require(actor, KSGL_ROLES)
        return self._load(actor, object_id)

    def versions(self, actor: Any, type_: str, code: str) -> list[dict[str, Any]]:
        self._require(actor, KSGL_ROLES)
        return self.store.find("kb_object", {"organization_id": actor.organization_id, "type": type_, "code": code}, order="version desc")

    def create_object(self, actor: Any, *, type: str, code: str, name: str = "", scope: dict[str, Any] | None = None,
                      body: dict[str, Any] | None = None, reason: str = "", _initial: dict[str, Any] | None = None) -> dict[str, Any]:
        self._require(actor, AUTHOR_ROLES, "Only fraud analysts may author knowledge")
        if type not in TYPES:
            _fail(422, f"type must be one of {', '.join(TYPES)}")
        if not _CODE.match(code or ""):
            _fail(422, "code must be 2-64 chars of letters, digits, _ . -")
        org = actor.organization_id
        if self.store.find("kb_object", {"organization_id": org, "type": type, "code": code}, limit=1):
            _fail(409, f"{type} '{code}' already exists; clone it to create a new version")
        row = {
            "organization_id": org, "type": type, "code": code, "version": 1, "status": "draft", "name": name or code,
            "scope": scope or {}, "body": body or {}, "change_reason": reason or None, "author_id": actor.id,
            "author_name": self.store.principal_name(actor.id), "history": [], **(_initial or {}),
        }
        row["history"] = [{"at": _now(), "by": actor.id, "by_name": row["author_name"], "action": "create", "note": reason}]
        o = self.store.insert("kb_object", row)
        self.store.audit(org, actor.id, "kb.object.create", {"object_id": o["id"], "type": type, "code": code, "version": 1})
        return o

    def update_object(self, actor: Any, object_id: str, *, name: str | None = None, scope: dict[str, Any] | None = None,
                      body: dict[str, Any] | None = None, reason: str = "") -> dict[str, Any]:
        self._require(actor, AUTHOR_ROLES)
        o = self._load(actor, object_id)
        if o["status"] not in ("draft", "ready_for_test"):
            _fail(409, "Only draft or ready-for-test versions can be edited; clone to create a new version")
        patch: dict[str, Any] = {"status": "draft", "replay": None}
        if name is not None:
            patch["name"] = name
        if scope is not None:
            patch["scope"] = scope
        if body is not None:
            patch["body"] = body
        if reason:
            patch["change_reason"] = reason
        return self._save(o, actor, "update", patch, reason, expect=("draft", "ready_for_test"))

    def clone_object(self, actor: Any, object_id: str) -> dict[str, Any]:
        self._require(actor, AUTHOR_ROLES)
        src = self._load(actor, object_id)
        siblings = self.store.find("kb_object", {"organization_id": src["organization_id"], "type": src["type"], "code": src["code"]})
        if any(s["status"] in ("draft", "ready_for_test", "trial") for s in siblings):
            _fail(409, "An unpublished version already exists for this object")
        version = max(s["version"] for s in siblings) + 1
        row = {
            "organization_id": src["organization_id"], "type": src["type"], "code": src["code"], "version": version,
            "status": "draft", "name": src["name"], "scope": src["scope"], "body": src["body"],
            "change_reason": f"Clone of v{src['version']}", "author_id": actor.id,
            "author_name": self.store.principal_name(actor.id),
            "history": [{"at": _now(), "by": actor.id, "by_name": self.store.principal_name(actor.id), "action": "clone",
                         "note": f"from v{src['version']}"}],
        }
        o = self.store.insert("kb_object", row)
        self.store.audit(o["organization_id"], actor.id, "kb.object.clone", {"object_id": o["id"], "code": o["code"], "version": version})
        return o

    # ---- lifecycle ----------------------------------------------------------------------------
    def submit(self, actor: Any, object_id: str) -> dict[str, Any]:
        self._require(actor, AUTHOR_ROLES)
        o = self._load(actor, object_id)
        if o["status"] != "draft":
            _fail(409, "Only a draft can be submitted for testing")
        errors = validate_body(o["type"], o["body"], o["name"])
        if errors:
            _fail(422, {"message": "Validation failed", "errors": errors})
        return self._save(o, actor, "submit", {"status": "ready_for_test"}, expect="draft")

    def start_trial(self, actor: Any, object_id: str) -> dict[str, Any]:
        self._require(actor, AUTHOR_ROLES)
        o = self._load(actor, object_id)
        if o["status"] != "ready_for_test":
            _fail(409, "Only a ready-for-test version can start a trial")
        replay = self._replay(o)
        return self._save(o, actor, "trial", {"status": "trial", "replay": replay}, expect="ready_for_test")

    def _case_values(self, org: str, case_ids: list[str] | None, limit: int = 30) -> list[dict[str, Any]]:
        return self.store.case_params(org, case_ids, limit)

    @staticmethod
    def _with_policy_defaults(params: dict[str, Any], overrides: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
        merged = dict(params)
        assumed = []
        for code, meta in PARAMETER_CATALOGUE.items():
            if meta.get("kind") == "policy" and code not in merged:
                merged[code] = meta["sample"]
                assumed.append(code)
        for k, v in (overrides or {}).items():
            if k in PARAMETER_CATALOGUE:
                merged[k] = v
                if k in assumed:
                    assumed.remove(k)
        return merged, assumed

    def _evaluate_one(self, org: str, type_: str, body: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        """Evaluate an object over one parameter set -> {computable, matched, value, error}."""
        try:
            if type_ == "motive":
                value = evaluate_formula(body.get("formula", ""), params)
                return {"computable": True, "matched": bool(value), "value": value, "error": None}
            if type_ == "behavior":
                value = evaluate_formula(body.get("condition", ""), params)
                return {"computable": True, "matched": bool(value), "value": value, "error": None}
            if type_ == "scenario":
                code = body.get("behavior_code", "")
                cands = self.store.find("kb_object", {"organization_id": org, "type": "behavior", "code": code}, order="version desc")
                cand = next((c for c in cands if c["status"] == "published"), None) or next((c for c in cands if c["status"] != "retired"), None)
                if not cand:
                    return {"computable": False, "matched": False, "value": None,
                            "error": {"code": "unknown_reference", "message": f"behavior '{code}' not found"}}
                return self._evaluate_one(org, "behavior", cand["body"], params)
        except FormulaError as e:
            return {"computable": False, "matched": False, "value": None, "error": e.as_dict()}
        return {"computable": True, "matched": False, "value": None, "error": None}

    def _replay(self, o: dict[str, Any]) -> dict[str, Any]:
        """Replay stub: evaluate over recent real cases; reports counts only (no driver contact)."""
        org = o["organization_id"]
        cases = self._case_values(org, None)
        prev = self.get_published(org, o["type"], o["code"])
        total = len(cases)
        matched = changed = not_computable = 0
        for c in cases:
            params, _ = self._with_policy_defaults(c["params"], None)
            res = self._evaluate_one(org, o["type"], o["body"], params)
            if not res["computable"]:
                not_computable += 1
                continue
            matched += 1 if res["matched"] else 0
            if prev is not None and prev["id"] != o["id"]:
                old = self._evaluate_one(org, o["type"], prev["body"], params)
                if old["matched"] != res["matched"] or old["value"] != res["value"]:
                    changed += 1
        computable = total - not_computable
        steps = len(o["body"].get("steps", [])) if o["type"] == "workflow" else 0
        return {
            "cases_total": total, "matched": matched, "changed_scenario": changed, "not_computable": not_computable,
            "est_turns": steps * total, "computable_ratio": round(computable / total, 3) if total else 1.0,
            "gate_passed": total == 0 or computable / total >= GATE_MIN_COMPUTABLE, "gate_min": GATE_MIN_COMPUTABLE,
            "run_at": _now(),
        }

    def preview(self, actor: Any, object_id: str, case_ids: list[str] | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._require(actor, KSGL_ROLES)
        o = self._load(actor, object_id)
        out = []
        for c in self._case_values(o["organization_id"], case_ids, limit=10):
            merged, assumed = self._with_policy_defaults(c["params"], params)
            res = self._evaluate_one(o["organization_id"], o["type"], o["body"], merged)
            used = sorted(validate_formula(o["body"].get("formula") or o["body"].get("condition") or "=0")["used_params"])
            out.append({"case_id": c["case_id"], "value": res["value"], "matched": res["matched"], "error": res["error"],
                        "params_used": {k: merged[k] for k in used if k in merged}, "assumed": [a for a in assumed if a in used]})
        self.store.audit(o["organization_id"], actor.id, "kb.object.preview", {"object_id": o["id"], "cases": len(out)})
        return {"object_id": o["id"], "results": out}

    def _check_references(self, o: dict[str, Any]) -> list[dict[str, Any]]:
        if o["type"] != "scenario":
            return []
        errs = []
        for key, t in (("motive_code", "motive"), ("behavior_code", "behavior"), ("workflow_code", "workflow")):
            code = o["body"].get(key)
            if not self.get_published(o["organization_id"], t, code):
                errs.append({"path": f"body.{key}", "code": "unpublished_reference",
                             "message": f"{t} '{code}' must be published first"})
        return errs

    def publish(self, actor: Any, object_id: str, override_reason: str | None = None) -> dict[str, Any]:
        self._require(actor, APPROVER_ROLES, "Only a senior analyst or admin may approve a release")
        o = self._load(actor, object_id)
        if str(o["author_id"]) == str(actor.id):
            _fail(403, "Four-eyes: the approver must differ from the author")
        if o["status"] != "trial":
            _fail(409, "Only a version in trial can be published")
        errors = self._check_references(o)
        gate_ok = (o.get("replay") or {}).get("gate_passed", True)
        override = (override_reason or "").strip()
        if not gate_ok and len(override) < 10:
            errors.append({"path": "replay", "code": "gate_failed", "message": "Trial gate not passed; an override reason (min 10 chars) is required"})
        if errors:
            _fail(422, {"message": "Cannot publish", "errors": errors})
        current = self.get_published(o["organization_id"], o["type"], o["code"])
        if current:
            self._save(current, actor, "superseded", {"status": "retired", "retired_reason": "superseded", "retired_at": _now()},
                       note=f"by v{o['version']}", expect="published")
        patch = {"status": "published", "approver_id": actor.id, "approver_name": self.store.principal_name(actor.id),
                 "published_at": _now(), "override_reason": override or None}
        return self._save(o, actor, "publish", patch, override, expect="trial")

    def retire(self, actor: Any, object_id: str, reason: str) -> dict[str, Any]:
        self._require(actor, AUTHOR_ROLES)
        o = self._load(actor, object_id)
        if o["status"] == "retired":
            _fail(409, "Already retired")
        if len((reason or "").strip()) < 3:
            _fail(422, "A reason is required")
        return self._save(o, actor, "retire", {"status": "retired", "retired_reason": reason.strip(), "retired_at": _now()}, reason)

    def rollback(self, actor: Any, object_id: str, reason: str) -> dict[str, Any]:
        self._require(actor, APPROVER_ROLES, "Only a senior analyst or admin may roll back a release")
        o = self._load(actor, object_id)
        if o["status"] != "published":
            _fail(409, "Only the published version can be rolled back")
        if len((reason or "").strip()) < 3:
            _fail(422, "A reason is required")
        siblings = self.store.find("kb_object", {"organization_id": o["organization_id"], "type": o["type"], "code": o["code"]},
                                   order="version desc")
        prev = next((s for s in siblings if s["version"] < o["version"] and s["status"] == "retired" and s.get("retired_reason") == "superseded"), None)
        if prev is None:
            _fail(409, "No previous version to roll back to")
        self._save(o, actor, "rollback", {"status": "retired", "retired_reason": "rolled_back", "retired_at": _now()}, reason, expect="published")
        return self._save(prev, actor, "restore", {"status": "published", "retired_reason": None, "retired_at": None, "published_at": _now()},
                          f"rollback from v{o['version']}: {reason}", expect="retired")

    # ---- similarity / registry ----------------------------------------------------------------
    def similar(self, actor: Any, text: str, type: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
        self._require(actor, KSGL_ROLES)
        rows = [r for r in self.list_objects(actor, type=type) if r["status"] != "retired"]
        latest: dict[tuple[str, str], dict[str, Any]] = {}
        for r in rows:  # list is version-desc per code
            latest.setdefault((r["type"], r["code"]), r)
        items = [(f"{t}:{c}", f"{r['name']} {c} {' '.join(_strings(r['body']))}") for (t, c), r in latest.items()]
        ranked = self.scorer.rank(text, items, limit=limit)
        out = []
        for key, score in ranked:
            r = latest[tuple(key.split(":", 1))]  # type: ignore[index]
            out.append({"type": r["type"], "code": r["code"], "name": r["name"], "status": r["status"],
                        "version": r["version"], "similarity": score})
        return out

    def registry(self, actor: Any) -> dict[str, Any]:
        if not set(actor.roles) & (KSGL_ROLES | {"manager", "reviewer"}):
            _fail(403, "Insufficient role permissions")
        counts = {t: len(self.list_published(actor.organization_id, t)) for t in TYPES}
        from src.services.agent_config_service import AgentConfigService

        cfg = self._config or AgentConfigService(self.store)
        enabled = cfg.explain_agent_enabled(actor.organization_id)
        agents = []
        for a in AGENTS:
            enabled_flag = enabled if a["controlled_by"] == "explain_agent_enabled" else None
            agents.append({**a, "enabled": enabled_flag,
                           "knowledge_published": {t: counts[t] for t in a["knowledge_types"]}})
        return {"agents": agents, "published_counts": counts, "tool_catalogue": list(TOOL_CATALOGUE)}

    # ---- policy documents ---------------------------------------------------------------------
    def create_document(self, actor: Any, *, name: str, code: str, text: str = "", filename: str | None = None,
                        content_type: str | None = None, size_bytes: int = 0, effective_from: str | None = None,
                        effective_to: str | None = None, region: str | None = None, service: str | None = None,
                        contract_type: str | None = None) -> dict[str, Any]:
        self._require(actor, AUTHOR_ROLES)
        missing = [k for k, v in (("name", name), ("code", code)) if not (v or "").strip()]
        if not (text or "").strip() and not filename:
            missing.append("file_or_text")
        if missing:
            _fail(422, {"message": "Missing required fields", "fields": missing})
        row = {
            "organization_id": actor.organization_id, "name": name.strip(), "code": code.strip(),
            "effective_from": effective_from or None, "effective_to": effective_to or None, "region": region or None,
            "service": service or None, "contract_type": contract_type or None, "filename": filename,
            "content_type": content_type, "size_bytes": int(size_bytes or 0), "text_excerpt": (text or "")[:200_000] or None,
            "indexing_status": indexing_status_for_new_document(), "uploaded_by": actor.id,
            "uploaded_by_name": self.store.principal_name(actor.id),
        }
        d = self.store.insert("kb_policy_document", row)
        self.store.audit(actor.organization_id, actor.id, "kb.document.create", {"document_id": d["id"], "code": d["code"]})
        return d

    def list_documents(self, actor: Any) -> list[dict[str, Any]]:
        self._require(actor, KSGL_ROLES)
        rows = self.store.find("kb_policy_document", {"organization_id": actor.organization_id}, order="created_at desc")
        agents = [a["name"] for a in AGENTS if a["uses_policy_documents"]]
        return [{**{k: v for k, v in r.items() if k != "text_excerpt"}, "has_text": bool(r.get("text_excerpt")), "used_by": agents} for r in rows]

    # ---- proposals queue ----------------------------------------------------------------------
    def create_proposal(self, organization_id: str, *, source: str, type: str, title: str, payload: dict[str, Any],
                        source_excerpt: str | None = None, source_ref: str | None = None, mapping: str = "new",
                        similarity: float | None = None, matched_code: str | None = None, created_by: str = "agent") -> dict[str, Any]:
        """Agent/system entry point (`propose_knowledge`): drafts only, never publishes."""
        if source not in PROPOSAL_SOURCES or type not in TYPES or mapping not in ("reuse", "extend", "new"):
            _fail(422, "Invalid proposal source, type or mapping")
        p = self.store.insert("kb_proposal", {
            "organization_id": organization_id, "source": source, "type": type, "title": title, "payload": payload,
            "source_excerpt": source_excerpt, "source_ref": source_ref, "mapping": mapping, "similarity": similarity,
            "matched_code": matched_code, "status": "pending", "created_by": created_by})
        self.store.audit(organization_id, None, "kb.proposal.create", {"proposal_id": p["id"], "source": source, "by": created_by})
        return p

    def list_proposals(self, actor: Any, status: str | None = None, source: str | None = None, type: str | None = None) -> list[dict[str, Any]]:
        self._require(actor, KSGL_ROLES)
        where: dict[str, Any] = {"organization_id": actor.organization_id}
        for k, v in (("status", status), ("source", source), ("type", type)):
            if v:
                where[k] = v
        return self.store.find("kb_proposal", where, order="created_at desc")

    def _proposal(self, actor: Any, proposal_id: str) -> dict[str, Any]:
        self._require(actor, AUTHOR_ROLES)
        p = self.store.get("kb_proposal", proposal_id)
        if not p or str(p["organization_id"]) != str(actor.organization_id):
            _fail(404, "Proposal not found")
        if p["status"] != "pending":
            _fail(409, "Proposal already decided")
        return p

    def _materialise(self, actor: Any, p: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        pl = payload or {}
        existing = self.store.find("kb_object", {"organization_id": p["organization_id"], "type": p["type"], "code": pl.get("code")}, order="version desc", limit=1)
        if existing:
            # reuse/extend or colliding code: land as a new draft version of the existing object
            base = existing[0]
            if base["status"] in ("draft", "ready_for_test", "trial"):
                _fail(409, "An unpublished version of this object already exists")
            cloned = self.clone_object(actor, base["id"])
            o = self.update_object(actor, cloned["id"], name=pl.get("name"), scope=pl.get("scope"), body=pl.get("body"),
                                   reason=f"From proposal {p['id']}")
        else:
            o = self.create_object(actor, type=p["type"], code=pl.get("code") or f"{p['type'][:3].upper()}_{p['id'][:6]}",
                                   name=pl.get("name") or p["title"], scope=pl.get("scope"), body=pl.get("body"),
                                   reason=f"From proposal {p['id']}")
        return self.submit(actor, o["id"])  # accept/edit only reaches ready_for_test; publishing goes through US6

    def accept_proposal(self, actor: Any, proposal_id: str) -> dict[str, Any]:
        p = self._proposal(actor, proposal_id)
        obj = self._materialise(actor, p, p["payload"])
        return self._decide(actor, p, "accepted", obj)

    def edit_proposal(self, actor: Any, proposal_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        p = self._proposal(actor, proposal_id)
        obj = self._materialise(actor, p, payload)
        return self._decide(actor, p, "edited", obj, payload=payload)

    def _decide(self, actor: Any, p: dict[str, Any], status: str, obj: dict[str, Any] | None, reason_code: str | None = None,
                note: str | None = None, payload: dict[str, Any] | None = None):
        patch: dict[str, Any] = {"status": status, "decided_by": actor.id, "decided_at": _now(), "reason_code": reason_code, "note": note,
                                 "resulting_object_id": obj["id"] if obj else None}
        if payload is not None:
            patch["payload"] = payload
        out = self.store.update("kb_proposal", p["id"], patch, where={"status": "pending"})
        if out is None:
            _fail(409, "Proposal already decided")
        self.store.audit(p["organization_id"], actor.id, f"kb.proposal.{status}",
                         {"proposal_id": p["id"], "reason_code": reason_code, "object_id": obj["id"] if obj else None})
        return {"proposal": out, "object": obj} if obj else out

    def reject_proposal(self, actor: Any, proposal_id: str, reason_code: str, note: str = "") -> dict[str, Any]:
        p = self._proposal(actor, proposal_id)
        if reason_code not in REJECT_REASONS:
            _fail(422, f"reason_code must be one of {', '.join(REJECT_REASONS)}")
        return self._decide(actor, p, "rejected", None, reason_code=reason_code, note=note)

    # ---- demo seed ----------------------------------------------------------------------------
    def seed_demo(self, actor: Any) -> dict[str, Any]:
        """Idempotent demo content: published motive/behavior/workflow/scenario + a draft + proposals + a document."""
        self._require(actor, frozenset({"admin"}), "Only admin may seed demo data")
        org = actor.organization_id
        created = 0

        def publish_direct(type_: str, code: str, name: str, body: dict[str, Any], scope: dict[str, Any] | None = None):
            nonlocal created
            if self.store.find("kb_object", {"organization_id": org, "type": type_, "code": code}, limit=1):
                return
            o = self.create_object(actor, type=type_, code=code, name=name, scope=scope or {}, body=body, reason="demo seed")
            self.store.update("kb_object", o["id"], {
                "status": "published", "author_id": None, "author_name": "Demo seed", "approver_id": actor.id,
                "approver_name": self.store.principal_name(actor.id), "published_at": _now(),
                "history": [*o["history"], {"at": _now(), "by": actor.id, "by_name": None, "action": "seed", "note": "published by demo seed"}]})
            created += 1

        publish_direct("motive", "MOT_MILESTONE_BONUS", "Thưởng mốc chuyến", {
            "beneficiary": "driver", "policy": "THUONG-MOC-T11",
            "formula": "=IF(trips_today+1>=milestone_trips, milestone_bonus_vnd-trip_cost_vnd, 0)", "threshold_label": "<NGƯỠNG_ĐỘNG_CƠ>"},
            {"region": "HN", "service": "car"})
        publish_direct("motive", "MOT_SURGE_SUBSIDY", "Lợi dụng hệ số giá tăng", {
            "beneficiary": "driver", "policy": "SURGE-T11", "formula": "=fare_vnd*(surge_multiplier-1)"}, {"service": "car"})
        publish_direct("behavior", "BHV_STATIONARY", "Xe gần như đứng yên trong cuốc", {
            "description": "Xe đứng yên lâu trong cuốc", "signals": ["stationary_duration_s"],
            "condition": "=stationary_duration_s>=300", "source_rule": "ERR-02"})
        publish_direct("behavior", "BHV_FAR_FROM_PICKUP", "Xe ở xa điểm đón khi nhận cuốc", {
            "description": "Xe cách điểm đón lớn", "signals": ["distance_to_pickup_m"],
            "condition": "=distance_to_pickup_m>=500", "source_rule": "ERR-05"})
        publish_direct("workflow", "WF_FAKE_TRIP_CAR", "Cuốc ảo · Car Platform", {
            "ask_first": ["Bạn có chở khách trong cuốc này không?"],
            "steps": [{"question": "Bạn có mã ticket hỗ trợ cho cuốc này không?", "tool": "identify_behavior", "branch": "Có mã -> so thời điểm tạo ticket"},
                      {"question": "Khách đã liên hệ bạn bằng cách nào?", "tool": "get_workflow", "branch": ""}],
            "stop_condition": "n_max", "help_condition": "no_tool_for_claim"}, {"service": "car"})
        publish_direct("scenario", "SCN_MILESTONE_STILL", "Thưởng mốc + xe đứng yên + có khách thật", {
            "motive_code": "MOT_MILESTONE_BONUS", "behavior_code": "BHV_STATIONARY", "reason": "Có khách thật",
            "workflow_code": "WF_FAKE_TRIP_CAR"})
        if not self.store.find("kb_object", {"organization_id": org, "type": "motive", "code": "MOT_HAIL_MILESTONE"}, limit=1):
            self.create_object(actor, type="motive", code="MOT_HAIL_MILESTONE", name="Cuốc vẫy vào mốc thưởng", scope={"service": "car"},
                               body={"beneficiary": "driver", "policy": "THUONG-MOC-T11",
                                     "formula": "=IF(trips_today+2>=milestone_trips, milestone_bonus_vnd, 0)"}, reason="demo seed draft")
            created += 1
        if not self.store.find("kb_policy_document", {"organization_id": org, "code": "THUONG-MOC-T11"}, limit=1):
            self.create_document(actor, name="Chính sách thưởng mốc chuyến tháng 11", code="THUONG-MOC-T11",
                                 text="Tài xế đạt mốc 10 cuốc trong ngày nhận thưởng 50.000 VND. Cuốc vẫy được tính vào mốc.",
                                 filename="thuong-moc-t11.txt", content_type="text/plain", size_bytes=120,
                                 effective_from="2026-11-01", region="HN", service="car", contract_type="full-time")
            created += 1
        existing_titles = {p["title"] for p in self.store.find("kb_proposal", {"organization_id": org})}
        for spec in (
            dict(source="policy_analysis", type="motive", title="Động cơ: thưởng mốc cho cuốc vẫy", mapping="extend",
                 matched_code="MOT_MILESTONE_BONUS", source_excerpt="Điều 3: Cuốc vẫy được tính vào mốc 10 cuốc trong ngày.",
                 source_ref="THUONG-MOC-T11 · tr.2",
                 payload={"code": "MOT_MILESTONE_BONUS", "name": "Thưởng mốc chuyến (mở rộng cuốc vẫy)", "scope": {"service": "car"},
                          "body": {"beneficiary": "driver", "policy": "THUONG-MOC-T11",
                                   "formula": "=IF(trips_today+1>=milestone_trips, milestone_bonus_vnd-trip_cost_vnd, 0)"}}),
            dict(source="help_reply", type="workflow", title="Bước workflow: tra lịch sử chuyến theo số điện thoại khách", mapping="new",
                 source_excerpt="VH: số này không có cuốc nào khác với TX.", source_ref="help-request demo",
                 payload={"code": "WF_REGULAR_CUSTOMER", "name": "Khách quen · tra lịch sử",
                          "body": {"ask_first": ["Khách có phải khách quen không?"],
                                   "steps": [{"question": "Số điện thoại khách là gì?", "tool": "request_help", "branch": ""}]}}),
        ):
            if spec["title"] not in existing_titles:
                spec = {**spec}
                spec["similarity"] = round(self.scorer.score(spec["title"], "Thưởng mốc chuyến thưởng mốc cuốc"), 3)
                self.create_proposal(org, created_by="seed", **spec)
                created += 1
        self.store.audit(org, actor.id, "kb.seed", {"created": created})
        return {"created": created}


_service: KbService | None = None


def get_kb_service() -> KbService:
    global _service
    if _service is None:
        _service = KbService()
    return _service


# Module-level read API for the explanation agent (S-D1): published rows only.
def get_published(organization_id: str, type_: str, code: str) -> dict[str, Any] | None:
    return get_kb_service().get_published(organization_id, type_, code)


def list_published(organization_id: str, type_: str) -> list[dict[str, Any]]:
    return get_kb_service().list_published(organization_id, type_)
