---
description: "Manual AI usage logger — ONLY for web tools (ChatGPT, Gemini Web, Claude.ai, etc.). NOT needed for Antigravity, OpenCode, Claude Code, or Codex."
---

# Manual AI Usage Logging (Web Tools Only)

Antigravity CLI, OpenCode, Claude Code, Cursor, Codex, Copilot, and Gemini CLI are **automatically logged** via lifecycle hooks or `log_antigravity.py` during `git push`. **Do NOT** run the command below for those tools.

This workflow is strictly reserved for **unhooked web interfaces** — such as ChatGPT, Gemini Web, Claude.ai, Perplexity, etc.

## Usage

**Linux / macOS / Git Bash:**
```bash
# Interactive mode (prompts for tool and query)
bash scripts/_pyrun.sh scripts/log_manual.py

# Single command mode
bash scripts/_pyrun.sh scripts/log_manual.py --tool "<tool-name>" --prompt "<prompt text>"
```

**Windows (cmd.exe / PowerShell):**
```cmd
scripts\_pyrun.cmd scripts\log_manual.py
scripts\_pyrun.cmd scripts\log_manual.py --tool "<tool-name>" --prompt "<prompt text>"
```

## Examples

```bash
bash scripts/_pyrun.sh scripts/log_manual.py --tool chatgpt --prompt "Brainstorm UI layout for verify page"
bash scripts/_pyrun.sh scripts/log_manual.py --tool gemini-web --prompt "Research risk scoring algorithms"
bash scripts/_pyrun.sh scripts/log_manual.py --tool claude-web --prompt "Explain OAuth2 PKCE flow"
```

Entries are appended to `.ai-log/session.jsonl` and submitted alongside automated logs during the next `git push`.
