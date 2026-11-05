---
description: "AI usage logging is fully automatic — do NOT call any log_* script manually"
activation: always-on
---

# AI Usage Logging — Automatic

Logging prompts into `.ai-log/session.jsonl` is **fully automated**. You (the AI agent) do **NOT** need to — and should **NOT** — run any manual logging commands after completing tasks.

## Mechanism

**During coding sessions**:
Antigravity executes hooks configured in `.agents/hooks.json`. The `PreInvocation` hook invokes `scripts/log_antigravity.py --hook` for each user prompt turn. Antigravity delivers the conversation `transcriptPath` via stdin, and the script appends any unlogged prompts (`USER_INPUT` + `USER_EXPLICIT`) directly to `.ai-log/session.jsonl`.

**During `git push`**:
1. The git pre-push hook runs `scripts/log_antigravity.py --auto` to sweep recent transcripts across `~/.gemini/antigravity-cli/brain` and `~/.gemini/antigravity-ide/brain`. This provides a safety net ensuring final prompts are captured.
2. The pre-push hook runs `scripts/submit_log.py`, uploading `.ai-log/session.jsonl` to the Phoenix grading server.

Duplicate entries are eliminated using unique `entry_id` hashes.

## Prohibited Actions

- ❌ **DO NOT** execute `scripts/log_antigravity.py "<summary>" "<model>"` after tasks. This legacy command format creates artificial entries.
- ❌ **DO NOT** execute `scripts/log_manual.py` for Antigravity, OpenCode, Claude Code, or Codex — those are handled automatically.
- ❌ **DO NOT** delete or manually edit files inside `.ai-log/`.

## When Intervention is Needed

- If the git pre-push hook reports an error, inform the user rather than bypassing with `--no-verify`.
- If using an unsupported web tool (e.g. ChatGPT web), refer the user to `.agents/workflows/log.md` to log manually.

## One-Time Setup

```bash
# Linux / macOS / Git Bash
bash scripts/setup_hooks.sh

# Windows PowerShell
powershell -ExecutionPolicy Bypass -File scripts\setup_hooks.ps1
```
