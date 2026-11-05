#!/usr/bin/env python3
"""
Sync Agent Harness — synchronizes skills, rules, subagents, MCP configs,
and hooks across Antigravity, OpenCode, Claude Code, OpenAI Codex, Cursor, and Gemini.
"""

import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = ROOT / ".agents"
SKILLS_SRC = AGENTS_DIR / "skills"
RULES_SRC = AGENTS_DIR / "rules"

TARGET_AGENTS = {
    "claude": ROOT / ".claude",
    "codex": ROOT / ".codex",
    "opencode": ROOT / ".opencode",
    "cursor": ROOT / ".cursor",
}


def sync_symlink(target_link: Path, source: Path):
    """Safely create or replace a relative symlink."""
    target_link.parent.mkdir(parents=True, exist_ok=True)
    rel_path = os.path.relpath(source, target_link.parent)
    if target_link.is_symlink() or target_link.exists():
        if target_link.is_symlink() and os.readlink(target_link) == rel_path:
            return
        if target_link.is_dir() and not target_link.is_symlink():
            shutil.rmtree(target_link)
        else:
            target_link.unlink()
    target_link.symlink_to(rel_path)
    print(f"  [symlink] {target_link.relative_to(ROOT)} -> {rel_path}")


def sync_skills():
    print("[1/5] Synchronizing skills across agents...")
    SKILLS_SRC.mkdir(parents=True, exist_ok=True)
    for agent_name, agent_dir in TARGET_AGENTS.items():
        if agent_name in ("claude", "codex", "opencode", "cursor"):
            dest = agent_dir / "skills"
            sync_symlink(dest, SKILLS_SRC)


def sync_rules():
    print("[2/5] Synchronizing rules and instructions...")
    RULES_SRC.mkdir(parents=True, exist_ok=True)

    master_agents = ROOT / "AGENTS.md"

    # Synchronize rules folder into all agent harnesses
    for agent_name, agent_dir in TARGET_AGENTS.items():
        rules_dest = agent_dir / "rules"
        sync_symlink(rules_dest, RULES_SRC)

    # Tool-specific instruction pointers
    # 1. ROOT/CLAUDE.md is the single authoritative entrypoint for Claude Code
    sync_symlink(ROOT / "CLAUDE.md", master_agents)
    # Clean up duplicate .claude/CLAUDE.md to prevent Claude Code reading AGENTS.md twice
    claude_nested = TARGET_AGENTS["claude"] / "CLAUDE.md"
    if claude_nested.is_symlink() or claude_nested.exists():
        claude_nested.unlink()

    # 2. Codex instruction pointer
    sync_symlink(TARGET_AGENTS["codex"] / "instructions.md", master_agents)


def sync_subagents():
    print("[3/5] Synchronizing subagents across harnesses...")
    subagents_file = AGENTS_DIR / "subagents.json"
    declared_subagents = {}
    if subagents_file.exists():
        try:
            declared_subagents = json.loads(subagents_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [warn] Failed to parse {subagents_file}: {e}")

    if not declared_subagents:
        print("  [warn] No declared subagents found in subagents.json.")
        return

    # 1. OpenCode Sync (.opencode/opencode.json)
    opencode_json_path = ROOT / ".opencode" / "opencode.json"
    root_opencode_json = ROOT / "opencode.json"

    if root_opencode_json.exists():
        if not opencode_json_path.exists():
            shutil.move(root_opencode_json, opencode_json_path)
        else:
            root_opencode_json.unlink()

    if opencode_json_path.exists():
        try:
            cfg = json.loads(opencode_json_path.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    else:
        cfg = {}

    cfg.setdefault("agents", {})
    cfg.setdefault("agent", {})
    for agent_id, agent_meta in declared_subagents.items():
        agent_entry = {
            "description": agent_meta.get("description", ""),
            "mode": agent_meta.get("mode", "subagent"),
            "system": agent_meta.get("prompt", ""),
        }
        model_opencode = agent_meta.get("models", {}).get("opencode")
        if model_opencode:
            agent_entry["model"] = model_opencode

        cfg["agents"][agent_id] = agent_entry
        # Backwards compatibility with v1 OpenCode
        legacy_entry = dict(agent_entry)
        legacy_entry["prompt"] = agent_entry["system"]
        cfg["agent"][agent_id] = legacy_entry

    opencode_json_path.parent.mkdir(parents=True, exist_ok=True)
    opencode_json_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    print(f"  [opencode] Updated OpenCode subagents in .opencode/opencode.json ({len(declared_subagents)} agents).")

    # 2. Claude Code Sync (.claude/agents/*.md)
    claude_agents_dir = TARGET_AGENTS["claude"] / "agents"
    claude_agents_dir.mkdir(parents=True, exist_ok=True)
    for agent_id, agent_meta in declared_subagents.items():
        tools_list = ", ".join(agent_meta.get("tools", ["Read", "Write", "Edit", "Bash", "Grep", "Glob"]))
        model_claude = agent_meta.get("models", {}).get("claude", "sonnet")
        desc = agent_meta.get("description", "")
        prompt = agent_meta.get("prompt", "").strip()

        md_content = f"""---
name: {agent_id}
description: {desc}
tools: {tools_list}
model: {model_claude}
---

{prompt}
"""
        agent_md_file = claude_agents_dir / f"{agent_id}.md"
        agent_md_file.write_text(md_content, encoding="utf-8")
    print(f"  [claude] Synced Claude Code subagent definitions in .claude/agents/ ({len(declared_subagents)} agents).")

    # 3. OpenAI Codex Sync (.codex/config.toml & .codex/agents/*.toml)
    codex_agents_dir = TARGET_AGENTS["codex"] / "agents"
    codex_agents_dir.mkdir(parents=True, exist_ok=True)

    codex_config_lines = [
        "# OpenAI Codex Project-Level Configuration",
        "[agents]",
        "enabled = true",
        'default_subagent_model = "gpt-5.6-luna"',
        'default_subagent_reasoning_effort = "low"',
        "",
    ]

    for agent_id, agent_meta in declared_subagents.items():
        model_codex = agent_meta.get("models", {}).get("codex", "gpt-5.6-luna")
        effort_codex = agent_meta.get("models", {}).get("codex_reasoning_effort", "low")
        desc = agent_meta.get("description", "").replace('"', '\\"')
        prompt = agent_meta.get("prompt", "").strip()

        # Write role TOML
        role_toml = codex_agents_dir / f"{agent_id}.toml"
        role_content = f"""model = "{model_codex}"
model_reasoning_effort = "{effort_codex}"
developer_instructions = '''{prompt}'''
"""
        role_toml.write_text(role_content, encoding="utf-8")

        # Add to codex config
        codex_config_lines.append(f"[agents.{agent_id}]")
        codex_config_lines.append(f'description = "{desc}"')
        codex_config_lines.append(f'config_file = "agents/{agent_id}.toml"')
        codex_config_lines.append("")

    codex_config_file = TARGET_AGENTS["codex"] / "config.toml"
    codex_config_file.write_text("\n".join(codex_config_lines) + "\n", encoding="utf-8")
    print(
        f"  [codex] Synced Codex subagents in .codex/config.toml and .codex/agents/ ({len(declared_subagents)} agents)."
    )


def sync_mcp():
    print("[4/5] Synchronizing MCP servers...")
    # Canonical single source of truth is .agents/mcp_config.json
    canonical_mcp = AGENTS_DIR / "mcp_config.json"
    root_mcp_config = ROOT / "mcp_config.json"

    # Clean up legacy root mcp_config.json to maintain a clean root level
    if root_mcp_config.exists() and not root_mcp_config.is_symlink():
        if not canonical_mcp.exists():
            shutil.move(root_mcp_config, canonical_mcp)
        else:
            root_mcp_config.unlink()

    if canonical_mcp.exists():
        # Hidden .mcp.json for Claude Code
        sync_symlink(ROOT / ".mcp.json", canonical_mcp)
        # Cursor MCP configuration
        sync_symlink(TARGET_AGENTS["cursor"] / "mcp.json", canonical_mcp)


def sync_hooks():
    print("[5/5] Checking hooks across harnesses...")
    hooks_status = []
    hooks_status.append(("Antigravity", (AGENTS_DIR / "hooks.json").exists()))
    hooks_status.append(("Claude Code", (TARGET_AGENTS["claude"] / "settings.json").exists()))
    hooks_status.append(("OpenCode", (ROOT / ".opencode" / "plugins" / "ai-log.js").exists()))
    hooks_status.append(("OpenAI Codex", (TARGET_AGENTS["codex"] / "hooks.json").exists()))

    for tool, ok in hooks_status:
        status_str = "ACTIVE" if ok else "MISSING"
        print(f"  [{status_str}] {tool}")


def main():
    print("========================================")
    print("Agent Harness Synchronization")
    print("========================================")
    sync_skills()
    sync_rules()
    sync_subagents()
    sync_mcp()
    sync_hooks()
    print("========================================")
    print("All agent harnesses synchronized successfully.")


if __name__ == "__main__":
    main()
