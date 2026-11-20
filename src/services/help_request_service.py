"""Help requests (`request_help`): create / claim / reply / lazy expiry, ceiling and proposal generation
(PRD-A US3, PRD-K US4, ADR-034). VH roles (and the analyst standing in for VH) work the queue.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException

from src.services.agent_config_service import AgentConfigService
from src.services.kb_service import KbService
from src.services.kb_store import Store

VH_QUEUE_ROLES = frozenset({"analyst", "senior_analyst", "fraud_analyst", "admin", "reviewer", "manager"})
OPEN_STATES = ("open", "claimed")
TRIGGERS = ("novel_scenario", "low_confidence", "unverifiable_evidence", "conflicting_sources", "safety", "workflow_step")
REPLY_MIN = 3


def _fail(status: int, detail: Any):
    raise HTTPException(status, detail)


def as_dt(v: Any) -> datetime | None:
    if v is None or isinstance(v, datetime):
        return v
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


class HelpRequestService:
    def __init__(self, store: Store, config: AgentConfigService, kb: KbService, now: Callable[[], datetime] | None = None):
        self.store = store
        self.config = config
        self.kb = kb
        self.now = now or (lambda: datetime.now(UTC))

    @staticmethod
    def require_vh(actor: Any) -> None:
        if not set(actor.roles) & VH_QUEUE_ROLES:
            _fail(403, "Insufficient role permissions")

    # ---- lifecycle ----------------------------------------------------------------------------
    def create(self, session: dict[str, Any], *, trigger: str, summary: str, stuck_point: str, facts: list[str],
               options: list[str]) -> dict[str, Any] | None:
        """Returns the request, or None when skipped (ceiling or per-session maximum reached)."""
        org = session["organization_id"]
        self.expire_lazy(org)
        per_session = int(self.config.get(org, "help_max_per_session", default=2))
        if int(session.get("help_count", 0)) >= per_session:
            return None
        queue = self.store.find("help_request", {"organization_id": org, "status": list(OPEN_STATES)})
        if len(queue) >= self.config.help_ceiling(org):
            return None
        sla = int(self.config.get(org, "help_sla_minutes", default=15))
        now = self.now()
        row = self.store.insert("help_request", {
            "organization_id": org, "session_id": session["id"], "case_id": session["case_id"], "status": "open",
            "trigger": trigger if trigger in TRIGGERS else "unverifiable_evidence", "summary": summary,
            "stuck_point": stuck_point, "facts": facts[:10], "options": options[:3], "reply_facts": [], "consumed": False,
            "created_at": now, "updated_at": now, "expires_at": now + timedelta(minutes=sla)})
        self.store.audit(org, None, "explain.help.create", {"help_id": row["id"], "case_id": session["case_id"], "trigger": row["trigger"]})
        return row

    def expire_lazy(self, org: str) -> list[dict[str, Any]]:
        """Expire open/claimed requests past their SLA; returns the rows that just expired."""
        now = self.now()
        out = []
        for r in self.store.find("help_request", {"organization_id": org, "status": list(OPEN_STATES)}):
            exp = as_dt(r["expires_at"])
            if exp is not None and exp <= now:
                upd = self.store.update("help_request", r["id"], {"status": "expired", "updated_at": now,
                                                                    "wait_seconds": int((now - as_dt(r["created_at"])).total_seconds())},
                                        where={"status": list(OPEN_STATES)})
                if upd:
                    self.store.audit(org, None, "explain.help.expire", {"help_id": r["id"]})
                    out.append(upd)
        return out

    def _load(self, actor: Any, help_id: str) -> dict[str, Any]:
        r = self.store.get("help_request", help_id)
        if not r or str(r["organization_id"]) != str(actor.organization_id):
            _fail(404, "Help request not found")
        return r

    def claim(self, actor: Any, help_id: str) -> dict[str, Any]:
        self.require_vh(actor)
        self.expire_lazy(actor.organization_id)
        r = self._load(actor, help_id)
        if r["status"] == "claimed" and r["claimed_by"] == actor.id:
            return r
        if r["status"] != "open":
            _fail(409, f"Help request is {r['status']}")
        now = self.now()
        upd = self.store.update("help_request", r["id"], {"status": "claimed", "claimed_by": actor.id, "claimed_at": now,
                                                          "claimed_by_name": self.store.principal_name(actor.id), "updated_at": now},
                                where={"status": "open"})
        if upd is None:
            _fail(409, "Help request was claimed by someone else")
        self.store.audit(actor.organization_id, actor.id, "explain.help.claim", {"help_id": r["id"]})
        return upd

    def reply(self, actor: Any, help_id: str, text: str, facts: list[str] | None = None) -> dict[str, Any]:
        self.require_vh(actor)
        self.expire_lazy(actor.organization_id)
        r = self._load(actor, help_id)
        if len((text or "").strip()) < REPLY_MIN:
            _fail(422, "Reply text is required")
        if r["status"] == "expired":
            _fail(409, "Help request expired")
        if r["status"] == "answered":
            _fail(409, "Help request already answered")
        if r["status"] == "claimed" and r["claimed_by"] != actor.id and "admin" not in actor.roles:
            _fail(409, "Help request is claimed by someone else")
        now = self.now()
        upd = self.store.update("help_request", r["id"], {
            "status": "answered", "reply": text.strip(), "reply_facts": [f for f in (facts or []) if str(f).strip()][:10],
            "replied_by": actor.id, "replied_by_name": self.store.principal_name(actor.id), "replied_at": now,
            "claimed_by": r["claimed_by"] or actor.id, "claimed_at": r["claimed_at"] or now, "updated_at": now,
            "wait_seconds": int((now - as_dt(r["created_at"])).total_seconds())}, where={"status": list(OPEN_STATES)})
        if upd is None:
            _fail(409, "Help request changed concurrently")
        self.store.audit(actor.organization_id, actor.id, "explain.help.reply", {"help_id": r["id"]})
        prop = self._proposal_from_reply(upd)
        upd = self.store.update("help_request", upd["id"], {"proposal_id": prop["id"]}) or upd
        return upd

    def _proposal_from_reply(self, h: dict[str, Any]) -> dict[str, Any]:
        """Draft workflow step proposal from the VH answer (never published by the agent)."""
        code = f"WF_HELP_{str(h['id'])[:8].upper()}"
        return self.kb.create_proposal(
            h["organization_id"], source="help_reply", type="workflow", mapping="new",
            title=f"Bước workflow từ kêu cứu: {h['stuck_point'][:80]}",
            payload={"code": code, "name": f"Từ kêu cứu · {h['stuck_point'][:40]}",
                     "body": {"ask_first": [], "steps": [{"question": h["stuck_point"], "tool": "request_help",
                                                          "branch": h["reply"]}]}},
            source_excerpt=h["reply"], source_ref=f"help_request:{h['id']}", created_by="driver_agent")

    # ---- reads --------------------------------------------------------------------------------
    def take_resolved(self, session_id: str) -> list[dict[str, Any]]:
        """Answered/expired requests of a session whose result the agent has not consumed yet."""
        rows = self.store.find("help_request", {"session_id": session_id, "consumed": False, "status": ["answered", "expired"]},
                               order="created_at asc")
        for r in rows:
            self.store.update("help_request", r["id"], {"consumed": True})
        return rows

    def for_session(self, session_id: str) -> list[dict[str, Any]]:
        return self.store.find("help_request", {"session_id": session_id}, order="created_at asc")

    def queue(self, actor: Any, status: str | None = None) -> dict[str, Any]:
        self.require_vh(actor)
        org = actor.organization_id
        self.expire_lazy(org)
        wanted = [s for s in (status or "open,claimed").split(",") if s in ("open", "claimed", "answered", "expired")] or list(OPEN_STATES)
        rows = self.store.find("help_request", {"organization_id": org, "status": wanted}, order="created_at asc")
        return {"items": rows, "counts": self.counts(org, expire=False)}

    def counts(self, org: str, expire: bool = True) -> dict[str, int]:
        if expire:
            self.expire_lazy(org)
        rows = self.store.find("help_request", {"organization_id": org, "status": list(OPEN_STATES)})
        o = sum(1 for r in rows if r["status"] == "open")
        return {"open": o, "claimed": len(rows) - o, "total": len(rows)}

    def get(self, actor: Any, help_id: str) -> dict[str, Any]:
        self.require_vh(actor)
        self.expire_lazy(actor.organization_id)
        return self._load(actor, help_id)
