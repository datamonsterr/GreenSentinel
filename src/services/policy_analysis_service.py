"""Policy analysis agent (PRD-K, ADR-033): policy document -> cited candidate knowledge -> proposals.

Pipeline: chunk text -> LLM extraction (pydantic-validated JSON) -> drop items whose citation is not a
verbatim substring of the document -> reuse/extend/new against *published* kb objects via the
similarity scorer -> `create_proposal(source="policy_analysis")`. Nothing is ever published here.
Fallback when the LLM is unavailable or returns garbage: no proposals, document marked `failed`.
"""

from __future__ import annotations

import io
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError

from src.services.kb_service import AUTHOR_ROLES, KbService, _strings
from src.services.llm import get_llm

ANALYSIS_MODEL = "z-ai/glm-5.3-flash"
INSTRUCTION_VERSION = "policy-analysis@1.0.0"
CANDIDATE_TYPES = ("parameter", "motive", "behavior")
REUSE_AT = 0.85  # score at/above which a published object is simply reused
MAX_CHUNKS = 12
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

SYSTEM_PROMPT = (
    "You extract candidate knowledge objects from a ride-hailing fraud policy document.\n"
    "Return ONLY JSON: {\"items\": [{\"type\": \"parameter|motive|behavior\", \"code\": \"UPPER_SNAKE\", "
    "\"name\": \"short Vietnamese name\", \"citation\": \"EXACT verbatim quote copied from the text\", "
    "\"body\": {...}}]}.\n"
    "body for parameter: {\"unit\", \"source\"}; motive: {\"beneficiary\": \"driver\", \"policy\", \"formula\": \"=...\"}; "
    "behavior: {\"description\", \"signals\": [], \"condition\": \"=...\"}.\n"
    "The citation MUST be copied character for character from the text. Never invent penalties, fines or "
    "enforcement actions. If nothing applies return {\"items\": []}."
)


class Candidate(BaseModel):
    type: Literal["parameter", "motive", "behavior"]
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=1)
    citation: str = Field(min_length=3)
    body: dict[str, Any] = Field(default_factory=dict)


class Extraction(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)


Extractor = Callable[[str, dict[str, Any]], str]


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ---- text extraction / chunking -----------------------------------------------------------------
def extract_text(filename: str, content: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith((".txt", ".md", ".csv", ".json")):
        return content.decode("utf-8", errors="replace")
    if name.endswith(".docx"):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                if z.getinfo("word/document.xml").file_size > 50_000_000:  # zip-bomb guard
                    raise ValueError("document.xml too large")
                root = ET.fromstring(z.read("word/document.xml"))
        except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
            raise ValueError(f"Cannot read docx: {e}") from e
        paras = ["".join(t.text or "" for t in p.iter(f"{_W}t")) for p in root.iter(f"{_W}p")]
        return "\n\n".join(p for p in paras if p.strip())
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader  # optional dependency, not installed by default
        except ImportError as e:
            raise ValueError("PDF text extraction is unavailable (pypdf not installed); paste the text instead") from e
        return "\n\n".join((pg.extract_text() or "") for pg in PdfReader(io.BytesIO(content)).pages)
    raise ValueError(f"Unsupported file type: {filename}")


def chunk_text(text: str, max_chars: int = 3500) -> list[str]:
    """Paragraph-packed chunks; every chunk is a verbatim slice-compatible piece of the source."""
    paras = [p for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    chunks: list[str] = []
    cur = ""
    for p in paras:
        while len(p) > max_chars:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(p[:max_chars])
            p = p[max_chars:]
        if cur and len(cur) + 2 + len(p) > max_chars:
            chunks.append(cur)
            cur = p
        else:
            cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        chunks.append(cur)
    return chunks


def _parse(raw: str) -> list[dict[str, Any]]:
    s = (raw or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL)
    if m:
        s = m.group(1).strip()
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        i, j = s.find("{"), s.rfind("}")
        if i < 0 or j <= i:
            raise ValueError("LLM reply is not valid JSON") from None
        data = json.loads(s[i:j + 1])
    try:
        return Extraction.model_validate(data).items
    except ValidationError as e:
        raise ValueError(f"LLM reply does not match the schema: {e.errors()[0]['msg']}") from e


def _llm_extractor(chunk: str, doc: dict[str, Any]) -> str:
    llm = get_llm(provider="openrouter", model=ANALYSIS_MODEL, temperature=0)
    msg = llm.invoke([("system", SYSTEM_PROMPT), ("human", f"Document: {doc.get('name')} ({doc.get('code')})\n\nTEXT:\n{chunk}")])
    content = msg.content
    return content if isinstance(content, str) else json.dumps(content)


class PolicyAnalysisService:
    def __init__(self, kb: KbService, extractor: Extractor | None = None, config: Any = None):
        self.kb = kb
        self.extractor = extractor or _llm_extractor
        self.config = config

    def _threshold(self, org: str) -> float:
        if self.config is None:
            from src.services.agent_config_service import AgentConfigService
            self.config = AgentConfigService(self.kb.store)
        return float(self.config.similarity_threshold(org))

    def _map(self, org: str, c: Candidate, threshold: float, cache: dict[str, list[tuple[str, str]]]) -> tuple[str, float | None, str | None]:
        if c.type not in cache:
            cache[c.type] = [(o["code"], f"{o['name']} {' '.join(_strings(o['body']))}") for o in self.kb.list_published(org, c.type)]
        ranked = self.kb.scorer.rank(f"{c.name} {' '.join(_strings(c.body))}", cache[c.type], limit=1)
        if not ranked or ranked[0][1] < threshold:
            return "new", (ranked[0][1] if ranked else None), None
        code, score = ranked[0]
        return ("reuse" if score >= max(threshold, REUSE_AT) else "extend"), score, code

    def _finish(self, doc_id: str, status: str, counts: dict[str, Any], error: str | None, actor_id: str) -> dict[str, Any]:
        row = self.kb.store.update("kb_policy_document", doc_id, {
            "analysis_status": status, "analysis_error": error, "analysis_counts": counts,
            "analyzed_at": _now(), "analyzed_by": actor_id})
        self.kb.store.audit(row["organization_id"], actor_id, "kb.document.analyze",
                            {"document_id": doc_id, "status": status, "counts": counts}, "accepted" if status == "done" else "failed")
        return row

    def analyze(self, actor: Any, document_id: str) -> dict[str, Any]:
        self.kb._require(actor, AUTHOR_ROLES)
        store = self.kb.store
        doc = store.get("kb_policy_document", document_id)
        if not doc or str(doc["organization_id"]) != str(actor.organization_id):
            raise HTTPException(404, "Document not found")
        if doc.get("analysis_status") == "running":
            raise HTTPException(409, "Analysis already running")
        store.update("kb_policy_document", doc["id"], {"analysis_status": "running", "analysis_error": None})
        counts: dict[str, Any] = {"chunks": 0, "candidates": 0, "rejected_citation": 0, "rejected_schema": 0,
                                  "duplicates": 0, "proposals": 0, "reuse": 0, "extend": 0, "new": 0}
        try:
            text = doc.get("text_excerpt") or ""
            if not text.strip():
                return self._finish(doc["id"], "failed", counts, "Document has no extractable text; paste the text or upload txt/md/docx.", actor.id)
            all_chunks = chunk_text(text)
            chunks = all_chunks[:MAX_CHUNKS]
            counts["chunks"] = len(chunks)
            counts["chunks_total"] = len(all_chunks)
            counts["truncated"] = len(all_chunks) > MAX_CHUNKS
            raw_items: list[dict[str, Any]] = []
            errors: list[str] = []
            for ch in chunks:
                try:
                    raw_items += _parse(self.extractor(ch, doc))
                except Exception as e:  # noqa: BLE001 - LLM/network/parse failures degrade to a failed status
                    errors.append(str(e) or e.__class__.__name__)
            if errors and len(errors) == len(chunks):
                return self._finish(doc["id"], "failed", counts, errors[0][:500], actor.id)
            if errors:
                counts["chunk_errors"] = len(errors)

            org = actor.organization_id
            threshold = self._threshold(org)
            cache: dict[str, list[tuple[str, str]]] = {}
            ref = f"doc:{doc['code']}"
            existing = {(p["type"], p["title"]) for p in store.find("kb_proposal", {"organization_id": org, "source_ref": ref, "status": "pending"})}
            seen: set[tuple[str, str]] = set()
            for item in raw_items:
                try:
                    c = Candidate.model_validate(item)
                except ValidationError:
                    counts["rejected_schema"] += 1
                    continue
                counts["candidates"] += 1
                if c.citation not in text:
                    counts["rejected_citation"] += 1
                    continue
                key = (c.type, c.name)
                if key in existing or key in seen:
                    counts["duplicates"] += 1
                    continue
                seen.add(key)
                mapping, score, matched = self._map(org, c, threshold, cache)
                self.kb.create_proposal(
                    org, source="policy_analysis", type=c.type, title=c.name,
                    payload={"code": c.code, "name": c.name, "scope": {k: doc[k] for k in ("region", "service", "contract_type") if doc.get(k)},
                             "body": c.body},
                    source_excerpt=c.citation, source_ref=ref, mapping=mapping, similarity=score, matched_code=matched,
                    created_by=f"agent:{INSTRUCTION_VERSION}")
                counts["proposals"] += 1
                counts[mapping] += 1
            return self._finish(doc["id"], "done", counts, None, actor.id)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            return self._finish(doc["id"], "failed", counts, str(e)[:500] or e.__class__.__name__, actor.id)
