"""Output guard and input signal detection for the driver explanation agent (PRD-A 8.6, ADR-034).

Pure functions. The guard is a hard validator: every agent message shown to the driver passes
`check_agent_text`; a failure means rewrite or fall back to a template question. Driver text is
data, never instructions: `detect_injection` only raises a flag for VH, it never changes behaviour.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_AGENT_CHARS = 600
MAX_DRIVER_CHARS = 2000
SAFE_QUESTION = "Bạn có thể kể rõ hơn về diễn biến của cuốc này không?"

_FORBIDDEN: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "fine",
        re.compile(
            r"mức phạt|\bphạt\b|truy thu|hướng xử lý|\bfines?\b|\bpenalt(?:y|ies)\b|\bclawback\b|\bsuspen(?:d|sion)\b|đình chỉ",
            re.I,
        ),
    ),
    (
        "conclusion",
        re.compile(
            r"(?:bạn|anh|chị)\s+(?:đã|đang|có)?\s*(?:vi phạm|gian lận|lừa đảo|làm giả)|vi phạm quy định|"
            r"\byou(?:'ve| have)?\s+(?:violated|cheated|committed fraud)|kết luận (?:là|rằng)|\bfraudulent\b",
            re.I,
        ),
    ),
    ("accusation", re.compile(r"nói dối|dối trá|bịa|\bliar\b|\blying\b|\blied\b", re.I)),
    ("threshold", re.compile(r"ngưỡng|\bthreshold\b|\bstationary_duration_s\b|\bdavi\b", re.I)),
    ("motive", re.compile(r"động cơ|\bmotive\b|công thức|\bformula\b|lợi ích kinh tế|thưởng mốc", re.I)),
    ("other_driver", re.compile(r"tài xế khác|\bother drivers?\b|\banother driver\b|\bTX\s*khác\b", re.I)),
    ("uuid", re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)),
)

_INJECTION = re.compile(
    r"ignore (?:all |the )?(?:previous|prior|above) (?:instructions|rules)|disregard (?:your|the) (?:rules|instructions)|"
    r"(?:reveal|show|print|repeat)\s+(?:your\s+)?(?:system|hidden)\s+prompt|system prompt|you are now|act as|jailbreak|"
    r"bỏ qua (?:mọi |tất cả )?(?:quy tắc|chỉ dẫn|hướng dẫn|luật)|quên (?:mọi|hết) (?:quy tắc|chỉ dẫn)|"
    r"(?:in|hiển thị|tiết lộ)\s+(?:ra\s+)?(?:system prompt|chỉ dẫn hệ thống)|từ giờ bạn là",
    re.I,
)
_SAFETY = re.compile(
    r"tai nạn|\baccident\b|\bcrash\b|cấp cứu|chấn thương|bị thương|suýt đâm|bị cướp|\brobbed\b|đe dọa|\bthreat(?:en|ened)\b|"
    r"quấy rối|\bharass|an toàn của tôi|\binjur",
    re.I,
)
_REASON_KEYWORDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "Tech",
        re.compile(
            r"\bgps\b|định vị|điện thoại (?:bị )?(?:lag|lỗi|treo)|app (?:bị )?lỗi|ứng dụng (?:bị )?lỗi|mất sóng|mất mạng",
            re.I,
        ),
    ),
    (
        "Customer",
        re.compile(r"khách (?:hủy|huỷ|không (?:đến|ra|có mặt)|bắt tôi|yêu cầu)|passenger (?:cancel|no[- ]show)", re.I),
    ),
)


@dataclass
class GuardResult:
    ok: bool
    violations: list[str] = field(default_factory=list)


def check_agent_text(text: str, other_markers: list[str] | None = None) -> GuardResult:
    """Validate one agent message before it is shown to the driver."""
    t = (text or "").strip()
    if not t:
        return GuardResult(False, ["empty"])
    violations: list[str] = []
    if len(t) > MAX_AGENT_CHARS:
        violations.append("too_long")
    for name, pat in _FORBIDDEN:
        if pat.search(t):
            violations.append(name)
    for m in other_markers or []:
        if m and m.lower() in t.lower():
            violations.append("other_driver")
            break
    return GuardResult(not violations, violations)


def detect_injection(text: str) -> bool:
    return bool(_INJECTION.search(text or ""))


def detect_safety(text: str) -> bool:
    return bool(_SAFETY.search(text or ""))


def detect_reason_change(text: str, current_reason: str) -> str | None:
    """Return the new reason code when the driver's text introduces a different reason, else None."""
    for code, pat in _REASON_KEYWORDS:
        if code != current_reason and pat.search(text or ""):
            return code
    return None


def scrub_driver_text(text: str) -> str:
    """Normalise driver input: strip control characters, collapse whitespace, cap length."""
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text or "")
    cleaned = re.sub(r"[ \t]+", " ", cleaned).strip()
    return cleaned[:MAX_DRIVER_CHARS]
