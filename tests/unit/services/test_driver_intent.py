"""Unit tests for driver intent detection (issue #573 item 4).

Covers:
- Escalation to analyst (Vietnamese with and without diacritics, English).
- Acceptance of closure (Vietnamese with and without diacritics, English).
- Distinguishing escalation from closure when both keywords appear.
- General statements and greetings that should neither escalate nor close.
"""

import pytest

from src.services.driver_intent import is_driver_closure, is_driver_escalation


@pytest.mark.parametrize(
    "message",
    [
        # Vietnamese with diacritics
        "Tôi muốn tiếp tục khiếu nại lên chuyên viên giám sát",
        "Tôi muốn khiếu nại lên chuyên viên",
        "Chuyển cho chuyên viên giúp tôi",
        "Tôi không đồng ý với kết quả này",
        "khiếu nại tiếp",
        "tiếp tục khiếu nại",
        "chuyển lên giám sát viên",
        "yêu cầu chuyên viên xem xét",
        "tôi không phục",
        "chuyển hồ sơ cho chuyên viên thẩm định",
        "gặp chuyên viên",
        "tôi muốn gặp người thật",
        # Vietnamese without diacritics
        "Toi muon tiep tuc khieu nai len chuyen vien giam sat",
        "Toi muon khieu nai len chuyen vien",
        "Chuyen cho chuyen vien giup toi",
        "khieu nai tiep",
        "tiep tuc khieu nai",
        "khong dong y",
        "chuyen len giam sat vien",
        "yeu cau chuyen vien xem xet",
        "toi khong phuc",
        "gap chuyen vien",
        "toi muon gap nguoi that",
        # English
        "I want to escalate to an analyst",
        "Please escalate this to a human analyst",
        "continue_appeal",
        "continue appeal",
        "escalate to fraud analyst",
        "speak to analyst",
        "transfer to supervisor",
        "human review requested",
        "talk to human",
        "appeal to analyst",
    ],
)
def test_is_driver_escalation_positive(message: str):
    assert is_driver_escalation(message) is True, f"Expected {message!r} to be recognized as escalation"


@pytest.mark.parametrize(
    "message",
    [
        "Tôi bị kẹt xe trên đường Nguyễn Trãi",
        "Toi bi ket xe o nga tu Kim Ma",
        "Xin chào hệ thống GSupport",
        "Cảm ơn bạn đã giải thích",
        "Đồng ý kết thúc",
        "dong y ket thuc",
        "Không khiếu nại thêm",
        "khong khieu nai them",
        "confirm_resolution",
        "no_further_appeal",
    ],
)
def test_is_driver_escalation_negative(message: str):
    assert is_driver_escalation(message) is False, f"Expected {message!r} NOT to be recognized as escalation"


@pytest.mark.parametrize(
    "message",
    [
        # Vietnamese with diacritics
        "Đồng ý kết thúc",
        "Không khiếu nại thêm",
        "Chấp nhận kết quả",
        "Đồng ý đóng vụ việc",
        "Tôi hài lòng với kết quả giải quyết",
        "kết thúc khiếu nại",
        "xác nhận kết thúc",
        "đóng hồ sơ",
        # Vietnamese without diacritics
        "Dong y ket thuc",
        "Khong khieu nai them",
        "Chap nhan ket qua",
        "Dong y dong",
        "hai long",
        "ket thuc khieu nai",
        "xac nhan ket thuc",
        "dong ho so",
        # English
        "confirm_resolution",
        "no_further_appeal",
        "accept resolution",
        "agree to close",
        "close case",
        "end dispute",
    ],
)
def test_is_driver_closure_positive(message: str):
    assert is_driver_closure(message) is True, f"Expected {message!r} to be recognized as closure"


@pytest.mark.parametrize(
    "message",
    [
        "Toi muon tiep tuc khieu nai len chuyen vien giam sat",
        "Tôi muốn tiếp tục khiếu nại",
        "Tôi bị tắc đường",
        "Xin chào",
        "Chuyển cho chuyên viên",
    ],
)
def test_is_driver_closure_negative(message: str):
    assert is_driver_closure(message) is False, f"Expected {message!r} NOT to be recognized as closure"


def test_escalation_takes_precedence_over_closure_keywords():
    # Message contains both negation and closure phrasing
    msg = "Tôi không đồng ý kết thúc, muốn khiếu nại lên chuyên viên"
    assert is_driver_escalation(msg) is True
