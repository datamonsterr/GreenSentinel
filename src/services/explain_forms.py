"""Explanation form: fixed question set per reason + <= K dynamic questions from a published workflow
(PRD-A US1, ADR-034). Pure functions; the form snapshot is stored on the session with `form_version`.
"""

from __future__ import annotations

import re
from typing import Any

FIELD_TYPES = ("text", "time", "location", "choice", "amount", "photo", "ticket")
REASONS = ("NotDone", "RealTrip", "Tech", "Customer", "Other")
REASON_LABELS: dict[str, dict[str, str]] = {
    "NotDone": {"vi": "Tôi không thực hiện cuốc này", "en": "I did not make this trip"},
    "RealTrip": {"vi": "Có khách thật", "en": "There was a real passenger"},
    "Tech": {"vi": "Sự cố kỹ thuật", "en": "Technical issue"},
    "Customer": {"vi": "Lý do từ khách hàng", "en": "Customer-related reason"},
    "Other": {"vi": "Lý do khác", "en": "Other reason"},
}
FORM_REVISION = "1"
_TICKET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{2,31}$")


def _f(
    id_: str, vi: str, en: str, type_: str, required: bool, options: list[tuple[str, str, str]] | None = None
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": id_,
        "label": {"vi": vi, "en": en},
        "type": type_,
        "required": required,
        "origin": "fixed",
    }
    if options:
        out["options"] = [{"value": v, "label": {"vi": a, "en": b}} for v, a, b in options]
    return out


_PAY = [
    ("cash", "Tiền mặt", "Cash"),
    ("transfer", "Chuyển khoản", "Bank transfer"),
    ("wallet", "Ví điện tử", "E-wallet"),
]

_FIXED: dict[str, list[dict[str, Any]]] = {
    "RealTrip": [
        _f("pickup_place", "Bạn đón khách ở đâu?", "Where did you pick up the passenger?", "location", True),
        _f("pickup_time", "Đón lúc mấy giờ?", "What time was the pickup?", "time", True),
        _f(
            "passenger_desc",
            "Mô tả khách (giới tính, độ tuổi, mang theo gì)",
            "Describe the passenger (gender, age, belongings)",
            "text",
            True,
        ),
        _f("dropoff_place", "Khách xuống ở đâu?", "Where did the passenger get off?", "location", True),
        _f("route", "Đi đường nào, có dừng giữa chừng không?", "Which route, any stops on the way?", "text", True),
        _f(
            "payment_amount", "Khách trả tiền bao nhiêu (VND)?", "How much did the passenger pay (VND)?", "amount", True
        ),
        _f("payment_method", "Khách trả tiền bằng cách nào?", "How did the passenger pay?", "choice", True, _PAY),
        _f("evidence_photo", "Ảnh / bằng chứng (nếu có)", "Photo / evidence (if any)", "photo", False),
    ],
    "NotDone": [
        _f("what_happened", "Điều gì đã xảy ra với cuốc này?", "What happened with this trip?", "text", True),
        _f(
            "trip_status",
            "Tình trạng cuốc theo bạn",
            "Trip status in your view",
            "choice",
            True,
            [
                ("not_started", "Chưa đón khách", "Never picked up"),
                ("cancelled", "Khách hủy", "Passenger cancelled"),
                ("other", "Khác", "Other"),
            ],
        ),
        _f("when_aware", "Bạn biết sự việc lúc mấy giờ?", "When did you become aware?", "time", False),
        _f("evidence_photo", "Ảnh / bằng chứng (nếu có)", "Photo / evidence (if any)", "photo", False),
    ],
    "Tech": [
        _f(
            "tech_issue",
            "Bạn gặp sự cố gì (GPS, app, mạng, thiết bị)?",
            "What went wrong (GPS, app, network, device)?",
            "text",
            True,
        ),
        _f("tech_time", "Sự cố xảy ra lúc mấy giờ?", "When did the issue occur?", "time", True),
        _f(
            "tech_other_trips",
            "Các cuốc khác trong ngày có bị như vậy không?",
            "Did other trips that day have the same issue?",
            "choice",
            True,
            [("yes", "Có", "Yes"), ("no", "Không", "No"), ("unsure", "Không chắc", "Not sure")],
        ),
        _f("tech_ticket", "Mã ticket báo lỗi (nếu có)", "Support ticket code (if any)", "ticket", False),
        _f("evidence_photo", "Ảnh chụp màn hình (nếu có)", "Screenshot (if any)", "photo", False),
    ],
    "Customer": [
        _f("customer_what", "Khách đã yêu cầu hoặc làm gì?", "What did the passenger ask or do?", "text", True),
        _f("customer_time", "Việc đó xảy ra lúc mấy giờ?", "When did it happen?", "time", True),
        _f("customer_place", "Xảy ra ở đâu?", "Where did it happen?", "location", True),
        _f(
            "customer_contact",
            "Khách liên hệ bạn bằng cách nào?",
            "How did the passenger contact you?",
            "choice",
            False,
            [("app", "Qua app", "In app"), ("phone", "Điện thoại", "Phone"), ("in_person", "Trực tiếp", "In person")],
        ),
        _f("evidence_photo", "Ảnh / bằng chứng (nếu có)", "Photo / evidence (if any)", "photo", False),
    ],
    "Other": [
        _f("detail", "Nội dung giải trình", "Your explanation", "text", True),
        _f("evidence_photo", "Đính kèm ảnh (nếu có)", "Attach a photo (if any)", "photo", False),
    ],
}


def build_form(reason: str, workflow: dict[str, Any] | None, k: int) -> dict[str, Any]:
    """Fixed fields of `reason` + up to `k` optional dynamic ones from `workflow` ({code, version, body})."""
    fixed = [dict(f) for f in _FIXED.get(reason, _FIXED["Other"])]
    fields = fixed
    wf_ref = None
    if workflow:
        wf_ref = {"code": workflow["code"], "version": workflow["version"]}
        dyn = 0
        for item in (workflow.get("body") or {}).get("ask_first") or []:
            if dyn >= max(0, k):
                break
            text = item.get("text") if isinstance(item, dict) else item
            if not isinstance(text, str) or not text.strip():
                continue
            type_ = item.get("type") if isinstance(item, dict) and item.get("type") in FIELD_TYPES else "text"
            dyn += 1
            field: dict[str, Any] = {
                "id": f"dyn_{dyn}",
                "label": {"vi": text.strip(), "en": text.strip()},
                "type": type_,
                "required": False,
                "origin": "workflow",
            }
            if type_ == "choice" and isinstance(item, dict):
                field["options"] = [
                    {"value": str(o), "label": {"vi": str(o), "en": str(o)}} for o in item.get("options", [])
                ]
            fields.append(field)
    version = f"{reason}.{FORM_REVISION}" + (f"+{wf_ref['code']}@{wf_ref['version']}" if wf_ref else "")
    return {
        "reason": reason,
        "form_version": version,
        "fields": fields,
        "workflow": wf_ref,
        "has_question_set": reason in _FIXED and reason != "Other",
    }


def driver_form_view(form: dict[str, Any]) -> dict[str, Any]:
    """Driver-facing form: no origin marks and no workflow reference (PRD-A US1)."""
    return {
        "reason": form["reason"],
        "form_version": form["form_version"],
        "has_question_set": form.get("has_question_set", False),
        "fields": [{k: v for k, v in f.items() if k != "origin"} for f in form["fields"]],
    }


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, (list, dict)) and not v)


def _amount_ok(v: Any) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return v >= 0
    if isinstance(v, str):
        s = re.sub(r"[.,\s]|đ|vnd|VND", "", v.strip())
        return s.isdigit()
    return False


def validate_answers(
    form: dict[str, Any], answers: dict[str, Any], *, strict_required: bool = True
) -> dict[str, list[Any]]:
    missing: list[str] = []
    invalid: list[dict[str, str]] = []
    for f in form["fields"]:
        v = answers.get(f["id"])
        if _blank(v):
            if f["required"] and strict_required:
                missing.append(f["id"])
            continue
        t = f["type"]
        if t == "amount" and not _amount_ok(v):
            invalid.append({"field": f["id"], "code": "invalid_amount"})
        elif t == "choice" and str(v) not in {o["value"] for o in f.get("options", [])}:
            invalid.append({"field": f["id"], "code": "invalid_choice"})
        elif t == "ticket" and not _TICKET.match(str(v).strip()):
            invalid.append({"field": f["id"], "code": "invalid_ticket"})
        elif t in ("text", "time", "location") and not isinstance(v, (str, dict)):
            invalid.append({"field": f["id"], "code": "invalid_text"})
    return {"missing": missing, "invalid": invalid}


def statement_text(form: dict[str, Any], answers: dict[str, Any]) -> str:
    """Readable statement (Vietnamese labels) used for summaries and statement versions."""
    lines = []
    for f in form["fields"]:
        v = answers.get(f["id"])
        if _blank(v):
            continue
        if isinstance(v, dict):
            v = v.get("text") or ", ".join(f"{a}={b}" for a, b in v.items())
        elif isinstance(v, list):
            v = f"{len(v)} tệp đính kèm"
        elif f["type"] == "choice":
            v = next((o["label"]["vi"] for o in f.get("options", []) if o["value"] == str(v)), v)
        lines.append(f"{f['label']['vi']}: {v}")
    return "\n".join(lines)
