import io
import json
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.services.agent_config_service import AgentConfigService
from src.services.kb_service import KbService
from src.services.kb_store import MemoryStore
from src.services.policy_analysis_service import PolicyAnalysisService, chunk_text, extract_text

ORG = "org-1"
ANALYST = SimpleNamespace(id="u-a", organization_id=ORG, roles=frozenset({"fraud_analyst"}))
DRIVER = SimpleNamespace(id="u-d", organization_id=ORG, roles=frozenset({"driver"}))
OTHER_ORG = SimpleNamespace(id="u-x", organization_id="org-2", roles=frozenset({"admin"}))

TEXT = (
    "Điều 1. Tài xế hoàn thành 10 chuyến trong ngày được thưởng mốc 200000 đồng.\n\n"
    "Điều 2. Chuyến đi mà xe đứng yên quá 300 giây bị xem là bất thường."
)
C1 = "hoàn thành 10 chuyến trong ngày được thưởng mốc 200000 đồng"
C2 = "xe đứng yên quá 300 giây"


def cand(type_, code, name, citation, body=None):
    return {"type": type_, "code": code, "name": name, "citation": citation, "body": body or {}}


@pytest.fixture()
def setup():
    store = MemoryStore()
    kb = KbService(store)
    doc = kb.create_document(ANALYST, name="Chính sách", code="DOC-1", text=TEXT)
    return store, kb, doc


def svc(kb, reply, config=None):
    def extractor(chunk, doc):
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, str) else json.dumps(reply)

    return PolicyAnalysisService(kb, extractor=extractor, config=config)


def publish(kb, store, type_, code, name, body):
    o = kb.create_object(ANALYST, type=type_, code=code, name=name, body=body)
    store.update("kb_object", o["id"], {"status": "published"})


def test_happy_path_creates_proposals_never_publishes(setup):
    store, kb, doc = setup
    reply = {"items": [
        cand("motive", "MOT_MILESTONE", "Thưởng mốc chuyến", C1, {"formula": "=1"}),
        cand("behavior", "BHV_STILL", "Xe đứng yên lâu", C2, {"condition": "=stationary_duration_s>=300"}),
    ]}
    out = svc(kb, reply).analyze(ANALYST, doc["id"])
    assert out["analysis_status"] == "done"
    assert out["analysis_counts"]["proposals"] == 2
    props = kb.list_proposals(ANALYST)
    assert {p["source"] for p in props} == {"policy_analysis"}
    assert all(p["status"] == "pending" and p["source_ref"] == "doc:DOC-1" for p in props)
    assert {p["source_excerpt"] for p in props} == {C1, C2}
    assert store.find("kb_object", {"organization_id": ORG}) == []


def test_citation_not_verbatim_rejected(setup):
    store, kb, doc = setup
    reply = {"items": [cand("motive", "M1", "x", "câu trích dẫn bịa đặt không có trong văn bản"),
                       cand("motive", "M2", "y", C1)]}
    out = svc(kb, reply).analyze(ANALYST, doc["id"])
    assert out["analysis_counts"]["rejected_citation"] == 1
    assert out["analysis_counts"]["proposals"] == 1


def test_mapping_reuse_extend_new(setup):
    store, kb, doc = setup
    publish(kb, store, "motive", "MOT_MILESTONE", "Thưởng mốc chuyến", {"formula": "=1", "policy": "thưởng mốc chuyến trong ngày"})
    publish(kb, store, "behavior", "BHV_X", "Xe đứng yên lâu trong cuốc", {"condition": "=stationary_duration_s>=1", "signals": []})
    reply = {"items": [
        cand("motive", "MOT_NEW1", "Thưởng mốc chuyến", C1, {"formula": "=1", "policy": "thưởng mốc chuyến trong ngày"}),
        cand("behavior", "BHV_NEW", "Xe đứng yên lâu trong cuốc kéo dài bất thường", C2, {"condition": "=stationary_duration_s>=1", "signals": []}),
        cand("parameter", "P_UNIQ", "Zzz qqq", C1, {"unit": "vnd", "source": "doc"}),
    ]}
    svc(kb, reply).analyze(ANALYST, doc["id"])
    by = {p["type"]: p for p in kb.list_proposals(ANALYST)}
    assert by["parameter"]["mapping"] == "new" and by["parameter"]["matched_code"] is None
    assert by["motive"]["mapping"] == "reuse" and by["motive"]["matched_code"] == "MOT_MILESTONE"
    assert by["behavior"]["mapping"] == "extend" and by["behavior"]["matched_code"] == "BHV_X"
    assert 0 < float(by["behavior"]["similarity"]) < 1


def test_threshold_from_config(setup):
    store, kb, doc = setup
    publish(kb, store, "behavior", "BHV_X", "Xe đứng yên lâu trong cuốc", {"condition": "=stationary_duration_s>=1", "signals": []})
    reply = {"items": [cand("behavior", "BHV_NEW", "Xe đứng yên lâu trong cuốc kéo dài bất thường", C2, {"condition": "=stationary_duration_s>=1", "signals": []})]}
    cfg = AgentConfigService(store)
    cfg.similarity_threshold = lambda org, scope="global": 0.99  # type: ignore[method-assign]
    svc(kb, reply, config=cfg).analyze(ANALYST, doc["id"])
    p = kb.list_proposals(ANALYST)[0]
    assert p["mapping"] == "new"


def test_llm_failure_marks_failed_no_proposals(setup):
    store, kb, doc = setup
    out = svc(kb, RuntimeError("openrouter down")).analyze(ANALYST, doc["id"])
    assert out["analysis_status"] == "failed"
    assert "openrouter down" in out["analysis_error"]
    assert kb.list_proposals(ANALYST) == []


def test_invalid_json_failed(setup):
    store, kb, doc = setup
    out = svc(kb, "not json at all").analyze(ANALYST, doc["id"])
    assert out["analysis_status"] == "failed"


def test_json_in_code_fence_ok_and_bad_items_dropped(setup):
    store, kb, doc = setup
    raw = "```json\n" + json.dumps({"items": [cand("motive", "M1", "ok", C1), {"type": "bogus", "citation": C2}]}) + "\n```"
    out = svc(kb, raw).analyze(ANALYST, doc["id"])
    assert out["analysis_status"] == "done" and out["analysis_counts"]["proposals"] == 1


def test_not_configured_fallback(setup, monkeypatch):
    store, kb, doc = setup

    def boom(*a, **k):
        raise RuntimeError("openrouter LLM credentials are not configured")

    monkeypatch.setattr("src.services.policy_analysis_service.get_llm", boom)
    out = PolicyAnalysisService(kb).analyze(ANALYST, doc["id"])
    assert out["analysis_status"] == "failed" and "credentials" in out["analysis_error"]


def test_rerun_does_not_duplicate_pending(setup):
    store, kb, doc = setup
    s = svc(kb, {"items": [cand("motive", "M1", "ok", C1)]})
    s.analyze(ANALYST, doc["id"])
    out = s.analyze(ANALYST, doc["id"])
    assert len(kb.list_proposals(ANALYST)) == 1 and out["analysis_counts"]["duplicates"] == 1


def test_gates_and_empty_text(setup):
    store, kb, doc = setup
    s = svc(kb, {"items": []})
    with pytest.raises(HTTPException) as e:
        s.analyze(DRIVER, doc["id"])
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        s.analyze(OTHER_ORG, doc["id"])
    assert e.value.status_code == 404
    d2 = kb.create_document(ANALYST, name="n", code="F", filename="a.pdf")
    out = s.analyze(ANALYST, d2["id"])
    assert out["analysis_status"] == "failed" and out["analysis_error"]


def test_running_conflict(setup):
    store, kb, doc = setup
    store.update("kb_policy_document", doc["id"], {"analysis_status": "running"})
    with pytest.raises(HTTPException) as e:
        svc(kb, {"items": []}).analyze(ANALYST, doc["id"])
    assert e.value.status_code == 409


def test_chunking():
    text = "\n\n".join(f"Đoạn {i} " + "x" * 100 for i in range(10))
    chunks = chunk_text(text, max_chars=250)
    assert len(chunks) > 1 and all(len(c) <= 250 for c in chunks)
    assert chunk_text("") == []


def test_extract_text_txt_and_docx():
    assert extract_text("a.md", "Xin chào".encode()) == "Xin chào"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml",
                   '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                   "<w:p><w:r><w:t>Điều 1</w:t></w:r></w:p><w:p><w:r><w:t>Nội dung</w:t></w:r></w:p></w:body></w:document>")
    assert extract_text("a.docx", buf.getvalue()) == "Điều 1\n\nNội dung"
    with pytest.raises(ValueError):
        extract_text("a.xlsx", b"x")


def test_document_over_chunk_cap_is_marked_truncated(setup):
    from src.services import policy_analysis_service as pas

    store, kb, _ = setup
    long_text = "\n\n".join(f"Điều {i}. " + ("nội dung chính sách " * 60) for i in range(60))
    doc = kb.create_document(ANALYST, name="Dài", code="DOC-LONG", text=long_text)
    total = len(chunk_text(long_text))
    assert total > pas.MAX_CHUNKS
    out = svc(kb, {"items": []}).analyze(ANALYST, doc["id"])
    counts = out["analysis_counts"]
    assert counts["chunks"] == pas.MAX_CHUNKS and counts["truncated"] is True and counts["chunks_total"] == total


def test_short_document_is_not_truncated(setup):
    _, kb, doc = setup
    counts = svc(kb, {"items": []}).analyze(ANALYST, doc["id"])["analysis_counts"]
    assert counts["truncated"] is False and counts["chunks_total"] == counts["chunks"]
