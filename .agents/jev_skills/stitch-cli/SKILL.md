---
name: stitch-cli
description: Google Stitch CLI for generating UI screens and design systems from the terminal and wiring them to coding agents. Use when asked to install Stitch, generate screens, preview prototypes, or connect Stitch to an agent. Replaces the removed Stitch MCP workflow.
---

# Stitch CLI

Official CLI (`@google/stitch`, released 2026-10-01 by Google Labs) — the
terminal channel for Stitch alongside MCP and SDK. No MCP server is configured
in this repo; use this CLI.

## Install (Node.js 20+)

```bash
npm install -g @google/stitch
stitch login
stitch --help   # commands change fast; trust --help over memory
```

## Core commands

```bash
stitch create project --title "My App"
stitch generate screen --device DESKTOP --prompt "Clean analytics dashboard with sidebar navigation"
stitch generate variants --creative-range REFINE    # or EXPLORE | REIMAGINE
stitch serve   # local preview server
```

## Connect coding agents (one command)

```bash
stitch agent-skills add --user
```

Installs Stitch Skills (`/stitch`: generate screens, extract a design system
from a URL, convert prototypes to React) for Claude Code, Cursor, Codex,
Gemini CLI, and Antigravity.

## Project workflow

1. Generate initial screen with `stitch generate screen`.
2. Iterate with `--creative-range` until direction is right.
3. Freeze visual rules in `DESIGN.md` (do not skip — agents drift style
   without it).
4. Implement pages against `DESIGN.md` (see `ui-designer` subagent).
5. Verify in browser; feed deviations into the next iteration.

## Caveats

- Alpha stage: pin versions in automation; generation follows account quotas.
- Community reports of "false success" (change reported but not applied) —
  review critical steps manually.
- `stitch loop` (continuous-improvement CLI workflow) is NOT the
  `stitch-loop` skill (batch multi-page generation). Do not confuse them.
