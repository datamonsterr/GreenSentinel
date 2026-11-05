"""Unit tests for driver agent content extraction."""

from src.agents.driver_agent import _extract_text_content


def test_extract_text_content_scalars():
    assert _extract_text_content("Hello World") == "Hello World"
    assert _extract_text_content("   Trimmed text   ") == "Trimmed text"
    assert _extract_text_content(12345) == "12345"
    assert _extract_text_content(42.5) == "42.5"
    assert _extract_text_content(None) == ""
    assert _extract_text_content("") == ""


def test_extract_text_content_dict_blocks():
    # Direct text block
    assert _extract_text_content({"type": "text", "text": "Report received"}) == "Report received"
    assert _extract_text_content({"content": "Content fallback"}) == "Content fallback"
    assert _extract_text_content({"message": "Message fallback"}) == "Message fallback"

    # Multiple keys in same dict block should all be extracted without dropping any
    assert _extract_text_content({"text": "Hello", "message": "World"}) == "Hello World"

    # Image block
    assert _extract_text_content({"type": "image_url"}) == "[Hình ảnh đính kèm]"

    # Custom key fallback
    assert _extract_text_content({"custom_field": "Arbitrary response", "type": "unknown_type"}) == "Arbitrary response"

    # Pure tool calls / tool use should be skipped
    assert _extract_text_content({"type": "tool_use", "text": "Should ignore"}) == ""
    assert _extract_text_content({"tool_calls": [{"name": "foo"}]}) == ""
    assert _extract_text_content({"type": "function_call"}) == ""

    # Hybrid response with tool_calls and explanatory text preserves the text explanation
    assert (
        _extract_text_content({"content": "Kiểm tra định vị GPS.", "tool_calls": [{"name": "inspect_telemetry"}]})
        == "Kiểm tra định vị GPS."
    )


def test_extract_text_content_list_and_nested_blocks():
    blocks = [
        {"type": "text", "text": "First paragraph."},
        {"type": "image_url"},
        "Raw string middle.",
        {"text": [{"type": "text", "text": "Nested inside list."}]},
        {"type": "tool_use", "name": "dummy"},
    ]
    extracted = _extract_text_content(blocks)
    assert extracted == "First paragraph. [Hình ảnh đính kèm] Raw string middle. Nested inside list."


def test_extract_text_content_circular_reference():
    d: dict = {"text": "Safe text"}
    d["self"] = d
    assert _extract_text_content(d) == "Safe text"

    # Circular reference through candidate key 'content'
    loop_dict: dict = {"role": "assistant"}
    loop_dict["content"] = [loop_dict, "Extracted content text"]
    assert _extract_text_content(loop_dict) == "Extracted content text"
