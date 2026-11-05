# AI Usage Logging & Audit Trail Guide

## Overview

The VinUni AI20K Build Phase requires continuous logging of AI agent prompts and assistant interactions for grading and verification.

## Supported AI Tools & Hooks

| Tool | Hook Configuration | Trigger Event |
|---|---|---|
| **Antigravity CLI** | `.agents/hooks.json` | `PreInvocation` (per turn) + pre-push transcript sweep |
| **OpenCode** | `.opencode/plugins/ai-log.js` | `chat.message` hook |
| **Claude Code** | `.claude/settings.json` | `UserPromptSubmit` hook |
| **OpenAI Codex** | `.codex/hooks.json` | `UserPromptSubmit` & `Stop` hooks |
| **Cursor** | `.cursor/hooks.json` | Before/after agent invocation |

## Manual Logging

If using web interfaces (ChatGPT, Claude web):

```bash
bash scripts/_pyrun.sh scripts/log_manual.py --tool chatgpt --prompt "Your prompt here"
```

## Grading Server Submission

Logs stored in `.ai-log/session.jsonl` are submitted automatically during `git push` via the pre-push hook:

```bash
bash scripts/setup_hooks.sh
```

Ensure your `.env` contains:
```env
AI_LOG_SERVER=https://phoenix.note.transformerlabs.ai/api/v1/log
AI_LOG_API_KEY=<your-team-api-key>
```
