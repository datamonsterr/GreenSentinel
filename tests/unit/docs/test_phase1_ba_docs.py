"""Public Phase 1 BA contracts; no app, database, or credential imports."""

import ast
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[3]
BA = ROOT / "docs" / "ba"
OWNED_BA_DOCS = (
    "PRD.md",
    "MVP.md",
    "USER_STORIES.md",
    "USE_CASES.md",
    "DECISION_LOG.md",
    "DISCOVERY_LOG.md",
    "DISCOVERY_POC_V2_DRIVER_AGENT.md",
    "README.md",
)
MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")


def normalized_prose(text: str) -> str:
    """Ignore presentation changes while retaining policy words and numbers."""
    text = MARKDOWN_LINK.sub(r"\1", text)
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    return re.sub(r"\s+", " ", re.sub(r"[*`$]", "", text)).strip().casefold()


def numbered_section(text: str, number: str, level: int) -> str:
    """Scope policy checks to a numbered section, independent of heading prose."""
    match = re.search(
        rf"^{'#' * level}\s+{re.escape(number)}\b[^\n]*\n(.*?)(?=^#{{1,{level}}}\s|\Z)",
        text,
        flags=re.M | re.S,
    )
    assert match is not None, f"Missing section {number}"
    return normalized_prose(match.group(1))


def benchmark_section(name: str) -> str:
    number = "9.3" if name == "PRD.md" else "6.1"
    return numbered_section((BA / name).read_text(encoding="utf-8"), number, 3)


def section(text: str, heading: str) -> str:
    """Read one second-level section, without depending on its prose layout."""
    return text.split(heading, 1)[1].split("\n## ", 1)[0]


def metadata_value(document: str, identifier: str, field: str) -> str:
    """Read one metadata field from one story/use-case section."""
    text = (BA / document).read_text(encoding="utf-8")
    scoped = section(text, f"## {identifier}")
    for line in scoped.splitlines():
        if "metadata" in line.casefold():
            match = re.search(rf"\b{re.escape(field)}\s*:\s*(.+)$", line, re.I)
            if match:
                return re.sub(r"\s+", " ", re.sub(r"[*`]", "", match.group(1))).strip().casefold()
    table_match = re.search(
        rf"^\|\s*\*{{0,2}}{re.escape(field)}\*{{0,2}}\s*\|\s*(.+?)\s*\|$",
        scoped,
        re.M | re.I,
    )
    if table_match:
        return re.sub(r"\s+", " ", re.sub(r"[*`]", "", table_match.group(1))).strip().casefold()
    pytest.fail(f"{identifier} is missing the {field} field")


@pytest.mark.parametrize(
    ("document", "identifier", "phase"),
    [
        ("USER_STORIES.md", f"US-L06-{number:02d}", phase)
        for number, phase in (
            (1, "2"),
            (2, "2"),
            (3, "2"),
            (5, "3"),
            (6, "2"),
            (7, "3"),
            (8, "3"),
            (9, "2+"),
            (10, "2+"),
        )
    ]
    + [
        ("USE_CASES.md", f"UC-L06-{number:02d}", phase)
        for number, phase in ((1, "2"), (2, "2"), (3, "2"), (5, "3"), (6, "2"), (7, "3"), (8, "2+"), (9, "2+"))
    ],
)
def test_non_core_metadata_priority_is_explicitly_deferred(document: str, identifier: str, phase: str) -> None:
    priority = metadata_value(document, identifier, "Priority")
    assert re.search(rf"\bdeferred\s*\(\s*phase\s*{re.escape(phase)}\s*\)", priority)
    assert not re.search(r"^\s*(?:must|high)\b", priority)


def test_core_use_case_priority_remains_phase1_must() -> None:
    priority = metadata_value("USE_CASES.md", "UC-L06-04", "Priority")
    assert re.search(r"\bphase\s*1\b", priority)
    assert re.search(r"\bmust\b", priority)


def use_case_field(name: str) -> str:
    """Read the contract field, ignoring Markdown emphasis and capitalization."""
    text = (BA / "USE_CASES.md").read_text(encoding="utf-8")
    scoped = section(text, "## UC-L06-04:")
    for line in scoped.splitlines():
        cells = line.strip().strip("|").split("|", 1)
        if len(cells) == 2 and cells[0].strip(" *`").casefold() == name.casefold():
            return re.sub(r"\s+", " ", re.sub(r"[*`$]", "", cells[1])).casefold()
    pytest.fail(f"UC-L06-04 is missing the {name} field")


def markdown_anchors(text: str) -> set[str]:
    """Resolve the ATX heading anchors used by the repository's Markdown docs."""
    text = re.sub(r"^```[^\n]*\n.*?^```\s*$", "", text, flags=re.M | re.S)
    anchors: set[str] = set()
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", text, re.M):
        heading = MARKDOWN_LINK.sub(r"\1", heading)
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        candidate = slug
        suffix = 0
        while candidate in anchors:
            suffix += 1
            candidate = f"{slug}-{suffix}"
        anchors.add(candidate)
    return anchors


@pytest.mark.parametrize("name", ["PRD.md", "MVP.md"])
def test_concordance_requires_strictly_more_than_ninety_percent(name: str) -> None:
    text = normalized_prose((BA / name).read_text(encoding="utf-8"))
    assert not re.search(r"(?:>=|≥|\\ge)\s*90(?:\.0)?\s*\\?%", text)
    assert re.search(r">\s*90(?:\.0)?\s*\\?%", benchmark_section(name))


@pytest.mark.parametrize("name", ["PRD.md", "MVP.md"])
def test_benchmark_requires_fixed_gold_and_separate_reviewer_totals(name: str) -> None:
    text = benchmark_section(name)
    assert re.search(r"\b(?:fixed|frozen) gold decisions\b|\bgold decisions are (?:fixed|frozen)\b", text)
    assert re.search(r"\b(?:3|three) independent reviewers\b", text)
    assert re.search(
        r"\b(?:each|every) reviewer (?:completes|reviews|adjudicates) (?:all )?30 cases\b"
        r"[^.;]*\bmust match (?:at least|a minimum of) 28 (?:fixed |frozen )?gold decisions\b",
        text,
    )
    assert re.search(r"\b27\s*/\s*30\s+(?:fails|does not pass)\b", text)
    assert re.search(r"\b(?:three|3) reviewer totals (?:separately|individually)\b", text)
    assert re.search(r"\bpooled average (?:cannot|must not|may not) (?:hide|mask) a failing reviewer\b", text)
    assert re.search(r"\bincomplete benchmark (?:cannot|must not|may not) pass\b", text)
    assert re.search(r"\b100(?:\.0)?\s*%\s+guardrail adherence\b", text)


@pytest.mark.parametrize("name", ["PRD.md", "MVP.md"])
def test_release_scope_approval_keeps_operator_validation_pending(name: str) -> None:
    text = numbered_section((BA / name).read_text(encoding="utf-8"), "1", 2)
    # Adoption provenance is immutable evidence, not a presentation detail.
    clauses = re.split(r"[;|]|[.](?:\s|$)", text)
    assert any("adopted" in clause and "2026-09-30" in clause and "@datamonsterr" in clause for clause in clauses)
    assert re.search(r"approved[^;|.]*release scope|release scope[^;|.]*approved", text)
    assert re.search(r"\bcv-01\b[^;|.]*\bpending\b", text)
    assert re.search(r"\b(?:operator uat|operator validation)\b[^;|.]*\bpending\b", text)
    assert not re.search(r"\bdraft\s*/\s*validation\b", text)


@pytest.mark.parametrize(
    ("name", "identifier"),
    [
        ("USER_STORIES.md", "US-L06-09"),
        ("USER_STORIES.md", "US-L06-10"),
        ("USE_CASES.md", "UC-L06-08"),
        ("USE_CASES.md", "UC-L06-09"),
    ],
)
def test_driver_expansion_is_deferred_reference(name: str, identifier: str) -> None:
    text = (BA / name).read_text(encoding="utf-8")
    scoped = section(text, f"## {identifier}")
    assert "Deferred" in scoped
    assert "existing implementation" in scoped.lower()
    assert not re.search(r"Priority.*(?:Must|High)", scoped)


def test_v2_autonomy_is_explicitly_superseded_history() -> None:
    text = (BA / "DISCOVERY_POC_V2_DRIVER_AGENT.md").read_text(encoding="utf-8")
    assert "Superseded" in text and "2026-09-30" in text
    historical = section(text, "## 4.")
    assert "historical" in historical.lower()
    assert "superseded" in historical.lower()
    assert "586caec05ddb7626a1f47066b55154e74d245cc0" in text
    assert "MERGED" in text


@pytest.mark.parametrize("name", ["PRD.md", "MVP.md", "USER_STORIES.md", "USE_CASES.md"])
def test_dismissal_and_adverse_actions_need_authorized_analyst_rationale(name: str) -> None:
    text = (BA / name).read_text(encoding="utf-8").lower()
    assert "all dismissals" in text
    assert "authorized analyst" in text
    assert "written rationale" in text
    assert "warnings" in text


def test_initial_adjudication_system_error_is_advisory_signal() -> None:
    alternatives = use_case_field("Alternative Courses")
    system_error = alternatives.split("uc-l06-04.ac.1:", 1)[1].split("uc-l06-04.ac.2:", 1)[0]
    assert "system error" in system_error
    assert "advisory" in system_error
    assert re.search(r"disagree\s*\(\s*system error\s*\)", system_error)
    clauses = re.split(r"[;.]|<br\s*/?>", system_error)
    assert any(re.search(r"\b(?:must not|not)\b.*\b(?:block|apply)\b", clause) for clause in clauses), (
        f"System Error alternative must be advisory without blocking or applying outcome: {system_error}"
    )


def test_initial_adjudication_postconditions_require_confirmation_and_rationale() -> None:
    postconditions = use_case_field("Postconditions")
    requirements = re.split(r"[.]|<br\s*/?>", postconditions)
    universal = next(
        (
            clause
            for clause in requirements
            if re.search(r"\b(?:all|every) dismissals?\b", clause)
            and re.search(r"\b(?:agree/disagree|analyst|adverse sanctions?)\b", clause)
        ),
        "",
    )
    assert universal, "Postconditions must cover all dismissals and analyst Agree/Disagree outcomes"
    assert re.search(r"\brequir\w*\b|\bmust\b|\bmandatory\b", universal)
    assert re.search(r"\bauthori[sz]ed analyst\b.*\bconfirm\w*\b", universal)
    assert "written rationale" in universal
    assert re.search(r"(?:>=|≥|\\ge|at least)\s*10\s*characters\b", universal)


@pytest.mark.parametrize("name", OWNED_BA_DOCS)
def test_owned_ba_local_links_and_heading_anchors_resolve(name: str) -> None:
    document = BA / name
    for _, destination in MARKDOWN_LINK.findall(document.read_text(encoding="utf-8")):
        target = urlsplit(destination)
        if target.scheme or target.netloc:
            continue  # Remote links are deliberately outside this offline contract.
        path = (document.parent / unquote(target.path)).resolve() if target.path else document
        context = f"{document.relative_to(ROOT)}: {destination}"
        assert path.is_relative_to(ROOT), f"Local link escapes repository: {context}"
        assert path.is_file(), f"Missing local file: {context}"
        if target.fragment:
            assert path.suffix.lower() == ".md", f"Expected Markdown heading: {context}"
            assert unquote(target.fragment) in markdown_anchors(path.read_text(encoding="utf-8")), (
                f"Missing Markdown heading anchor: {context}"
            )


@pytest.mark.parametrize("name", ["PRD.md", "MVP.md"])
def test_classifier_confidence_is_advisory_and_uncalibrated_by_default(name: str) -> None:
    text = (BA / name).read_text(encoding="utf-8").lower()
    assert "[0,1]" in text.replace(" ", "")
    assert "score_semantics" in text and "uncalibrated_model_confidence" in text
    assert "not accuracy" in text and "guilt probability" in text
    assert "authorization" in text
    assert "held-out" in text and "version" in text


@pytest.mark.parametrize("name", ["PRD.md", "MVP.md"])
def test_top_k_route_alternatives_are_optional_pending_product_decision(name: str) -> None:
    text = (BA / name).read_text(encoding="utf-8").lower()
    assert "top-k route alternatives" in text
    assert re.search(r"optional.*pending.*scoped product decision", text)
    assert re.search(r"not.*must.*detector.*score metric", text)


def test_acceptance_matrix_covers_policy_and_links_real_impacted_tests() -> None:
    text = (BA / "PRD.md").read_text(encoding="utf-8")
    matrix = section(text, "## 10.")
    for acceptance_id in range(1, 10):
        assert f"AC-P1-{acceptance_id:02d}" in matrix
    assert "test_phase1_ba_docs.py" in matrix
    assert not re.search(r"#L\d", text)
    assert "obsolete" in matrix.lower() and "issues/73" in matrix
    assert "not run" in matrix.lower()
    test_links = re.findall(r"\[(test_\w+)\]\(([^)]+\.py)\)", matrix)
    assert len(test_links) >= 6
    for node, target in test_links:
        source = (BA / target).resolve()
        assert source.is_relative_to(ROOT) and source.is_file()
        tree = ast.parse(source.read_text(encoding="utf-8"))
        names = {
            definition.name
            for definition in ast.walk(tree)
            if isinstance(definition, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert node in names, f"{node} does not exist in {source.relative_to(ROOT)}"
