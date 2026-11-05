"""Public documentation contracts; no application or credential-dependent imports."""

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[3]
ARCHITECTURE = ROOT / "docs" / "architecture"
ADR_008 = "adr-008-poc-v2-async-driver-agent-and-a2a-collaboration.md"
ADR_009 = "adr-009-poc-v2-precedent-workflow-mining-and-jev-similarity.md"
ADR_010 = "adr-010-driver-gsupport-case-sessions-and-shadcn-chatui.md"
DOCUMENTS = ("POC_DESIGN.md", "ARCHITECTURE.md", ADR_008, ADR_009, ADR_010)


def test_corroboration_requires_analyst_confirmation_in_adr_008() -> None:
    text = (ARCHITECTURE / ADR_008).read_text(encoding="utf-8")
    boundary = re.search(r"### 1\. .*?(?=\n### |\Z)", text, flags=re.S)
    assert boundary is not None
    decision = boundary.group().lower()
    assert "auto_dismissed" not in decision, "Corroboration still authorizes automatic dismissal"
    assert "authorized analyst" in decision
    assert "confirmation" in decision
    assert "written rationale" in decision


@pytest.mark.parametrize("filename", DOCUMENTS)
def test_release_authority_is_distinct_from_merged_runtime(filename: str) -> None:
    text = (ARCHITECTURE / filename).read_text(encoding="utf-8")
    notice = re.search(r"## Release authority and runtime boundary\n(.*?)(?=\n## |\Z)", text, re.S)
    assert notice is not None, f"{filename} lacks a release/runtime boundary"
    correction = notice.group(1).lower()
    for required in ("2026-09-30", "@datamonsterr", "merged", "historical", "deferred", "rationale"):
        assert required in correction
    assert "no automatic dismissal" in correction
    assert "authorized analyst" in correction and "confirmation" in correction
    assert "warnings" in correction and "blocked" in correction
    assert "../ba/PRD.md" in notice.group(1)
    assert "586caec05ddb7626a1f47066b55154e74d245cc0" in correction
    assert "/issues/73" in correction
    assert "auto_dismissed" in correction, "Name the inherited runtime gap explicitly"


@pytest.mark.parametrize("filename", (ADR_008, ADR_009, ADR_010))
def test_v2_decision_history_is_retained_without_release_authorization(filename: str) -> None:
    text = (ARCHITECTURE / filename).read_text(encoding="utf-8")
    status = re.search(r"## Status\n(.*?)(?=\n## |\Z)", text, re.S)
    assert status is not None
    assert "superseded" in status.group(1).lower()
    history = re.search(r"## Historical decision record\n(.*?)(?=\n## |\Z)", text, re.S)
    assert history is not None
    assert history.group(1).strip(), "Retain the old decision as an identifiable historical record"


def test_release_diagrams_never_skip_the_analyst_gate() -> None:
    text = (ARCHITECTURE / "POC_DESIGN.md").read_text(encoding="utf-8")
    diagrams = re.findall(r"```mermaid\n(.*?)```", text, re.S)
    assert diagrams
    assert not any("auto_dismissed" in diagram for diagram in diagrams)
    assert any("confirmation" in diagram.lower() and "rationale" in diagram.lower() for diagram in diagrams)


def test_precedent_similarity_is_raw_relevance_not_probability() -> None:
    text = (ARCHITECTURE / ADR_009).read_text(encoding="utf-8")
    field = re.search(r"^\s*- `similarity_score`: (.*)$", text, re.M)
    assert field is not None
    semantics = field.group(1).lower()
    assert "raw" in semantics and "uncalibrated" in semantics and "relevance" in semantics
    assert "not" in semantics and "probability" in semantics
    assert "100% operational uptime" not in text


@pytest.mark.parametrize("filename", ("POC_DESIGN.md", "ARCHITECTURE.md"))
def test_classifier_defaults_and_aggregate_quality_are_separate(filename: str) -> None:
    text = (ARCHITECTURE / filename).read_text(encoding="utf-8")
    assert re.search(r'score_semantics\s*=\s*"uncalibrated_model_confidence"', text)
    assert "aggregate decision quality" in text.lower()
    assert "per-case" in text.lower()


@pytest.mark.parametrize("filename", ("POC_DESIGN.md", "ARCHITECTURE.md", ADR_009))
def test_route_alternatives_are_optional_and_distinct_from_retrieval(filename: str) -> None:
    text = (ARCHITECTURE / filename).read_text(encoding="utf-8")
    paragraph = next((p.lower() for p in text.split("\n\n") if "Top-k ROUTE" in p), "")
    assert "optional" in paragraph and "pending product scope" in paragraph
    assert "rag retrieval top-k" in paragraph


def _heading_anchors(text: str) -> set[str]:
    """GitHub-style heading IDs, including duplicate heading suffixes."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    counts: dict[str, int] = {}
    anchors: set[str] = set()
    for heading in re.findall(r"^#{1,6}\s+(.+)$", text, re.M):
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        count = counts.get(slug, 0)
        anchors.add(f"{slug}-{count}" if count else slug)
        counts[slug] = count + 1
    return anchors


@pytest.mark.parametrize("filename", DOCUMENTS)
def test_owned_document_links_are_portable_and_resolve(filename: str) -> None:
    document = ARCHITECTURE / filename
    text = document.read_text(encoding="utf-8")
    assert "file:///" not in text
    for destination in re.findall(r"\[[^\]\n]+\]\(([^\s)]+)\)", text):
        link = urlsplit(destination)
        if link.scheme in ("https", "http", "mailto"):
            continue  # Network availability is not a public documentation contract.
        assert not link.scheme and not link.netloc, destination
        assert not link.path.startswith("/"), destination
        target = (document.parent / unquote(link.path)).resolve() if link.path else document
        assert target.is_relative_to(ROOT), destination
        assert target.is_file(), destination
        if link.fragment and target.suffix == ".md":
            assert unquote(link.fragment) in _heading_anchors(target.read_text(encoding="utf-8")), destination


@pytest.mark.parametrize("filename", DOCUMENTS)
def test_architecture_questions_remain_discoverable(filename: str) -> None:
    text = (ARCHITECTURE / filename).read_text(encoding="utf-8").lower()
    for question in (
        "system topology",
        "state and graph lifecycle",
        "tool contracts",
        "data flow",
        "trade-offs",
        "security boundaries",
    ):
        assert question in text, f"{filename} does not cover {question}"


@pytest.mark.parametrize("filename", ("POC_DESIGN.md", "ARCHITECTURE.md"))
def test_strict_prd_human_outcomes_are_not_replaced_by_compact_v1(filename: str) -> None:
    text = (ARCHITECTURE / filename).read_text(encoding="utf-8")
    scope = re.search(r"## Approved Phase 1 analyst outcomes\n(.*?)(?=\n## |\Z)", text, re.S)
    assert scope is not None, "Compact v1 commands cannot replace the FR-04 release outcomes"
    approved = scope.group(1).lower()
    if filename == "ARCHITECTURE.md":
        for outcome in (
            "agree",
            "disagree",
            "request more evidence",
        ):
            assert outcome in approved
        assert "rationale" in approved and "confirmation" in approved
    else:
        for outcome in (
            "dismiss false alarm",
            "request more evidence",
            "issue warning",
            "approve fine",
            "suspend",
            "escalate",
        ):
            assert outcome in approved
        assert "senior" in approved and "rationale" in approved and "confirmation" in approved


@pytest.mark.parametrize("filename", DOCUMENTS)
def test_current_runtime_boundary_preserves_upstream_remediation(filename: str) -> None:
    text = (ARCHITECTURE / filename).read_text(encoding="utf-8")
    notice = re.search(r"## Release authority and runtime boundary\n(.*?)(?=\n## |\Z)", text, re.S)
    assert notice is not None
    current = re.sub(r"\s+", " ", notice.group(1)).lower()
    assert "/pull/93" in current, "Accepted upstream remediation must be distinguished from PR #40 history"
    assert "16c1ad6bdc910badbe852418bc5de5b456759156" in current
    assert "legacy" in current and "auto_dismissed" in current
    assert not re.search(r"can still (?:write|set).*auto_dismissed", current)
