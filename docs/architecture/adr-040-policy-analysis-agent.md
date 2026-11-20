# ADR-040: Policy analysis agent

Status: Accepted · Scope: `POST /knowledge/documents/{id}/analyze`, `src/services/policy_analysis_service.py`, `app.kb_policy_document.analysis_*` (PRD-K US1, slice S-P). Builds on [ADR-032](adr-032-knowledge-base-roles-and-lifecycle.md).

## Context

Analysts upload policy text (ADR-032) but turning it into motives, behaviours and parameters was manual. Policy text is untrusted data and an LLM can invent rules, so every extracted item must be traceable to the document and reviewed by a human.

## Decision

1. **Pipeline** (service tier, no SQL): chunk text (paragraph packed, 3500 chars, max 12 chunks) -> LLM extraction (OpenRouter `z-ai/glm-5.3-flash` through `get_llm`, temperature 0) -> pydantic `Candidate` validation (`parameter|motive|behavior`, code, name, citation, body) -> **drop any item whose `citation` is not a verbatim substring of the document text** -> map against *published* `kb_object` rows of the same type with `default_scorer()` (token-overlap Jaccard; embeddings stay `embeddings_not_configured`) -> `KbService.create_proposal`.
2. **Mapping**: best score `< similarity_threshold` (agent config, default 0.6) = `new`; `>= max(threshold, 0.85)` = `reuse`; otherwise `extend`. `similarity` and `matched_code` are stored on the proposal.
3. **Never auto-publish**: only `kb_proposal` rows (`source=policy_analysis`, `source_ref=doc:<code>`, `source_excerpt`=citation, status `pending`). Accept/edit lands in `ready_for_test` via the existing queue; publish keeps the 4-eyes gate. The DB check constraint value is `policy_analysis` (ADR-032), not `policy_document`.
4. **Fallback**: missing credentials, network error, invalid JSON or no text = zero proposals, document `analysis_status=failed` with `analysis_error`. Partial chunk failures still produce proposals from good chunks (`chunk_errors` count). Re-runs skip a pending proposal with the same type+title (`duplicates`).
5. **Status on the document** (migration `20261120130000_policy_analysis.sql`, additive/idempotent): `analysis_status` (`pending|running|done|failed`), `analysis_error`, `analysis_counts` jsonb (chunks, candidates, proposals, reuse/extend/new, rejected_citation, rejected_schema, duplicates), `analyzed_at`, `analyzed_by`. A concurrent run returns 409. Each run writes audit `kb.document.analyze`.
6. **Gate**: analyst family and admin (ADR-032 `AUTHOR_ROLES`); organisation scoped. Run is synchronous in the request (bounded by chunk cap).
7. **Text extraction** (installed deps only): txt/md/csv/json decode, docx via `zipfile` + XML, pdf only if `pypdf` is importable (otherwise 422 "paste the text"). The upload route accepts optional `content_base64` and extracts server-side into `text_excerpt`.

## Consequences

Zero hallucinated rules reach the queue without a quote that exists in the source. Token similarity is a weak reuse signal until embeddings exist; humans decide on every item. No async job: very large documents are truncated to 12 chunks.

## Rejected

Auto-publish on high similarity; trusting LLM citations without substring check; a separate `policy_analysis_run` table (YAGNI: last run only on the document).


## Decision (2026-11-20): Synchronous run, truncation visible, PDF stays unsupported

- Analysis stays synchronous inside the request. Documents are capped at `MAX_CHUNKS = 12` chunks; `analysis_counts` now records `chunks_total` and `truncated` (true when the cap dropped chunks). The documents panel shows "Đã cắt bớt / Truncated (x/y chunks)" so the analyst knows the tail was not analysed.
- PDF upload stays rejected with 422 (no new dependency); paste text or upload txt/md/docx.
