#!/usr/bin/env bun

/**
 * Codex integration for the Jev skill selector (P-063).
 * Extracts user prompt, runs Jev decision routing, and includes the user
 * prompt explicitly in the returned hook output.
 */
import { handleCodex, extractPromptFromPayload } from "./jev_hook";

export { extractPromptFromPayload as extractPrompt };

export async function run(rawInput: string) {
  return handleCodex(rawInput);
}

if (import.meta.main) {
  (async () => {
    const chunks: Buffer[] = [];
    if (!process.stdin.isTTY) {
      for await (const chunk of process.stdin) chunks.push(Buffer.from(chunk));
    }
    const rawInput = chunks.length
      ? Buffer.concat(chunks).toString("utf-8")
      : process.argv.slice(2).join(" ");

    try {
      const output = await handleCodex(rawInput);
      const wireOutput = {
        continue: true,
        hookSpecificOutput: {
          hookEventName: "UserPromptSubmit" as const,
          additionalContext: output.hookSpecificOutput?.additionalContext ?? output.injectedContext ?? "",
        },
      };
      console.log(JSON.stringify(wireOutput, null, 2));
    } catch (error) {
      console.error(`[jev-codex-selector] ${error instanceof Error ? error.message : String(error)}`);
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
  })();
}
