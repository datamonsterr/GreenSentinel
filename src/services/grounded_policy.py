"""Version-scoped extractive policy retrieval; no unsupported policy generation."""

import re
from collections.abc import Iterable

from src.models.policy import PolicyCitation, PolicySource


class PolicyRepository:
    def __init__(self, sources: Iterable[PolicySource] = ()) -> None:
        self._sources = tuple(PolicySource.model_validate(s) for s in sources)

    def retrieve(self, version: str, topic: str | None = None) -> list[PolicyCitation]:
        rows = [s for s in self._sources if s.version == version]
        if topic:
            key = topic.casefold()
            rows = [s for s in rows if key in s.id.casefold() or key in s.text.casefold()]
        unique = {tuple(sorted(row.model_dump().items())): row for row in rows}
        return [
            PolicyCitation.model_validate(row.model_dump())
            for row in sorted(unique.values(), key=lambda row: (row.source, row.section, row.id, row.text))
        ]

    @staticmethod
    def has_conflict(rows: list[PolicyCitation]) -> bool:
        groups: dict[tuple[str, str, str], set[str]] = {}
        for row in rows:
            groups.setdefault((row.source, row.section, row.id), set()).add(row.text)
        return any(len(texts) > 1 for texts in groups.values())

    def resolve(self, version: str, topic: str | None) -> tuple[list[PolicyCitation], str | None]:
        # Check the complete version: querying one topic must not hide a conflicting record.
        all_rows = self.retrieve(version)
        if self.has_conflict(all_rows):
            return [], "Conflicting policy records in requested version."
        rows = self.retrieve(version, topic)
        if not rows:
            return [], "No policy text matches requested topic and version."
        return rows, None


def answer_policy_question(
    question: str, repository: PolicyRepository, version: str, *, contradictory_evidence: bool = False
) -> dict[str, object]:
    """Return relevant exact text; absence and explicit evidence conflicts abstain."""

    def abstain(reason: str) -> dict[str, object]:
        return {"answer": None, "citations": [], "policy_version": None, "abstained": True, "rationale": reason}

    if not question.strip() or not version.strip():
        return abstain("Missing question or policy version.")
    if contradictory_evidence:
        return abstain("Contradictory evidence requires analyst review.")
    rows, error = repository.resolve(version, None)
    if error:
        return abstain(error)
    stopwords = {"the", "and", "are", "for", "what", "does", "with", "this", "that"}
    words = {
        word.casefold()
        for word in re.findall(r"[\w-]+", question)
        if len(word) > 2 and word.casefold() not in stopwords
    }
    citations = [
        row
        for row in rows
        if words.intersection(word.casefold() for word in re.findall(r"[\w-]+", row.text + " " + row.id))
    ]
    if not citations:
        return abstain("No relevant policy text in requested version.")
    return {
        "answer": "\n".join(row.text for row in citations),
        "citations": [row.model_dump() for row in citations],
        "policy_version": version,
        "abstained": False,
        "rationale": None,
    }


def ask_policy(
    question: str, version: str, repository: PolicyRepository, *, contradictory_evidence: bool = False
) -> dict[str, object]:
    return answer_policy_question(question, repository, version, contradictory_evidence=contradictory_evidence)
