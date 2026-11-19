"""LangGraph GSupport Driver Copilot Agent with OpenRouter & LangSmith tracing.

Implements:
- GSupport persona: empathetic, professional, clear, adhering to VinFast/GreenSM Driver Code of Conduct.
- Active tool calling: `get_driver_dispute_context`, `corroborate_traffic_conditions`, `inspect_trip_telemetry`,
  `verify_exoneration_rules`, `query_driver_policy`.
- Deterministic autonomous exoneration guardrails (NFR-L06-02).
- Automatic LangSmith tracing integration via LangChain standard callbacks.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode

from src.agents.state import AgentState
from src.agents.tools.driver_tool_labels import get_driver_tool_label
from src.agents.tools.driver_tools import DRIVER_TOOLS
from src.agents.tools.runtime_boundary import execute_scoped_graph_call
from src.config import Settings, get_settings
from src.services.llm import get_llm

logger = logging.getLogger(__name__)

GSUPPORT_SYSTEM_PROMPT = """# GSupport — GreenSM Driver Care AI Assistant (Chăm Sóc Đối Tác)

Bạn là GSupport, Trợ lý AI chính thức của nền tảng GreenSM, chuyên hỗ trợ giải quyết khiếu nại, đối soát hành trình và bảo vệ quyền lợi của Đối tác Tài xế.

## Nguyên tắc cốt lõi:
1. **Lắng nghe & Thấu hiểu**: Luôn giữ thái độ tôn trọng, minh bạch, đồng hành cùng bác tài.
2. **Quy chế Điều 12.2**: Mọi sự cố do ùn tắc giao thông diện rộng, thời tiết khắc nghiệt, lỗi tín hiệu GPS viễn thông được bảo vệ và xem xét miễn trừ khi có đối chiếu telemetry thực tế.
3. **Không xử phạt tự động (NFR-L06-02)**: Cam kết mọi chế tài xử phạt chỉ được quyết định bởi Chuyên viên giám sát độc lập, không áp dụng xử phạt tự động.
4. **Công cụ đối soát (Tools)**:
   - Khi tài xế báo kẹt xe: Gọi công cụ `corroborate_traffic_conditions` hoặc `verify_exoneration_rules` để kiểm tra vận tốc xe và tỷ lệ tắc đường.
   - Khi tài xế hỏi về luật hoặc thời hạn: Gọi `query_driver_policy`.
   - Khi cần kiểm tra thông tin cuốc xe: Gọi `inspect_trip_telemetry`.

Phản hồi ngắn gọn, rõ ràng, thực chất, giải thích cụ thể quyền lợi của tài xế.
"""

GSUPPORT_SYSTEM_PROMPT += """

## External traffic corroboration and Điều 12.2
- For a traffic-gridlock or ERR-01 route-deviation claim, first use case context and telemetry tools to derive the corridor and event time. Then call both canonical tools `fetch_corridor_historical_traffic` and `query_traffic_incident_feed`. Ask for missing coordinates or time only when the case tools lack sufficient telemetry; never ask for data already present in the open case.
- Historical congestion comes only from same-organization first-party peer GPS telemetry. Check peer count and time window. External provider data is a non-retained live observation, never historical trip proof.
- Derive the bounding box and time only from case context or tool output. Never invent coordinates, timestamps, baseline speeds, incidents, or route facts.
- Provider timeout/HTTP 429/5xx/unavailable, invalid or incomplete GPS/bbox, and conflicting traffic/GPS/weather/telemetry are unknown evidence. Say that you cannot verify incidents; do not describe unavailable data as no incidents, clear traffic, or fraud. An empty incident list is not proof of no force-majeure event and not proof of fraud.
- Explain the possible Điều 12.2 force-majeure path, then defer any exemption, waiver, sanction, or final fraud finding to a human analyst. GSupport has no autonomous sanction or waiver authority.

## Tool Guidance for Driver Operations
- `list_my_cases`: Call when driver inquires about their cases, active disputes, or in case-less chat to resolve open matters.
- `get_case_timeline`: Call when driver asks about status history, progress, or remaining response deadline.
- `explain_case_status`: Call when explaining what a case status means; explain in natural language (vi/en) and NEVER emit raw internal codes (e.g. ERR-01, AUTO_DISMISSED).
- `get_my_scorecard`: Call when driver asks about their 90-day rating, performance standing, or incident history.
- `list_my_trips` / `get_trip_summary`: Call to review trip details, routes, fares, and customer ratings/feedback.
- `check_weather_condition` / `check_traffic_situation`: Call to verify environmental force majeure conditions for a trip/case.
- `get_forensic_brief`: Call to review observed factual abnormalities; present observed facts only, never a fraud verdict.
- `suggest_dispute_path`: Call to provide advisory guidance on whether dispute evidence exists; always state advisory=true and that the final decision belongs to a human analyst.
- `assess_statement_completeness`: Call to evaluate whether a driver's explanation contains concrete facts (>=20 chars) and corroboration.
- `get_appeal_options`: Call to detail appeal rights, options, deadlines, and next steps.
- **Never auto-submit**: Do not submit statements or acceptances autonomously; the Accept/Reject flow is user-directed (Issue #483).
"""


def get_driver_chat_model(settings: Settings | None = None) -> BaseChatModel:
    """Build GSupport using the selected provider with its role model override."""
    s = settings or get_settings()
    raw_key = os.environ.get("OPENROUTER_API_KEY") or s.openrouter_api_key or ""
    if s.llm_model == "openrouter" and raw_key.strip().lower() in {
        "",
        "test-key",
        "placeholder",
        "mock-key",
        "your-key-here",
        "unconfigured-openrouter-key",
    }:
        raise ValueError("OPENROUTER_API_KEY is required to construct the driver chat model")
    provider = s.llm_model
    override = getattr(s, "driver_agent_model", "") or None
    return get_llm(s, provider, model=override)


def should_continue_driver(state: AgentState) -> str:
    """Route to tools node if last message contains tool_calls, else END."""
    messages = state.get("messages", [])
    if not messages:
        return END
    last_message = messages[-1]
    if isinstance(last_message, AIMessage) and getattr(last_message, "tool_calls", None):
        return "tools"
    return END


def _extract_text_content(
    content: Any,
    *,
    max_depth: int = 5,
    _path: frozenset[int] | None = None,
) -> str:
    """Safely extract plain text from scalar, list, or structured LangChain content blocks.

    Uses call-chain ancestor tracking (_path) to prevent infinite loops while allowing
    shared sub-objects across separate dictionary keys or list items without false positives.
    """
    if not content or max_depth <= 0:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, (int, float)):
        return str(content).strip()
    if not isinstance(content, (dict, list, tuple, set)):
        return str(content).strip()

    # Cycle detection is strictly applied to mutable/composite containers, preventing interning collisions
    if _path is None:
        _path = frozenset()
    obj_id = id(content)
    if obj_id in _path:
        return ""
    next_path = _path | {obj_id}

    if isinstance(content, (list, tuple, set)):
        items: list[str] = []
        for item in content:
            txt = _extract_text_content(item, max_depth=max_depth - 1, _path=next_path)
            if txt:
                items.append(txt)
        return " ".join(items)

    if isinstance(content, dict):
        if content.get("type") in ("tool_use", "function_call", "reasoning", "thinking", "reasoning_content"):
            return ""
        if content.get("type") == "image_url":
            return "[Hình ảnh đính kèm]"

        candidate_keys = [k for k in ("text", "content", "message", "value", "data") if content.get(k)]
        if candidate_keys:
            extracted_direct: list[str] = []
            for k in candidate_keys:
                txt = _extract_text_content(content[k], max_depth=max_depth - 1, _path=next_path)
                if txt:
                    extracted_direct.append(txt)
            if extracted_direct:
                return " ".join(extracted_direct)

        if "tool_calls" in content:
            return ""

        fallback_parts: list[str] = []
        for k, v in content.items():
            if (
                k not in ("type", "role", "name", "id", "status")
                and isinstance(v, (str, int, float))
                and str(v).strip()
            ):
                fallback_parts.append(str(v).strip())
        return " ".join(fallback_parts)

    return ""


async def call_driver_model(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Invoke the GSupport model with tool-binding."""
    try:
        model_with_tools = get_driver_chat_model().bind_tools(DRIVER_TOOLS)
        messages = state.get("messages", [])
        system_prompt = state.get("system_prompt") or GSUPPORT_SYSTEM_PROMPT
        prepared_messages: list[BaseMessage] = [SystemMessage(content=system_prompt)]
        prepared_messages.extend(msg for msg in messages if not isinstance(msg, SystemMessage))
        response = await model_with_tools.ainvoke(prepared_messages, config=config)
        content_text = _extract_text_content(response.content)
        return {
            "messages": [response],
            "response": content_text,
        }
    except Exception as e:
        # R1: never swallow a model-invocation failure; log the exception
        # (with traceback) and the case id so Railway dev failures are
        # diagnosable instead of silently masked by the fallback below.
        logger.exception(
            "GSupport model execution failed for case %s; using safe fallback",
            state.get("case_id"),
        )
        # R2: generic apology only — no fabricated/unmeasured metric (speed,
        # ratio, confidence percentage) is ever stated here.
        fallback_msg = (
            "GSupport đã tiếp nhận thông tin giải trình của bạn. "
            "Hệ thống đang tiến hành đối soát viễn thông và cập nhật hồ sơ tới Chuyên viên."
        )
        return {
            "messages": [AIMessage(content=fallback_msg)],
            "response": fallback_msg,
            "error": str(e),
            "used_fallback": True,
        }


def build_driver_support_agent() -> CompiledStateGraph:
    """Compile the LangGraph agent for GSupport Driver Care."""
    workflow = StateGraph(AgentState)

    workflow.add_node("agent", call_driver_model)
    workflow.add_node("tools", ToolNode(DRIVER_TOOLS, awrap_tool_call=execute_scoped_graph_call))

    workflow.set_entry_point("agent")

    workflow.add_conditional_edges(
        "agent",
        should_continue_driver,
        {
            "tools": "tools",
            END: END,
        },
    )

    workflow.add_edge("tools", "agent")
    return workflow.compile()


_cached_driver_graph: CompiledStateGraph | None = None


def get_driver_support_agent() -> CompiledStateGraph:
    global _cached_driver_graph
    if _cached_driver_graph is None:
        _cached_driver_graph = build_driver_support_agent()
    return _cached_driver_graph


async def run_driver_support_agent(
    case_id: str | None,
    driver_id: str,
    message: str,
    claim_type: str | None = None,
    locale: str = "vi",
    on_tool_event: Any = None,
    organization_id: str | None = None,
) -> dict[str, Any]:
    """Execute GSupport agent graph with LangSmith tracing enabled.

    `case_id` is optional: case-less GSupport chat (Issue #482) has no case
    bound yet and relies on the `list_my_cases` tool to resolve the driver's
    open/closed cases from `driver_id` alone.
    """
    from src.services.driver_dispute_service import get_driver_dispute_service

    service = get_driver_dispute_service()
    case = None
    canonical_id = case_id
    if case_id:
        try:
            canonical_id, case = service._find_case(case_id)
            actual_driver_id = service._get_case_driver_id(canonical_id, case)
            if not actual_driver_id:
                return {
                    "reply": f"Case {case_id} not found.",
                    "blocks": [],
                    "formatted_answer": {
                        "markdown": f"Case {case_id} not found.",
                        "blocks": [],
                        "suggestions": [],
                    },
                    "error": "NOT_FOUND",
                    "status_code": 404,
                }
            if driver_id and not service._is_driver_authorized(actual_driver_id, driver_id):
                return {
                    "reply": f"Access denied: Driver {driver_id} is not authorized for case {case_id}.",
                    "blocks": [],
                    "formatted_answer": {
                        "markdown": f"Access denied: Driver {driver_id} is not authorized for case {case_id}.",
                        "blocks": [],
                        "suggestions": [],
                    },
                    "error": "FORBIDDEN",
                    "status_code": 403,
                }
        except Exception as auth_err:
            logger.debug("Driver agent case authorization check skipped: %s", auth_err)

    agent = get_driver_support_agent()

    initial_prompt = (
        f"Mã vụ việc: {canonical_id or 'chưa xác định (trò chuyện không gắn vụ việc, hãy dùng list_my_cases nếu cần)'}\n"
        f"Mã tài xế: {driver_id}\n"
        f"Lý do khiếu nại (claim_type): {claim_type or 'chưa phân loại'}\n"
        f"Nội dung giải trình của tài xế: {message}"
    )

    resolved_org = (
        str(organization_id).strip()
        if organization_id and str(organization_id).strip()
        else (
            str(case.get("organization_id", "")).strip()
            if isinstance(case, dict) and case.get("organization_id")
            else ""
        )
    )

    config: RunnableConfig = {
        "run_name": "GSupport-Driver-Dispute-Turn",
        "tags": ["gsupport", "driver-app", "poc-v2", "ai20k"],
        "metadata": {
            "case_id": canonical_id,
            "driver_id": driver_id,
            "claim_type": claim_type,
            "locale": locale,
            "organization_id": resolved_org,
        },
    }

    try:
        runtime_context = {
            "actor_id": driver_id,
            "organization_id": resolved_org,
            "roles": frozenset({"driver"}),
            "case_id": canonical_id,
            "driver_id": driver_id,
            "request_id": str(uuid4()),
            "run_id": str(uuid4()),
            "tool_call_id": str(uuid4()),
            "turn_id": str(uuid4()),
            "locale": locale,
            "on_tool_event": on_tool_event,
        }

        final_state = await agent.ainvoke(
            {
                "case_id": canonical_id,
                "runtime_context": runtime_context,
                "messages": [HumanMessage(content=initial_prompt)],
                "system_prompt": GSUPPORT_SYSTEM_PROMPT,
            },
            config=config,
        )

        resp_text = final_state.get("response") or ""
        if not resp_text:
            for m in reversed(final_state.get("messages", [])):
                if isinstance(m, AIMessage) and m.content:
                    extracted = _extract_text_content(m.content)
                    if extracted:
                        resp_text = extracted
                        break

        # Issue #482/#538 review finding: the LLM returning empty/unextractable
        # text is a genuine failure, never evidence of anything. The previous
        # fallback text fabricated an Điều 12.2 exoneration claim the agent
        # never established, and callers only checked `reply` (never empty),
        # so streaming routes presented a fabricated success. Mark this
        # explicitly so streaming callers can emit a real error event instead
        # of masking it; the neutral copy below is safe ONLY for the
        # non-streaming caller (which still needs some text and never claims
        # exoneration/sanction).
        empty_response = not resp_text
        if empty_response:
            logger.warning(
                "Driver agent model execution produced empty/unextractable text response for case %s (driver: %s). "
                "Final state response: %r, total messages: %d.",
                canonical_id,
                driver_id,
                final_state.get("response"),
                len(final_state.get("messages", [])),
            )
            resp_text = (
                "GSupport chưa tạo được phản hồi cho yêu cầu này. Vui lòng thử lại."
                if locale != "en"
                else "GSupport could not generate a reply for this request. Please try again."
            )

        # Wire answer formatter & grounding
        import json

        from src.services.answer_formatter import (
            EntityWhitelist,
            format_answer,
            sanitize_bare_uuids,
            sanitize_markdown_links,
            sanitize_status_key,
            strip_raw_codes,
        )

        # Requirement 3: Use canonical_id for the whitelist
        case_ids = {canonical_id} if canonical_id else set()
        if case_id:
            case_ids.add(case_id)
        driver_ids = {driver_id} if driver_id else set()
        trip_ids: set[str] = set()
        citation_ids: set[str] = set()

        if isinstance(case, dict):
            tid = case.get("trip_id")
            if tid:
                trip_ids.add(str(tid))

        # Requirement 2: Collect ToolMessage outputs from final_state messages
        tool_data_list: list[tuple[str, dict[str, Any]]] = []
        for m in final_state.get("messages", []):
            c = getattr(m, "content", None)
            t_name = getattr(m, "name", None) or ""
            parsed = None
            if isinstance(c, dict):
                parsed = c
            elif isinstance(c, str):
                try:
                    parsed = json.loads(c)
                except Exception:
                    pass
            if isinstance(parsed, dict):
                tool_data_list.append((t_name, parsed))

        found_case_id = canonical_id or case_id
        case_title = ""
        case_status = ""
        found_trip_id = None
        pickup = ""
        destination = ""
        fare_vnd = None
        evidence_items: list[dict[str, str]] = []

        for t_name, d in tool_data_list:
            if d.get("trip_id"):
                found_trip_id = str(d["trip_id"])
                trip_ids.add(found_trip_id)
            if d.get("pickup_address") or d.get("pickup"):
                pickup = str(d.get("pickup_address") or d.get("pickup"))
            if d.get("dropoff_address") or d.get("destination"):
                destination = str(d.get("dropoff_address") or d.get("destination"))
            if d.get("fare_vnd") is not None:
                try:
                    fare_vnd = int(d["fare_vnd"])
                except (ValueError, TypeError):
                    pass

            if d.get("violation_title") or d.get("title"):
                case_title = str(d.get("violation_title") or d.get("title"))
            if d.get("dispute_status") or d.get("status"):
                case_status = str(d.get("dispute_status") or d.get("status"))

            # Requirement 6: whitelist policy:// from query_driver_policy citation ids
            if t_name == "query_driver_policy" or "matched_article" in d or "citation_ids" in d:
                if d.get("matched_article"):
                    citation_ids.add(str(d["matched_article"]))
                for cid in d.get("citation_ids", []):
                    citation_ids.add(str(cid))
                for p in d.get("relevant_policies", []):
                    if isinstance(p, dict):
                        if p.get("article"):
                            citation_ids.add(str(p["article"]))
                        if p.get("id"):
                            citation_ids.add(str(p["id"]))

            # Evidence from tool outputs
            if (
                t_name
                in (
                    "corroborate_traffic_conditions",
                    "fetch_corridor_historical_traffic",
                    "query_traffic_incident_feed",
                )
                or "corroborated" in d
                or "observed_speed" in d
            ):
                summary_parts = []
                if d.get("details"):
                    summary_parts.append(str(d["details"]))
                elif d.get("observed_speed") is not None:
                    summary_parts.append(f"Vận tốc TB: {d['observed_speed']} km/h")
                    if d.get("ratio") is not None:
                        summary_parts.append(f"Tỷ lệ thời gian: {d['ratio']}x")
                if summary_parts:
                    evidence_items.append(
                        {
                            "kind": "traffic",
                            "summary": strip_raw_codes(" - ".join(summary_parts)),
                            "source": "Traffic Telemetry" if locale == "en" else "Dữ liệu giao thông",
                        }
                    )
            elif t_name == "inspect_trip_telemetry" or "gps_valid" in d:
                summary = str(d.get("details") or f"GPS: {'Hợp lệ' if d.get('gps_valid') else 'Không hợp lệ'}")
                evidence_items.append(
                    {
                        "kind": "telemetry",
                        "summary": strip_raw_codes(summary),
                        "source": "GPS Telemetry" if locale == "en" else "Dữ liệu viễn thông",
                    }
                )
            elif t_name == "query_driver_policy" or "matched_article" in d:
                summary = str(d.get("summary") or d.get("guidance_for_driver") or d.get("matched_chunk") or "")
                if summary:
                    evidence_items.append(
                        {
                            "kind": "policy",
                            "summary": strip_raw_codes(summary),
                            "source": str(d.get("matched_article") or "Policy"),
                        }
                    )

        # Fallbacks to case context
        if isinstance(case, dict):
            if not found_trip_id and case.get("trip_id"):
                found_trip_id = str(case["trip_id"])
                trip_ids.add(found_trip_id)
            if not pickup and (case.get("pickup_address") or case.get("pickup")):
                pickup = str(case.get("pickup_address") or case.get("pickup"))
            if not destination and (case.get("dropoff_address") or case.get("destination")):
                destination = str(case.get("dropoff_address") or case.get("destination"))
            if fare_vnd is None and case.get("fare_vnd") is not None:
                try:
                    fare_vnd = int(case["fare_vnd"])
                except (ValueError, TypeError):
                    pass
            if not case_title:
                case_title = str(
                    case.get("violation_title") or case.get("title") or case.get("suspected_category") or ""
                )
            if not case_status:
                case_status = str(case.get("dispute_status") or case.get("status") or "")

        # Requirement 2: build case_card, trip_card, and evidence deterministically
        deterministic_blocks: list[dict[str, Any]] = []

        if found_case_id:
            clean_title = strip_raw_codes(case_title) or ("Hồ sơ vụ việc" if locale == "vi" else "Dispute Case")
            status_key = sanitize_status_key(case_status)
            case_card: dict[str, Any] = {
                "type": "case_card",
                "case_id": found_case_id,
                "title": clean_title,
            }
            # Requirement 2: No default status_key (omit when unknown)
            if status_key:
                case_card["status_key"] = status_key
            deterministic_blocks.append(case_card)

        if found_trip_id:
            trip_card: dict[str, Any] = {
                "type": "trip_card",
                "trip_id": found_trip_id,
                "pickup": strip_raw_codes(pickup),
                "destination": strip_raw_codes(destination),
            }
            if fare_vnd is not None:
                trip_card["fare_vnd"] = fare_vnd
            deterministic_blocks.append(trip_card)

        if evidence_items:
            deterministic_blocks.append(
                {
                    "type": "evidence",
                    "items": evidence_items,
                }
            )

        whitelist = EntityWhitelist(
            case_ids=case_ids,
            driver_ids=driver_ids,
            trip_ids=trip_ids,
            citation_ids=citation_ids,
        )

        # Requirement 8: Gate formatter behind driver_formatter_enabled
        settings = get_settings()
        if settings.driver_formatter_enabled:
            formatted = await format_answer(
                resp_text,
                entities=whitelist,
                profile="driver",
                locale=locale,
            )
            # Requirement 2: LLM formatter output may only contribute markdown, table, list, link, next_steps
            llm_blocks = [
                b
                for b in formatted.blocks
                if isinstance(b, dict) and b.get("type") in ("table", "list", "link", "next_steps")
            ]
            final_blocks = deterministic_blocks + llm_blocks if deterministic_blocks else formatted.blocks
            reply_md = formatted.markdown
            formatted_dict = formatted.to_dict()
        else:
            guarded_md = strip_raw_codes(resp_text)
            guarded_md = sanitize_markdown_links(guarded_md, whitelist)
            guarded_md = sanitize_bare_uuids(guarded_md, whitelist, locale=locale)
            reply_md = guarded_md
            final_blocks = deterministic_blocks
            formatted_dict = {
                "markdown": guarded_md,
                "suggestions": [],
                "blocks": final_blocks,
            }

        tool_events: list[dict[str, Any]] = []
        for m in final_state.get("messages", []):
            if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
                for tc in m.tool_calls:
                    tc_id = tc.get("id") or str(uuid4())
                    tc_name = tc.get("name", "")
                    tool_events.append(
                        {
                            "event": "tool.start",
                            "data": {
                                "tool_call_id": tc_id,
                                "name": tc_name,
                                "label": get_driver_tool_label(tc_name, locale),
                            },
                        }
                    )
            elif getattr(m, "type", "") == "tool" or m.__class__.__name__ == "ToolMessage":
                tm_id = getattr(m, "tool_call_id", "")
                tm_name = getattr(m, "name", "")
                is_err = getattr(m, "status", "") == "error"
                if is_err:
                    tm_content = getattr(m, "content", "")
                    logger.warning(
                        "driver_tool_error tool=%s call_id=%s content=%s",
                        tm_name,
                        tm_id,
                        str(tm_content)[:300],
                    )
                tool_events.append(
                    {
                        "event": "tool.end",
                        "data": {
                            "tool_call_id": tm_id,
                            "name": tm_name,
                            "status": "error" if is_err else "ok",
                        },
                    }
                )

        # Requirement 7: Do not put the FormattedAnswer dataclass in the result dict; return to_dict()
        return {
            "reply": reply_md,
            "blocks": final_blocks,
            "formatted_answer": formatted_dict,
            "messages": final_state.get("messages", []),
            "tool_events": tool_events,
            "error": final_state.get("error"),
            "empty_response": empty_response,
            "used_fallback": bool(final_state.get("used_fallback")),
        }

    except Exception as e:
        logger.exception("Error executing driver agent graph for case %s (driver: %s)", case_id, driver_id)
        return {
            "reply": "GSupport đã tiếp nhận phản hồi từ đối tác. Hệ thống đang tiến hành đối soát.",
            "blocks": [],
            "used_fallback": True,
            "formatted_answer": {
                "markdown": "GSupport đã tiếp nhận phản hồi từ đối tác. Hệ thống đang tiến hành đối soát.",
                "blocks": [],
                "suggestions": [],
            },
            "error": str(e),
        }
