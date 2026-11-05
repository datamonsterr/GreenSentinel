"""Golden structure assertions on representative answer formatter fixtures."""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from src.services.answer_formatter import (
    EntityWhitelist,
    format_answer,
)

FIXTURES_DIR = Path("tests/fixtures/answer_formatter")
UUID_PATTERN = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")


def get_all_fixtures() -> list[Path]:
    return sorted(FIXTURES_DIR.glob("*.json"))


@pytest.mark.parametrize("fixture_path", get_all_fixtures(), ids=lambda p: p.stem)
@pytest.mark.asyncio
async def test_fixture_golden_structure(fixture_path: Path):
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    raw_answer = data["raw_answer"]
    citations = data.get("citations", [])
    entities_data = data.get("entities", {})
    mock_output = data["mock_formatted_output"]

    entities = EntityWhitelist(
        case_ids=set(entities_data.get("case_ids", [])),
        driver_ids=set(entities_data.get("driver_ids", [])),
        trip_ids=set(entities_data.get("trip_ids", [])),
        citation_ids=set(entities_data.get("citation_ids", [])),
    )

    async def fake_provider(*args: Any, **kwargs: Any) -> Any:
        class FakeResponse:
            text = json.dumps(mock_output, ensure_ascii=False)

        return FakeResponse()

    result = await format_answer(
        raw_answer,
        citations=citations,
        entities=entities,
        provider=fake_provider,
    )

    md = result.markdown

    # 1. First line headline must be one bold sentence, not a "###" heading
    first_line = md.strip().split("\n")[0]
    assert first_line.startswith("**") and first_line.endswith("**"), (
        f"Headline must be one bold sentence: {first_line}"
    )
    assert not first_line.startswith("#"), f"Headline must not use markdown heading #: {first_line}"

    # 2. Paragraphs separated by blank lines
    assert "\n\n" in md or len(md.splitlines()) <= 2

    # 3. No bare UUIDs in prose (outside link definitions case://...)
    # Remove markdown link URLs before testing bare UUIDs
    clean_text = re.sub(r"\]\([^)]+\)", "]", md)
    bare_uuids = UUID_PATTERN.findall(clean_text)
    assert not bare_uuids, f"Bare UUIDs found in prose: {bare_uuids}"

    # 4. Table present when list of >= 3 items (e.g. driver_history or related_cases_vehicle)
    if fixture_path.stem in {"driver_history", "related_cases_vehicle"}:
        assert "|" in md and ("-+-" in md or "| :---" in md or "| ---" in md), (
            f"Markdown table expected for >= 3 comparable items in {fixture_path.name}"
        )

    # 5. Suggestions 1..3 items, labels <= 40 chars, suggestions must be Vietnamese
    assert 1 <= len(result.suggestions) <= 3
    vietnamese_char_pattern = re.compile(
        r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ"
        r"ÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ]"
    )
    for s in result.suggestions:
        assert len(s["label"]) <= 40, f"Suggestion label exceeds 40 chars: {s['label']}"
        assert s["prompt"], "Suggestion prompt must not be empty"
        assert vietnamese_char_pattern.search(s["label"]), f"Suggestion label must be Vietnamese: {s['label']}"
        assert vietnamese_char_pattern.search(s["prompt"]), f"Suggestion prompt must be Vietnamese: {s['prompt']}"

    # 6. If trip lacks trip_id, render "pickup → destination" as plain bold text without link
    if fixture_path.stem == "trip_without_id":
        assert "trip://" not in md
        assert "**Hồ Gươm → Cầu Giấy**" in md

    # 7. Never output empty sections (no headings with no content, no dangling colon headers)
    for line in md.splitlines():
        trimmed = line.strip()
        assert not trimmed.startswith("###"), f"No ### headings allowed: {trimmed}"
        if trimmed.startswith("#"):
            assert not trimmed.endswith(":"), f"Heading cannot end with colon: {trimmed}"
    assert not re.search(r"^#+\s+[^\n]+\n\s*(?:#+|$)", md, flags=re.M), "No empty heading sections allowed"
