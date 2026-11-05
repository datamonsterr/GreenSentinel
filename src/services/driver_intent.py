"""Driver intent detection for escalation and closure (Issue #573 item 4).

Detects explicit driver intent to:
1. Escalate dispute to an analyst (Vietnamese with/without diacritics and English).
2. Accept closure / confirm resolution without further appeal (Vietnamese with/without diacritics and English).
"""

from __future__ import annotations

import re
import unicodedata

_ESCALATION_EXACT_PHRASES: tuple[str, ...] = (
    "continue_appeal",
    "continue appeal",
    "tiep tuc khieu nai",
    "khieu nai tiep",
    "khong dong y",
    "khong phuc",
    "yeu cau xem xet",
    "toi muon khieu nai",
    "khieu nai len",
    "chuyen len chuyen vien",
    "chuyen cho chuyen vien",
    "chuyen chuyen vien",
    "gap chuyen vien",
    "chuyen vien giam sat",
    "chuyen vien phan tich",
    "chuyen vien tham dinh",
    "chuyen vien doc lap",
    "giam sat vien",
    "nguoi that",
    "con nguoi",
    "escalat",
    "human review",
    "talk to human",
    "speak to human",
    "speak to analyst",
    "transfer to analyst",
    "transfer to supervisor",
    "appeal to analyst",
    "dispute this",
    "talk to an analyst",
    "talk to analyst",
)

_CLOSURE_EXACT_PHRASES: tuple[str, ...] = (
    "confirm_resolution",
    "no_further_appeal",
    "khong khieu nai them",
    "dong y ket thuc",
    "chap nhan ket qua",
    "dong y dong",
    "khong khieu nai",
    "ket thuc khieu nai",
    "hai long",
    "xac nhan ket thuc",
    "dong ho so",
    "dong vu viec",
    "agree to close",
    "accept resolution",
    "close case",
    "end dispute",
    "satisfied",
)

_TARGET_PATTERN = re.compile(r"\b(chuyen vien|giam sat|analyst|supervisor|human|nguoi that|con nguoi)\b")
_ACTION_PATTERN = re.compile(
    r"\b(khieu nai|chuyen|gap|yeu cau|gui|len|cho|talk|speak|transfer|appeal|dispute|review|escalat|khiem nha)\b"
)


def strip_vietnamese_diacritics(text: str) -> str:
    """Normalize text and strip Vietnamese combining diacritics to plain ASCII."""
    if not text:
        return ""
    text = text.replace("đ", "d").replace("Đ", "D")
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c)).lower().strip()


def is_driver_escalation(text: str) -> bool:
    """Check if the driver explicitly asks to escalate to an analyst (Vietnamese or English)."""
    if not text or not text.strip():
        return False
    norm = strip_vietnamese_diacritics(text)

    # 1. Exact phrase match
    if any(phrase in norm for phrase in _ESCALATION_EXACT_PHRASES):
        return True

    # 2. Structural match: target entity (analyst/supervisor/human) + action (escalate/appeal/transfer)
    has_target = bool(_TARGET_PATTERN.search(norm))
    has_action = bool(_ACTION_PATTERN.search(norm))
    return has_target and has_action


def is_driver_closure(text: str) -> bool:
    """Check if the driver accepts closure or confirms resolution without further appeal."""
    if not text or not text.strip():
        return False

    # Escalation takes precedence over closure keywords
    if is_driver_escalation(text):
        return False

    norm = strip_vietnamese_diacritics(text)
    return any(phrase in norm for phrase in _CLOSURE_EXACT_PHRASES)
