"""Issue 60 long-conversation runner; gold scores only, live API state gates outcomes."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request

DEFAULT_GOLDEN = Path(__file__).parent / "golden_set/agent_conversations_v1.json"
TERMINAL_EVENTS = {"run.completed", "run.error", "terminal", "done", "complete", "error"}
CATALOG = {
    "get_case_context",
    "list_cases",
    "get_trip_lifecycle_evidence",
    "inspect_trip_telemetry",
    "compare_trip_routes",
    "check_system_error_guardrail",
    "check_traffic_situation",
    "check_weather_condition",
    "get_driver_history",
    "check_related_cases_to_vehicle",
    "search_policy_documents",
    "get_dispute_dossier",
    "search_case_precedents",
    "get_case_map_snapshot",
    "draft_evidence_request",
    "draft_case_minutes",
    "preview_case_minutes",
    "request_action_approval",
    "ask_interactive_question",
    "get_action_status",
}
TOOL_ALIASES = {
    "get_case_evidence": "get_trip_lifecycle_evidence",
    "get_route_snapshot": "get_case_map_snapshot",
    "get_driver_telemetry": "inspect_trip_telemetry",
    "get_platform_status": "check_system_error_guardrail",
    "get_provider_status": "check_system_error_guardrail",
    "get_policy_version": "search_policy_documents",
    "get_interactive_question": "ask_interactive_question",
    "record_question_answer": "get_action_status",
    "get_driver_conversation": "get_dispute_dossier",
    "get_delivery_status": "get_action_status",
    "get_actor_permissions": "get_case_context",
}


@dataclass
class TurnResult:
    turn_id: str
    status_code: int
    latency_ms: float
    events: list[dict[str, Any]]
    answer: str = ""
    trace_refs: list[str] | None = None
    error: str | None = None


def load_scenarios(path: Path = DEFAULT_GOLDEN) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != "1.0" or not isinstance(data.get("scenarios"), list):
        raise ValueError("invalid golden-set schema")
    ids = set()
    seed_path = path.parents[2] / "data/synthetic/seed_data.json"
    seeded_ids = []
    if seed_path.exists():
        try:
            seed_data = json.loads(seed_path.read_text(encoding="utf-8"))
            seeded_ids = [str(row["id"]) for row in seed_data.get("cases", []) if row.get("id")]
        except (OSError, json.JSONDecodeError):
            seeded_ids = []
    for s in data["scenarios"]:
        if s.get("id") in ids or not s.get("id") or not s.get("case_id") or len(s.get("turns", [])) < 12:
            raise ValueError(f"invalid or duplicate scenario: {s.get('id')}")
        ids.add(s["id"])
        if s["case_id"].startswith("seed-") and seeded_ids:
            s["case_id"] = seeded_ids[len(ids) - 1]
        if any(not isinstance(t, str) or not t.strip() for t in s["turns"]):
            raise ValueError(f"empty turn in {s['id']}")
        if not s.get("gold", {}).get("required_tools"):
            raise ValueError(f"held-out gold missing for {s['id']}")
        s["gold"]["required_tools"] = [TOOL_ALIASES.get(x, x) for x in s["gold"]["required_tools"]]
        unknown = set(s["gold"]["required_tools"]) - CATALOG
        if unknown:
            raise ValueError(f"non-catalog tools in {s['id']}: {sorted(unknown)}")
    return data["scenarios"]


def parse_sse(raw: str) -> list[dict[str, Any]]:
    out = []
    event = "message"
    data = []

    def flush():
        nonlocal event, data
        if data:
            try:
                value = json.loads("\n".join(data))
            except json.JSONDecodeError:
                value = {"text": "\n".join(data)}
            if isinstance(value, dict):
                value.setdefault("event", event)
                out.append(value)
        event = "message"
        data = []

    for line in raw.splitlines():
        if not line.strip():
            flush()
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    flush()
    return out


def payload(e: dict[str, Any]) -> dict[str, Any]:
    value = e.get("payload") or e.get("data") or e
    return value if isinstance(value, dict) else {}


def event_kind(e: dict[str, Any]) -> str:
    return str(e.get("event") or e.get("type") or e.get("kind") or payload(e).get("type") or "")


def tool_records(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pair tool.start/end by tool_call_id, preserving observed sequence and repeats."""
    active = {}
    records = []
    for seq, e in enumerate(events):
        p = payload(e)
        kind = event_kind(e)
        cid = str(p.get("tool_call_id") or e.get("tool_call_id") or f"seq-{seq}")
        name = p.get("tool") or p.get("name") or e.get("tool") or e.get("name")
        if kind == "interaction.request":
            tool_id = p.get("tool_id")
            data = p.get("data") if isinstance(p.get("data"), dict) else {}
            records.append(
                {
                    "tool_call_id": cid,
                    "tool": str(tool_id or ""),
                    "sequence": seq,
                    "payload": data,
                    "status": "requested",
                }
            )
        elif kind.endswith("tool.start"):
            active[cid] = {"tool_call_id": cid, "tool": str(name or ""), "start_sequence": seq}
        elif kind.endswith("tool.end"):
            row = active.pop(cid, {"tool_call_id": cid, "tool": str(name or "")})
            row.update(end_sequence=seq, status=p.get("status") or e.get("status"))
            records.append(row)
        elif name:
            records.append({"tool_call_id": cid, "tool": str(name), "sequence": seq, "status": p.get("status")})
    records.extend({**row, "status": "open"} for row in active.values())
    return records


def _post_stream(base, case, query, turn, token, timeout):
    body = json.dumps({"query": query, "turn_id": turn, "event_schema_version": "1.1"}).encode()
    req = request.Request(
        f"{base.rstrip('/')}/api/v1/cases/{case}/agent-runtime/stream",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "text/event-stream"},
    )
    start = time.perf_counter()
    with request.urlopen(req, timeout=timeout) as res:
        return res.status, res.read().decode(), (time.perf_counter() - start) * 1000


def run_scenario(scenario, *, base_url, token, post=_post_stream, timeout=120, respondent=None):
    rows = []
    for n, query in enumerate(scenario["turns"], 1):
        tid = f"{scenario['id']}-t{n:02d}"
        try:
            status, raw, latency = post(base_url, scenario["case_id"], query, tid, token, timeout)
            events = parse_sse(raw)
            refs = [
                str(payload(e)[key])
                for e in events
                for key in ("trace_id", "run_id", "trace_url")
                if payload(e).get(key)
            ]
            answer = "".join(str(payload(e).get(key, "")) for e in events for key in ("text", "answer", "content"))
            row = TurnResult(tid, status, latency, events, answer, refs)
            rows.append(row)
            if respondent:
                for e in events:
                    if payload(e).get("kind") == "question" or event_kind(e).endswith("question"):
                        respondent({"case_id": scenario["case_id"], "question": payload(e), "turn_id": tid})
        except (error.HTTPError, error.URLError, TimeoutError) as exc:
            rows.append(TurnResult(tid, getattr(exc, "code", 0), 0, [], error=str(exc)))
    return score_scenario(scenario, rows)


def score_scenario(scenario, turns: Iterable[TurnResult], api_state=None):
    rows = list(turns)
    gold = scenario["gold"]
    records = [r for t in rows for r in tool_records(t.events)]
    names = [r["tool"] for r in records if r.get("tool")]
    expected = set(gold["required_tools"])
    terminals = [e for t in rows for e in t.events if event_kind(e) in TERMINAL_EVENTS]
    live = bool(api_state and api_state.get("live") and api_state.get("terminal_outcome"))
    positive = bool(gold.get("requires_terminal_proof"))
    terminal_proof = bool(
        live and (api_state or {}).get("terminal_artifact_id") and (api_state or {}).get("terminal_outcome")
    )
    return {
        "scenario_id": scenario["id"],
        "turns": len(rows),
        "tool_records": records,
        "tool_coverage": len(set(names) & expected) / len(expected),
        "tool_sequence": [r["tool"] for r in records],
        "terminal_event": terminals[-1] if terminals else None,
        "terminal_outcome": (api_state or {}).get("terminal_outcome"),
        "terminal_matches_api_state": terminal_proof if positive else False,
        "live_state_verified": live,
        "terminal_proof": terminal_proof,
        "human_signoff": (api_state or {}).get("human_signoff"),
        "delivery": (api_state or {}).get("delivery"),
        "duplicate_result": (api_state or {}).get("duplicate_result"),
        "denied_count": (api_state or {}).get("denied_count", 0),
        "langsmith_trace_refs": sorted(set(x for t in rows for x in (t.trace_refs or []))),
        "latency_ms": {
            "p50": statistics.median([t.latency_ms for t in rows]) if rows else 0,
            "p95": sorted([t.latency_ms for t in rows])[max(0, int(len(rows) * 0.95) - 1)] if rows else 0,
        },
        "http_errors": sum(t.status_code >= 400 or bool(t.error) for t in rows),
        "failed_closed": positive and not terminal_proof,
    }


def aggregate_case_state(case_id: str, fetch: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
    state = fetch(case_id)
    if not state.get("live", True):
        raise ValueError("case state is not live API state")
    return {"case_id": case_id, **state}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--token", required=True)
    ap.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    ap.add_argument("--scenario")
    ap.add_argument("--timeout", type=float, default=120)
    ap.add_argument("--mode", choices=("live", "fixture"), default="live")
    ap.add_argument("--state-path-template", default="/api/v1/cases/{case_id}")
    args = ap.parse_args()
    scenarios = load_scenarios(args.golden)
    if args.scenario:
        scenarios = [s for s in scenarios if s["id"] == args.scenario]
    if not scenarios:
        raise SystemExit("no matching scenarios")
    if args.mode == "fixture":
        raise SystemExit("fixture mode has no CLI state mutation; use injected HTTP seam")

    def fetch(case_id):
        req = request.Request(
            args.base_url.rstrip("/") + args.state_path_template.format(case_id=case_id),
            headers={"Authorization": f"Bearer {args.token}"},
        )
        with request.urlopen(req, timeout=args.timeout) as res:
            value = json.loads(res.read())
            value["live"] = True
            return value

    results = []
    for s in scenarios:
        result = run_scenario(s, base_url=args.base_url, token=args.token, timeout=args.timeout)
        try:
            result["api_state"] = aggregate_case_state(s["case_id"], fetch)
        except (error.HTTPError, error.URLError, TimeoutError, ValueError) as exc:
            result["api_state_error"] = str(exc)
            result["failed_closed"] = True
        results.append(result)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
