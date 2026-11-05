"""LLM Answer Formatter for GreenSM Fraud Analyst Copilot.

Produces structured Vietnamese markdown with valid entity links and next-step
suggestions, guarded by strict entity whitelisting, timeout fallback, and
the forensic brief zero-hallucination invariant.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from google.genai import types

logger = logging.getLogger(__name__)

PROMPT_FILE = Path(__file__).resolve().parent.parent / "agents" / "prompts" / "answer_formatter_vi.md"
DRIVER_PROMPT_FILE = Path(__file__).resolve().parent.parent / "agents" / "prompts" / "answer_formatter_driver.md"
UUID_PATTERN = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((case|driver|trip|policy)://([^)]+)\)")
ERR_CODE_PATTERN = re.compile(r"\bERR[-_]0\d+\b", re.IGNORECASE)
UPPER_SNAKE_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b")
STATUS_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
ALLOWED_EVIDENCE_KINDS = frozenset({"weather", "traffic", "telemetry", "policy"})


@dataclass
class FormattedAnswer:
    markdown: str
    suggestions: list[dict[str, str]] = field(default_factory=list)
    blocks: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "markdown": self.markdown,
            "suggestions": self.suggestions,
            "blocks": self.blocks,
        }

    def __getitem__(self, item: str) -> Any:
        if item == "markdown":
            return self.markdown
        if item == "suggestions":
            return self.suggestions
        if item == "blocks":
            return self.blocks
        raise KeyError(item)

    def get(self, item: str, default: Any = None) -> Any:
        try:
            return self[item]
        except KeyError:
            return default


@dataclass
class EntityWhitelist:
    case_ids: set[str] = field(default_factory=set)
    driver_ids: set[str] = field(default_factory=set)
    trip_ids: set[str] = field(default_factory=set)
    citation_ids: set[str] = field(default_factory=set)

    def is_whitelisted(self, scheme: str, target: str) -> bool:
        # Strip query string from trip or other URIs
        raw_id = target.split("?")[0].strip()
        if scheme == "case":
            return raw_id in self.case_ids or target in self.case_ids
        if scheme == "driver":
            return raw_id in self.driver_ids or target in self.driver_ids
        if scheme == "trip":
            return raw_id in self.trip_ids or target in self.trip_ids
        if scheme == "policy":
            return raw_id in self.citation_ids or target in self.citation_ids
        return False


def normalize_whitelist(entities: Any) -> EntityWhitelist:
    if isinstance(entities, EntityWhitelist):
        return entities
    if isinstance(entities, set):
        return EntityWhitelist(
            case_ids=set(entities),
            driver_ids=set(entities),
            trip_ids=set(entities),
            citation_ids=set(entities),
        )
    if isinstance(entities, dict):
        return EntityWhitelist(
            case_ids=set(entities.get("case_ids", [])),
            driver_ids=set(entities.get("driver_ids", [])),
            trip_ids=set(entities.get("trip_ids", [])),
            citation_ids=set(entities.get("citation_ids", [])),
        )
    return EntityWhitelist()


def sanitize_markdown_links(markdown: str, entities: EntityWhitelist) -> str:
    """Replace links whose target id is not whitelisted with their plain title."""

    def replacer(match: re.Match[str]) -> str:
        title = match.group(1)
        scheme = match.group(2)
        uri = match.group(3)
        if entities.is_whitelisted(scheme, uri):
            return match.group(0)
        return title

    return LINK_PATTERN.sub(replacer, markdown)


def sanitize_bare_uuids(markdown: str, entities: EntityWhitelist, locale: str = "vi") -> str:
    """Convert bare UUIDs outside markdown links to entity links if whitelisted, else drop entirely."""
    parts = re.split(r"(\[[^\]]+\]\([^)]+\))", markdown)
    is_en = locale == "en"
    driver_label = "Driver" if is_en else "Tài xế"
    trip_label = "Trip" if is_en else "Chuyến đi"
    case_label = "Case" if is_en else "Vụ việc"

    for i in range(0, len(parts), 2):

        def repl(m: re.Match[str]) -> str:
            uid = m.group(0)
            if uid in entities.driver_ids:
                return f"[{driver_label}](driver://{uid})"
            if uid in entities.trip_ids:
                return f"[{trip_label}](trip://{uid})"
            if uid in entities.case_ids:
                return f"[{case_label}](case://{uid})"
            return ""

        parts[i] = UUID_PATTERN.sub(repl, parts[i])
    return "".join(parts)


def clean_suggestions(raw_suggestions: list[Any]) -> list[dict[str, str]]:
    cleaned = []
    for item in raw_suggestions:
        if isinstance(item, dict):
            label = str(item.get("label", "")).strip()[:40]
            prompt = str(item.get("prompt", "")).strip()
            if label and prompt:
                cleaned.append({"label": label, "prompt": prompt})
    return cleaned[:3]


@lru_cache(maxsize=1)
def load_formatter_system_prompt() -> str:
    if PROMPT_FILE.exists():
        return PROMPT_FILE.read_text(encoding="utf-8")
    return "Bạn là trợ lý định dạng câu trả lời tiếng Việt cho GreenSM Fraud Copilot."


@lru_cache(maxsize=4)
def load_driver_formatter_system_prompt(locale: str = "vi") -> str:
    base = ""
    if DRIVER_PROMPT_FILE.exists():
        base = DRIVER_PROMPT_FILE.read_text(encoding="utf-8")
    else:
        base = "GSupport Driver Answer Formatter."

    if locale == "en":
        return (
            f"{base}\n\n"
            "CURRENT REQUEST DIRECTIVE: Active locale is English ('en'). "
            "Output all markdown text and block labels in English."
        )
    return (
        f"{base}\n\n"
        "CURRENT REQUEST DIRECTIVE: Ngôn ngữ hiển thị hiện tại là tiếng Việt ('vi'). "
        "Xuất toàn bộ văn bản markdown và nhãn khối bằng tiếng Việt."
    )


def strip_raw_codes(text: str) -> str:
    """Strip internal error codes (ERR-0x) and raw UPPER_SNAKE status codes."""
    if not text:
        return ""
    cleaned = ERR_CODE_PATTERN.sub("", text)
    cleaned = UPPER_SNAKE_PATTERN.sub("", cleaned)
    # Clean up empty parenthetical / bracket remnants and duplicate spaces
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    cleaned = re.sub(r"\[\s*\]", "", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r" \.", ".", cleaned)
    cleaned = re.sub(r" ,", ",", cleaned)
    return cleaned.strip()


def sanitize_status_key(key: Any) -> str:
    """Normalize status key to lowercase snake_case; strip ERR_0\\d variants, require ^[a-z][a-z0-9_]*$ else drop."""
    if not key:
        return ""
    s = str(key).strip().lower()
    if s.startswith("_"):
        return ""
    s = re.sub(r"err[-_]0\d+", "", s, flags=re.IGNORECASE).strip(" _-")
    if STATUS_KEY_PATTERN.match(s):
        return s
    return ""


def sanitize_driver_blocks(raw_blocks: list[Any], whitelist: EntityWhitelist) -> list[dict[str, Any]]:
    """Validate, filter and sanitize typed blocks for driver profile."""
    sanitized: list[dict[str, Any]] = []

    for block in raw_blocks:
        if not isinstance(block, dict):
            continue
        b_type = block.get("type")
        if b_type == "case_card":
            case_id = str(block.get("case_id", "")).strip()
            if not whitelist.is_whitelisted("case", case_id):
                continue
            title = strip_raw_codes(str(block.get("title", "")))
            status_key = sanitize_status_key(block.get("status_key"))
            card: dict[str, Any] = {
                "type": "case_card",
                "case_id": case_id,
                "title": title,
            }
            if status_key:
                card["status_key"] = status_key
            sanitized.append(card)
        elif b_type == "trip_card":
            trip_id = str(block.get("trip_id", "")).strip()
            if not whitelist.is_whitelisted("trip", trip_id):
                continue
            pickup = strip_raw_codes(str(block.get("pickup", "")))
            destination = strip_raw_codes(str(block.get("destination", "")))
            card: dict[str, Any] = {
                "type": "trip_card",
                "trip_id": trip_id,
                "pickup": pickup,
                "destination": destination,
            }
            if "fare_vnd" in block and block["fare_vnd"] is not None:
                try:
                    card["fare_vnd"] = int(block["fare_vnd"])
                except (ValueError, TypeError):
                    pass
            sanitized.append(card)
        elif b_type == "table":
            columns = [strip_raw_codes(str(c)) for c in block.get("columns", []) if str(c).strip()]
            raw_rows = block.get("rows", [])
            rows: list[list[str]] = []
            if columns and isinstance(raw_rows, list):
                num_cols = len(columns)
                for r in raw_rows:
                    if isinstance(r, (list, tuple)) and len(r) == num_cols:
                        rows.append([strip_raw_codes(str(cell)) for cell in r])
            if columns:
                sanitized.append(
                    {
                        "type": "table",
                        "columns": columns,
                        "rows": rows,
                    }
                )
        elif b_type == "list":
            items = []
            for it in block.get("items", []):
                if not isinstance(it, dict):
                    continue
                label = strip_raw_codes(str(it.get("label", "")))
                href = str(it.get("href", "")).strip()
                valid_href = False
                if href.startswith("case://"):
                    cid = href[7:].split("?")[0].strip()
                    valid_href = whitelist.is_whitelisted("case", cid)
                elif href.startswith("trip://"):
                    tid = href[7:].split("?")[0].strip()
                    valid_href = whitelist.is_whitelisted("trip", tid)
                elif href.startswith("policy://"):
                    pid = href[9:].split("?")[0].strip()
                    valid_href = whitelist.is_whitelisted("policy", pid)
                elif href.startswith("https://"):
                    valid_href = True

                if valid_href and label:
                    items.append({"label": label, "href": href})
            if items:
                sanitized.append(
                    {
                        "type": "list",
                        "items": items,
                    }
                )
        elif b_type == "link":
            label = strip_raw_codes(str(block.get("label", "")))
            url = str(block.get("url", "")).strip()
            valid_url = False
            if url.startswith("case://"):
                cid = url[7:].split("?")[0].strip()
                valid_url = whitelist.is_whitelisted("case", cid)
            elif url.startswith("trip://"):
                tid = url[7:].split("?")[0].strip()
                valid_url = whitelist.is_whitelisted("trip", tid)
            elif url.startswith("policy://"):
                pid = url[9:].split("?")[0].strip()
                valid_url = whitelist.is_whitelisted("policy", pid)
            elif url.startswith("https://"):
                valid_url = True
            if valid_url and label:
                sanitized.append(
                    {
                        "type": "link",
                        "label": label,
                        "url": url,
                    }
                )
        elif b_type == "status_pill":
            status_key = sanitize_status_key(block.get("status_key"))
            if status_key:
                sanitized.append(
                    {
                        "type": "status_pill",
                        "status_key": status_key,
                    }
                )
        elif b_type == "evidence":
            items = []
            for it in block.get("items", []):
                if not isinstance(it, dict):
                    continue
                kind = strip_raw_codes(str(it.get("kind", ""))).lower()
                summary = strip_raw_codes(str(it.get("summary", "")))
                source = strip_raw_codes(str(it.get("source", "")))
                if kind in ALLOWED_EVIDENCE_KINDS and summary:
                    items.append({"kind": kind, "summary": summary, "source": source})
            if items:
                sanitized.append(
                    {
                        "type": "evidence",
                        "items": items,
                    }
                )
        elif b_type == "next_steps":
            items = []
            for it in block.get("items", []):
                if not isinstance(it, dict):
                    continue
                label = strip_raw_codes(str(it.get("label", "")))[:40]
                prompt = strip_raw_codes(str(it.get("prompt", "")))
                if label and prompt:
                    items.append({"label": label, "prompt": prompt})
            if items:
                sanitized.append(
                    {
                        "type": "next_steps",
                        "items": items,
                    }
                )
        elif b_type == "confirmation":
            action = str(block.get("action", "")).strip()
            if action not in ("acknowledge", "submit_statement"):
                continue
            allowed_keys = {"incident_type", "description", "evidence"}
            checklist: list[dict[str, Any]] = []
            raw_checklist = block.get("checklist", [])
            if isinstance(raw_checklist, list):
                for it in raw_checklist:
                    if not isinstance(it, dict):
                        continue
                    k = str(it.get("key", "")).strip()
                    if k not in allowed_keys:
                        continue
                    entry: dict[str, Any] = {"key": k, "ok": bool(it.get("ok"))}
                    if "label" in it and it["label"] is not None:
                        lbl = strip_raw_codes(str(it["label"]))
                        if lbl:
                            entry["label"] = lbl
                    checklist.append(entry)
            summary = strip_raw_codes(str(block.get("summary", "")))
            sanitized.append(
                {
                    "type": "confirmation",
                    "action": action,
                    "checklist": checklist,
                    "summary": summary,
                }
            )

    return sanitized


async def _invoke_provider(provider: Any, contents: list[Any], declarations: list[dict[str, Any]], system: str) -> str:
    # Handle different provider signatures
    if callable(provider):
        sig = inspect.signature(provider)
        param_count = len(sig.parameters)
        if param_count == 2:
            resp = await provider(contents, system)
        elif param_count == 3:
            resp = await provider(contents, declarations, system)
        else:
            resp = await provider(contents=contents, declarations=declarations, system=system)
    else:
        raise TypeError(f"Provider {provider} is not callable")

    # Extract text from response
    if hasattr(resp, "text") and resp.text:
        return resp.text
    if hasattr(resp, "candidates") and resp.candidates:
        content = resp.candidates[0].content
        return "".join(
            p.text
            for p in getattr(content, "parts", []) or []
            if getattr(p, "text", None) and not getattr(p, "thought", False)
        ).strip()
    if isinstance(resp, str):
        return resp
    raise ValueError(f"Could not extract text from provider response: {resp}")


async def format_answer(
    raw_answer: str,
    *,
    citations: list[dict[str, Any]] | None = None,
    entities: EntityWhitelist | set[str] | dict[str, Any] | None = None,
    provider: Any = None,
    timeout_seconds: float = 15.0,
    profile: str = "analyst",
    locale: str = "vi",
) -> FormattedAnswer:
    """Format a raw answer into structured Vietnamese markdown or typed blocks.

    Supported profiles:
    - "analyst": Vietnamese markdown with 1-line bold headline and next-step suggestions.
    - "driver": Short empathetic markdown with typed blocks (case_card, trip_card, etc.) in locale.

    On any timeout (>15s), provider failure, or invalid JSON, safely falls back
    to FormattedAnswer with sanitized markdown.
    """
    if not raw_answer or not raw_answer.strip():
        return FormattedAnswer(markdown=raw_answer or "", suggestions=[], blocks=[])

    whitelist = normalize_whitelist(entities)
    citations_list = citations or []

    if provider is None:
        from src.services.agent_runtime import _provider

        provider = _provider

    if profile == "driver":
        system_prompt = load_driver_formatter_system_prompt(locale=locale)
        user_payload = {
            "raw_answer": raw_answer,
            "locale": locale,
            "citations": citations_list,
            "entities": {
                "case_ids": list(whitelist.case_ids),
                "driver_ids": list(whitelist.driver_ids),
                "trip_ids": list(whitelist.trip_ids),
                "citation_ids": list(whitelist.citation_ids),
            },
        }
    else:
        system_prompt = load_formatter_system_prompt()
        user_payload = {
            "raw_answer": raw_answer,
            "citations": citations_list,
            "entities": {
                "case_ids": list(whitelist.case_ids),
                "driver_ids": list(whitelist.driver_ids),
                "trip_ids": list(whitelist.trip_ids),
                "citation_ids": list(whitelist.citation_ids),
            },
        }

    user_text = (
        "Vui lòng định dạng câu trả lời sau đây theo đúng nguyên tắc và trả về định dạng JSON duy nhất:\n"
        + json.dumps(user_payload, ensure_ascii=False, indent=2)
    )
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=user_text)])]

    try:
        async with asyncio.timeout(timeout_seconds):
            raw_response = await _invoke_provider(provider, contents, [], system_prompt)

            # Strip markdown code blocks if wrapped
            cleaned_text = raw_response.strip()
            if cleaned_text.startswith("```json"):
                cleaned_text = cleaned_text[7:]
            elif cleaned_text.startswith("```"):
                cleaned_text = cleaned_text[3:]
            if cleaned_text.endswith("```"):
                cleaned_text = cleaned_text[:-3]
            cleaned_text = cleaned_text.strip()

            parsed = json.loads(cleaned_text)
            if not isinstance(parsed, dict) or "markdown" not in parsed:
                raise ValueError("Parsed JSON missing 'markdown' key")

            formatted_md = str(parsed["markdown"])

            if profile == "driver":
                guarded_md = strip_raw_codes(formatted_md)
                guarded_md = sanitize_markdown_links(guarded_md, whitelist)
                guarded_md = sanitize_bare_uuids(guarded_md, whitelist, locale=locale)

                raw_blocks = parsed.get("blocks", [])
                if not isinstance(raw_blocks, list):
                    raw_blocks = []
                blocks = sanitize_driver_blocks(raw_blocks, whitelist)

                # Extract suggestions from next_steps block if present
                suggestions: list[dict[str, str]] = []
                for b in blocks:
                    if b.get("type") == "next_steps":
                        for it in b.get("items", []):
                            suggestions.append({"label": it["label"], "prompt": it["prompt"]})
                        break
                if not suggestions:
                    suggestions = clean_suggestions(parsed.get("suggestions", []))

                return FormattedAnswer(markdown=guarded_md, suggestions=suggestions, blocks=blocks)

            # Analyst profile
            raw_suggestions = parsed.get("suggestions", [])
            if not isinstance(raw_suggestions, list):
                raw_suggestions = []

            guarded_md = sanitize_markdown_links(formatted_md, whitelist)
            guarded_md = sanitize_bare_uuids(guarded_md, whitelist)
            suggestions = clean_suggestions(raw_suggestions)

            return FormattedAnswer(markdown=guarded_md, suggestions=suggestions, blocks=[])
    except Exception as exc:
        logger.warning("Answer formatting failed or timed out: %s; falling back to raw answer", exc)
        if profile == "driver":
            guarded_md = strip_raw_codes(raw_answer)
            guarded_md = sanitize_markdown_links(guarded_md, whitelist)
            guarded_md = sanitize_bare_uuids(guarded_md, whitelist, locale=locale)
            return FormattedAnswer(markdown=guarded_md, suggestions=[], blocks=[])
        return FormattedAnswer(markdown=raw_answer, suggestions=[], blocks=[])
