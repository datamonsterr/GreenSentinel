---
name: research-report
description: Author concise executive research reports and methodology comparisons. Combines literature survey findings, dataset profile, standardized benchmark results, and production feasibility for project GreenSentinel into a structured technical report with templates. Use when summarizing paper research, presenting benchmark evaluations, proposing architecture decisions (ADR), or finalizing research sprints.
argument-hint: [topic] [output-file]
---

# Research Report Skill

Author concise, evidence-backed research synthesis reports for GreenSentinel (VinUni AI20K Build Phase).

## Core Principles
1. **Executive First**: Begin with the decision, recommended method, and quantified trade-off (F1 vs Latency vs Cost).
2. **Deterministic Citations**: Every candidate paper must include title, authors, publication venue/year, arXiv/DOI link, and implementation repo link.
3. **Unified Benchmark Leaderboard**: Must embed the standardized benchmark table comparing all evaluated candidates on the same test split.
4. **Production Feasibility**: Explicitly score feasibility against GreenSentinel constraints:
   - GreenSM ride-hailing GPS trajectory anomaly detection (DAVI, SSD)
   - FastAPI async service latency SLA (< 50ms p95)
   - Real-time vs batch processing trade-offs.

---

## Standard Report Template

Use the following Markdown structure when authoring a report under `docs/research/` or `docs/worklog/`:

```markdown
# Research Report: [Topic / Technique Name]

**Date:** YYYY-MM-DD  
**Status:** [PROPOSED | VALIDATED | REJECTED]  
**Author / Subagent:** [Agent Name]  
**Primary Recommendation:** [Selected Winner Method]  

---

## 1. Executive Summary
- **Objective:** What problem was investigated? (e.g. Real-time GPS detour fraud detection).
- **Key Finding:** Which paper/method performed best and why?
- **Trade-off Decision:** High-level summary of accuracy vs inference latency vs implementation complexity.

---

## 2. Problem Framing & GreenSentinel Constraints
- **Use Case:** [e.g., GreenSM customer dispute & abnormal detour detection]
- **Target Metrics:** F1-score >= 0.85, Inference latency <= 15ms (p95), RAM <= 100MB.
- **Data Modality:** GPS coordinates, speed, bearing, OSRM distance ratios, customer dispute text.

---

## 3. Literature Candidates Evaluated

| # | Paper Title | Venue / Year | Key Idea | Code Repo / Status |
|---|-------------|--------------|----------|--------------------|
| 1 | [Paper Name](https://arxiv.org/abs/...) | KDD 2024 | Graph temporal convolutions on trajectories | [GitHub](https://github.com/...) (Active) |
| 2 | [Paper Name](https://arxiv.org/abs/...) | NeurIPS 2023 | Contrastive learning on sub-trajectories | [GitHub](https://github.com/...) (Reproduced) |
| 3 | [Baseline] | Baseline | Z-score & spatial buffer heuristics | Native implementation |

---

## 4. Benchmark Leaderboard

Evaluated on: `data/benchmark/test_split.parquet` (N = 10,000 samples, locked seed 42).

| Rank | Method | F1-Score | ROC-AUC | Precision | Recall | Latency p50 | Latency p95 | RAM (MB) | Throughput |
|------|--------|----------|---------|-----------|--------|-------------|-------------|----------|------------|
| 1 | **[Method A]** | 0.912 | 0.963 | 0.920 | 0.904 | 0.85 ms | 1.90 ms | 18.4 MB | 11,760 qps |
| 2 | **[Method B]** | 0.882 | 0.941 | 0.891 | 0.874 | 1.20 ms | 2.85 ms | 34.2 MB | 6,890 qps |
| 3 | **[Baseline]** | 0.761 | 0.812 | 0.730 | 0.795 | 0.12 ms | 0.25 ms | 4.1 MB | 83,330 qps |

---

## 5. Application to GreenSentinel Architecture
- **Inference Integration:** How does this fit into `services/` and `api/`?
- **FastAPI Endpoint Impact:** Does it meet the async loop requirements?
- **Data Pipeline Integration:** How are GPS features extracted before model invocation?

---

## 6. Next Steps & Decision
- [ ] Log Architectural Decision Record: `docs/architecture/adr-NNN-[method].md`
- [ ] Create implementation branch via `using-git-worktrees`
- [ ] Implement production service with test coverage (`pytest-coverage`)
```
