# ADR-014: Versioned grounded advisory reasoning and evaluation

## Status

Accepted for implementation and local fixture evaluation on 2026-10-03. Release acceptance remains separate.

## Context

[Issue #62](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/62) extends the existing offline forensic reasoning baseline and versioned policy lookup. PRD FR-06 and the Phase 1 ERR-02/ERR-05 scope govern the implementation. The user explicitly authorized bypassing the #64 dependency gate and subsequently authorized reuse of its branch artifacts. Neither instruction accepts #64's DoD or closes that issue.

The previous local draft cited hard-coded clause names, declared heuristic scores calibrated, and constructed benchmark inputs from suite names. Those claims cannot support grounded advisory reasoning.

## Decision

- Retrieve exact source text from the requested policy version and return structured citations. Missing sources, unknown versions and contradictory evidence cause abstention.
- Keep classification advisory. Scores express ordinal rule support, never violation probability or retrieval similarity. Do not assert calibration merely because a diagnostic was calculated.
- Freeze evaluation inputs and compare baseline and candidate on identical case IDs and inputs. Separate runtime evidence from evaluation labels. Unsupported corpus adapters remain explicitly `not_run`.
- Reuse the versioned #64 corpus and validators with their original provenance and pending SME status. Reuse does not establish independent review or production validity.

### Approved local acceptance thresholds

The user approved the following thresholds in this chat on 2026-10-03, before any tuning in this implementation session, with the explicit limitation **fixture/local only**:

| Metric | Threshold |
|---|---|
| Accuracy | >= 0.85 |
| ERR-02 F1 | >= 0.85 |
| ERR-05 F1 | >= 0.80 |
| no_violation F1 | >= 0.80 |
| insufficient_evidence F1 | >= 0.85 |
| Grounding errors | 0 |
| Schema validity | 100% |
| Automated sanctions | 0 |

No release certification, unseen-corpus claim, SME approval, or hosted acceptance follows from these thresholds. Existing development fixtures and previously exposed corpus records must be identified as such. Held-out results must not be used to tune the candidate.

## Topology, lifecycle and tool contracts

The standalone baseline retains strict Pydantic input/output contracts. A service owns versioned policy retrieval; the agent applies classification and abstention rules. The existing authorized runtime policy tool retrieves case-specific published database chunks. FastAPI, LangGraph graph structure, and SSE protocols remain as previously implemented; no new sanction tool or deferred driver flow is introduced.

Data flows from measured input to classification, version-scoped retrieval and exact citations, then to advisory JSON. Evaluation labels are consumed only after both models receive identical runtime input. Retrieval failure leaves the core analyst workflow available and causes advisory abstention.

## Rationale and alternatives

Source-backed extraction is auditable and works without fabricating handbook text. Unversioned search risks mixing policies. Hard-coded legal clause names lack source evidence. Fixed heuristic scores cannot establish calibrated probabilities; diagnostic calibration metrics must retain that boundary.

## Security and consequences

Strict input validation rejects unknown evaluation metadata and non-finite numbers. Existing runtime authorization remains enforced. No secrets, database migrations, punitive writes or external model traffic are required for fixture verification. Independent SME review, approved production policy documents and environment-specific acceptance remain outstanding evidence requirements.
