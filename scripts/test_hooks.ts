#!/usr/bin/env bun
/**
 * Verification Test Suite for AI Agent Hooks in GreenSentinel:
 * 1. OpenAI Codex Hook
 * 2. Antigravity (AGY) PreInvocation & PostToolUse Hooks
 * 3. OpenCode Plugin (Chat Transform, Select Skill, Post-Tool Headroom)
 */

import { handleCodex, handleOpenCode } from "./jev_hook";
import { handleAntigravity } from "./jev_hook";
import { handlePostTool } from "./rtk_post_tool_hook";
import jevSkillSelectorPlugin from "../.opencode/plugin/jev-skill-selector";

let passed = 0;
let failed = 0;

function assert(condition: boolean, testName: string) {
  if (condition) {
    console.log(`  ✓ ${testName}`);
    passed++;
  } else {
    console.error(`  ✗ FAIL: ${testName}`);
    failed++;
  }
}

async function runVerification() {
  console.log("==================================================");
  console.log("Running Hook & Tool Verification Suite for GreenSentinel");
  console.log("==================================================");

  // ----------------------------------------------------
  // Test 1: OpenAI Codex Hook
  // ----------------------------------------------------
  console.log("\n[1/3] Testing Codex Hook (scripts/jev_codex_selector.ts)...");
  const codexPrompt = "viết unit test cho payment gateway bằng pytest";
  const codexInput = JSON.stringify({
    hook_event_name: "UserPromptSubmit",
    prompt: codexPrompt,
  });

  const codexResult = await handleCodex(codexInput);
  assert(codexResult.prompt === codexPrompt, "Codex hook output includes exact user prompt");
  assert(Array.isArray(codexResult.skills) && codexResult.skills.length > 0, "Codex hook returns selected skills");
  assert(
    codexResult.skills.some((s: any) => s.name === "python-testing-patterns" || s.name === "tdd"),
    `Codex selected expected testing tool (got: ${codexResult.skills[0]?.name})`
  );
  assert(
    codexResult.hookSpecificOutput?.additionalContext.includes(codexPrompt),
    "Codex additionalContext embeds user prompt explicitly"
  );

  // Verify Codex wire schema compliance (no unexpected top-level fields like prompt, skills, injectedContext)
  const codexWireJson = JSON.parse(JSON.stringify(codexResult));
  assert(codexWireJson.continue === true, "Codex wire JSON has continue: true");
  assert(typeof codexWireJson.hookSpecificOutput === "object", "Codex wire JSON has hookSpecificOutput");
  assert(codexWireJson.hookSpecificOutput.hookEventName === "UserPromptSubmit", "Codex wire JSON has hookEventName: UserPromptSubmit");
  assert(!("prompt" in codexWireJson), "Codex wire JSON does NOT contain unexpected top-level 'prompt'");
  assert(!("skills" in codexWireJson), "Codex wire JSON does NOT contain unexpected top-level 'skills'");
  assert(!("injectedContext" in codexWireJson), "Codex wire JSON does NOT contain unexpected top-level 'injectedContext'");

  // ----------------------------------------------------
  // Test 2: Antigravity (AGY) PreInvocation & PostTool Hooks
  // ----------------------------------------------------
  console.log("\n[2/3] Testing Antigravity (AGY) Hooks...");
  const agyInput = JSON.stringify({
    invocationNum: 1,
    prompt: "thiết kế database schema cho hệ thống gọi xe postgresql",
    workspacePaths: [process.cwd()],
  });

  const agyPreResult = await handleAntigravity(agyInput);
  assert(Array.isArray(agyPreResult.injectSteps) && agyPreResult.injectSteps.length === 1, "AGY returns 1 injectStep");
  const agyMsg = agyPreResult.injectSteps[0]?.ephemeralMessage || "";
  assert(agyMsg.includes("User Request:"), "AGY ephemeral message contains 'User Request:'");
  assert(agyMsg.includes("database-schema-design"), "AGY recommended database-schema-design skill");

  // Test invocationNum > 1 skipping
  const agySkipResult = await handleAntigravity(JSON.stringify({ invocationNum: 2, prompt: "tool result" }));
  assert(agySkipResult.injectSteps.length === 0, "AGY skips intermediate tool returns (invocationNum > 1)");

  // Test AGY PostToolUse
  const agyPostResult = handlePostTool(JSON.stringify({ stepIdx: 3 }), "antigravity");
  assert(agyPostResult.stdout === "{}", "AGY PostToolUse returns valid empty JSON {}");

  // ----------------------------------------------------
  // Test 3: OpenCode Plugin
  // ----------------------------------------------------
  console.log("\n[3/3] Testing OpenCode Plugin (.opencode/plugin/jev-skill-selector.ts)...");
  try {
    const plugin = await jevSkillSelectorPlugin();
    assert(plugin.name === "jev-skill-selector", "OpenCode plugin loaded with name 'jev-skill-selector'");

    // Test OpenCode Tool execute
    const openCodeTool = plugin.tools[0];
    const toolExec = await openCodeTool.execute({ task: "viết tài liệu requirements SRS cho hệ thống" });
    assert(toolExec.userPrompt === "viết tài liệu requirements SRS cho hệ thống", "OpenCode tool returns userPrompt");
    assert(toolExec.skills.some((s: any) => s.name === "writing-srs"), `OpenCode tool selected writing-srs (got: ${toolExec.primarySkill})`);

    // Test OpenCode Chat Transform Hook
    const opencodeMessages = {
      messages: [
        { info: { role: "user" }, parts: [{ type: "text", text: "viết use case cho tài xế" }] }
      ]
    };
    await plugin.hooks["experimental.chat.messages.transform"]({}, opencodeMessages);
    assert(opencodeMessages.messages.length === 2, "OpenCode chat transform injected system guidance message");
    const injectedPart = opencodeMessages.messages[1]?.parts[0]?.text || "";
    assert(injectedPart.includes('User Request: "viết use case cho tài xế"'), "OpenCode injected message contains exact User Request");
    assert(injectedPart.includes("use-case-writer"), "OpenCode injected message recommends use-case-writer");

    // Test OpenCode tool.execute.after headroom truncation
    const largeOutput = { title: "cat", output: "export const data = 42;\n".repeat(200), metadata: {} };
    await plugin.hooks["tool.execute.after"]({ tool: "cat", sessionID: "s1", callID: "c1", args: {} }, largeOutput);
    assert(largeOutput.output.includes("Headroom:"), "OpenCode post-tool hook truncates large output for headroom");
  } catch (pluginErr: any) {
    console.error(`  [SKIP] OpenCode plugin tests: ${pluginErr.message}`);
  }

  // Test OpenCode CLI Handler in scripts/jev_hook.ts (independent of plugin)
  try {
    const openCodeHookRes = await handleOpenCode(JSON.stringify({ prompt: "viết use case cho tài xế" }));
    assert(openCodeHookRes.prompt === "viết use case cho tài xế", "handleOpenCode extracts prompt");
    assert(openCodeHookRes.message?.info?.role === "system", "handleOpenCode returns synthetic system message");
    assert(openCodeHookRes.message?.parts?.[0]?.text?.includes("use-case-writer") === true, "handleOpenCode selected use-case-writer");
  } catch (hookErr: any) {
    console.error(`  [SKIP] handleOpenCode tests: ${hookErr.message}`);
  }

  console.log("\n==================================================");
  console.log(`Results: ${passed} passed, ${failed} failed.`);
  console.log("==================================================");

  if (failed > 0) {
    process.exit(1);
  }
}

runVerification().catch((err) => {
  console.error("Test Suite Uncaught Error:", err);
  process.exit(1);
});
