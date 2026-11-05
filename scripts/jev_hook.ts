#!/usr/bin/env bun
/**
 * Unified Jev Skill Selector Hook for Project P-063.
 * Supports: OpenAI Codex, Claude Code, and Antigravity (agy).
 *
 * Ensures the user prompt is explicitly extracted, evaluated, and included
 * in the returned context / hook response.
 */

import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { fileURLToPath } from "node:url";

const __dirname_compat =
  (import.meta as any).dir ??                       // Bun
  (import.meta as any).dirname ??                    // Node ≥21
  path.dirname(fileURLToPath(import.meta.url));      // Node <21 / tsx

const ROOT = path.resolve(__dirname_compat, "..");
export const DEFAULT_SKILLS_BANK = path.join(ROOT, ".agents", "jev_skills");

// ---------------------------------------------------------------------------
// Environment & Jev Module Resolution
// ---------------------------------------------------------------------------

function loadEnv(): void {
  const candidates = [
    path.join(ROOT, ".env"),
    path.resolve(os.homedir(), "dev", "jev_skill_selector", ".env"),
    path.join(os.homedir(), ".gemini", "config", ".env"),
    path.join(os.homedir(), ".env"),
  ];

  for (const envFile of candidates) {
    if (!fs.existsSync(envFile)) continue;
    try {
      const content = fs.readFileSync(envFile, "utf-8");
      for (const rawLine of content.split("\n")) {
        const line = rawLine.trim();
        if (!line || line.startsWith("#")) continue;
        const eqIdx = line.indexOf("=");
        if (eqIdx > 0) {
          const key = line.slice(0, eqIdx).trim();
          let val = line.slice(eqIdx + 1).trim();
          if (
            (val.startsWith('"') && val.endsWith('"')) ||
            (val.startsWith("'") && val.endsWith("'"))
          ) {
            val = val.slice(1, -1);
          }
          if (!process.env[key]) {
            process.env[key] = val;
          }
        }
      }
    } catch {
      // Ignore reading errors
    }
  }

  if (!process.env.SKILLS_BANK_PATH || !fs.existsSync(process.env.SKILLS_BANK_PATH)) {
    process.env.SKILLS_BANK_PATH = DEFAULT_SKILLS_BANK;
  }

  // Prioritize dedicated JEV_SKILL_* configuration for the skill selector
  if (process.env.JEV_SKILL_API_KEY) {
    process.env.OPENROUTER_API_KEY = process.env.JEV_SKILL_API_KEY;
    process.env.JEV_API_KEY = process.env.JEV_SKILL_API_KEY;
  }
  if (process.env.JEV_SKILL_MODEL) {
    process.env.MODEL = process.env.JEV_SKILL_MODEL;
    process.env.JEV_MODEL = process.env.JEV_SKILL_MODEL;
  }
  if (process.env.JEV_SKILL_INJECT_CONTENT !== undefined) {
    process.env.JEV_INJECT_CONTENT = process.env.JEV_SKILL_INJECT_CONTENT;
  }
}

// Load env variables at startup
loadEnv();

export async function resolveJevModule() {
  const candidates = [
    process.env.JEV_SELECTOR_PATH,
    process.env.JEV_PATH ? path.join(process.env.JEV_PATH, "index.ts") : undefined,
    "/home/dat/dev/jev_skill_selector/index.ts",
    path.resolve(os.homedir(), "dev", "jev_skill_selector", "index.ts"),
    path.resolve(os.homedir(), "dev", "jev_auto_select_skills", "index.ts"),
    path.resolve(ROOT, ".agents", "skills", "jev-skill-selector", "scripts", "selector.ts"),
    path.resolve(os.homedir(), ".agents", "jev_skill_selector", "index.ts"),
  ].filter((c): c is string => Boolean(c));

  for (const cand of candidates) {
    if (cand && fs.existsSync(cand)) {
      try {
        const mod = await import(cand);
        return mod;
      } catch (err) {
        console.error(`[jev-hook] Failed to import Jev from ${cand}:`, err);
      }
    }
  }

  throw new Error(
    "Could not locate jev_skill_selector index.ts. Please set JEV_SELECTOR_PATH or JEV_PATH."
  );
}

// ---------------------------------------------------------------------------
// Prompt Extraction Helpers
// ---------------------------------------------------------------------------

export type GenericHookInput = {
  prompt?: string;
  userPrompt?: string;
  user_prompt?: string;
  text?: string;
  content?: string;
  input?: string;
  messages?: Array<{
    role?: string;
    content?: string | Array<{ type?: string; text?: string }>;
  }>;
  invocationNum?: number;
  initialNumSteps?: number;
  conversationId?: string;
  workspacePaths?: string[];
  transcriptPath?: string;
  artifactDirectoryPath?: string;
  modelName?: string;
};

export function extractPromptFromPayload(rawInput: string): { prompt: string; parsed: GenericHookInput } {
  if (!rawInput.trim()) return { prompt: "", parsed: {} };

  try {
    const data = JSON.parse(rawInput) as GenericHookInput;

    // 1. Direct prompt fields
    if (typeof data.prompt === "string" && data.prompt.trim()) {
      return { prompt: data.prompt.trim(), parsed: data };
    }
    if (typeof data.userPrompt === "string" && data.userPrompt.trim()) {
      return { prompt: data.userPrompt.trim(), parsed: data };
    }
    if (typeof data.user_prompt === "string" && data.user_prompt.trim()) {
      return { prompt: data.user_prompt.trim(), parsed: data };
    }
    if (typeof data.text === "string" && data.text.trim()) {
      return { prompt: data.text.trim(), parsed: data };
    }
    if (typeof data.content === "string" && data.content.trim()) {
      return { prompt: data.content.trim(), parsed: data };
    }
    if (typeof data.input === "string" && data.input.trim()) {
      return { prompt: data.input.trim(), parsed: data };
    }

    // 2. Chat messages array (supports Claude, OpenAI, Antigravity, OpenCode)
    if (Array.isArray(data.messages) && data.messages.length > 0) {
      const lastUser = [...data.messages].reverse().find((m: any) => {
        const role = m.role || m.info?.role;
        return role === "user";
      });
      if (lastUser) {
        if (typeof lastUser.content === "string" && lastUser.content.trim()) {
          return { prompt: lastUser.content.trim(), parsed: data };
        }
        if (Array.isArray(lastUser.content)) {
          const text = lastUser.content
            .map((part: any) => (typeof part === "object" ? part.text || "" : String(part)))
            .join("\n")
            .trim();
          if (text) return { prompt: text, parsed: data };
        }
        // OpenCode format: parts array
        if (Array.isArray((lastUser as any).parts)) {
          const text = (lastUser as any).parts
            .filter((p: any) => p?.type === "text" && typeof p.text === "string")
            .map((p: any) => p.text)
            .join("\n")
            .trim();
          if (text) return { prompt: text, parsed: data };
        }
      }
    }

    // 3. Antigravity transcript reading if transcriptPath or conversationId given
    const transcriptPath = findAntigravityTranscript(data);
    if (transcriptPath) {
      const promptFromTranscript = extractPromptFromTranscriptFile(transcriptPath);
      if (promptFromTranscript) {
        return { prompt: promptFromTranscript, parsed: data };
      }
    }

    return { prompt: "", parsed: data };
  } catch {
    // rawInput was plain text
    return { prompt: rawInput.trim(), parsed: {} };
  }
}

function findAntigravityTranscript(data: GenericHookInput): string | null {
  if (data.transcriptPath && fs.existsSync(data.transcriptPath)) {
    return data.transcriptPath;
  }
  const convId = data.conversationId;
  if (!convId) return null;

  const home = os.homedir();
  const candidates = [
    path.join(home, ".gemini", "antigravity-cli", "brain", convId, ".system_generated", "logs", "transcript.jsonl"),
    path.join(home, ".gemini", "antigravity-ide", "brain", convId, ".system_generated", "logs", "transcript.jsonl"),
    path.join(home, ".gemini", "antigravity", "brain", convId, ".system_generated", "logs", "transcript.jsonl"),
  ];

  for (const cand of candidates) {
    if (fs.existsSync(cand)) return cand;
  }
  return null;
}

function extractPromptFromTranscriptFile(filePath: string): string {
  if (!fs.existsSync(filePath)) return "";
  try {
    const content = fs.readFileSync(filePath, "utf-8");
    const lines = content.trim().split("\n");
    for (let i = lines.length - 1; i >= 0; i--) {
      const line = lines[i].trim();
      if (!line) continue;
      try {
        const entry = JSON.parse(line);
        if (entry.type === "USER_INPUT" && entry.source === "USER_EXPLICIT") {
          const text = entry.content || "";
          const reqMatch = /<USER_REQUEST>([\s\S]*?)<\/USER_REQUEST>/.exec(text);
          if (reqMatch) return reqMatch[1].trim();
          return text
            .replace(/<(?:ADDITIONAL_METADATA|USER_SETTINGS_CHANGE|SYSTEM_MESSAGE)>[\s\S]*?<\/(?:ADDITIONAL_METADATA|USER_SETTINGS_CHANGE|SYSTEM_MESSAGE)>/g, "")
            .trim();
        }
      } catch {
        continue;
      }
    }
  } catch {
    return "";
  }
  return "";
}

// ---------------------------------------------------------------------------
// Skill Context Formatter (Always includes the user prompt)
// ---------------------------------------------------------------------------

export interface SelectedSkillInfo {
  name: string;
  probability: number;
  confidence: number;
  description?: string;
  content?: string;
  path?: string;
}

export function formatRoutingContext(
  prompt: string,
  skills: SelectedSkillInfo[],
  skillsBankDir: string = DEFAULT_SKILLS_BANK,
  options?: { includeContent?: boolean }
): string {
  if (skills.length === 0) return "";

  const shouldIncludeContent =
    options?.includeContent ?? (process.env.JEV_INJECT_CONTENT !== "false");

  const lines = [
    "🎯 **[Jev Dynamic Skill Routing]**",
    `User Request: "${prompt}"`,
    "",
    "Recommended skill(s) for this task:",
    "",
  ];

  for (const skill of skills) {
    const prob = (skill.probability * 100).toFixed(1);
    const conf = (skill.confidence * 100).toFixed(0);
    const skillPath = skill.path || path.join(skillsBankDir, skill.name, "SKILL.md");
    const hasPath = fs.existsSync(skillPath);

    lines.push(`• **${skill.name}** (Prob: ${prob}% | Conf: ${conf}%)`);
    if (hasPath) {
      lines.push(`  - Path: \`${skillPath}\``);
    }
    if (skill.description) {
      lines.push(`  - Description: ${skill.description}`);
    }
  }

  if (shouldIncludeContent) {
    lines.push("", "---", "");
    for (const skill of skills) {
      const skillPath = skill.path || path.join(skillsBankDir, skill.name, "SKILL.md");
      lines.push(`## Skill: ${skill.name}`);
      if (fs.existsSync(skillPath)) {
        lines.push(`*Location: \`${skillPath}\`*`, "");
        try {
          lines.push(fs.readFileSync(skillPath, "utf-8").trim());
        } catch {}
      } else if (skill.description) {
        lines.push(`### Description`, skill.description);
      }
      lines.push("", "---", "");
    }
    lines.push("*Instruction:* Apply the above skill instructions and workflows directly to fulfill the user prompt.");
  } else {
    lines.push("");
    lines.push("*Instruction:* Read and follow the recommended skill workflow if relevant to the request.");
  }

  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Tool Handlers
// ---------------------------------------------------------------------------

export interface CodexWireOutput {
  continue?: boolean;
  hookSpecificOutput: {
    hookEventName: "UserPromptSubmit";
    additionalContext: string;
  };
}

export interface CodexHookResult extends CodexWireOutput {
  prompt: string;
  skills: SelectedSkillInfo[];
  injectedContext: string;
  toJSON(): CodexWireOutput;
}

/**
 * Handle OpenAI Codex UserPromptSubmit Hook
 */
export async function handleCodex(rawInput: string): Promise<CodexHookResult> {
  const { prompt } = extractPromptFromPayload(rawInput);
  if (!prompt) {
    return {
      continue: true,
      prompt: "",
      skills: [],
      injectedContext: "",
      hookSpecificOutput: {
        hookEventName: "UserPromptSubmit",
        additionalContext: "",
      },
      toJSON() {
        return {
          continue: true,
          hookSpecificOutput: {
            hookEventName: "UserPromptSubmit",
            additionalContext: "",
          },
        };
      },
    };
  }

  try {
    const jev = await resolveJevModule();
    const skillsDir = process.env.SKILLS_BANK_PATH || DEFAULT_SKILLS_BANK;
    const result = await jev.selectSkills({
      userPrompt: prompt,
      skillsDir,
      options: { includeContent: true },
    });

    const selected = (result.selectedSkills || []).map((s: any) => ({
      name: s.name,
      probability: s.probability,
      confidence: s.confidence,
      description: s.description,
      content: s.content,
      path: s.path,
    }));

    const additionalContext = formatRoutingContext(prompt, selected, skillsDir);

    return {
      continue: true,
      prompt,
      skills: selected,
      injectedContext: additionalContext,
      hookSpecificOutput: {
        hookEventName: "UserPromptSubmit",
        additionalContext,
      },
      toJSON() {
        return {
          continue: true,
          hookSpecificOutput: {
            hookEventName: "UserPromptSubmit",
            additionalContext,
          },
        };
      },
    };
  } catch (err: any) {
    console.error(`[jev-hook][codex] Error: ${err.message}`);
    return {
      continue: true,
      prompt,
      skills: [],
      injectedContext: "",
      hookSpecificOutput: {
        hookEventName: "UserPromptSubmit",
        additionalContext: "",
      },
      toJSON() {
        return {
          continue: true,
          hookSpecificOutput: {
            hookEventName: "UserPromptSubmit",
            additionalContext: "",
          },
        };
      },
    };
  }
}

/**
 * Handle Claude Code UserPromptSubmit Hook
 */
export async function handleClaude(rawInput: string): Promise<string> {
  const { prompt } = extractPromptFromPayload(rawInput);
  if (!prompt) return "";

  try {
    const jev = await resolveJevModule();
    const skillsDir = process.env.SKILLS_BANK_PATH || DEFAULT_SKILLS_BANK;
    const result = await jev.selectSkills({
      userPrompt: prompt,
      skillsDir,
      options: { includeContent: true },
    });

    const selected = (result.selectedSkills || []).map((s: any) => ({
      name: s.name,
      probability: s.probability,
      confidence: s.confidence,
      description: s.description,
      content: s.content,
      path: s.path,
    }));

    return formatRoutingContext(prompt, selected, skillsDir);
  } catch (err: any) {
    console.error(`[jev-hook][claude] Error: ${err.message}`);
    return "";
  }
}

/**
 * Handle Antigravity (agy) PreInvocation Hook
 */
export async function handleAntigravity(rawInput: string): Promise<any> {
  const emptyOutput = { injectSteps: [] };
  const { prompt, parsed } = extractPromptFromPayload(rawInput);

  // Skip intermediate model turns in tool-call loops (invocationNum > 1)
  if (parsed.invocationNum !== undefined && parsed.invocationNum > 1) {
    return emptyOutput;
  }

  if (!prompt || prompt.length < 2) {
    return emptyOutput;
  }

  try {
    const jev = await resolveJevModule();
    const skillsDir = process.env.SKILLS_BANK_PATH || DEFAULT_SKILLS_BANK;
    const result = await jev.selectSkills({
      userPrompt: prompt,
      skillsDir,
      options: { includeContent: true },
    });

    const selected = (result.selectedSkills || []).map((s: any) => ({
      name: s.name,
      probability: s.probability,
      confidence: s.confidence,
      description: s.description,
      content: s.content,
      path: s.path,
    }));

    if (selected.length === 0) {
      return emptyOutput;
    }

    const message = formatRoutingContext(prompt, selected, skillsDir);

    return {
      injectSteps: [
        {
          ephemeralMessage: message,
        },
      ],
    };
  } catch (err: any) {
    console.error(`[jev-hook][antigravity] Error: ${err.message}`);
    return emptyOutput;
  }
}

/**
 * Handle OpenCode Hook & Message Transform
 */
export interface OpenCodeHookResult {
  prompt: string;
  skills: SelectedSkillInfo[];
  injectedContext: string;
  message?: {
    info: { role: string; synthetic: boolean };
    parts: Array<{ type: string; text: string }>;
  };
}

export async function handleOpenCode(rawInput: string): Promise<OpenCodeHookResult> {
  const { prompt } = extractPromptFromPayload(rawInput);
  if (!prompt) {
    return {
      prompt: "",
      skills: [],
      injectedContext: "",
    };
  }

  try {
    const jev = await resolveJevModule();
    const skillsDir = process.env.SKILLS_BANK_PATH || DEFAULT_SKILLS_BANK;
    const result = await jev.selectSkills({
      userPrompt: prompt,
      skillsDir,
      options: { includeContent: true },
    });

    const selected = (result.selectedSkills || []).map((s: any) => ({
      name: s.name,
      probability: s.probability,
      confidence: s.confidence,
      description: s.description,
      content: s.content,
      path: s.path,
    }));

    const additionalContext = formatRoutingContext(prompt, selected, skillsDir);

    return {
      prompt,
      skills: selected,
      injectedContext: additionalContext,
      message: {
        info: { role: "system", synthetic: true },
        parts: [{ type: "text", text: additionalContext }],
      },
    };
  } catch (err: any) {
    console.error(`[jev-hook][opencode] Error: ${err.message}`);
    return {
      prompt,
      skills: [],
      injectedContext: "",
    };
  }
}

// ---------------------------------------------------------------------------
// Environment / Tool Auto-Detection & Main Execution
// ---------------------------------------------------------------------------

export type TargetTool = "codex" | "claude" | "antigravity" | "agy" | "opencode";

export function detectTool(argv: string[], env: NodeJS.ProcessEnv, rawInput: string): TargetTool {
  // 1. Explicit CLI argument: --tool=NAME
  for (const arg of argv) {
    if (arg.startsWith("--tool=")) {
      const tool = arg.split("=")[1].toLowerCase();
      if (tool === "agy") return "antigravity";
      if (
        tool === "codex" ||
        tool === "claude" ||
        tool === "antigravity" ||
        tool === "opencode"
      ) {
        return tool as TargetTool;
      }
    }
  }

  // 2. Signature in input JSON
  if (rawInput && rawInput.trim().startsWith("{")) {
    try {
      const parsed = JSON.parse(rawInput);
      if ("invocationNum" in parsed || "transcriptPath" in parsed || "artifactDirectoryPath" in parsed) {
        return "antigravity";
      }
      if (parsed.hook_event_name === "UserPromptSubmit" && !env.CLAUDE_CODE) {
        return "codex";
      }
      if ("sessionID" in parsed && ("model" in parsed || "parts" in parsed)) {
        return "opencode";
      }
    } catch {}
  }

  // 3. Environment variables
  if (env.ANTIGRAVITY || env.GEMINI_CLI) return "antigravity";
  if (env.CLAUDE_CODE || env.CLAUDE_WORKSPACE) return "claude";
  if (env.OPENCODE || env.OPENCODE_SESSION) return "opencode";
  if (env.CODEX_RUNNER || env.CODEX || env.CODEX_THREAD_ID) return "codex";

  return "codex";
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

    const tool = detectTool(process.argv, process.env, input);

    try {
      if (tool === "antigravity" || tool === "agy") {
        const out = await handleAntigravity(input);
        console.log(JSON.stringify(out, null, 2));
      } else if (tool === "claude") {
        const out = await handleClaude(input);
        if (out) console.log(out);
      } else if (tool === "opencode") {
        const out = await handleOpenCode(input);
        console.log(JSON.stringify(out, null, 2));
      } else {
        // Default to Codex: stdout MUST adhere strictly to user-prompt-submit.command.output (no extra top-level fields)
        const out = await handleCodex(input);
        const wireOutput: CodexWireOutput = {
          continue: true,
          hookSpecificOutput: {
            hookEventName: "UserPromptSubmit",
            additionalContext: out.hookSpecificOutput?.additionalContext ?? out.injectedContext ?? "",
          },
        };
        console.log(JSON.stringify(wireOutput, null, 2));
      }
    } catch (err: any) {
      console.error(`[jev-hook] ${tool} failed: ${err.message}`);
      if (tool === "antigravity" || tool === "agy") {
        console.log(JSON.stringify({ injectSteps: [] }));
      } else if (tool === "opencode") {
        console.log(JSON.stringify({ prompt: "", skills: [], injectedContext: "" }));
      } else if (tool === "codex" || tool === undefined) {
        console.log(
          JSON.stringify({
            continue: true,
            hookSpecificOutput: {
              hookEventName: "UserPromptSubmit",
              additionalContext: "",
            },
          }, null, 2)
        );
      }
    }
  })();
}
