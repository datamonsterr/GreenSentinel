#!/usr/bin/env bun
/**
 * RTK & Headroom Post-Tool Invocation Hook for Project P-063.
 * Enforces zero-fluff, token conservation, and context headroom after tool execution.
 * Reference: https://github.com/juliusbrussee/caveman
 */

import fs from "node:fs";
import path from "node:path";

interface PostToolPayload {
  tool?: string;
  tool_name?: string;
  toolName?: string;
  stepIdx?: number;
  output?: string;
  error?: string;
  tool_response?: any;
}

export function handlePostTool(rawInput: string, toolEnv: string = "agy"): { stdout: string } {
  let payload: PostToolPayload = {};
  try {
    if (rawInput.trim().startsWith("{")) {
      payload = JSON.parse(rawInput);
    }
  } catch {}

  // Antigravity contract expects empty JSON object on PostToolUse
  if (toolEnv === "antigravity" || toolEnv === "agy") {
    return { stdout: "{}" };
  }

  // Claude Code / Codex format: can output a concise reminder
  const reminder = "[RTK/Headroom]: Tool executed. Be terse. Surgical diffs only, no conversational filler or preamble. Preserve headroom.";
  return { stdout: reminder };
}

if (import.meta.main) {
  (async () => {
    let input = "";
    if (!process.stdin.isTTY) {
      const chunks: Buffer[] = [];
      for await (const chunk of process.stdin) {
        chunks.push(Buffer.from(chunk));
      }
      input = Buffer.concat(chunks).toString("utf-8").trim();
    } else {
      input = process.argv.slice(2).filter((a) => !a.startsWith("--")).join(" ");
    }

    let toolEnv = "agy";
    for (const arg of process.argv) {
      if (arg.startsWith("--tool=")) {
        toolEnv = arg.split("=")[1].toLowerCase();
      }
    }

    const result = handlePostTool(input, toolEnv);
    if (result.stdout) {
      console.log(result.stdout);
    }
  })();
}
