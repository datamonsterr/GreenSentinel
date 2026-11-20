"""Driver explanation session service v2 (PRD-A, ADR-034).

One session per case: form (fixed + <= K dynamic) -> immutable statement_v1 -> round-1 assessment ->
bounded agent loop (think -> tool -> observe -> ask, at most N_max answered turns) -> summary
confirm/edit -> round-2 assessment -> submitted. The LLM only writes text and structured judgements;
every number comes from code tools. Any LLM failure falls back to the deterministic implementation;
a disabled kill switch skips the agent entirely (static form only).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException

from src.services import explain_guard as guard
from src.services.agent_config_service import AgentConfigService, get_agent_config_service
from src.services.explain_forms import (
    REASON_LABELS,
    REASONS,
    build_form,
    driver_form_view,
    statement_text,
    validate_answers,
)
from src.services.explain_llm import (
    INSTRUCTION_VERSION,
    AssessmentOut,
    DeterministicExplainLLM,
    ExplainLLM,
    StepOut,
    SummaryOut,
    default_plan,
    get_explain_llm,
)
from src.services.explain_tools import ExplainTools, allowed_tools
from src.services.help_request_service import VH_QUEUE_ROLES, HelpRequestService, as_dt
from src.services.kb_service import KbService, get_kb_service
from src.services.kb_store import Store, default_store

FLAGS = ("novel_scenario", "statement_changed", "ai_inconclusive", "session_interrupted", "asked_for_help", "asked_for_help_skipped")
FEEDBACK_ERROR_TYPES = ("wrong_facts", "wrong_reasoning", "missing_question", "redundant_or_tone", "missing_tool_source",
                        "wrong_scenario_or_workflow")
ANALYST_ROLES = frozenset({"analyst", "senior_analyst", "fraud_analyst", "admin", "reviewer", "ops_director", "marketplace_director", "manager"})
FEEDBACK_ROLES = frozenset({"analyst", "senior_analyst", "fraud_analyst", "admin", "reviewer", "manager"})
MAX_ITER = 4  # tool/help hops inside one advance
logger = logging.getLogger(__name__)
SWEEP_MIN_INTERVAL_S = 60  # help-count poll triggers sweep(org) at most once per org per minute
HELP_AFTER_TURNS = 3  # M: low confidence only triggers help after this many answered turns
WAIT_MESSAGE = "Mình cần kiểm tra thêm thông tin, bạn chờ mình một chút nhé."
CLOSE_MESSAGE = "Mình đã ghi nhận thông tin, mình sẽ gửi cho vận hành xem xét."
SUBMITTED_MESSAGE = {"vi": "Đã gửi giải trình, VH sẽ phản hồi trong thời gian sớm nhất.",
                     "en": "Your explanation was sent. Operations will respond soon."}
CHECKING_MESSAGE = {"vi": "Đang kiểm tra giải trình", "en": "Checking your explanation"}
OFFER_END_MESSAGE = "Bạn có thể bấm Kết thúc để gửi những gì đã khai nếu không tiện trả lời tiếp."
_DONT_KNOW = re.compile(r"không biết|không nhớ|không rõ|don't know|dont know|no idea", re.I)
_MUTABLE = ("reason", "state", "mode", "form_version", "form_schema", "answers", "workflow_code", "workflow_version", "scenario_code",
            "scenario_version", *FLAGS, "turns_used", "n_max", "edits_used", "help_count", "plan", "memory", "provenance",
            "open_points", "summary", "model", "instruction_version", "submitted_at", "last_interaction_at")


def _fail(status: int, detail: Any):
    raise HTTPException(status, detail)


def _iso(v: Any) -> str | None:
    d = as_dt(v)
    return d.isoformat() if d else None


class ExplainService:
    def __init__(self, store: Store | None = None, kb: KbService | None = None, config: AgentConfigService | None = None,
                 llm: ExplainLLM | None = None, now: Callable[[], datetime] | None = None):
        self._store = store
        self._kb = kb
        self._config = config
        self._llm = llm
        self.now = now or (lambda: datetime.now(UTC))
        self._help: HelpRequestService | None = None
        self._last_sweep: dict[str, datetime] = {}
        self.fallback_llm = DeterministicExplainLLM()

    # ---- wiring -------------------------------------------------------------------------------
    @property
    def store(self) -> Store:
        if self._store is None:
            self._store = default_store()
        return self._store

    @property
    def kb(self) -> KbService:
        return self._kb or get_kb_service()

    @property
    def config(self) -> AgentConfigService:
        return self._config or get_agent_config_service()

    @property
    def llm(self) -> ExplainLLM:
        return self._llm or get_explain_llm()

    @property
    def help(self) -> HelpRequestService:
        if self._help is None:
            self._help = HelpRequestService(self.store, self.config, self.kb, self.now)
        return self._help

    def tools(self, org: str) -> ExplainTools:
        return ExplainTools(self.kb, self.store, self.kb.scorer, self.config.similarity_threshold(org))

    # ---- persistence helpers ------------------------------------------------------------------
    def _case(self, org: str, case_id: str) -> dict[str, Any]:
        c = self.store.case_info(org, case_id)
        if not c:
            _fail(404, "Case not found")
        return c

    def _own_case(self, principal: Any, case_id: str) -> dict[str, Any]:
        c = self._case(principal.organization_id, case_id)
        if "driver" not in principal.roles or not principal.driver_id or str(c.get("driver_id")) != str(principal.driver_id):
            _fail(404, "Case not found")  # anti-probing: never distinguish "not mine" from "does not exist"
        return c

    def _session_for(self, org: str, case_id: str) -> dict[str, Any] | None:
        rows = self.store.find("explain_session", {"organization_id": org, "case_id": case_id}, limit=1)
        return rows[0] if rows else None

    def _persist(self, s: dict[str, Any], where: dict[str, Any] | None = None) -> dict[str, Any]:
        s["updated_at"] = self.now()
        patch = {c: s[c] for c in (*_MUTABLE, "updated_at")}
        out = self.store.update("explain_session", s["id"], patch, where=where)
        if out is None:
            _fail(409, "Session changed concurrently; reload and retry")
        s.update(out)
        return s

    def _turn(self, s: dict[str, Any], kind: str, content: str = "", *, visible: bool = False, payload: dict[str, Any] | None = None,
              tool: str | None = None, kb_code: str | None = None, kb_version: int | None = None) -> dict[str, Any]:
        seq = len(self.store.find("explain_turn", {"session_id": s["id"]})) + 1
        return self.store.insert("explain_turn", {
            "organization_id": s["organization_id"], "session_id": s["id"], "seq": seq, "kind": kind, "visible_to_driver": visible,
            "content": content, "payload": payload or {}, "tool": tool, "kb_code": kb_code, "kb_version": kb_version,
            "created_at": self.now()})

    def _flag(self, s: dict[str, Any], flag: str, why: str = "") -> None:
        if not s.get(flag):
            s[flag] = True
            self._turn(s, "flag", flag, payload={"flag": flag, "why": why})

    def _statement(self, s: dict[str, Any], source: str, text: str, content: dict[str, Any], reason: str | None = None) -> dict[str, Any]:
        version = len(self.store.find("statement_version", {"session_id": s["id"]})) + 1
        return self.store.insert("statement_version", {
            "organization_id": s["organization_id"], "session_id": s["id"], "version": version, "source": source,
            "reason": reason or s["reason"], "content": content, "text": text, "created_at": self.now()})

    def _provenance(self, s: dict[str, Any], tool_result: dict[str, Any], turn_seq: int) -> None:
        for r in tool_result.get("refs") or []:
            key = (r["type"], r["code"], r["version"], tool_result["tool"])
            if not any((p["type"], p["code"], p["version"], p["tool"]) == key for p in s["provenance"]):
                s["provenance"].append({**r, "tool": tool_result["tool"], "turn_seq": turn_seq, "at": self.now().isoformat()})

    def _run_logged(self, s: dict[str, Any], result: dict[str, Any], note: str = "") -> dict[str, Any]:
        """Persist one tool call: turn with code+version (provenance), audit, memory."""
        ref = (result.get("refs") or [{}])[0]
        t = self._turn(s, "tool_call", note or result["tool"], tool=result["tool"], kb_code=ref.get("code"), kb_version=ref.get("version"),
                       payload={"ok": result["ok"], "error": result.get("error"), "data": result.get("data"), "refs": result.get("refs", [])})
        self._provenance(s, result, t["seq"])
        s["memory"].setdefault("tool_results", {})[result["tool"]] = {"ok": result["ok"], "error": result.get("error"), "data": result.get("data")}
        self.store.audit(s["organization_id"], None, f"explain.tool.{result['tool']}",
                         {"session_id": s["id"], "ok": result["ok"], "refs": result.get("refs", [])})
        return result

    # ---- LLM call with deterministic fallback -------------------------------------------------
    async def _safe(self, s: dict[str, Any], name: str, *args: Any) -> Any:
        try:
            out = await getattr(self.llm, name)(*args)
            return out
        except Exception as e:  # timeout, auth, network, pydantic validation: all degrade to the deterministic path
            s["memory"]["llm_failures"] = int(s["memory"].get("llm_failures", 0)) + 1
            self._turn(s, "system", "llm_fallback", payload={"call": name, "error": f"{type(e).__name__}: {str(e)[:200]}"})
            return await getattr(self.fallback_llm, name)(*args)

    @staticmethod
    def _stmt(s: dict[str, Any]) -> str:
        return (s.get("memory") or {}).get("statement_text") or statement_text(s["form_schema"], s["answers"])

    def _ctx(self, s: dict[str, Any], **extra: Any) -> dict[str, Any]:
        m = s["memory"]
        wf = m.get("workflow_body")
        return {
            "instruction_version": INSTRUCTION_VERSION, "reason": m.get("current_reason", s["reason"]), "original_reason": s["reason"],
            "statement_text": self._stmt(s), "answers": m.get("answers", []), "plan": s["plan"], "turns_used": s["turns_used"],
            "n_max": s["n_max"], "tool_results": m.get("tool_results", {}), "scenario": m.get("scenario"), "workflow_body": wf,
            "allowed_tools": sorted(allowed_tools(wf)), "contradictions": m.get("contradictions", []),
            "matched_evidence": m.get("matched_evidence", []), "missing_internal": m.get("missing_internal", []),
            "open_points": s["open_points"], "help_answers": m.get("help_answers", []), "help_expired": m.get("help_expired", []),
            "waiting_for_help": bool(m.get("waiting_help_id")), "confidence": m.get("confidence"),
            "statement_change": m.get("statement_change"), "ai_inconclusive": s["ai_inconclusive"],
            "session_interrupted": s["session_interrupted"], **extra}

    # ---- form + start -------------------------------------------------------------------------
    def _workflow_for(self, org: str, case_id: str, reason: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        """Published workflow chosen for the form: match_scenario over the case behaviours."""
        tools = self.tools(org)
        beh = tools.identify_behavior(org, case_id)
        behaviors = (beh.get("data") or {}).get("behaviors", []) if beh["ok"] else []
        sc = tools.match_scenario(org, case_id, reason, behaviors)
        wf = None
        if sc["data"].get("matched"):
            r = tools.get_workflow(org, sc["data"].get("workflow_code"))
            if r["ok"]:
                wf = r["data"]
        return wf, sc

    def _rule_scope(self, case: dict[str, Any]) -> str:
        return f"rule:{case['category']}" if case.get("category") else "global"

    async def start(self, principal: Any, case_id: str, reason: str) -> dict[str, Any]:
        org = principal.organization_id
        case = self._own_case(principal, case_id)
        if reason not in REASONS:
            _fail(422, f"reason must be one of {list(REASONS)}")
        enabled = self.config.explain_agent_enabled(org)
        s = self._session_for(org, case_id)
        if s is not None:
            s = await self._tick(s)
            if s["state"] != "draft":
                return self.driver_view(s)
        wf, sc = self._workflow_for(org, case_id, reason) if enabled else (None, {"data": {}})
        form = build_form(reason, wf, self.config.k_dynamic(org, self._rule_scope(case)))
        scope = self._rule_scope(case)
        fields = {
            "reason": reason, "form_version": form["form_version"], "form_schema": form, "mode": "agent" if enabled else "fallback",
            "workflow_code": form["workflow"]["code"] if form["workflow"] else None,
            "workflow_version": form["workflow"]["version"] if form["workflow"] else None,
            "n_max": self.config.n_max(org, scope), "last_interaction_at": self.now()}
        if s is None:
            s = self.store.insert("explain_session", {
                "organization_id": org, "case_id": case_id, "driver_id": str(principal.driver_id), "state": "draft", "answers": {},
                "plan": [], "memory": {}, "provenance": [], "open_points": [], "turns_used": 0, "edits_used": 0, "help_count": 0,
                "scenario_code": None, "scenario_version": None, "summary": None, "model": None, "instruction_version": None,
                "submitted_at": None, "started_at": self.now(), "created_at": self.now(), "updated_at": self.now(),
                **{f: False for f in FLAGS}, **fields})
            self.store.audit(org, principal.id, "explain.session.start", {"session_id": s["id"], "case_id": case_id, "mode": fields["mode"]})
        else:
            s.update(fields)
            self._persist(s, where={"state": "draft"})
        return self.driver_view(s)

    # ---- lazy transitions ---------------------------------------------------------------------
    async def _tick(self, s: dict[str, Any]) -> dict[str, Any]:
        """Lazy maintenance: resolve help, then T-minute auto-submit of an idle chat session."""
        if s["state"] == "asking" and s["memory"].get("waiting_help_id"):
            self._refresh_help(s)
            if not s["memory"].get("waiting_help_id") and not s["memory"].get("pending_question"):
                await self._advance(s)
        if s["state"] in ("asking", "summary"):
            idle = self.now() - as_dt(s["last_interaction_at"])
            if idle > timedelta(minutes=self.config.t_draft_minutes(s["organization_id"])):
                await self._auto_submit(s)
        return s

    def _refresh_help(self, s: dict[str, Any]) -> None:
        self.help.expire_lazy(s["organization_id"])
        rid = s["memory"].get("waiting_help_id")
        h = self.store.get("help_request", rid) if rid else None
        if h and h["status"] in ("answered", "expired"):
            s["memory"]["waiting_help_id"] = None
            self._persist(s)

    async def _auto_submit(self, s: dict[str, Any]) -> None:
        self._flag(s, "session_interrupted", "idle beyond T minutes")
        if s["state"] == "asking":
            s["summary"] = (await self.fallback_llm.summarize(self._ctx(s))).text
        self._statement(s, "auto", s["summary"] or "", {"auto": True})
        await self._finalize(s)

    async def sweep(self, org: str) -> int:
        """Sweeper entry (cron/worker): auto-submit every idle session of the org."""
        n = 0
        for s in self.store.find("explain_session", {"organization_id": org, "state": ["asking", "summary"]}):
            before = s["state"]
            s = await self._tick(s)
            n += int(before != s["state"])
        return n

    async def sweep_throttled(self, org: str, min_interval_s: int = SWEEP_MIN_INTERVAL_S) -> int:
        """Sweep at most once per `min_interval_s` per org (in-process); failures never break the caller."""
        now = self.now()
        last = self._last_sweep.get(org)
        if last is not None and (now - last).total_seconds() < min_interval_s:
            return 0
        self._last_sweep[org] = now
        try:
            return await self.sweep(org)
        except Exception:  # noqa: BLE001 - best-effort side effect of a polled endpoint
            logger.warning("explain sweep failed for org %s", org, exc_info=True)
            return 0

    # ---- draft + submit -----------------------------------------------------------------------
    def _load_own(self, principal: Any, case_id: str) -> dict[str, Any]:
        self._own_case(principal, case_id)
        s = self._session_for(principal.organization_id, case_id)
        if not s:
            _fail(404, "Explanation session not found")
        return s

    async def get_for_driver(self, principal: Any, case_id: str) -> dict[str, Any]:
        s = self._load_own(principal, case_id)
        s = await self._tick(s)
        return self.driver_view(s)

    async def save_draft(self, principal: Any, case_id: str, answers: dict[str, Any]) -> dict[str, Any]:
        s = self._load_own(principal, case_id)
        if s["state"] != "draft":
            _fail(409, "The form was already submitted")
        known = {f["id"] for f in s["form_schema"]["fields"]}
        s["answers"] = {**s["answers"], **{k: v for k, v in answers.items() if k in known}}
        s["last_interaction_at"] = self.now()
        self._persist(s, where={"state": "draft"})
        return self.driver_view(s)

    async def submit(self, principal: Any, case_id: str, answers: dict[str, Any]) -> dict[str, Any]:
        s = self._load_own(principal, case_id)
        if s["state"] != "draft":
            _fail(409, "The form was already submitted")
        form = s["form_schema"]
        known = {f["id"] for f in form["fields"]}
        merged = {**s["answers"], **{k: v for k, v in answers.items() if k in known}}
        check = validate_answers(form, merged)
        if check["missing"] or check["invalid"]:
            _fail(422, {"code": "form_invalid", **check})
        enabled = self.config.explain_agent_enabled(s["organization_id"])
        text = statement_text(form, merged)
        s["answers"] = merged
        s["memory"]["statement_text"] = text
        s["submitted_at"] = self.now()
        s["last_interaction_at"] = self.now()
        s["state"] = "investigating" if enabled and s["mode"] == "agent" else "submitted"
        if not enabled:
            s["mode"] = "fallback"
        self._persist(s, where={"state": "draft"})
        self._statement(s, "form", text, {"answers": merged, "reason": s["reason"], "form_version": s["form_version"],
                                           "workflow": form.get("workflow")})
        self.store.audit(s["organization_id"], principal.id, "explain.statement.submit", {"session_id": s["id"], "mode": s["mode"]})
        if s["state"] == "submitted":
            self._hand_over(s)
            self._turn(s, "system", "fallback_submit", payload={"reason": "kill_switch" if not enabled else "mode_fallback"})
            return self.driver_view(s)
        await self._investigate(s)
        return self.driver_view(s)

    # ---- investigation (round 1) --------------------------------------------------------------
    async def _investigate(self, s: dict[str, Any]) -> None:
        org, case_id = s["organization_id"], s["case_id"]
        tools = self.tools(org)
        m = s["memory"]
        m.update({"current_reason": s["reason"], "answers": [], "help_answers": [], "help_expired": [], "contradictions": [],
                  "matched_evidence": [], "missing_internal": [], "waiting_help_id": None, "pending_question": None})
        s["model"] = getattr(self.llm, "model", None)
        s["instruction_version"] = INSTRUCTION_VERSION
        statement = self._stmt(s)
        beh = self._run_logged(s, tools.identify_behavior(org, case_id))
        behaviors = (beh["data"] or {}).get("behaviors", []) if beh["ok"] else []
        if not beh["ok"]:
            m["missing_internal"].append(beh["error"])
        for b in behaviors:
            m["matched_evidence"].append(f"behavior:{b['code']}@{b['version']}")
        lm = self._run_logged(s, tools.list_motives(org))
        motives: list[dict[str, Any]] = []
        if lm["ok"]:
            for mo in lm["data"]["motives"]:
                r = self._run_logged(s, tools.compute_motive(org, case_id, mo["code"]), note=f"compute_motive:{mo['code']}")
                if r["ok"]:
                    motives.append(r["data"])
                else:
                    m["missing_internal"].append(r["error"])
        m["motives"] = motives  # VH only
        sc = self._run_logged(s, tools.match_scenario(org, case_id, s["reason"], behaviors))
        m["similar_scenarios"] = (sc["data"] or {}).get("similar", [])
        wf_body = None
        if sc["ok"] and sc["data"]["matched"]:
            m["scenario"] = sc["data"]["scenario"]
            s["scenario_code"], s["scenario_version"] = sc["data"]["scenario"]["code"], sc["data"]["scenario"]["version"]
            wf = self._run_logged(s, tools.get_workflow(org, sc["data"].get("workflow_code")))
            if wf["ok"]:
                wf_body = wf["data"]["body"]
                s["workflow_code"], s["workflow_version"] = wf["data"]["code"], wf["data"]["version"]
            else:
                m["missing_internal"].append(wf["error"])
        else:
            m["scenario"] = None
            self._flag(s, "novel_scenario", "no published scenario above the similarity threshold")
        m["workflow_body"] = wf_body
        out: AssessmentOut = await self._safe(s, "assess", self._ctx(s), 1)
        s["plan"] = [p.model_dump() for p in (out.plan or default_plan(s["reason"], wf_body))]
        s["open_points"] = list(out.open_points)
        m["confidence"] = out.confidence
        m["missing_internal"] = list(dict.fromkeys([*m["missing_internal"], *out.missing_internal]))
        m["matched_evidence"] = list(dict.fromkeys([*m["matched_evidence"], *out.matched_evidence]))
        self._round(s, 1, "form", out)
        if out.state == "needs_driver":
            s["state"] = "asking"
            self._persist(s)
            self._turn(s, "plan_update", "initial plan", payload={"plan": s["plan"]})
            opening = f"Mình đã nhận giải trình của bạn. Mình cần làm rõ thêm vài điểm nhé.\n{statement}".strip()
            self._turn(s, "agent_message", opening, visible=True)
            await self._advance(s)
        else:
            s["state"] = "submitted"
            self._persist(s)
            self._hand_over(s)

    def _round(self, s: dict[str, Any], no: int, source: str, out: AssessmentOut) -> dict[str, Any]:
        m = s["memory"]
        motive = None
        if m.get("motives"):
            motive = {"items": m["motives"], "visible_to": "vh_only"}
        return self.store.insert("assessment_round", {
            "organization_id": s["organization_id"], "session_id": s["id"], "round": no, "source": source, "state": out.state,
            "matched_evidence": out.matched_evidence, "contradictions": out.contradictions, "open_points": out.open_points,
            "missing_internal": out.missing_internal, "statement_change": out.statement_change, "confidence": out.confidence,
            "suggested_reason_code": out.suggested_reason_code, "suggested_questions": out.suggested_questions, "motive": motive,
            "provenance": list(s["provenance"]), "turns_used": s["turns_used"], "n_max": s["n_max"],
            "llm_used": not m.get("llm_failures"), "created_at": self.now()})

    # ---- agent loop ---------------------------------------------------------------------------
    async def _advance(self, s: dict[str, Any]) -> None:
        """think -> tool -> observe -> ask. Returns with a pending question, a wait, or the summary state."""
        m = s["memory"]
        for _ in range(MAX_ITER):
            self._absorb_help(s)
            if s["turns_used"] >= s["n_max"]:
                self._flag(s, "ai_inconclusive", f"N_max={s['n_max']} reached")
                await self._to_summary(s)
                return
            if m.get("waiting_help_id") and m.get("help_blocking"):
                self._persist(s)
                return
            out: StepOut = await self._safe(s, "step", self._ctx(s))
            self._apply_step(s, out)
            if out.action == "done":
                await self._to_summary(s)
                return
            if out.action == "tool":
                self._agent_tool(s, out.tool or "", out.tool_args)
                continue
            if out.action == "help":
                if self._request_help(s, out.help_trigger or "unverifiable_evidence", out.help_stuck_point or "Cần VH kiểm tra bằng chứng",
                                      out.help_options):
                    self._persist(s)
                    return
                continue
            if (out.confidence is not None and out.confidence < self.config.confidence_threshold(s["organization_id"])
                    and s["turns_used"] >= HELP_AFTER_TURNS and not s["asked_for_help"]):
                self._request_help(s, "low_confidence", "Độ tin cậy thấp sau nhiều lượt", [])
            if s["novel_scenario"] and not s["asked_for_help"] and not s["asked_for_help_skipped"] and s["turns_used"] == 0:
                self._request_help(s, "novel_scenario", "Không có kịch bản đã phát hành khớp với giải trình", [])
            self._ask(s, out)
            self._persist(s)
            return
        await self._to_summary(s)

    def _apply_step(self, s: dict[str, Any], out: StepOut) -> None:
        m = s["memory"]
        by_id = {p["id"]: p for p in s["plan"]}
        changed = False
        for pid in out.plan_done:
            if pid in by_id and not by_id[pid]["done"] and out.action != "ask":
                by_id[pid]["done"] = True
                changed = True
        for p in out.plan_add:
            if p.id not in by_id:
                s["plan"].append(p.model_dump())
                changed = True
        if out.confidence is not None:
            m["confidence"] = out.confidence
        m["contradictions"] = list(dict.fromkeys([*m.get("contradictions", []), *out.contradictions]))
        m["matched_evidence"] = list(dict.fromkeys([*m.get("matched_evidence", []), *out.matched_evidence]))
        if changed:
            self._turn(s, "plan_update", "plan updated", payload={"plan": s["plan"]})
        if out.thought:
            self._turn(s, "system", "thought", payload={"thought": out.thought[:500], "action": out.action})

    def _ask(self, s: dict[str, Any], out: StepOut) -> None:
        m = s["memory"]
        plan_pt = next((p for p in s["plan"] if p["id"] in out.plan_done and not p["done"]), None) \
            or next((p for p in s["plan"] if not p["done"]), None)
        q = (out.question or "").strip() or (plan_pt["text"] if plan_pt else "")
        res = guard.check_agent_text(q)
        if not res.ok:
            self._turn(s, "guard", "rejected agent question", payload={"violations": res.violations, "rejected": q[:300]})
            alt = plan_pt["text"] if plan_pt else ""
            q = alt if guard.check_agent_text(alt).ok else guard.SAFE_QUESTION
        point_id = plan_pt["id"] if plan_pt else None
        if plan_pt:
            plan_pt["done"] = True
        t = self._turn(s, "agent_question", q, visible=True, payload={"plan_point": point_id,
                                                                   "tool": plan_pt.get("tool") if plan_pt else None})
        m["pending_question"] = {"seq": t["seq"], "text": q, "plan_point": point_id}

    def _agent_tool(self, s: dict[str, Any], name: str, args: dict[str, Any]) -> None:
        m = s["memory"]
        org, case_id = s["organization_id"], s["case_id"]
        tools = self.tools(org)
        if name not in allowed_tools(m.get("workflow_body")):
            self._run_logged(s, {"tool": name or "unknown", "ok": False, "data": None, "refs": [],
                                 "error": "không tra được: tool không được workflow cho phép"})
            return
        behaviors = ((m.get("tool_results", {}).get("identify_behavior") or {}).get("data") or {}).get("behaviors", [])
        if name == "identify_behavior":
            r = tools.identify_behavior(org, case_id)
        elif name == "list_motives":
            r = tools.list_motives(org, s.get("scenario_code"))
        elif name == "compute_motive":
            r = tools.compute_motive(org, case_id, str(args.get("motive_code", "")))
        elif name == "match_scenario":
            r = tools.match_scenario(org, case_id, m.get("current_reason", s["reason"]), behaviors)
        elif name == "get_workflow":
            r = tools.get_workflow(org, args.get("code") or s.get("workflow_code"))
        elif name == "propose_knowledge":
            r = self._propose(s, args)
        elif name == "request_help":
            self._request_help(s, "workflow_step", str(args.get("stuck_point") or "Cần VH kiểm tra"), list(args.get("options") or []))
            return
        else:
            r = {"tool": name, "ok": False, "data": None, "refs": [], "error": "không tra được: tool không tồn tại"}
        self._run_logged(s, r)

    def _propose(self, s: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.tools(s["organization_id"]).propose_knowledge(
                s["organization_id"], type_=str(args.get("type", "workflow")), title=str(args.get("title", "Đề xuất từ phiên giải trình"))[:200],
                payload=dict(args.get("payload") or {}), source=str(args.get("source", "closed_case")),
                source_excerpt=args.get("excerpt"), source_ref=f"explain_session:{s['id']}")
        except HTTPException as e:
            return {"tool": "propose_knowledge", "ok": False, "data": None, "refs": [], "error": f"không tra được: {e.detail}"}

    # ---- help ---------------------------------------------------------------------------------
    def _request_help(self, s: dict[str, Any], trigger: str, stuck_point: str, options: list[str]) -> bool:
        """request_help tool. True when a request is now open for this session. Novel-scenario and
        low-confidence requests are non-blocking (the agent keeps asking the default set); the rest block."""
        m = s["memory"]
        if m.get("waiting_help_id"):
            if not m.get("help_blocking") and trigger not in ("novel_scenario", "low_confidence"):
                m["help_blocking"] = True  # a non-blocking request becomes blocking: the driver now cited unverifiable evidence
                self._turn(s, "help", "help_upgraded", payload={"help_id": m["waiting_help_id"], "trigger": trigger})
                self._turn(s, "agent_message", WAIT_MESSAGE, visible=True)
            return bool(m.get("help_blocking"))
        facts = [f"{k}: {v['error'] or 'ok'}" for k, v in (m.get("tool_results") or {}).items()]
        facts += [f"Lời khai: {qa['answer'][:120]}" for qa in m.get("answers", [])[-3:]]
        summary = self._stmt(s)[:600]
        row = self.help.create(s, trigger=trigger, summary=summary, stuck_point=stuck_point, facts=facts,
                               options=options or ["Xác nhận bằng chứng của tài xế", "Không xác nhận được", "Cần tài xế bổ sung thêm"])
        if row is None:
            self._flag(s, "asked_for_help_skipped", "ceiling or per-session maximum reached")
            return False
        s["help_count"] += 1
        self._flag(s, "asked_for_help", trigger)
        m["waiting_help_id"] = row["id"]
        m["help_blocking"] = trigger not in ("novel_scenario", "low_confidence")
        self._turn(s, "help", "request_help", payload={"help_id": row["id"], "trigger": row["trigger"], "stuck_point": stuck_point})
        self._turn(s, "agent_message", WAIT_MESSAGE, visible=True)
        return True

    def _absorb_help(self, s: dict[str, Any]) -> None:
        m = s["memory"]
        for r in self.help.take_resolved(s["id"]):
            if r["status"] == "answered":
                m.setdefault("help_answers", []).append({"help_id": r["id"], "facts": [r["reply"], *(r.get("reply_facts") or [])]})
                self._turn(s, "help", "help_answered", payload={"help_id": r["id"], "reply": r["reply"], "by": r.get("replied_by_name"),
                                                               "wait_seconds": r.get("wait_seconds")})
            else:
                m.setdefault("help_expired", []).append({"help_id": r["id"], "stuck_point": r["stuck_point"]})
                if r["stuck_point"] not in s["open_points"]:
                    s["open_points"].append(r["stuck_point"])
                self._turn(s, "help", "help_expired", payload={"help_id": r["id"]})
            if m.get("waiting_help_id") == r["id"]:
                m["waiting_help_id"] = None

    async def after_help_change(self, session_ids: list[str]) -> None:
        """VH replied or SLA expired: let the agent continue (eager, so a driver poll sees the next question)."""
        for sid in dict.fromkeys(session_ids):
            s = self.store.get("explain_session", sid)
            if s and s["state"] == "asking" and s["memory"].get("waiting_help_id"):
                self._refresh_help(s)
                if not s["memory"].get("waiting_help_id") and not s["memory"].get("pending_question"):
                    await self._advance(s)

    # ---- driver answers -----------------------------------------------------------------------
    async def answer(self, principal: Any, case_id: str, text: str, attachments: list[str] | None = None,
                     ticket_code: str | None = None) -> dict[str, Any]:
        s = self._load_own(principal, case_id)
        s = await self._tick(s)
        if s["state"] != "asking":
            _fail(409, {"code": "not_asking", "state": s["state"]})
        m = s["memory"]
        pending = m.get("pending_question")
        if not pending:
            _fail(409, {"code": "waiting_for_help" if m.get("waiting_help_id") else "no_pending_question"})

        clean = guard.scrub_driver_text(text)
        if not clean and not attachments and not ticket_code:
            _fail(422, "Answer is empty")
        if guard.detect_injection(clean):
            self._turn(s, "flag", "prompt_injection", payload={"flag": "prompt_injection", "excerpt": clean[:200]})
            m["injection_count"] = int(m.get("injection_count", 0)) + 1
        self._turn(s, "driver_answer", clean, visible=True,
                   payload={"attachments": attachments or [], "ticket_code": ticket_code, "answers_seq": pending["seq"]})
        s["turns_used"] += 1
        s["last_interaction_at"] = self.now()
        m["answers"].append({"question": pending["text"], "answer": clean or "(đính kèm)", "ticket_code": ticket_code,
                             "attachments": attachments or []})
        m["pending_question"] = None
        m["unanswered_streak"] = (m.get("unanswered_streak", 0) + 1) if _DONT_KNOW.search(clean) else 0
        if ticket_code:
            m["ticket_code"] = ticket_code
        new_reason = guard.detect_reason_change(clean, m.get("current_reason", s["reason"]))
        if new_reason:
            self._reason_changed(s, new_reason, clean)
        plan_pt = next((p for p in s["plan"] if p["id"] == pending.get("plan_point")), None)
        safety = guard.detect_safety(clean)
        if safety:
            self._request_help(s, "safety", "Tài xế nêu tai nạn hoặc sự cố an toàn", [])
        elif (plan_pt and plan_pt.get("tool") == "request_help") or ticket_code:
            self._request_help(s, "workflow_step" if not ticket_code else "unverifiable_evidence",
                               f"Tài xế đưa bằng chứng agent không tự kiểm tra được: {clean[:160]}", [])
        elif plan_pt and plan_pt.get("tool") and plan_pt["tool"] != "request_help":
            self._agent_tool(s, plan_pt["tool"], {})
        if m["unanswered_streak"] >= 2:
            self._turn(s, "agent_message", OFFER_END_MESSAGE, visible=True)
            m["unanswered_streak"] = 0
        await self._advance(s)
        return self.driver_view(s)

    def _reason_changed(self, s: dict[str, Any], new_reason: str, text: str) -> None:
        m = s["memory"]
        old = m.get("current_reason", s["reason"])
        m["current_reason"] = new_reason
        m["statement_change"] = f"{old} -> {new_reason}"
        self._flag(s, "statement_changed", m["statement_change"])
        self._statement(s, "chat", text, {"reason_change": {"from": old, "to": new_reason}}, reason=new_reason)
        tools = self.tools(s["organization_id"])
        behaviors = ((m.get("tool_results", {}).get("identify_behavior") or {}).get("data") or {}).get("behaviors", [])
        sc = self._run_logged(s, tools.match_scenario(s["organization_id"], s["case_id"], new_reason, behaviors), note="re-match after reason change")
        if sc["ok"] and sc["data"]["matched"]:
            m["scenario"] = sc["data"]["scenario"]
            s["scenario_code"], s["scenario_version"] = sc["data"]["scenario"]["code"], sc["data"]["scenario"]["version"]
            wf = self._run_logged(s, tools.get_workflow(s["organization_id"], sc["data"].get("workflow_code")))
            if wf["ok"]:
                m["workflow_body"] = wf["data"]["body"]
                s["workflow_code"], s["workflow_version"] = wf["data"]["code"], wf["data"]["version"]
                known = {p["id"] for p in s["plan"]}
                new_pts = [p.model_dump() for p in default_plan(new_reason, wf["data"]["body"]) if p.id not in known]
                s["plan"].extend(new_pts)
                self._turn(s, "plan_update", "plan re-based on new reason", payload={"plan": s["plan"]})

    # ---- end / summary ------------------------------------------------------------------------
    async def end(self, principal: Any, case_id: str) -> dict[str, Any]:
        s = self._load_own(principal, case_id)
        s = await self._tick(s)
        if s["state"] != "asking":
            _fail(409, {"code": "not_asking", "state": s["state"]})
        s["last_interaction_at"] = self.now()
        s["memory"]["pending_question"] = None
        await self._to_summary(s)
        return self.driver_view(s)

    async def _to_summary(self, s: dict[str, Any]) -> None:
        out: SummaryOut = await self._safe(s, "summarize", self._ctx(s))
        s["summary"] = out.text
        s["state"] = "summary"
        s["memory"]["pending_question"] = None
        s["last_interaction_at"] = self.now()
        self._turn(s, "agent_message", CLOSE_MESSAGE, visible=True)
        self._turn(s, "agent_message", out.text, visible=True, payload={"kind": "summary"})
        self._persist(s)

    async def edit_summary(self, principal: Any, case_id: str, text: str) -> dict[str, Any]:
        s = self._load_own(principal, case_id)
        s = await self._tick(s)
        if s["state"] != "summary":
            _fail(409, {"code": "not_in_summary", "state": s["state"]})
        limit = self.config.edit_limit(s["organization_id"])
        if s["edits_used"] >= limit:
            _fail(409, {"code": "edit_limit", "limit": limit})
        clean = guard.scrub_driver_text(text)
        if len(clean) < 3:
            _fail(422, "Edit text is required")
        if guard.detect_injection(clean):
            self._turn(s, "flag", "prompt_injection", payload={"flag": "prompt_injection", "excerpt": clean[:200]})
        out: SummaryOut = await self._safe(s, "summarize", self._ctx(s, edit=clean, previous_summary=s["summary"]))
        s["summary"] = out.text
        s["edits_used"] += 1
        s["last_interaction_at"] = self.now()
        self._statement(s, "edit", clean, {"edit": clean, "summary": out.text})
        self._turn(s, "driver_answer", clean, visible=True, payload={"kind": "summary_edit"})
        self._turn(s, "agent_message", out.text, visible=True, payload={"kind": "summary"})
        self._persist(s)
        return self.driver_view(s)

    async def confirm_summary(self, principal: Any, case_id: str) -> dict[str, Any]:
        s = self._load_own(principal, case_id)
        s = await self._tick(s)
        if s["state"] != "summary":
            _fail(409, {"code": "not_in_summary", "state": s["state"]})
        self._statement(s, "summary", s["summary"] or "", {"confirmed": True})
        await self._finalize(s, expect="summary")
        return self.driver_view(s)

    async def _finalize(self, s: dict[str, Any], expect: str | None = None) -> None:
        """Round-2 assessment and hand-over to VH (state submitted)."""
        s["memory"]["pending_question"] = None
        self._absorb_help(s)
        out: AssessmentOut = await self._safe(s, "assess", self._ctx(s, summary=s["summary"]), 2)
        self._round(s, 2, "chat", out)
        s["open_points"] = list(dict.fromkeys([*s["open_points"], *out.open_points]))
        s["memory"]["confidence"] = out.confidence
        s["state"] = "submitted"
        s["last_interaction_at"] = self.now()
        self._persist(s, where={"state": expect} if expect else None)
        self.store.audit(s["organization_id"], None, "explain.session.submitted",
                         {"session_id": s["id"], "interrupted": s["session_interrupted"], "inconclusive": s["ai_inconclusive"]})
        self._hand_over(s)

    def _hand_over(self, s: dict[str, Any]) -> None:
        """Submitted explanation -> case waits on analysts (dispute_status pending_review; status unchanged)."""
        if self.store.mark_driver_answered(s["organization_id"], s["case_id"]):
            self.store.audit(s["organization_id"], None, "explain.case.pending_review", {"case_id": s["case_id"], "session_id": s["id"]})

    # ---- views --------------------------------------------------------------------------------
    def driver_view(self, s: dict[str, Any]) -> dict[str, Any]:
        m = s.get("memory") or {}
        turns = self.store.find("explain_turn", {"session_id": s["id"], "visible_to_driver": True}, order="seq asc")
        state = s["state"]
        ui = {"draft": "form", "investigating": "checking", "asking": "chat", "summary": "summary", "submitted": "submitted"}[state]
        q = m.get("pending_question")
        return {
            "session_id": s["id"], "case_id": s["case_id"], "state": state, "ui_status": ui, "mode": s["mode"], "reason": s["reason"],
            "form": {**driver_form_view(s["form_schema"]), "answers": s["answers"]},
            "messages": [{"seq": t["seq"], "role": "driver" if t["kind"] == "driver_answer" else "agent", "kind": t["kind"],
                          "text": t["content"], "at": _iso(t["created_at"]), "is_summary": (t.get("payload") or {}).get("kind") == "summary"}
                         for t in turns],
            "current_question": {"seq": q["seq"], "text": q["text"]} if q and state == "asking" else None,
            "waiting_for_help": bool(m.get("waiting_help_id")) and bool(m.get("help_blocking")) and state == "asking",
            "can_end": state == "asking", "summary": s["summary"] if state in ("summary", "submitted") else None,
            "edits_left": max(0, self.config.edit_limit(s["organization_id"]) - s["edits_used"]) if state == "summary" else 0,
            "status_text": CHECKING_MESSAGE if state == "investigating" else (SUBMITTED_MESSAGE if state == "submitted" else None),
            "submitted_at": _iso(s["submitted_at"]), "last_interaction_at": _iso(s["last_interaction_at"]),
            "idle_timeout_minutes": self.config.t_draft_minutes(s["organization_id"])}

    def analyst_view(self, actor: Any, case_id: str) -> dict[str, Any]:
        if not set(actor.roles) & ANALYST_ROLES:
            _fail(403, "Insufficient role permissions")
        self._case(actor.organization_id, case_id)
        s = self._session_for(actor.organization_id, case_id)
        if not s:
            _fail(404, "Explanation session not found")
        self.help.expire_lazy(actor.organization_id)
        sid = s["id"]
        rounds = self.store.find("assessment_round", {"session_id": sid}, order="round asc")
        versions = self.store.find("statement_version", {"session_id": sid}, order="version asc")
        turns = self.store.find("explain_turn", {"session_id": sid}, order="seq asc")
        helps = self.help.for_session(sid)
        fb = self.store.find("vh_feedback", {"session_id": sid}, order="created_at asc")
        latest = rounds[-1] if rounds else None
        m = s["memory"]
        return {
            "session": {k: s[k] for k in ("id", "case_id", "driver_id", "reason", "state", "mode", "form_version", "workflow_code",
                                          "workflow_version", "scenario_code", "scenario_version", "turns_used", "n_max", "edits_used",
                                          "help_count", "model", "instruction_version", "summary")}
                       | {"current_reason": m.get("current_reason", s["reason"]), "submitted_at": _iso(s["submitted_at"]),
                          "started_at": _iso(s["started_at"]), "last_interaction_at": _iso(s["last_interaction_at"])},
            "flags": {f: bool(s[f]) for f in FLAGS},
            "form": {**s["form_schema"], "answers": s["answers"]},
            "statement_versions": [{"version": v["version"], "source": v["source"], "reason": v["reason"], "text": v["text"],
                                    "content": v["content"], "created_at": _iso(v["created_at"])} for v in versions],
            "rounds": [{"round": r["round"], "source": r["source"], "state": r["state"], "matched_evidence": r["matched_evidence"],
                        "contradictions": r["contradictions"], "open_points": r["open_points"], "missing_internal": r["missing_internal"],
                        "statement_change": r["statement_change"], "confidence": r["confidence"], "turns_used": r["turns_used"],
                        "n_max": r["n_max"], "llm_used": r["llm_used"], "created_at": _iso(r["created_at"])} for r in rounds],
            "transcript": [{"seq": t["seq"], "kind": t["kind"], "visible_to_driver": t["visible_to_driver"], "text": t["content"],
                            "tool": t["tool"], "kb_code": t["kb_code"], "kb_version": t["kb_version"], "payload": t["payload"],
                            "at": _iso(t["created_at"])} for t in turns],
            "provenance": s["provenance"],
            "similar_scenarios": (m.get("similar_scenarios") or [])[:3],
            "plan": s["plan"], "open_points": s["open_points"],
            "suggestion": None if not latest else {
                "round": latest["round"], "state": latest["state"], "reason_code": latest["suggested_reason_code"],
                "confidence": latest["confidence"], "motive": latest["motive"], "suggested_questions": latest["suggested_questions"],
                "turns_used": s["turns_used"], "n_max": s["n_max"]},
            "help_requests": [self._help_row(h) for h in helps],
            "feedback": [{"id": f["id"], "verdict": f["verdict"], "error_types": f["error_types"], "comment": f["comment"],
                          "author_name": f["author_name"], "created_at": _iso(f["created_at"])} for f in fb],
        }

    @staticmethod
    def _help_row(h: dict[str, Any]) -> dict[str, Any]:
        return {"id": h["id"], "session_id": h["session_id"], "case_id": h["case_id"], "status": h["status"], "trigger": h["trigger"],
                "summary": h["summary"], "stuck_point": h["stuck_point"], "facts": h["facts"], "options": h["options"],
                "claimed_by_name": h.get("claimed_by_name"), "claimed_at": _iso(h.get("claimed_at")), "reply": h.get("reply"),
                "reply_facts": h.get("reply_facts") or [], "replied_by_name": h.get("replied_by_name"),
                "replied_at": _iso(h.get("replied_at")), "wait_seconds": h.get("wait_seconds"), "proposal_id": h.get("proposal_id"),
                "created_at": _iso(h["created_at"]), "expires_at": _iso(h["expires_at"])}

    # ---- VH feedback --------------------------------------------------------------------------
    def feedback(self, actor: Any, case_id: str, verdict: str, error_types: list[str], comment: str | None) -> dict[str, Any]:
        if not set(actor.roles) & FEEDBACK_ROLES:
            _fail(403, "Insufficient role permissions")
        self._case(actor.organization_id, case_id)
        s = self._session_for(actor.organization_id, case_id)
        if not s:
            _fail(404, "Explanation session not found")
        if verdict not in ("agree", "disagree"):
            _fail(422, "verdict must be agree or disagree")
        bad = [e for e in error_types if e not in FEEDBACK_ERROR_TYPES]
        if bad:
            _fail(422, f"unknown error types {bad}")
        if verdict == "disagree" and not error_types:
            _fail(422, "Disagree requires at least one error type")
        row = self.store.insert("vh_feedback", {
            "organization_id": s["organization_id"], "session_id": s["id"], "case_id": case_id, "verdict": verdict,
            "error_types": error_types if verdict == "disagree" else [], "comment": (comment or "").strip() or None,
            "author_id": actor.id, "author_name": self.store.principal_name(actor.id), "created_at": self.now()})
        self.store.audit(actor.organization_id, actor.id, "explain.feedback", {"session_id": s["id"], "verdict": verdict, "errors": error_types})
        return {"id": row["id"], "verdict": row["verdict"], "error_types": row["error_types"], "comment": row["comment"],
                "created_at": _iso(row["created_at"])}

    # ---- help queue (analyst stands in for VH) ------------------------------------------------
    async def help_queue(self, actor: Any, status: str | None = None) -> dict[str, Any]:
        self.help.require_vh(actor)
        await self._expired(self.help.expire_lazy(actor.organization_id))
        q = self.help.queue(actor, status)
        return {"items": [self._help_row(h) for h in q["items"]], "counts": q["counts"]}

    async def help_count(self, actor: Any) -> dict[str, int]:
        self.help.require_vh(actor)
        await self.sweep_throttled(actor.organization_id)
        await self._expired(self.help.expire_lazy(actor.organization_id))
        return self.help.counts(actor.organization_id, expire=False)

    async def _expired(self, rows: list[dict[str, Any]]) -> None:
        await self.after_help_change([r["session_id"] for r in rows])

    async def help_detail(self, actor: Any, help_id: str) -> dict[str, Any]:
        self.help.require_vh(actor)
        await self._expired(self.help.expire_lazy(actor.organization_id))
        h = self.help.get(actor, help_id)
        s = self.store.get("explain_session", h["session_id"])
        turns = self.store.find("explain_turn", {"session_id": h["session_id"]}, order="seq asc")
        return {**self._help_row(h), "transcript": [{"seq": t["seq"], "kind": t["kind"], "text": t["content"]} for t in turns
                                                      if t["kind"] in ("agent_question", "agent_message", "driver_answer")],
                "statement_text": self._stmt(s) if s else None, "reason": (s or {}).get("reason")}

    async def help_claim(self, actor: Any, help_id: str) -> dict[str, Any]:
        await self._expired(self.help.expire_lazy(actor.organization_id))
        return self._help_row(self.help.claim(actor, help_id))

    async def help_reply(self, actor: Any, help_id: str, text: str, facts: list[str] | None = None) -> dict[str, Any]:
        row = self.help.reply(actor, help_id, text, facts)
        await self.after_help_change([row["session_id"]])
        return self._help_row(row)


_service: ExplainService | None = None


def get_explain_service() -> ExplainService:
    global _service
    if _service is None:
        _service = ExplainService()
    return _service


__all__ = ["ExplainService", "get_explain_service", "FLAGS", "FEEDBACK_ERROR_TYPES", "REASON_LABELS", "VH_QUEUE_ROLES"]
