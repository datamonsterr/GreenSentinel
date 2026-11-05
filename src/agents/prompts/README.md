# GreenSM Copilot System Prompts Repository

This directory contains version-controlled system prompt templates and specifications for the GreenSM Sentinel Copilot agents.

## Canonical Files

- [`fraud_analyst_system_prompt.md`](fraud_analyst_system_prompt.md): Active system prompt (`v1.3.0-traffic-corroboration`) enforcing Prior Evidence First, external traffic corroboration, and Human-in-the-Loop adjudication.

## Versioning & Architecture

- **Active Version Constant:** `SYSTEM_PROMPT_VERSION = "v1.3.0-traffic-corroboration"` in [`src/agents/graph.py`](../graph.py).
- **Single Source of Truth:** `load_system_prompt()` in `src/agents/graph.py` reads `fraud_analyst_system_prompt.md` at runtime, eliminating hardcoded duplicated strings.
- **Traceability:** Model assessments in PostgreSQL record `prompt_version` corresponding to this semantic tag.

## Verification & Execution Commands

```bash
# Evaluate prompt & core reasoning baseline against synthetic golden set
python -m eval.reasoning_baseline

# Run targeted prompt and contract tests
pytest tests/test_agents/test_graph.py tests/test_agents/test_forensic_baseline.py -v
```
