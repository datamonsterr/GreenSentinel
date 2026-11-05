"""Unit tests for src/services/answer_formatter.py."""

import asyncio
from typing import Any

import pytest

from src.services.answer_formatter import (
    EntityWhitelist,
    FormattedAnswer,
    format_answer,
    sanitize_bare_uuids,
    sanitize_markdown_links,
)


@pytest.mark.asyncio
async def test_formatted_answer_dataclass():
    res = FormattedAnswer(markdown="# Test", suggestions=[{"label": "L1", "prompt": "P1"}])
    assert res.markdown == "# Test"
    assert len(res.suggestions) == 1


@pytest.mark.asyncio
async def test_format_answer_happy_path():
    raw_answer = "Kết luận: Vụ việc 018f2f4e-b000-7000-8000-000000000001 ghi nhận tài xế 018f2f4e-b300-7000-8000-000000000001 vi phạm trong chuyến trip_001."
    citations = [
        {"id": "c1", "source": "Quy chế 2026", "section": "Điều 14.1", "content": "Chiếm đoạt cuốc", "score": 0.9}
    ]
    entities = EntityWhitelist(
        case_ids={"018f2f4e-b000-7000-8000-000000000001"},
        driver_ids={"018f2f4e-b300-7000-8000-000000000001"},
        trip_ids={"trip_001"},
        citation_ids={"c1"},
    )

    async def fake_provider(contents: Any, declarations: Any, system: str) -> Any:
        class FakeResponse:
            text = """{
  "markdown": "**Xác nhận tài xế có hành vi vi phạm chiếm đoạt cuốc.**\\n\\nHồ sơ [Vụ việc](case://018f2f4e-b000-7000-8000-000000000001) liên quan đến [Tài xế Nguyễn Văn A](driver://018f2f4e-b300-7000-8000-000000000001).\\n\\nChuyến đi: [Hồ Gươm → Cầu Giấy](trip://trip_001?pickup=H%C3%B2+G%C6%B0%C6%A1m&dest=C%E1%BA%A7u+Gi%E1%BA%A5y).\\n\\nCăn cứ quy định tại [1](policy://c1).",
  "suggestions": [
    {"label": "Xem lịch sử tài xế", "prompt": "Tra cứu lịch sử các chuyến trước"},
    {"label": "Xem hồ sơ tương tự", "prompt": "Tìm các vụ việc vi phạm tương tự"}
  ]
}"""

        return FakeResponse()

    result = await format_answer(
        raw_answer,
        citations=citations,
        entities=entities,
        provider=fake_provider,
    )
    assert isinstance(result, FormattedAnswer)
    assert "**" in result.markdown  # 1-line headline with bold conclusion
    assert "case://018f2f4e-b000-7000-8000-000000000001" in result.markdown
    assert "driver://018f2f4e-b300-7000-8000-000000000001" in result.markdown
    assert "trip://trip_001" in result.markdown
    assert "policy://c1" in result.markdown
    assert len(result.suggestions) == 2
    assert all(len(s["label"]) <= 40 for s in result.suggestions)


@pytest.mark.asyncio
async def test_entity_whitelist_guard_replaces_unwhitelisted_with_plain_title():
    text = (
        "Xem [Hồ sơ vụ việc](case://unknown-case-id) và [Vụ việc hợp lệ](case://known-case-id). "
        "Tài xế [Nguyễn Văn A](driver://d-known) cùng [Trần Văn B](driver://d-unknown). "
        "Chuyến [Điểm A → Điểm B](trip://t-known?pickup=A&dest=B) và [Chuyến lạ](trip://t-unknown). "
        "Dẫn chiếu [1](policy://c1) và [2](policy://c999)."
    )
    whitelist = EntityWhitelist(
        case_ids={"known-case-id"},
        driver_ids={"d-known"},
        trip_ids={"t-known"},
        citation_ids={"c1"},
    )
    sanitized = sanitize_markdown_links(text, whitelist)
    # unwhitelisted links replaced with plain title
    assert "[Hồ sơ vụ việc](case://unknown-case-id)" not in sanitized
    assert "Hồ sơ vụ việc" in sanitized

    assert "[Vụ việc hợp lệ](case://known-case-id)" in sanitized

    assert "[Nguyễn Văn A](driver://d-known)" in sanitized
    assert "[Trần Văn B](driver://d-unknown)" not in sanitized
    assert "Trần Văn B" in sanitized

    assert "[Điểm A → Điểm B](trip://t-known?pickup=A&dest=B)" in sanitized
    assert "[Chuyến lạ](trip://t-unknown)" not in sanitized
    assert "Chuyến lạ" in sanitized

    assert "[1](policy://c1)" in sanitized
    assert "[2](policy://c999)" not in sanitized
    assert " 2." in sanitized or "và 2." in sanitized or "2" in sanitized


@pytest.mark.asyncio
async def test_fallback_on_invalid_json():
    raw_answer = "Câu trả lời nguyên bản khi lỗi"

    async def bad_provider(*args: Any, **kwargs: Any) -> Any:
        class FakeResponse:
            text = "This is not valid JSON at all!"

        return FakeResponse()

    result = await format_answer(
        raw_answer,
        citations=[],
        entities=EntityWhitelist(),
        provider=bad_provider,
    )
    # Fallback to raw answer + 0 suggestions
    assert result.markdown == raw_answer
    assert result.suggestions == []


@pytest.mark.asyncio
async def test_fallback_on_provider_exception():
    raw_answer = "Câu trả lời thô"

    async def error_provider(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Provider down")

    result = await format_answer(
        raw_answer,
        citations=[],
        entities=EntityWhitelist(),
        provider=error_provider,
    )
    assert result.markdown == raw_answer
    assert result.suggestions == []


@pytest.mark.asyncio
async def test_fallback_on_timeout():
    raw_answer = "Câu trả lời thô khi timeout"

    async def slow_provider(*args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(0.2)

        class FakeResponse:
            text = '{"markdown": "ok", "suggestions": []}'

        return FakeResponse()

    result = await format_answer(
        raw_answer,
        citations=[],
        entities=EntityWhitelist(),
        provider=slow_provider,
        timeout_seconds=0.05,
    )
    assert result.markdown == raw_answer
    assert result.suggestions == []


@pytest.mark.asyncio
async def test_cap_suggestions_at_3_and_label_at_40():
    raw_answer = "Dữ liệu thô"

    async def verbose_suggestions_provider(*args: Any, **kwargs: Any) -> Any:
        class FakeResponse:
            text = """{
  "markdown": "**Kết luận chính.**\\n\\nNội dung chi tiết.",
  "suggestions": [
    {"label": "Nhãn rất dài hơn bốn mươi ký tự chắc chắn sẽ bị cắt ngắn lại", "prompt": "P1"},
    {"label": "Nhãn 2", "prompt": "P2"},
    {"label": "Nhãn 3", "prompt": "P3"},
    {"label": "Nhãn 4 thừa", "prompt": "P4"},
    {"label": "Nhãn 5 thừa", "prompt": "P5"}
  ]
}"""

        return FakeResponse()

    result = await format_answer(
        raw_answer,
        citations=[],
        entities=EntityWhitelist(),
        provider=verbose_suggestions_provider,
    )
    assert len(result.suggestions) == 3
    for s in result.suggestions:
        assert len(s["label"]) <= 40


def test_sanitize_bare_uuids_driver_id():
    uuid_str = "018f2f4e-b300-7000-8000-000000000001"
    text = f"Thông tin tài xế {uuid_str} cần kiểm tra."
    whitelist = EntityWhitelist(driver_ids={uuid_str})
    res = sanitize_bare_uuids(text, whitelist)
    assert res == f"Thông tin tài xế [Tài xế](driver://{uuid_str}) cần kiểm tra."


def test_sanitize_bare_uuids_trip_id():
    uuid_str = "018f2f4e-b200-7000-8000-000000000002"
    text = f"Hành trình chuyến đi {uuid_str} có bất thường."
    whitelist = EntityWhitelist(trip_ids={uuid_str})
    res = sanitize_bare_uuids(text, whitelist)
    assert res == f"Hành trình chuyến đi [Chuyến đi](trip://{uuid_str}) có bất thường."


def test_sanitize_bare_uuids_case_id():
    uuid_str = "018f2f4e-b000-7000-8000-000000000003"
    text = f"Xem xét hồ sơ {uuid_str} ngay."
    whitelist = EntityWhitelist(case_ids={uuid_str})
    res = sanitize_bare_uuids(text, whitelist)
    assert res == f"Xem xét hồ sơ [Vụ việc](case://{uuid_str}) ngay."


def test_sanitize_bare_uuids_unknown_dropped_no_fake_label():
    uuid_str = "018f2f4e-b999-7000-8000-000000000099"
    text = f"Mã không xác định {uuid_str}."
    whitelist = EntityWhitelist()
    res = sanitize_bare_uuids(text, whitelist)
    assert res == "Mã không xác định ."
    assert "Vụ việc" not in res
    assert uuid_str not in res


def test_sanitize_bare_uuids_preserves_existing_markdown_links():
    driver_uuid = "018f2f4e-b300-7000-8000-000000000001"
    case_uuid = "018f2f4e-b000-7000-8000-000000000002"
    text = f"[Tài xế Nguyễn Văn A](driver://{driver_uuid}) trong hồ sơ {case_uuid}."
    whitelist = EntityWhitelist(driver_ids={driver_uuid}, case_ids={case_uuid})
    res = sanitize_bare_uuids(text, whitelist)
    assert res == f"[Tài xế Nguyễn Văn A](driver://{driver_uuid}) trong hồ sơ [Vụ việc](case://{case_uuid})."


# ---------------------------------------------------------------------------
# Driver Profile Unit Tests (Issue #484)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_driver_format_answer_all_block_types():
    raw_answer = "Tài xế có chuyến đi trip_001 liên quan vụ việc case_001."
    entities = EntityWhitelist(
        case_ids={"case_001"},
        trip_ids={"trip_001"},
        citation_ids={"c12_2"},
    )

    async def fake_driver_provider(contents: Any, declarations: Any, system: str) -> Any:
        class FakeResponse:
            text = """{
  "markdown": "GSupport đã tiếp nhận thông tin và kiểm tra dữ liệu.",
  "blocks": [
    {
      "type": "case_card",
      "case_id": "case_001",
      "title": "Kiểm tra lộ trình bất thường",
      "status_key": "under_review"
    },
    {
      "type": "trip_card",
      "trip_id": "trip_001",
      "pickup": "Hồ Gươm",
      "destination": "Cầu Giấy",
      "fare_vnd": 85000
    },
    {
      "type": "table",
      "columns": ["Thời gian", "Sự kiện"],
      "rows": [["14:30", "Ùn tắc Kim Mã"]]
    },
    {
      "type": "list",
      "items": [
        {"label": "Hồ sơ vụ việc", "href": "case://case_001"},
        {"label": "Quy chế bảo vệ", "href": "policy://c12_2"},
        {"label": "Trang chủ", "href": "https://greensm.vn"}
      ]
    },
    {
      "type": "link",
      "label": "Hướng dẫn khiếu nại",
      "url": "https://greensm.vn/help"
    },
    {
      "type": "status_pill",
      "status_key": "under_review"
    },
    {
      "type": "evidence",
      "items": [
        {"kind": "traffic", "summary": "Ùn tắc cục bộ Kim Mã", "source": "Peer GPS"}
      ]
    },
    {
      "type": "next_steps",
      "items": [
        {"label": "Gửi giải trình", "prompt": "Tôi muốn gửi giải trình về sự cố kẹt xe"}
      ]
    }
  ]
}"""

        return FakeResponse()

    result = await format_answer(
        raw_answer,
        entities=entities,
        provider=fake_driver_provider,
        profile="driver",
        locale="vi",
    )

    assert result.markdown == "GSupport đã tiếp nhận thông tin và kiểm tra dữ liệu."
    assert len(result.blocks) == 8
    block_types = [b["type"] for b in result.blocks]
    assert block_types == [
        "case_card",
        "trip_card",
        "table",
        "list",
        "link",
        "status_pill",
        "evidence",
        "next_steps",
    ]
    # Check next_steps populated suggestions
    assert len(result.suggestions) == 1
    assert result.suggestions[0]["label"] == "Gửi giải trình"


@pytest.mark.asyncio
async def test_driver_format_answer_drops_non_whitelisted_entities():
    raw_answer = "Chi tiết vụ việc và chuyến đi."
    entities = EntityWhitelist(
        case_ids={"case_valid"},
        trip_ids={"trip_valid"},
        citation_ids={"policy_valid"},
    )

    async def fake_provider(contents: Any, declarations: Any, system: str) -> Any:
        class FakeResponse:
            text = """{
  "markdown": "Thông tin chi tiết",
  "blocks": [
    {"type": "case_card", "case_id": "case_invalid", "title": "Vụ việc lạ", "status_key": "under_review"},
    {"type": "case_card", "case_id": "case_valid", "title": "Vụ việc hợp lệ", "status_key": "under_review"},
    {"type": "trip_card", "trip_id": "trip_invalid", "pickup": "A", "destination": "B"},
    {"type": "trip_card", "trip_id": "trip_valid", "pickup": "C", "destination": "D"},
    {
      "type": "list",
      "items": [
        {"label": "Vụ việc lạ", "href": "case://case_invalid"},
        {"label": "Vụ việc đúng", "href": "case://case_valid"},
        {"label": "Chuyến đi lạ", "href": "trip://trip_invalid"},
        {"label": "Chính sách đúng", "href": "policy://policy_valid"},
        {"label": "Chính sách lạ", "href": "policy://policy_invalid"},
        {"label": "Web hợp lệ", "href": "https://greensm.vn"}
      ]
    },
    {"type": "link", "label": "Link lạ", "url": "case://case_invalid"},
    {"type": "link", "label": "Link đúng", "url": "case://case_valid"},
    {"type": "link", "label": "Web", "url": "https://example.com"}
  ]
}"""

        return FakeResponse()

    result = await format_answer(
        raw_answer,
        entities=entities,
        provider=fake_provider,
        profile="driver",
    )

    # case_invalid dropped, case_valid kept
    case_cards = [b for b in result.blocks if b["type"] == "case_card"]
    assert len(case_cards) == 1
    assert case_cards[0]["case_id"] == "case_valid"

    # trip_invalid dropped, trip_valid kept
    trip_cards = [b for b in result.blocks if b["type"] == "trip_card"]
    assert len(trip_cards) == 1
    assert trip_cards[0]["trip_id"] == "trip_valid"

    # list block items filtered
    list_blocks = [b for b in result.blocks if b["type"] == "list"]
    assert len(list_blocks) == 1
    remaining_hrefs = [item["href"] for item in list_blocks[0]["items"]]
    assert remaining_hrefs == ["case://case_valid", "policy://policy_valid", "https://greensm.vn"]

    # link blocks filtered
    link_blocks = [b for b in result.blocks if b["type"] == "link"]
    assert len(link_blocks) == 2
    assert {lnk["url"] for lnk in link_blocks} == {"case://case_valid", "https://example.com"}


@pytest.mark.asyncio
async def test_driver_format_answer_strips_raw_codes():
    raw_answer = "Lỗi ERR-01 ghi nhận mã ERR-02 và trạng thái AUTO_DISMISSED."
    entities = EntityWhitelist(case_ids={"case_001"})

    async def fake_provider(contents: Any, declarations: Any, system: str) -> Any:
        class FakeResponse:
            text = """{
  "markdown": "Hồ sơ có mã lỗi ERR-01 và trạng thái AUTO_DISMISSED.",
  "blocks": [
    {"type": "status_pill", "status_key": "AUTO_DISMISSED"},
    {"type": "status_pill", "status_key": "ERR-01"},
    {"type": "case_card", "case_id": "case_001", "title": "Vụ việc ERR-02", "status_key": "PENDING_REVIEW"}
  ]
}"""

        return FakeResponse()

    result = await format_answer(
        raw_answer,
        entities=entities,
        provider=fake_provider,
        profile="driver",
    )

    # Raw codes stripped from markdown
    assert "ERR-01" not in result.markdown
    assert "ERR-02" not in result.markdown
    assert "AUTO_DISMISSED" not in result.markdown

    # Status keys cleaned
    pills = [b for b in result.blocks if b["type"] == "status_pill"]
    assert len(pills) == 1  # ERR-01 dropped
    assert pills[0]["status_key"] == "auto_dismissed"

    case_cards = [b for b in result.blocks if b["type"] == "case_card"]
    assert len(case_cards) == 1
    assert case_cards[0]["status_key"] == "pending_review"
    assert "ERR-02" not in case_cards[0]["title"]


@pytest.mark.asyncio
async def test_driver_format_answer_timeout_fallback_to_plain_markdown():
    # Requirement 1: Driver timeout/exception fallback must sanitize (strip ERR-0x/ERR_0x and UPPER_SNAKE codes, bare UUIDs, unwhitelisted links)
    raw_answer = (
        "Lỗi ERR-01 và mã ERR_02 trạng thái PENDING_REVIEW với vụ việc "
        "018f2f4e-b000-7000-8000-000000000001 và liên kết [Lạ](case://unknown-case) [Đúng](case://018f2f4e-b000-7000-8000-000000000001)."
    )
    whitelist = EntityWhitelist(
        case_ids={"018f2f4e-b000-7000-8000-000000000001"},
    )

    async def slow_provider(*args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(0.2)

        class FakeResponse:
            text = '{"markdown": "ok", "blocks": []}'

        return FakeResponse()

    result = await format_answer(
        raw_answer,
        entities=whitelist,
        provider=slow_provider,
        timeout_seconds=0.05,
        profile="driver",
        locale="vi",
    )
    # Must NOT passthrough raw unsanitized error codes, UPPER_SNAKE, unwhitelisted links
    assert "ERR-01" not in result.markdown
    assert "ERR_02" not in result.markdown
    assert "PENDING_REVIEW" not in result.markdown
    assert "case://unknown-case" not in result.markdown
    assert "case://018f2f4e-b000-7000-8000-000000000001" in result.markdown
    assert result.blocks == []
    assert result.suggestions == []


@pytest.mark.asyncio
async def test_driver_format_answer_locale_param():
    raw_answer = "Your trip has been reviewed."

    captured_system = ""

    async def capturing_provider(contents: Any, declarations: Any, system: str) -> Any:
        nonlocal captured_system
        captured_system = system

        class FakeResponse:
            text = '{"markdown": "Your trip has been reviewed.", "blocks": []}'

        return FakeResponse()

    result = await format_answer(
        raw_answer,
        provider=capturing_provider,
        profile="driver",
        locale="en",
    )
    assert result.markdown == "Your trip has been reviewed."
    assert "English" in captured_system or "GSupport" in captured_system


def test_sanitize_bare_uuids_locale():
    from src.services.answer_formatter import sanitize_bare_uuids

    uid = "018f2f4e-b000-7000-8000-000000000001"

    # vi locale (default)
    text_case = f"Hồ sơ {uid}"
    assert (
        sanitize_bare_uuids(text_case, EntityWhitelist(case_ids={uid}), locale="vi") == f"Hồ sơ [Vụ việc](case://{uid})"
    )
    assert (
        sanitize_bare_uuids(text_case, EntityWhitelist(driver_ids={uid}), locale="vi")
        == f"Hồ sơ [Tài xế](driver://{uid})"
    )
    assert (
        sanitize_bare_uuids(text_case, EntityWhitelist(trip_ids={uid}), locale="vi")
        == f"Hồ sơ [Chuyến đi](trip://{uid})"
    )

    # en locale
    assert sanitize_bare_uuids(text_case, EntityWhitelist(case_ids={uid}), locale="en") == f"Hồ sơ [Case](case://{uid})"
    assert (
        sanitize_bare_uuids(text_case, EntityWhitelist(driver_ids={uid}), locale="en")
        == f"Hồ sơ [Driver](driver://{uid})"
    )
    assert sanitize_bare_uuids(text_case, EntityWhitelist(trip_ids={uid}), locale="en") == f"Hồ sơ [Trip](trip://{uid})"


def test_sanitize_status_key_rules():
    from src.services.answer_formatter import sanitize_status_key

    # Valid lowercase snake_case starting with [a-z]
    assert sanitize_status_key("under_review") == "under_review"
    assert sanitize_status_key("auto_dismissed") == "auto_dismissed"
    assert sanitize_status_key("pending_analyst_review") == "pending_analyst_review"
    assert sanitize_status_key("PENDING_REVIEW") == "pending_review"

    # Strip ERR_0\d variants
    assert sanitize_status_key("ERR_01") == ""
    assert sanitize_status_key("ERR-01") == ""
    assert sanitize_status_key("err_02") == ""
    assert sanitize_status_key("ERR_03_resolved") == "resolved"

    # Reject non-snake_case or strings not starting with [a-z]
    assert sanitize_status_key("under-review") == ""
    assert sanitize_status_key("123_invalid") == ""
    assert sanitize_status_key("_leading_underscore") == ""
    assert sanitize_status_key("") == ""
    assert sanitize_status_key(None) == ""


@pytest.mark.asyncio
async def test_case_card_no_default_status_key():
    from src.services.answer_formatter import sanitize_driver_blocks

    whitelist = EntityWhitelist(case_ids={"case_123"})
    # Status key omitted when unknown
    blocks = [{"type": "case_card", "case_id": "case_123", "title": "Khiếu nại"}]
    sanitized = sanitize_driver_blocks(blocks, whitelist)
    assert len(sanitized) == 1
    assert sanitized[0]["case_id"] == "case_123"
    assert "status_key" not in sanitized[0]


@pytest.mark.asyncio
async def test_table_row_length_must_equal_columns():
    from src.services.answer_formatter import sanitize_driver_blocks

    blocks = [
        {
            "type": "table",
            "columns": ["Col1", "Col2", "Col3"],
            "rows": [
                ["A", "B", "C"],  # Valid length = 3
                ["A", "B"],  # Invalid length = 2, dropped
                ["A", "B", "C", "D"],  # Invalid length = 4, dropped
                ["X", "Y", "Z"],  # Valid length = 3
            ],
        }
    ]
    sanitized = sanitize_driver_blocks(blocks, EntityWhitelist())
    assert len(sanitized) == 1
    rows = sanitized[0]["rows"]
    assert len(rows) == 2
    assert rows == [["A", "B", "C"], ["X", "Y", "Z"]]


@pytest.mark.asyncio
async def test_link_and_list_blocks_https_only():
    from src.services.answer_formatter import sanitize_driver_blocks

    whitelist = EntityWhitelist(citation_ids={"policy_1"})
    blocks = [
        {
            "type": "list",
            "items": [
                {"label": "HTTPS Web", "href": "https://example.com/ok"},
                {"label": "HTTP Web", "href": "http://example.com/insecure"},
                {"label": "Policy Link", "href": "policy://policy_1"},
            ],
        },
        {"type": "link", "label": "HTTPS", "url": "https://example.com/safe"},
        {"type": "link", "label": "HTTP", "url": "http://example.com/insecure"},
    ]
    sanitized = sanitize_driver_blocks(blocks, whitelist)
    list_block = [b for b in sanitized if b["type"] == "list"][0]
    hrefs = [it["href"] for it in list_block["items"]]
    assert "https://example.com/ok" in hrefs
    assert "policy://policy_1" in hrefs
    assert "http://example.com/insecure" not in hrefs

    link_blocks = [b for b in sanitized if b["type"] == "link"]
    assert len(link_blocks) == 1
    assert link_blocks[0]["url"] == "https://example.com/safe"


@pytest.mark.asyncio
async def test_evidence_kind_enum_filtering():
    from src.services.answer_formatter import sanitize_driver_blocks

    blocks = [
        {
            "type": "evidence",
            "items": [
                {"kind": "traffic", "summary": "Tắc đường", "source": "GPS"},
                {"kind": "weather", "summary": "Mưa to", "source": "WeatherAPI"},
                {"kind": "telemetry", "summary": "Vận tốc 3km/h", "source": "OBD"},
                {"kind": "policy", "summary": "Điều 12.2", "source": "Policy"},
                {"kind": "unknown_kind", "summary": "Không hợp lệ", "source": "Bad"},
                {"kind": "gps_spoof", "summary": "Không thuộc enum", "source": "Bad"},
            ],
        }
    ]
    sanitized = sanitize_driver_blocks(blocks, EntityWhitelist())
    assert len(sanitized) == 1
    items = sanitized[0]["items"]
    assert len(items) == 4
    kinds = {it["kind"] for it in items}
    assert kinds == {"traffic", "weather", "telemetry", "policy"}
