"""Read-only knowledge tools of the driver explanation agent (PRD-A US6, ADR-034).

All tools read PUBLISHED knowledge only (via the kb service), compute every number in code and return
`{tool, ok, data, error, refs}` where `refs` carry type/code/version for provenance. A failing formula or
missing parameter returns `ok: False` with a "không tra được" reason; the agent never guesses a value.
"""

from __future__ import annotations

from typing import Any

from src.services.explain_forms import REASON_LABELS
from src.services.kb_formula import PARAMETER_CATALOGUE, FormulaError, evaluate_formula
from src.services.kb_service import TOOL_CATALOGUE, KbService
from src.services.kb_similarity import SimilarityScorer
from src.services.kb_store import Store

INVESTIGATION_TOOLS = ("identify_behavior", "list_motives", "compute_motive", "match_scenario", "get_workflow")
ALWAYS_ALLOWED = ("request_help", "propose_knowledge")
MAX_MOTIVES = 5
NOT_FOUND = "không tra được"


def _ref(obj: dict[str, Any]) -> dict[str, Any]:
    return {"type": obj["type"], "code": obj["code"], "version": obj["version"]}


def _fail(tool: str, reason: str) -> dict[str, Any]:
    return {"tool": tool, "ok": False, "data": None, "error": f"{NOT_FOUND}: {reason}", "refs": []}


def allowed_tools(workflow_body: dict[str, Any] | None) -> set[str]:
    """Tools the loop may call: the workflow's step tools, else all investigation tools; help/propose always."""
    if workflow_body is not None:
        step_tools = {str(s.get("tool")) for s in workflow_body.get("steps") or [] if s.get("tool")}
        return (step_tools | set(ALWAYS_ALLOWED)) & set(TOOL_CATALOGUE)
    return set(INVESTIGATION_TOOLS) | set(ALWAYS_ALLOWED)


class ExplainTools:
    def __init__(self, kb: KbService, store: Store, scorer: SimilarityScorer, similarity_threshold: float):
        self.kb = kb
        self.store = store
        self.scorer = scorer
        self.threshold = similarity_threshold

    # ---- parameters ---------------------------------------------------------------------------
    def case_values(self, org: str, case_id: str) -> tuple[dict[str, Any], list[str]]:
        rows = self.store.case_params(org, [case_id], 1)
        params = dict(rows[0]["params"]) if rows else {}
        assumed: list[str] = []
        for code, meta in PARAMETER_CATALOGUE.items():
            if meta.get("kind") == "policy" and code not in params:
                params[code] = meta["sample"]
                assumed.append(code)
        return params, assumed

    # ---- tools --------------------------------------------------------------------------------
    def identify_behavior(self, org: str, case_id: str) -> dict[str, Any]:
        behaviors = self.kb.list_published(org, "behavior")
        if not behaviors:
            return _fail("identify_behavior", "chưa có hành vi nào được phát hành")
        params, assumed = self.case_values(org, case_id)
        matched, skipped = [], []
        for b in behaviors:
            try:
                hit = bool(evaluate_formula(b["body"].get("condition", ""), params))
            except FormulaError as e:
                skipped.append({"code": b["code"], "version": b["version"], "reason": e.as_dict().get("message", "formula error")})
                continue
            if hit:
                sig = {s: params.get(s) for s in b["body"].get("signals") or [] if s in params}
                matched.append({"code": b["code"], "version": b["version"], "name": b["name"], "signals": sig})
        refs = [{"type": "behavior", "code": m["code"], "version": m["version"]} for m in matched]
        return {"tool": "identify_behavior", "ok": True, "data": {"behaviors": matched, "not_computable": skipped, "assumed_params": assumed},
                "error": None, "refs": refs}

    def list_motives(self, org: str, scenario_code: str | None = None) -> dict[str, Any]:
        motives = self.kb.list_published(org, "motive")
        if scenario_code:
            sc = self.kb.get_published(org, "scenario", scenario_code)
            if sc:
                motives = [m for m in motives if m["code"] == sc["body"].get("motive_code")]
        if not motives:
            return _fail("list_motives", "chưa có động cơ nào được phát hành")
        items = [{"code": m["code"], "version": m["version"], "name": m["name"]} for m in motives[:MAX_MOTIVES]]
        return {"tool": "list_motives", "ok": True, "data": {"motives": items}, "error": None,
                "refs": [{"type": "motive", "code": i["code"], "version": i["version"]} for i in items]}

    def compute_motive(self, org: str, case_id: str, motive_code: str) -> dict[str, Any]:
        m = self.kb.get_published(org, "motive", motive_code)
        if not m:
            return _fail("compute_motive", f"động cơ '{motive_code}' chưa được phát hành")
        params, assumed = self.case_values(org, case_id)
        try:
            value = evaluate_formula(m["body"].get("formula", ""), params)
        except FormulaError as e:
            return {"tool": "compute_motive", "ok": False, "data": None, "refs": [_ref(m)],
                    "error": f"{NOT_FOUND}: {e.as_dict().get('message', 'công thức lỗi')}"}
        threshold = float(m["body"].get("threshold_vnd") or 0)
        num = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
        return {"tool": "compute_motive", "ok": True, "refs": [_ref(m)], "error": None,
                "data": {"code": m["code"], "version": m["version"], "value": num, "threshold": threshold,
                         "over_threshold": bool(num is not None and num > threshold), "params_used": params, "assumed_params": assumed}}

    def match_scenario(self, org: str, case_id: str, reason: str, behaviors: list[dict[str, Any]]) -> dict[str, Any]:
        scenarios = self.kb.list_published(org, "scenario")
        if not scenarios:
            return {"tool": "match_scenario", "ok": True, "refs": [], "error": None,
                    "data": {"matched": False, "novel_scenario": True, "best_score": 0.0, "similar": []}}
        label = REASON_LABELS.get(reason, {}).get("vi", reason)
        have = {b["code"] for b in behaviors}
        scored = []
        for s in scenarios:
            reason_sim = max(self.scorer.score(label, str(s["body"].get("reason", ""))), 1.0 if s["body"].get("reason_code") == reason else 0.0)
            beh = 1.0 if s["body"].get("behavior_code") in have else 0.0
            scored.append((round(0.5 * reason_sim + 0.5 * beh, 4), s))
        scored.sort(key=lambda t: (-t[0], t[1]["code"]))
        similar = [{"code": s["code"], "version": s["version"], "name": s["name"], "score": sc} for sc, s in scored[:3]]
        best_score, best = scored[0]
        if best_score >= self.threshold:
            return {"tool": "match_scenario", "ok": True, "refs": [_ref(best)], "error": None,
                    "data": {"matched": True, "novel_scenario": False, "scenario": {"code": best["code"], "version": best["version"], "name": best["name"]},
                             "workflow_code": best["body"].get("workflow_code"), "motive_code": best["body"].get("motive_code"),
                             "behavior_code": best["body"].get("behavior_code"), "best_score": best_score, "similar": similar}}
        return {"tool": "match_scenario", "ok": True, "refs": [], "error": None,
                "data": {"matched": False, "novel_scenario": True, "best_score": best_score, "similar": similar}}

    def get_workflow(self, org: str, code: str | None) -> dict[str, Any]:
        wf = self.kb.get_published(org, "workflow", code) if code else None
        if not wf:
            return _fail("get_workflow", f"workflow '{code}' chưa được phát hành")
        return {"tool": "get_workflow", "ok": True, "refs": [_ref(wf)], "error": None,
                "data": {"code": wf["code"], "version": wf["version"], "body": wf["body"]}}

    def propose_knowledge(self, org: str, *, type_: str, title: str, payload: dict[str, Any], source: str, source_excerpt: str | None,
                          source_ref: str | None) -> dict[str, Any]:
        """Draft proposal for KSGL review; the agent can never publish."""
        p = self.kb.create_proposal(org, source=source, type=type_, title=title, payload=payload, source_excerpt=source_excerpt,
                                    source_ref=source_ref, created_by="driver_agent")
        return {"tool": "propose_knowledge", "ok": True, "data": {"proposal_id": p["id"], "status": p["status"]}, "error": None, "refs": []}
